"""Оркестратор калибровки: план по дисциплине, шаги, повторы, тайм-ауты (без сети и сокетов)."""

from __future__ import annotations

import pytest

from neurotlon_launcher.bridge_link import StepProgress
from neurotlon_launcher.calibration import (
    BRIDGE_SILENT,
    LINK_DROPPED,
    LINK_WAIT_S,
    TEXT_NO_SIGNAL,
    TEXT_WEAK,
    Calibrate,
    CalibrationRun,
    PlanStep,
    Reset,
    plan_for,
    reason_text,
    sensors_view,
)
from neurotlon_launcher.testing import FakeLink

EMG = {"emg": "connected"}
DARTS = {"eeg": "connected", "emg": "connected"}
PONG = {"emg_left": "connected", "emg_right": "connected"}


def live(states: dict[str, str], calibrated: tuple[str, ...] = ()) -> FakeLink:
    link = FakeLink()
    link.go_live(states, calibrated, "alpha")
    return link


def drive(run: CalibrationRun, link: FakeLink, now: float) -> list[object]:
    """Один шаг машины: обновить и применить команды к подставной связи."""
    commands = run.update(link.view(), now)
    for command in commands:
        if isinstance(command, Reset):
            link.reset()
        else:
            link.calibrate(command.signal, command.step)
    return list(commands)


# --- план ---


def test_darts_and_football_plan_muscle_then_brain() -> None:
    for discipline in ("darts", "football"):
        plan = plan_for(discipline)
        assert [(s.id, s.kind, s.signals) for s in plan] == [
            ("muscle", "cycle", ("emg",)),
            ("brain", "baseline", ("eeg",)),
        ]
        assert [s.duration_s for s in plan] == [20.0, 12.0]


def test_pong_plan_is_one_parallel_step() -> None:
    (step,) = plan_for("pong")
    assert (step.id, step.kind, step.signals) == ("muscle", "cycle", ("emg_left", "emg_right"))
    assert step.segments_total == 4


@pytest.mark.parametrize(
    ("duration", "expected"), [(1.0, 20.0), (7.0, 20.0), (12.0, 29.0), (20.0, 45.0)]
)
def test_timeout_is_twice_duration_plus_five_with_a_floor(duration: float, expected: float) -> None:
    assert PlanStep("x", "cycle", ("emg",), duration).timeout_s == expected


def test_reason_text_translates_known_reasons_only() -> None:
    assert reason_text("сокращение слабое, нет отличия от покоя") == TEXT_WEAK
    assert reason_text("нет данных в покое") == TEXT_NO_SIGNAL
    assert reason_text("нет данных при напряжении") == TEXT_NO_SIGNAL
    assert reason_text("датчик отключён") == "датчик отключён"
    assert reason_text(None) is None


# --- ход шагов ---


def test_fresh_run_resets_then_starts_the_first_step_only() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))  # остатки прежнего участника
    run = CalibrationRun(plan_for("darts"), fresh=True)
    assert drive(run, link, 0.0) == [Reset(), Calibrate("emg", "cycle")]
    assert link.calls == [("reset",), ("calibrate", "emg", "cycle")]
    assert drive(run, link, 0.1) == []  # шаг идёт, мозг ждёт своей очереди


def test_not_fresh_run_keeps_calibration_and_skips_ready_steps() -> None:
    link = live(DARTS, calibrated=("emg",))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == [Calibrate("eeg", "baseline")]
    assert ("reset",) not in link.calls


def test_not_fresh_with_everything_calibrated_is_ready_without_commands() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == []
    view = run.view(link.view())
    assert view.ready and view.current is None
    assert [s.status for s in view.steps] == ["done", "done"]


def test_fresh_view_hides_old_calibration_until_reset_is_sent() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=True)
    view = run.view(link.view())
    assert not view.ready
    assert [s.status for s in view.steps] == ["pending", "pending"]


