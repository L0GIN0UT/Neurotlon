"""Тесты по итогам ревью: сброс, тайм-ауты, датчики, ограничения и страховки."""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from neurotlon_bridge.processing import emg as bridge_emg
from neurotlon_launcher import calibration, game, web_bridge
from neurotlon_launcher.bridge_link import (
    BridgeLink,
    SocketBridgeLink,
    parse_progress,
    parse_sample,
)
from neurotlon_launcher.calibration import (
    CONNECT_WAIT_S,
    COUNTDOWN_S,
    SENSOR_MISSING,
    SENSOR_WAIT_S,
    Calibrate,
    CalibrationRun,
    Reset,
    plan_for,
)
from neurotlon_launcher.config import parse_config
from neurotlon_launcher.machine import Calibrating, Checking, StationMachine, TechnicalProblem
from neurotlon_launcher.snapshot import calibrating_view
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
from neurotlon_launcher.web_bridge import BridgeServer, LiveState

DARTS = {"eeg": "connected", "emg": "connected"}
PONG = {"emg_left": "connected", "emg_right": "connected"}
CD = float(COUNTDOWN_S)
TOKEN = "t" * 32


def apply(run: CalibrationRun, link: FakeLink, now: float) -> list[Any]:
    commands = run.update(link.view(), now)
    for command in commands:
        ok = (
            link.reset()
            if isinstance(command, Reset)
            else link.calibrate(command.signal, command.step)
        )
        if not ok:
            run.command_failed(command)
    return list(commands)


# --- сброс подтверждается ---


def test_lost_reset_is_repeated_and_old_calibration_is_not_counted() -> None:
    link = FakeLink()
    link.go_live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=True)
    commands = run.update(link.view(), 0.0)
    assert commands[0] == Reset()
    for command in commands:  # связь оборвалась между view() и отправкой
        run.command_failed(command)
    link.go_live(DARTS, calibrated=("emg", "eeg"))  # мост поднял старую калибровку из файла
    assert not run.view(link.view()).ready  # сброс не подтверждён
    assert [s.status for s in run.view(link.view()).steps] == ["pending", "pending"]
    assert apply(run, link, 1.0)[0] == Reset()  # сброс повторяется на новом hello
    assert not run.view(link.view()).ready


def test_clean_hello_after_a_lost_reset_confirms_it() -> None:
    link = FakeLink()
    link.go_live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=True)
    for command in run.update(link.view(), 0.0):
        run.command_failed(command)
    link.go_live(DARTS)  # новый hello: у моста ничего нет
    assert apply(run, link, 1.0) == []  # reset повторять незачем
    assert apply(run, link, 1.0 + CD) == [Calibrate("emg", "cycle")]


def test_own_results_survive_a_bridge_restart_but_foreign_ones_do_not() -> None:
    link = FakeLink()
    link.go_live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=True)
    apply(run, link, 0.0)
    apply(run, link, CD)
    link.finish("emg", "cycle")
    apply(run, link, CD + 1.0)
    link.go_live(DARTS, calibrated=("emg",))  # мост восстановил нашу ЭМГ
    assert Reset() not in apply(run, link, CD + 2.0)
    link.go_live(DARTS, calibrated=("emg", "eeg"))  # ЭЭГ мы не калибровали
    assert apply(run, link, CD + 3.0)[0] == Reset()


def test_machine_does_not_launch_on_a_stale_file_after_reconnect() -> None:
    rig = MachineRig()
    rig.to_calibrating()
    rig.link.go_live(DARTS, calibrated=("emg", "eeg"))
    real_reset = rig.link.reset
    rig.link.reset = lambda: (real_reset(), False)[1]  # type: ignore[method-assign]
    rig.machine.tick()
    rig.link.go_live(DARTS, calibrated=("emg", "eeg"))
    screen = rig.machine.calibration_screen()
    assert screen is not None and not screen.run.ready
    rig.machine.calibration_continue()
    assert isinstance(rig.machine.state, Calibrating)


# --- смешанное состояние, датчик, молчание ---


def test_only_pending_signals_start_when_the_other_is_restored() -> None:
    link = FakeLink()
    link.go_live(PONG, calibrated=("emg_left",))
    run = CalibrationRun(plan_for("pong"), fresh=False)
    assert apply(run, link, 0.0) == []
    assert apply(run, link, CD) == [Calibrate("emg_right", "cycle")]
    parts = run.view(link.view()).steps[0].parts
    assert [p.status for p in parts] == ["done", "running"]


