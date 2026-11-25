"""Машина: экран калибровки между «Подтверждением» и игрой (с подставной связью с мостом)."""

from __future__ import annotations

import uuid

from neurotlon_launcher import texts
from neurotlon_launcher.api import Busy
from neurotlon_launcher.bridge_link import BridgeLink
from neurotlon_launcher.calibration import BRIDGE_SILENT, LINK_DROPPED
from neurotlon_launcher.game import Aborted, Finished, GameEntry, GameOutcome, GameRequest
from neurotlon_launcher.machine import (
    Calibrating,
    Checking,
    Confirm,
    Done,
    Idle,
    Playing,
    Starting,
    State,
    StationMachine,
    TechnicalProblem,
)
from neurotlon_launcher.testing import (
    FakeApi,
    FakeLink,
    FakeQueue,
    FakeRunner,
    Ids,
    SyncExecutor,
    Time,
    eligibility,
)

DARTS_STATES = {"eeg": "connected", "emg": "connected"}
PONG_STATES = {"emg_left": "connected", "emg_right": "connected"}
DARTS_DONE = Finished((GameEntry("NT07", "completed", 42),))


class CheckedRunner(FakeRunner):
    """Запоминает, была ли связь с мостом уже закрыта, когда игра стартовала."""

    def __init__(self, links: list[FakeLink], *outcomes: GameOutcome) -> None:
        super().__init__(*outcomes)
        self.links = links
        self.closed_at_start: list[bool] = []

    def start(self, request: GameRequest) -> None:
        self.closed_at_start.append(all(link.closed for link in self.links))
        super().start(request)


class Rig:
    def __init__(self, discipline: str = "darts", *outcomes: GameOutcome) -> None:
        self.links: list[FakeLink] = []
        self.api = FakeApi()
        self.queue = FakeQueue()
        self.runner = CheckedRunner(self.links, *outcomes)
        self.time = Time()
        self.machine = StationMachine(
            discipline,
            self.api,
            self.queue,
            self.runner,
            clock=self.time.clock,
            monotonic=self.time.monotonic,
            new_session_id=Ids(),
            executor=SyncExecutor(),
            bridge_link=self._make_link,
        )

    def _make_link(self) -> BridgeLink:
        link = FakeLink()
        self.links.append(link)
        return link

    @property
    def state(self) -> State:
        return self.machine.state

    @property
    def link(self) -> FakeLink:
        return self.links[-1]

    def tick(self, seconds: float = 0.0) -> None:
        self.time.mono += seconds
        self.machine.tick()

    def to_calibrating(self, code: str = "NT07") -> None:
        self.machine.enter_code(code)
        self.machine.tick()
        self.machine.confirm()
        self.machine.tick()
        assert isinstance(self.state, Calibrating)

    def pong_to_calibrating(self) -> None:
        for code in ("NT03", "NT14"):
            self.machine.enter_code(code)
            self.machine.tick()
            self.machine.confirm()
        self.machine.tick()
        assert isinstance(self.state, Calibrating)


def calibrate_darts(rig: Rig) -> None:
    rig.link.go_live(DARTS_STATES, eeg_method="alpha")
    rig.tick()
    rig.link.finish("emg", "cycle")
    rig.tick(1)
    rig.link.finish("eeg", "baseline")
    rig.tick(1)


def test_confirm_goes_to_starting_then_calibrating_without_launching() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.machine.enter_code("7")
    rig.machine.tick()
    rig.machine.confirm()
    assert isinstance(rig.state, Starting) and rig.state.fresh
    assert rig.links == []  # связь открывается только на экране калибровки
    rig.machine.tick()
    state = rig.state
    assert isinstance(state, Calibrating)
    assert (state.session_id, state.duration, state.fresh) == (uuid.UUID(int=1), 90, True)
    assert rig.api.started == [(uuid.UUID(int=1), "darts", ["NT07"])]  # «занят» виден до калибровки
    assert rig.runner.requests == []
    assert rig.queue.active is None
    assert len(rig.links) == 1 and not rig.links[0].closed