def test_steps_follow_each_other_and_become_ready() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == [Calibrate("emg", "cycle")]
    link.running("emg", "cycle", 0.4, segment=2, phase="relax", phase_left_s=3.0)
    view = run.view(link.view())
    muscle = view.steps[0]
    assert (muscle.status, muscle.segment, muscle.phase, muscle.phase_left_s) == (
        "running",
        2,
        "relax",
        3.0,
    )
    assert muscle.progress == pytest.approx(0.4)
    assert view.current == "muscle" and not view.ready
    link.finish("emg", "cycle")
    assert drive(run, link, 5.0) == [Calibrate("eeg", "baseline")]
    link.finish("eeg", "baseline")
    assert drive(run, link, 9.0) == []
    view = run.view(link.view())
    assert view.ready and view.current is None


def test_pong_calibrates_both_hands_at_once_and_reports_them_separately() -> None:
    link = live(PONG)
    run = CalibrationRun(plan_for("pong"), fresh=False)
    assert drive(run, link, 0.0) == [
        Calibrate("emg_left", "cycle"),
        Calibrate("emg_right", "cycle"),
    ]
    link.running("emg_left", "cycle", 0.5, segment=3, phase="tense", phase_left_s=2.0)
    link.running("emg_right", "cycle", 0.25, segment=2, phase="relax", phase_left_s=1.0)
    link.fail("emg_right", "cycle", "сокращение слабое, нет отличия от покоя")
    link.finish("emg_left", "cycle")
    drive(run, link, 3.0)
    step = run.view(link.view()).steps[0]
    assert step.status == "failed"
    assert [(p.signal, p.status) for p in step.parts] == [
        ("emg_left", "done"),
        ("emg_right", "failed"),
    ]
    assert step.reason_text == TEXT_WEAK
    assert step.parts[1].reason_text == TEXT_WEAK
    assert not run.view(link.view()).ready


def test_pong_retry_of_one_hand_keeps_the_other() -> None:
    link = live(PONG, calibrated=("emg_left",))
    run = CalibrationRun(plan_for("pong"), fresh=False)
    drive(run, link, 0.0)
    link.fail("emg_right", "cycle", "нет данных в покое")
    drive(run, link, 1.0)
    commands = run.retry("emg_right", link.view(), 2.0)
    assert commands == [Calibrate("emg_right", "cycle")]
    assert run.view(link.view()).steps[0].parts[0].status == "done"
    assert run.view(link.view()).steps[0].parts[1].status == "running"


def test_failed_step_waits_for_a_retry_and_blocks_the_next() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    link.fail("emg", "cycle", "сокращение слабое, нет отличия от покоя")
    assert drive(run, link, 2.0) == []  # мозг не стартует, пока мышца провалена
    assert link.calls == [("calibrate", "emg", "cycle")]
    view = run.view(link.view())
    assert view.steps[0].status == "failed" and view.current == "muscle"
    assert run.retry("muscle", link.view(), 3.0) == [Calibrate("emg", "cycle")]
    assert run.view(link.view()).steps[0].status == "running"


def test_retry_by_signal_and_unknown_key() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert run.retry("eeg", link.view(), 0.0) == [Calibrate("eeg", "baseline")]
    assert run.retry("nonsense", link.view(), 0.0) == []


def test_recalibrating_a_done_step_is_possible() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    for command in run.retry("brain", link.view(), 0.0):
        assert isinstance(command, Calibrate)
        link.calibrate(command.signal, command.step)
    view = run.view(link.view())
    assert [s.status for s in view.steps] == ["done", "running"]
    assert not view.ready


def test_restart_resets_and_starts_from_the_first_step() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert run.restart(link.view(), 0.0) == [Reset(), Calibrate("emg", "cycle")]


def test_bridge_error_reason_is_shown_as_is() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    link.fail("emg", "cycle", "датчик отключён")
    drive(run, link, 1.0)
    assert run.view(link.view()).steps[0].reason_text == "датчик отключён"


# --- датчики, связь, тайм-ауты ---