def test_sensor_that_never_connects_fails_the_step_with_a_reason() -> None:
    link = FakeLink()
    link.go_live({"eeg": "connected", "emg": "disconnected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert apply(run, link, 0.0) == []
    apply(run, link, CONNECT_WAIT_S - 1)
    assert run.view(link.view()).connect_error is None
    apply(run, link, CONNECT_WAIT_S + 1)
    view = run.view(link.view())
    assert view.connect_error is not None and view.stage == "connecting"
    assert [s.status for s in view.steps] == ["pending", "pending"]  # калибровка не начиналась
    link.states["emg"] = "connected"
    assert apply(run, link, CONNECT_WAIT_S + 2) == []
    link.states["emg"] = "disconnected"  # пропал в отсчёте: ждём, потом понятная причина
    apply(run, link, CONNECT_WAIT_S + 2 + CD)
    apply(run, link, CONNECT_WAIT_S + 2 + CD + SENSOR_WAIT_S)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", SENSOR_MISSING)
    link.states["emg"] = "connected"
    t = CONNECT_WAIT_S + 3 + CD + SENSOR_WAIT_S
    assert run.retry("muscle", link.view(), t) == []
    assert apply(run, link, t) == []
    assert apply(run, link, t + CD) == [Calibrate("emg", "cycle")]


def test_silence_timeout_is_extended_by_every_bridge_message() -> None:
    link = FakeLink()
    link.go_live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    apply(run, link, 0.0)
    now = 0.0
    for second in range(1, 61):  # в bridge.toml шаг длится 30 с и 6 сегментов
        now = float(second)
        link.running(
            "emg", "cycle", second / 60, segment=1 + second // 10, phase="tense", phase_left_s=1.0
        )
        apply(run, link, now)
    step = run.view(link.view()).steps[0]
    assert step.status == "running"  # ложного «Мост не отвечает» нет
    assert step.segments_total == 7  # больше запасных четырёх: берём то, что прислал мост
    apply(run, link, now + 46)
    assert run.view(link.view()).steps[0].status == "failed"


def test_reason_texts_match_the_bridge_literals() -> None:
    source = Path(bridge_emg.__file__).read_text(encoding="utf-8")
    for reason in calibration._REASON_TEXTS:
        assert f'"{reason}"' in source, reason


# --- машина: сбой запуска, закрытие, снимок ---


class MachineRig:
    def __init__(self, executor: Any = None, runner: FakeRunner | None = None) -> None:
        self.links: list[FakeLink] = []
        self.queue = FakeQueue()
        self.time = Time()
        self.machine = StationMachine(
            "darts",
            FakeApi(),
            self.queue,
            runner or FakeRunner(),
            clock=self.time.clock,
            monotonic=self.time.monotonic,
            new_session_id=Ids(),
            executor=executor or SyncExecutor(),
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


def test_launch_failure_leads_to_a_problem_screen_not_a_stuck_station() -> None:
    rig = MachineRig()
    rig.to_calibrating()

    def broken(active: Any) -> None:
        raise OSError("диск полон")

    rig.queue.set_active = broken  # type: ignore[method-assign]
    rig.link.go_live({"eeg": "emulated", "emg": "emulated"})
    rig.machine.tick()
    state = rig.machine.state
    assert isinstance(state, TechnicalProblem) and "игру" in state.reason
    rig.machine.back()
    assert isinstance(rig.machine.state, Checking)


def test_calibrating_snapshot_never_raises_without_a_link() -> None:
    rig = MachineRig()
    rig.to_calibrating()
    state = rig.machine.state
    assert isinstance(state, Calibrating)
    rig.machine._link = None
    view = calibrating_view(rig.machine, state.players)
    assert view["link"] == "connecting" and view["ready"] is False and view["steps"] == []


def test_back_does_not_wait_for_a_slow_link_to_close() -> None:
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    rig = MachineRig(executor=pool)
    try:
        rig.machine.enter_code("7")
        deadline = time.monotonic() + 3
        while not isinstance(rig.machine.state, Calibrating) and time.monotonic() < deadline:
            rig.machine.tick()
            if rig.machine.state.__class__.__name__ == "Confirm":
                rig.machine.confirm()
            time.sleep(0.01)
        assert isinstance(rig.machine.state, Calibrating)
        link = rig.link
        link.close = lambda: release.wait(5)  # type: ignore[method-assign,assignment]
        started = time.monotonic()
        rig.machine.back()
        assert time.monotonic() - started < 1.0
        assert isinstance(rig.machine.state, Checking)
    finally:
        release.set()
        pool.shutdown(wait=True)


# --- числа ---


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 10**400, "1", True])
def test_non_finite_numbers_from_the_bridge_are_dropped(bad: Any) -> None:
    assert parse_sample({"t_ms": bad, "signals": {}}, 1) is None
    sample = parse_sample({"t_ms": 1, "signals": {"emg": {"value": bad, "valid": True}}}, 1)
    assert sample is not None and sample.signals == {}
    parsed = parse_progress(
        {
            "signal": "emg",
            "step": "cycle",
            "status": "running",
            "progress": bad,
            "segment": bad,
            "phase_left_s": bad,
        }
    )
    assert parsed is not None
    assert (parsed[1].segment, parsed[1].phase_left_s, parsed[1].progress) == (None, None, 0.0)


def test_nan_cannot_reach_the_published_json() -> None:
    live = LiveState()
    with pytest.raises(ValueError):
        live.publish({"x": float("nan")})


def test_battery_nan_from_a_real_socket_is_ignored() -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    link = SocketBridgeLink("127.0.0.1", port, reconnect_s=0.05)
    try:
        conn, _ = listener.accept()
        hello = b'{"type":"hello","signals":[{"name":"emg","state":"connected"}]}\n'
        conn.sendall(
            hello + b'{"type":"sensor","signal":"emg","state":"connected","battery":NaN}\n'
        )
        deadline = time.monotonic() + 3
        while link.view().link != "live" and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
        assert link.view().batteries.get("emg") is None
        conn.close()
    finally:
        link.close()
        listener.close()


# --- bridge_answers: общий срок ---


def test_bridge_answers_has_one_deadline_for_a_drip_feeding_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(game, "HELLO_WAIT_S", 0.4)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    stop = threading.Event()

    def drip() -> None:
        conn, _ = listener.accept()
        with conn:
            while not stop.is_set():
                try:
                    conn.sendall(b" ")  # байт за байтом, без перевода строки
                except OSError:
                    return
                time.sleep(0.1)

    thread = threading.Thread(target=drip, daemon=True)
    thread.start()
    started = time.monotonic()
    assert not game.bridge_answers("127.0.0.1", port)
    assert time.monotonic() - started < 1.5
    stop.set()
    thread.join(timeout=2)
    listener.close()


# --- лимит SSE-подписчиков ---


def test_sse_subscribers_are_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_bridge, "MAX_STREAMS", 2)
    machine = StationMachine(
        "darts", FakeApi(), FakeQueue(), FakeRunner(), executor=SyncExecutor(), bridge_link=None
    )
    station = web_bridge.Station(machine, StationStatus)
    server = BridgeServer(station, TOKEN)
    station.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    opened = []
    try:
        for path in ("/api/events", "/api/signals"):
            request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}?token={TOKEN}")
            opened.append(urllib.request.urlopen(request, timeout=5))
        for path in ("/api/events", "/api/signals"):
            request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}?token={TOKEN}")
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
            assert caught.value.code == 503
        assert server.acquire_stream() is False
        server.release_stream()
        assert server.acquire_stream() is True
    finally:
        for stream in opened:
            stream.close()
        server.close()


# --- настройки ---


def test_non_loopback_bridge_host_is_warned_about(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    base: dict[str, Any] = {
        "server_url": "https://x",
        "token_file": "t",
        "game": {"command": ["g"]},
    }
    with caplog.at_level(logging.WARNING):
        parse_config({**base, "bridge": {"host": "127.0.0.1"}}, tmp_path)
        assert not caplog.records
        config = parse_config({**base, "bridge": {"host": "0.0.0.0"}}, tmp_path)
    assert config.bridge_host == "0.0.0.0"  # предупреждаем, но не запрещаем
    assert any("0.0.0.0" in r.getMessage() for r in caplog.records)
    assert re.search("локальн", caplog.text)
