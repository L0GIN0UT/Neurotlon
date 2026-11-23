import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import yaml
from jsonschema import Draft202012Validator

from neurotlon_launcher.api import HttpStationApi, Offline, Unauthorized
from neurotlon_launcher.heartbeat import HeartbeatLoop

OPENAPI = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "shared" / "openapi.yaml").read_text(encoding="utf-8")
)
HEARTBEAT_SCHEMA = Draft202012Validator(
    {"$ref": "#/components/schemas/Heartbeat", "components": OPENAPI["components"]}
)
SESSION = uuid.UUID("0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10")


def view_of(state: str, session: uuid.UUID | None) -> Callable[[], tuple[str, uuid.UUID | None]]:
    return lambda: (state, session)


class RecordingSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, uuid.UUID | None, int, dict[str, str]]] = []
        self.error = error
        self.called = threading.Event()

    def heartbeat(
        self, state: str, session_id: uuid.UUID | None, queue_length: int, sensors: dict[str, str]
    ) -> None:
        self.calls.append((state, session_id, queue_length, sensors))
        self.called.set()
        if self.error is not None:
            raise self.error


def test_beat_reports_view_and_queue() -> None:
    sink = RecordingSink()
    loop = HeartbeatLoop(sink, lambda: ("playing", SESSION), lambda: 3)
    assert loop.beat() is True
    assert sink.calls == [("playing", SESSION, 3, {})]


def test_beat_swallows_api_errors() -> None:
    for error in (Offline("down"), Unauthorized(401, "unauthorized")):
        loop = HeartbeatLoop(RecordingSink(error), lambda: ("idle", None), lambda: 0)
        assert loop.beat() is False


def test_payload_validates_against_openapi() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(204)

    client = httpx2.Client(base_url="http://srv", transport=httpx2.MockTransport(handler))
    api = HttpStationApi("http://srv", "tok", client=client)
    for state, session in [("idle", None), ("confirming", None), ("playing", SESSION)]:
        assert HeartbeatLoop(api, view_of(state, session), lambda: 7).beat()
    assert len(bodies) == 3
    for body in bodies:
        HEARTBEAT_SCHEMA.validate(body)
    assert bodies[2]["session_id"] == str(SESSION)
    assert "session_id" not in bodies[0]


def test_thread_beats_and_stops() -> None:
    sink = RecordingSink()
    loop = HeartbeatLoop(sink, lambda: ("idle", None), lambda: 0, interval_s=0.01)
    loop.start()
    try:
        assert sink.called.wait(5)
    finally:
        loop.stop()
    count = len(sink.calls)
    assert count >= 1
    assert len(sink.calls) == count  # после stop новых нет


def test_online_flag_follows_last_beat() -> None:
    sink = RecordingSink()
    loop = HeartbeatLoop(sink, view_of("idle", None), lambda: 0)
    assert loop.online is None
    assert loop.beat()
    assert loop.online is True
    sink.error = Offline("down")
    assert not loop.beat()
    assert loop.online is False