def test_busy_participant_is_reported_before_calibration() -> None:
    rig = Rig("darts")
    rig.api.start_error = Busy(409, "busy_on_other_station")
    rig.machine.enter_code("7")
    rig.machine.tick()
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Confirm) and rig.state.notice == texts.BUSY
    assert rig.links == []


def test_full_darts_flow_resets_calibrates_and_launches_after_closing_the_link() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.to_calibrating()
    rig.tick()  # связи нет: ничего не отправляется
    assert rig.link.calls == []
    rig.link.go_live(DARTS_STATES, calibrated=("emg",), eeg_method="alpha")  # остатки прошлого
    rig.tick()
    assert rig.link.calls == [("reset",), ("calibrate", "emg", "cycle")]
    rig.link.running("emg", "cycle", 0.5, segment=3, phase="tense", phase_left_s=2.0)
    rig.tick()
    rig.link.finish("emg", "cycle")
    rig.tick()
    assert rig.link.calls[-1] == ("calibrate", "eeg", "baseline")
    rig.machine.calibration_continue()  # мозг ещё не готов
    assert isinstance(rig.state, Calibrating)
    rig.link.finish("eeg", "baseline")
    rig.tick()
    screen = rig.machine.calibration_screen()
    assert screen is not None and screen.run.ready
    rig.machine.calibration_continue()
    assert isinstance(rig.state, Playing)
    assert rig.runner.closed_at_start == [True]
    assert rig.link.closed
    assert rig.queue.active is not None and rig.queue.active.session_id == str(uuid.UUID(int=1))
    assert [p.code for p in rig.runner.requests[0].players] == ["NT07"]
    rig.tick()
    assert isinstance(rig.state, Done)


def test_continue_is_ignored_until_ready_and_outside_calibration() -> None:
    rig = Rig("darts")
    rig.machine.calibration_continue()
    rig.machine.calibration_restart()
    rig.machine.calibration_retry("muscle")
    assert isinstance(rig.state, Idle)
    rig.to_calibrating()
    rig.link.go_live(DARTS_STATES)
    rig.tick()
    rig.machine.calibration_continue()
    assert isinstance(rig.state, Calibrating)
    assert rig.runner.requests == []


def test_retry_after_technical_problem_keeps_calibration_and_sends_no_reset() -> None:
    rig = Rig("darts", Aborted("игра упала"), DARTS_DONE)
    rig.to_calibrating()
    calibrate_darts(rig)
    rig.machine.calibration_continue()
    rig.tick()
    assert isinstance(rig.state, TechnicalProblem)
    rig.machine.retry()
    assert isinstance(rig.state, Starting) and not rig.state.fresh
    rig.machine.tick()
    assert isinstance(rig.state, Calibrating) and not rig.state.fresh
    assert len(rig.links) == 2
    rig.link.go_live(DARTS_STATES, calibrated=("emg", "eeg"), eeg_method="alpha")
    rig.tick()
    assert rig.link.calls == []  # ни reset, ни повторной калибровки
    rig.machine.calibration_continue()
    assert isinstance(rig.state, Playing)
    assert rig.runner.closed_at_start == [True, True]
    assert rig.api.started == [(uuid.UUID(int=1), "darts", ["NT07"])] * 2


def test_new_participant_gets_a_fresh_reset() -> None:
    rig = Rig("darts", DARTS_DONE, DARTS_DONE)
    rig.to_calibrating("NT07")
    calibrate_darts(rig)
    rig.machine.calibration_continue()
    rig.tick()  # игра закончилась
    assert isinstance(rig.state, Done)
    rig.tick(10)
    assert isinstance(rig.state, Idle)
    rig.to_calibrating("NT08")
    rig.link.go_live(DARTS_STATES, calibrated=("emg", "eeg"))
    rig.tick()
    assert rig.link.calls[0] == ("reset",)


def test_back_from_calibration_closes_the_link_and_returns_to_checking() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    link = rig.link
    rig.machine.back()
    assert link.closed
    assert isinstance(rig.state, Checking) and rig.state.code == "NT07"
    assert rig.runner.requests == []
    assert rig.queue.active is None
    assert rig.machine.calibration_screen() is None


