import json
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

from neurotlon_launcher.api import ApiProblem, Offline
from neurotlon_launcher.outbox import Outbox
from neurotlon_launcher.sender import BACKOFF_S, Sender, backoff_delay


def payload(n: int = 1) -> dict[str, Any]:
    return {
        "session_id": str(uuid.UUID(int=n)),
        "discipline": "darts",
        "section": "bci",
        "finished_at": "2027-01-01T13:05:00+04:00",
        "entries": [{"participant_code": "NT01", "outcome": "completed", "points": 5}],
    }


class ScriptedApi:
    """Принимает результаты; по `plan[session_id]` может бросать ошибку."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.plan: dict[str, Exception] = {}

    def submit_result(self, body: dict[str, Any]) -> None:
        sid = body["session_id"]
        if sid in self.plan:
            raise self.plan[sid]
        self.sent.append(sid)


@pytest.fixture
def outbox(tmp_path: Path) -> Outbox:
    return Outbox(tmp_path / "data" / "outbox.db")


def test_add_is_idempotent_and_ordered(outbox: Outbox) -> None:
    for n in (3, 1, 2, 1):
        outbox.add(payload(n))
    assert [i.payload["session_id"][-1] for i in outbox.pending()] == ["3", "1", "2"]
    assert outbox.pending_count() == 3


def test_wal_mode_enabled(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    mode = box._db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "o.db"
    first = Outbox(path)
    first.add(payload(1))
    first.add(payload(2))
    first.mark_sent(payload(1)["session_id"])
    first.record_failure(payload(2)["session_id"], "нет связи")
    first.close()
    second = Outbox(path)
    items = second.pending()
    assert [i.session_id for i in items] == [payload(2)["session_id"]]
    assert (items[0].attempts, items[0].last_error) == (1, "нет связи")
    assert items[0].payload == payload(2)


def test_sender_sends_in_order_and_marks_sent(outbox: Outbox) -> None:
    api = ScriptedApi()
    for n in (2, 1, 3):
        outbox.add(payload(n))
    assert Sender(outbox, api).send_pending() is True
    assert [s[-1] for s in api.sent] == ["2", "1", "3"]
    assert outbox.pending_count() == 0


def test_offline_stops_pass_keeps_order_and_retries(outbox: Outbox) -> None:
    api = ScriptedApi()
    for n in (1, 2):
        outbox.add(payload(n))
    api.plan[payload(1)["session_id"]] = Offline("down")
    sender = Sender(outbox, api)
    assert sender.send_pending() is False
    assert api.sent == []  # второй не обгоняет первый
    assert outbox.pending()[0].attempts == 1
    del api.plan[payload(1)["session_id"]]
    assert sender.send_pending() is True
    assert [s[-1] for s in api.sent] == ["1", "2"]


@pytest.mark.parametrize("status", [403, 404, 409, 422])
def test_rejected_is_kept_and_not_retried(outbox: Outbox, status: int) -> None:
    api = ScriptedApi()
    outbox.add(payload(1))
    outbox.add(payload(2))
    api.plan[payload(1)["session_id"]] = ApiProblem(status, "invalid_entries", "bad")
    sender = Sender(outbox, api)
    assert sender.send_pending() is True
    assert [s[-1] for s in api.sent] == ["2"]  # очередь идёт дальше
    rejected = outbox.rejected()
    assert [r.session_id for r in rejected] == [payload(1)["session_id"]]
    assert str(status) in (rejected[0].last_error or "")
    assert outbox.pending_count() == 0
    api.plan.clear()
    sender.send_pending()
    assert [s[-1] for s in api.sent] == ["2"]  # молча не повторяется
    assert outbox.rejected_count() == 1


@pytest.mark.parametrize("status", [401, 500, 503])
def test_other_server_errors_are_retried(outbox: Outbox, status: int) -> None:
    api = ScriptedApi()
    outbox.add(payload(1))
    api.plan[payload(1)["session_id"]] = ApiProblem(status, "x")
    sender = Sender(outbox, api)
    assert sender.send_pending() is False
    assert outbox.pending_count() == 1
    assert outbox.rejected_count() == 0


def test_backoff_schedule() -> None:
    assert [backoff_delay(i) for i in range(7)] == [1, 2, 5, 10, 30, 30, 30]
    assert BACKOFF_S == (1.0, 2.0, 5.0, 10.0, 30.0)


def test_thread_sends_after_kick_and_stops(outbox: Outbox) -> None:
    delivered = threading.Event()

    class SignalingApi(ScriptedApi):
        def submit_result(self, body: dict[str, Any]) -> None:
            super().submit_result(body)
            delivered.set()

    api = SignalingApi()
    sender = Sender(outbox, api, poll_s=60)
    sender.start()
    try:
        outbox.add(payload(1))
        sender.kick()
        assert delivered.wait(5)
    finally:
        sender.stop()
    assert outbox.pending_count() == 0


def test_export_rejected_writes_json_for_the_judge(outbox: Outbox, tmp_path: Path) -> None:
    api = ScriptedApi()
    outbox.add(payload(1))
    outbox.add(payload(2))
    api.plan[payload(1)["session_id"]] = ApiProblem(404, "unknown_participant", "no such id")
    Sender(outbox, api).send_pending()
    exported = tmp_path / "data" / "rejected.json"  # sender exports on rejection
    data = json.loads(exported.read_text(encoding="utf-8"))
    assert [d["session_id"] for d in data] == [payload(1)["session_id"]]
    assert data[0]["participant_codes"] == ["NT01"]
    assert "404" in data[0]["error"]
    assert outbox.export_rejected() == exported
    assert not list(exported.parent.glob("*.tmp"))


def test_sender_stops_between_items_when_stopped(outbox: Outbox) -> None:
    for n in (1, 2, 3):
        outbox.add(payload(n))
    holder: list[Sender] = []

    class StoppingApi(ScriptedApi):
        def submit_result(self, body: dict[str, Any]) -> None:
            super().submit_result(body)
            holder[0].stop()

    api = StoppingApi()
    holder.append(Sender(outbox, api))
    holder[0].send_pending()
    assert len(api.sent) == 1
    assert outbox.pending_count() == 2