def test_step_waits_until_the_sensor_is_connected() -> None:
    link = live({"eeg": "connected", "emg": "connecting"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == []
    link.states["emg"] = "connected"
    assert drive(run, link, 0.5) == [Calibrate("emg", "cycle")]


def test_nothing_is_sent_while_the_link_is_not_live() -> None:
    link = FakeLink()
    run = CalibrationRun(plan_for("darts"), fresh=True)
    assert drive(run, link, 0.0) == []
    link.link = "lost"
    assert drive(run, link, 1.0) == []


def test_silent_bridge_marks_steps_failed_after_the_wait_and_retry_extends_it() -> None:
    link = FakeLink()  # connecting
    run = CalibrationRun(plan_for("darts"), fresh=True)
    drive(run, link, 0.0)
    assert run.view(link.view()).steps[0].status == "pending"
    drive(run, link, LINK_WAIT_S)
    view = run.view(link.view())
    assert [s.status for s in view.steps] == ["failed", "failed"]
    assert view.steps[0].reason_text == BRIDGE_SILENT
    assert run.retry("muscle", link.view(), LINK_WAIT_S + 1) == []
    drive(run, link, LINK_WAIT_S + 2)
    assert run.view(link.view()).steps[0].status == "pending"
    drive(run, link, 2 * LINK_WAIT_S + 1)
    assert run.view(link.view()).steps[0].status == "failed"


def test_silent_bridge_that_appears_later_starts_calibration() -> None:
    link = FakeLink()
    run = CalibrationRun(plan_for("darts"), fresh=True)
    drive(run, link, 0.0)
    drive(run, link, 30.0)
    link.go_live(DARTS)
    assert drive(run, link, 31.0) == [Reset(), Calibrate("emg", "cycle")]
    assert run.view(link.view()).steps[0].status == "running"


def test_running_step_times_out_when_the_bridge_goes_quiet() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 44.9)
    assert run.view(link.view()).steps[0].status == "running"
    drive(run, link, 45.1)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", BRIDGE_SILENT)


def test_baseline_timeout_is_shorter() -> None:
    link = live(DARTS, calibrated=("emg",))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 29.1)
    assert run.view(link.view()).steps[1].status == "failed"


def test_losing_the_link_fails_the_running_step() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    link.running("emg", "cycle", 0.3)
    link.drop()
    drive(run, link, 3.0)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", LINK_DROPPED)
    assert not run.view(link.view()).ready


def test_bridge_restart_keeps_done_steps_and_rereads_the_rest() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    link.finish("emg", "cycle")
    drive(run, link, 5.0)  # мозг идёт
    link.drop()
    drive(run, link, 8.0)
    assert [s.status for s in run.view(link.view()).steps] == ["done", "failed"]
    # мост перезапустился и восстановил мышцу с диска
    link.go_live(DARTS, calibrated=("emg",), eeg_method="alpha")
    assert drive(run, link, 12.0) == []  # мозг провален: ждёт повтора
    assert [s.status for s in run.view(link.view()).steps] == ["done", "failed"]
    assert run.retry("brain", link.view(), 13.0) == [Calibrate("eeg", "baseline")]


def test_restored_bridge_that_forgot_a_signal_makes_its_step_pending_again() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.view(link.view()).ready
    link.drop()
    link.go_live(DARTS, calibrated=("emg",), eeg_method="emotions")  # emotions не восстановился
    assert drive(run, link, 5.0) == [Calibrate("eeg", "baseline")]
    assert [s.status for s in run.view(link.view()).steps] == ["done", "running"]


def test_stale_failed_status_from_the_bridge_is_ignored_until_we_ask() -> None:
    link = live(DARTS)
    link.progress["emg"] = StepProgress("cycle", "failed", 0.0, "старая причина")
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == [Calibrate("emg", "cycle")]


def test_sensors_view_lists_state_and_battery() -> None:
    link = live({"eeg": "connected", "emg": "connecting"})
    link.batteries["eeg"] = 81
    assert sensors_view(link.view()) == [
        {"signal": "eeg", "state": "connected", "battery": 81},
        {"signal": "emg", "state": "connecting", "battery": None},
    ]