def test_closing_the_machine_closes_the_link() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    rig.machine.close()
    assert rig.link.closed


def test_heartbeat_reports_calibrating_with_session() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    assert rig.machine.heartbeat_view() == ("calibrating", uuid.UUID(int=1))


def test_silent_bridge_fails_the_step_with_a_reason_and_retry_restarts_it() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    rig.link.go_live(DARTS_STATES)
    rig.tick()
    rig.tick(46)
    screen = rig.machine.calibration_screen()
    assert screen is not None
    assert (screen.run.steps[0].status, screen.run.steps[0].reason_text) == (
        "failed",
        BRIDGE_SILENT,
    )
    rig.machine.calibration_retry("muscle")
    assert rig.link.calls[-1] == ("calibrate", "emg", "cycle")
    screen = rig.machine.calibration_screen()
    assert screen is not None and screen.run.steps[0].status == "running"


def test_lost_link_fails_the_running_step() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    rig.link.go_live(DARTS_STATES)
    rig.tick()
    rig.link.drop()
    rig.tick()
    screen = rig.machine.calibration_screen()
    assert screen is not None
    assert screen.link.link == "lost"
    assert screen.run.steps[0].reason_text == LINK_DROPPED
    assert not screen.run.ready


def test_restart_resets_and_starts_over() -> None:
    rig = Rig("darts")
    rig.to_calibrating()
    calibrate_darts(rig)
    rig.machine.calibration_restart()
    assert rig.link.calls[-2:] == [("reset",), ("calibrate", "emg", "cycle")]
    screen = rig.machine.calibration_screen()
    assert screen is not None and not screen.run.ready


def test_pong_calibrates_both_hands_together() -> None:
    rig = Rig(
        "pong",
        Finished((GameEntry("NT03", "completed", 5, 1), GameEntry("NT14", "completed", 3, 0))),
    )
    rig.pong_to_calibrating()
    rig.link.go_live(PONG_STATES)
    rig.tick()
    assert rig.link.calls == [
        ("reset",),
        ("calibrate", "emg_left", "cycle"),
        ("calibrate", "emg_right", "cycle"),
    ]
    rig.link.finish("emg_left", "cycle")
    rig.link.fail("emg_right", "cycle", "нет данных в покое")
    rig.tick()
    rig.machine.calibration_continue()
    assert isinstance(rig.state, Calibrating)
    rig.machine.calibration_retry("emg_right")
    assert rig.link.calls[-1] == ("calibrate", "emg_right", "cycle")
    rig.link.finish("emg_right", "cycle")
    rig.tick()
    rig.machine.calibration_continue()
    assert isinstance(rig.state, Playing)
    assert [p.code for p in rig.runner.requests[0].players] == ["NT03", "NT14"]


def test_emulated_bridge_skips_calibration() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.to_calibrating()
    rig.link.go_live({"eeg": "emulated", "emg": "emulated"})
    rig.tick()
    assert isinstance(rig.state, Playing)
    assert rig.link.calls == []
    assert rig.runner.closed_at_start == [True]


def test_machine_without_a_bridge_link_goes_straight_to_the_game() -> None:
    rig = Rig("darts", DARTS_DONE)
    plain = StationMachine(
        "darts",
        rig.api,
        rig.queue,
        rig.runner,
        clock=rig.time.clock,
        monotonic=rig.time.monotonic,
        new_session_id=Ids(),
        executor=SyncExecutor(),
    )
    api = eligibility("NT07")
    rig.api.people["NT07"] = api
    plain.enter_code("7")
    plain.tick()
    plain.confirm()
    plain.tick()
    assert isinstance(plain.state, Playing)
    assert rig.links == []


def test_signal_link_is_available_only_while_calibrating() -> None:
    rig = Rig("darts")
    assert rig.machine.signal_link is None
    rig.to_calibrating()
    first = rig.machine.signal_link
    assert first is not None and first[1] is rig.link
    rig.machine.back()
    assert rig.machine.signal_link is None
    rig.machine.tick()
    rig.machine.confirm()
    rig.machine.tick()
    second = rig.machine.signal_link
    assert second is not None and second[0] != first[0]  # новая связь, новый номер
