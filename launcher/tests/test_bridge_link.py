"""Связь с мостом: разбор сообщений, подставной сокет-сервер и настоящий мост на эмуляторе."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.server import BridgeServer, BridgeThread
from neurotlon_contracts.contract import shared_dir
from neurotlon_launcher.bridge_link import (
    FINAL_STEPS,
    SocketBridgeLink,
    parse_hello,
    parse_progress,
    parse_sample,
)
from neurotlon_launcher.calibration import Calibrate, CalibrationRun, Reset, plan_for

TIMEOUT_S = 5.0


def wait_for(cond: Callable[[], bool], timeout_s: float = TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def line(**fields: Any) -> bytes:
    return json.dumps(fields, ensure_ascii=False).encode() + b"\n"


HELLO = line(
    type="hello",
    protocol=1,
    signals=[{"name": "eeg", "state": "connected"}, {"name": "emg", "state": "connected"}],
    features=["burst", "calibration_state"],
    eeg_method="alpha",
    calibrated=["emg"],
)


def sample(t_ms: int, emg: float = 0.5) -> bytes:
    return line(
        type="sample",
        t_ms=t_ms,
        signals={
            "emg": {"value": emg, "valid": True},
            "eeg": {"value": 0.0, "valid": False, "reason": "artifact"},
        },
    )


class FakeBridge:
    """Сокет-сервер, который говорит как мост: принимает одного клиента за раз."""

    def __init__(self, port: int = 0) -> None:
        self._listener = socket.create_server(("127.0.0.1", port))
        self.port: int = self._listener.getsockname()[1]
        self.received = b""
        self.accepted = 0
        self.reject = False
        self._conn: socket.socket | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            self.accepted += 1
            if self.reject:
                conn.close()
                continue
            conn.settimeout(0.1)
            self._conn = conn
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self.received += chunk
            conn.close()
            self._conn = None

    def send(self, *messages: bytes) -> None:
        assert wait_for(lambda: self._conn is not None)
        assert self._conn is not None
        self._conn.sendall(b"".join(messages))

    def drop(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.shutdown(socket.SHUT_RDWR)
        # Старое соединение ещё числится текущим, пока поток сервера его не закроет:
        # без ожидания следующий send() ушёл бы в уже закрытый сокет.
        assert wait_for(lambda: self._conn is not conn)

    @property
    def commands(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.received.split(b"\n") if item]

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)


@pytest.fixture
def bridge() -> Iterator[FakeBridge]:
    server = FakeBridge()
    yield server
    server.close()


@pytest.fixture
def link(bridge: FakeBridge) -> Iterator[SocketBridgeLink]:
    connection = SocketBridgeLink("127.0.0.1", bridge.port, reconnect_s=0.05)
    yield connection
    connection.close()


# --- разбор сообщений ---


def test_parse_hello_tolerates_old_and_odd_bridges() -> None:
    assert parse_hello({"signals": [{"name": "emg", "state": "emulated"}]}).calibrated == ()
    hello = parse_hello(json.loads(HELLO))
    assert hello.signals == (("eeg", "connected"), ("emg", "connected"))
    assert (hello.eeg_method, hello.calibrated) == ("alpha", ("emg",))
    assert parse_hello(
        {"signals": "x", "calibrated": "emg", "features": [1, "burst"]}
    ).features == ("burst",)


def test_parse_progress_defaults_and_clamps() -> None:
    parsed = parse_progress({"signal": "emg", "step": "cycle", "status": "done"})
    assert parsed is not None and parsed[1].progress == 1.0
    parsed = parse_progress(
        {"signal": "emg", "step": "cycle", "status": "running", "progress": 7, "segment": 2.0}
    )
    assert parsed is not None and (parsed[1].progress, parsed[1].segment) == (1.0, 2)
    assert parse_progress({"signal": "emg", "step": "cycle"}) is None


def test_parse_sample_keeps_valid_flag_and_reason() -> None:
    record = parse_sample(json.loads(sample(10)), 1)
    assert record is not None
    assert record.signals["emg"].ok and record.signals["emg"].reason is None
    assert record.signals["eeg"].reason == "artifact" and not record.signals["eeg"].ok
    assert parse_sample({"t_ms": "x", "signals": {}}, 1) is None
    broken = parse_sample({"t_ms": 1, "signals": {"emg": {"value": "x", "valid": True}}}, 1)
    assert broken is not None and broken.signals == {}


# --- настоящая связь ---


def test_link_goes_live_on_hello_and_reads_state(
    bridge: FakeBridge, link: SocketBridgeLink
) -> None:
    assert link.view().link == "connecting"
    bridge.send(HELLO, line(type="sensor", signal="eeg", state="connected", battery=77))
    assert wait_for(lambda: link.view().batteries.get("eeg") == 77)
    view = link.view()
    assert view.link == "live" and view.generation == 1
    assert view.states == {"eeg": "connected", "emg": "connected"}
    assert view.calibrated == frozenset({"emg"})
    assert view.hello is not None and view.hello.eeg_method == "alpha"


def test_calibration_messages_track_progress_and_the_calibrated_set(
    bridge: FakeBridge, link: SocketBridgeLink
) -> None:
    bridge.send(HELLO)
    assert wait_for(lambda: link.view().link == "live")
    assert link.calibrate("emg", "cycle")
    assert link.view().calibrated == frozenset()  # шкала сразу считается стёртой
    bridge.send(
        line(
            type="calibration",
            signal="emg",
            step="cycle",
            status="running",
            progress=0.4,
            segment=2,
            phase="relax",
            phase_left_s=3.5,
        )
    )
    assert wait_for(lambda: "emg" in link.view().progress)
    progress = link.view().progress["emg"]
    assert (progress.status, progress.segment, progress.phase) == ("running", 2, "relax")
    assert "emg" not in link.view().calibrated
    bridge.send(line(type="calibration", signal="emg", step="cycle", status="done"))
    assert wait_for(lambda: "emg" in link.view().calibrated)
    bridge.send(
        line(type="calibration", signal="eeg", step="baseline", status="failed", reason="x")
    )
    bridge.send(line(type="calibration", signal="emg", step="rest", status="done"))
    assert wait_for(lambda: "emg" not in link.view().calibrated)  # rest без contract шкалы не даёт


def test_commands_reach_the_bridge_as_protocol_lines(
    bridge: FakeBridge, link: SocketBridgeLink
) -> None:
    bridge.send(HELLO)
    assert wait_for(lambda: link.view().link == "live")
    assert link.calibrate("eeg", "baseline") and link.reset()
    assert wait_for(lambda: len(bridge.commands) == 2)
    assert bridge.commands == [
        {"type": "calibrate", "signal": "eeg", "step": "baseline"},
        {"type": "reset"},
    ]
    assert link.view().calibrated == frozenset()


def test_ring_gives_the_newest_samples_and_bursts_once(
    bridge: FakeBridge, link: SocketBridgeLink
) -> None:
    bridge.send(HELLO, *(sample(t) for t in range(0, 300, 20)))
    bridge.send(line(type="burst", signal="emg", t_ms=100, seq=1, rise=0.8))
    assert wait_for(
        lambda: len(link.recent(0, 0, 100).samples) == 15 and bool(link.recent(0, 0, 1).bursts)
    )
    batch = link.recent(0, 0, 10)
    assert [s.t_ms for s in batch.samples] == list(range(100, 300, 20))  # только последние 10
    assert [(b.signal, b.t_ms, b.rise) for b in batch.bursts] == [("emg", 100, 0.8)]
    again = link.recent(batch.cursor, batch.bursts[-1].n, 10)
    assert again.samples == () and again.bursts == ()
    bridge.send(sample(400))
    assert wait_for(lambda: len(link.recent(batch.cursor, 0, 10).samples) == 1)


def test_dropped_link_is_lost_then_live_again_with_a_new_generation(
    bridge: FakeBridge, link: SocketBridgeLink
) -> None:
    bridge.send(HELLO)
    assert wait_for(lambda: link.view().link == "live")
    bridge.drop()
    assert wait_for(lambda: link.view().link == "lost")
    bridge.send(HELLO.replace(b'"calibrated": ["emg"]', b'"calibrated": []'))
    assert wait_for(lambda: link.view().generation == 2 and link.view().link == "live")
    assert link.view().calibrated == frozenset()  # после перезапуска моста список перечитан


def test_rejected_connection_stays_connecting_and_never_gets_hello() -> None:
    server = FakeBridge()
    server.reject = True
    connection = SocketBridgeLink("127.0.0.1", server.port, reconnect_s=0.02)
    try:
        assert wait_for(lambda: server.accepted >= 3)
        assert connection.view().link == "connecting"
        server.reject = False
        server.send(HELLO)
        assert wait_for(lambda: connection.view().link == "live")
    finally:
        connection.close()
        server.close()


def test_close_waits_until_the_socket_is_closed(bridge: FakeBridge) -> None:
    connection = SocketBridgeLink("127.0.0.1", bridge.port, reconnect_s=0.05)
    bridge.send(HELLO)
    assert wait_for(lambda: connection.view().link == "live")
    connection.close()
    assert not bridge.connected or wait_for(lambda: not bridge.connected)
    assert not connection._thread.is_alive()
    connection.close()  # повторное закрытие безопасно
    accepted = bridge.accepted
    time.sleep(0.2)
    assert bridge.accepted == accepted  # после закрытия не переподключается


def test_garbage_lines_are_ignored(bridge: FakeBridge, link: SocketBridgeLink) -> None:
    bridge.send(b"not json\n", b"[]\n", HELLO, line(type="mystery"), line(type="sample", t_ms=1))
    assert wait_for(lambda: link.view().link == "live")


# --- согласованность с контрактом ---


def test_names_used_by_the_launcher_exist_in_the_bridge_schema() -> None:
    schema = json.loads((shared_dir() / "bridge-protocol.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    assert set(FINAL_STEPS) <= set(defs["CalibrationStep"]["enum"])
    plan = [step for discipline in ("darts", "pong") for step in plan_for(discipline)]
    assert {step.kind for step in plan} <= set(defs["CalibrationStep"]["enum"])
    assert {s for step in plan for s in step.signals} <= set(defs["SignalName"]["enum"])
    assert "calibration_state" in defs["Feature"]["enum"]
    assert set(defs["Hello"]["properties"]) >= {"calibrated", "features", "eeg_method"}
    assert {"running", "done", "failed"} == set(defs["Calibration"]["properties"]["status"]["enum"])
    assert set(defs["Calibrate"]["properties"]) >= {"signal", "step"}


# --- настоящий мост (эмулятор): связь, шаги, закрытие ---


@pytest.fixture
def real_bridge() -> Iterator[BridgeServer]:
    source = EmulatedSource("darts", time.monotonic, speed=40.0)
    server = BridgeServer(source, port=0, rate_hz=100, calibration_interval_s=0.01)
    thread = BridgeThread(server)
    thread.start()
    yield server
    thread.stop()


def test_link_runs_calibration_against_the_real_bridge(real_bridge: BridgeServer) -> None:
    connection = SocketBridgeLink("127.0.0.1", real_bridge.port, reconnect_s=0.05)
    try:
        assert wait_for(lambda: connection.view().link == "live")
        view = connection.view()
        assert set(view.states.values()) == {"emulated"} and view.emulated
        assert view.hello is not None and "calibration_state" in view.hello.features
        assert view.calibrated == frozenset()  # эмулятору калибровка не нужна
        run = CalibrationRun(plan_for("darts"), fresh=True)
        now = 0.0
        deadline = time.monotonic() + TIMEOUT_S
        while not run.view(connection.view()).ready and time.monotonic() < deadline:
            now += 0.05
            for command in run.update(connection.view(), now):
                if isinstance(command, Reset):
                    connection.reset()
                else:
                    assert isinstance(command, Calibrate)
                    connection.calibrate(command.signal, command.step)
            time.sleep(0.01)
        assert run.view(connection.view()).ready
        assert connection.view().calibrated == frozenset({"emg", "eeg"})
        assert wait_for(lambda: connection.recent(0, 0, 10).samples != ())
    finally:
        connection.close()


def test_slot_is_free_for_the_game_after_the_link_is_closed(real_bridge: BridgeServer) -> None:
    from neurotlon_launcher.game import bridge_answers

    connection = SocketBridgeLink("127.0.0.1", real_bridge.port, reconnect_s=0.05)
    assert wait_for(lambda: connection.view().link == "live")
    assert not bridge_answers("127.0.0.1", real_bridge.port)  # слот занят лаунчером: hello нет
    connection.close()
    assert wait_for(lambda: bridge_answers("127.0.0.1", real_bridge.port))


def test_commands_are_refused_without_a_connection() -> None:
    connection = SocketBridgeLink("127.0.0.1", 9, reconnect_s=0.05)  # там никто не слушает
    try:
        assert not connection.calibrate("emg", "cycle")
        assert not connection.reset()
    finally:
        connection.close()


def test_bridge_listening_counts_a_port_that_accepts_without_hello() -> None:
    import socket

    from neurotlon_launcher.game import bridge_answers, bridge_listening

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert bridge_listening("127.0.0.1", port)  # слушает, но `hello` не шлёт
        assert not bridge_answers("127.0.0.1", port)
    finally:
        server.close()
    assert not bridge_listening("127.0.0.1", port)
