"""Экран калибровки по HTTP: снимок `calibrating`, поток `/api/signals`, команды."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import IO, Any

import pytest

from neurotlon_launcher import web_bridge
from neurotlon_launcher.bridge_link import BridgeLink, BurstRecord, Reading, SampleRecord
from neurotlon_launcher.machine import Calibrating, StationMachine
from neurotlon_launcher.signal_stream import FRAME_SAMPLES, SignalCursor, next_frame
from neurotlon_launcher.snapshot import snapshot
from neurotlon_launcher.status import StationStatus
from neurotlon_launcher.testing import (
    FakeApi,
    FakeLink,
    FakeQueue,
    FakeRunner,
    Ids,
    SyncExecutor,
    Time,
)
from neurotlon_launcher.web_bridge import BridgeServer, Station

TOKEN = "t" * 32
DARTS_STATES = {"eeg": "connected", "emg": "connected"}


class Rig:
    def __init__(self, discipline: str = "darts") -> None:
        self.links: list[FakeLink] = []
        self.runner = FakeRunner()
        self.time = Time()
        self.machine = StationMachine(
            discipline,
            FakeApi(),
            FakeQueue(),
            self.runner,
            clock=self.time.clock,
            monotonic=self.time.monotonic,
            new_session_id=Ids(),
            executor=SyncExecutor(),
            bridge_link=self._link,
        )

    def _link(self) -> BridgeLink:
        self.links.append(FakeLink())
        return self.links[-1]

    @property
    def link(self) -> FakeLink:
        return self.links[-1]

    def to_calibrating(self) -> None:
        self.machine.enter_code("7")
        self.machine.tick()
        self.machine.confirm()
        self.machine.tick()
        assert isinstance(self.machine.state, Calibrating)


@pytest.fixture
def rig() -> Iterator[tuple[Rig, BridgeServer]]:
    r = Rig()
    station = Station(r.machine, lambda: StationStatus(0, 0, True))
    server = BridgeServer(station, TOKEN)
    station.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield r, server
    server.close()


def call(
    server: BridgeServer,
    path: str,
    *,
    method: str = "GET",
    body: Any = None,
    token: str | None = TOKEN,
    host: str | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}", data=data, method=method
    )
    if token is not None:
        request.add_header("X-Station-Token", token)
    if host is not None:
        request.add_header("Host", host)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def command(server: BridgeServer, action: str, value: Any = None) -> int:
    body: dict[str, Any] = {"action": action}
    if value is not None:
        body["value"] = value
    return call(server, "/api/command", method="POST", body=body)[0]


def sample(seq: int, emg: float = 0.5, eeg_ok: bool = True) -> SampleRecord:
    eeg = Reading(0.25, True) if eeg_ok else Reading(0.0, False, "artifact")
    return SampleRecord(seq, 1000 + seq * 20, {"emg": Reading(emg, True), "eeg": eeg})


def read_frame(stream: IO[bytes]) -> dict[str, Any]:
    while True:
        text = stream.readline()
        if text.startswith(b"data: "):
            stream.readline()
            frame: dict[str, Any] = json.loads(text[6:])
            return frame


# --- снимок ---


def test_snapshot_of_the_calibrating_screen() -> None:
    rig = Rig()
    rig.to_calibrating()
    view = snapshot(rig.machine, StationStatus())["state"]
    assert view["kind"] == "calibrating"
    assert view["link"] == "connecting"
    assert view["sensors"] == [] and view["eeg_method"] is None
    assert [s["id"] for s in view["steps"]] == ["muscle", "brain"]
    assert (view["current"], view["ready"]) == ("muscle", False)
    rig.link.go_live({**DARTS_STATES, "eeg": "connecting"}, eeg_method="alpha")
    rig.link.batteries["emg"] = 64
    rig.machine.tick()
    rig.link.running("emg", "cycle", 0.31234, segment=2, phase="relax", phase_left_s=3.46)
    view = snapshot(rig.machine, StationStatus())["state"]
    assert view["link"] == "live" and view["eeg_method"] == "alpha"
    assert view["sensors"] == [
        {"signal": "eeg", "state": "connecting", "battery": None},
        {"signal": "emg", "state": "connected", "battery": 64},
    ]
    assert view["steps"][0] == {
        "id": "muscle",
        "step": "cycle",
        "signals": ["emg"],
        "status": "running",
        "progress": 0.312,
        "segment": 2,
        "segments_total": 4,
        "phase": "relax",
        "phase_left_s": 3.5,
        "reason_text": None,
        "parts": [{"signal": "emg", "status": "running", "progress": 0.312, "reason_text": None}],
    }
    assert view["steps"][1]["status"] == "pending"
    assert view["players"][0]["code"] == "NT07"
    json.dumps(view, ensure_ascii=False)  # сериализуется без доработок


def test_snapshot_has_no_signal_values_so_it_does_not_change_ten_times_a_second() -> None:
    rig = Rig()
    rig.to_calibrating()
    rig.link.go_live(DARTS_STATES)
    before = json.dumps(snapshot(rig.machine, StationStatus()))
    rig.link.samples.append(sample(1))
    assert json.dumps(snapshot(rig.machine, StationStatus())) == before


# --- /api/signals ---


def test_signals_require_token_and_local_host(rig: tuple[Rig, BridgeServer]) -> None:
    _, server = rig
    assert call(server, "/api/signals", token=None)[0] == 403
    assert call(server, "/api/signals", token="wrong")[0] == 403
    assert call(server, "/api/signals", host="evil.example")[0] == 403


def test_signals_frame_format_and_incremental_delivery(rig: tuple[Rig, BridgeServer]) -> None:
    r, server = rig
    r.to_calibrating()
    r.link.go_live(DARTS_STATES)
    r.link.samples = [sample(i, emg=0.1 * i, eeg_ok=i != 2) for i in range(1, 4)]
    r.link.bursts = [BurstRecord(1, "emg", 1040, 0.8), BurstRecord(2, "emg", 1060, None)]
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/signals?token={TOKEN}")
    with urllib.request.urlopen(request, timeout=5) as stream:
        assert stream.headers["Content-Type"] == "text/event-stream"
        frame = read_frame(stream)
        assert frame["gen"] == 1
        assert [s["t_ms"] for s in frame["samples"]] == [1020, 1040, 1060]
        assert frame["samples"][0]["signals"] == {
            "emg": {"v": 0.1, "ok": True},
            "eeg": {"v": 0.25, "ok": True},
        }
        assert frame["samples"][1]["signals"]["eeg"] == {"v": 0.0, "ok": False, "r": "artifact"}
        assert frame["bursts"] == [
            {"signal": "emg", "t_ms": 1040, "rise": 0.8},
            {"signal": "emg", "t_ms": 1060},
        ]
        r.link.samples.append(sample(4))
        nxt = read_frame(stream)
        assert [s["t_ms"] for s in nxt["samples"]] == [1080]  # только новое
        assert nxt["bursts"] == []


def test_signals_stream_is_quiet_outside_calibration(
    rig: tuple[Rig, BridgeServer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_bridge, "SIGNALS_KEEPALIVE_S", 0.3)
    _, server = rig
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/signals?token={TOKEN}")
    with urllib.request.urlopen(request, timeout=5) as stream:
        assert stream.readline() == b": keepalive\n"
        stream.readline()


def test_a_new_calibration_starts_the_stream_from_the_new_link(
    rig: tuple[Rig, BridgeServer],
) -> None:
    r, server = rig
    r.to_calibrating()
    r.link.go_live(DARTS_STATES)
    r.link.samples = [sample(1)]
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/signals?token={TOKEN}")
    with urllib.request.urlopen(request, timeout=5) as stream:
        assert len(read_frame(stream)["samples"]) == 1
        r.machine.back()
        r.machine.tick()
        r.machine.confirm()
        r.machine.tick()
        r.link.go_live(DARTS_STATES)
        r.link.samples = [sample(1), sample(2)]  # у новой связи нумерация снова с единицы
        assert len(read_frame(stream)["samples"]) == 2


def test_frame_never_exceeds_the_per_frame_limit() -> None:
    link = FakeLink()
    link.go_live(DARTS_STATES)
    link.samples = [sample(i) for i in range(1, 101)]
    cursor = SignalCursor()
    frame = next_frame(cursor, 1, link)
    assert frame is not None and len(frame["samples"]) == FRAME_SAMPLES
    assert frame["samples"][-1]["t_ms"] == sample(100).t_ms
    assert next_frame(cursor, 1, link) is None
    assert next_frame(cursor, 1, None) is None


# --- команды ---


def test_calibration_commands_drive_the_machine(rig: tuple[Rig, BridgeServer]) -> None:
    r, server = rig
    r.to_calibrating()
    r.link.go_live(DARTS_STATES)
    r.machine.tick()
    assert command(server, "calibration_restart") == 204
    assert r.link.calls[-2:] == [("reset",), ("calibrate", "emg", "cycle")]
    assert command(server, "calibration_retry", "eeg") == 204
    assert r.link.calls[-1] == ("calibrate", "eeg", "baseline")
    assert command(server, "calibration_continue") == 204
    assert isinstance(r.machine.state, Calibrating)  # ещё не готово
    r.link.finish("emg", "cycle")
    r.link.finish("eeg", "baseline")
    assert command(server, "calibration_continue") == 204
    assert r.link.closed
    assert r.runner.requests


@pytest.mark.parametrize(
    ("action", "value"),
    [("calibration_retry", None), ("calibration_retry", 5), ("calibration_continue_now", None)],
)
def test_calibration_commands_reject_bad_arguments(
    rig: tuple[Rig, BridgeServer], action: str, value: Any
) -> None:
    r, server = rig
    r.to_calibrating()
    body: dict[str, Any] = {"action": action}
    if value is not None:
        body["value"] = value
    assert call(server, "/api/command", method="POST", body=body)[0] == 400
