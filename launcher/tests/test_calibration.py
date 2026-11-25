"""Оркестратор калибровки: план по дисциплине, подключение, отсчёты, шаги, повторы, тайм-ауты."""

from __future__ import annotations

import pytest

from neurotlon_launcher.bridge_link import Hello, StepProgress
from neurotlon_launcher.calibration import (
    BASELINE_DURATION_S,
    BRIDGE_SILENT,
    CONNECT_TIMEOUT,
    CONNECT_WAIT_S,
    COUNTDOWN_S,
    EEG_FAILED,
    EEG_GRACE_S,
    EEG_NO_DATA_S,
    LINK_DROPPED,
    LINK_WAIT_S,
    MISSING_AFTER_S,
    NO_EEG_DATA,
    SENSOR_MISSING,
    SENSOR_WAIT_S,
    TEXT_NO_SIGNAL,
    TEXT_WEAK,
    Calibrate,
    CalibrationRun,
    PlanStep,
    Reset,
    plan_for,
    reason_text,
)
from neurotlon_launcher.testing import FakeLink

DARTS = {"eeg": "connected", "emg": "connected"}
PONG = {"emg_left": "connected", "emg_right": "connected"}
CD = float(COUNTDOWN_S)


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
            link.calibrate(command.signal, command.step, command.duration_s)
    return list(commands)


def begin(run: CalibrationRun, link: FakeLink, now: float = 0.0) -> list[object]:
    """Пройти подключение и отсчёт первого шага; вернуть команды после отсчёта."""
    drive(run, link, now)
    return drive(run, link, now + CD)


# --- план ---


def test_darts_and_football_plan_emg_then_eeg() -> None:
    for discipline in ("darts", "football"):
        plan = plan_for(discipline)
        assert [(s.id, s.kind, s.signals, s.title) for s in plan] == [
            ("emg", "cycle", ("emg",), "Калибровка ЭМГ"),
            ("eeg", "baseline", ("eeg",), "Калибровка ЭЭГ"),
        ]
        assert [s.duration_s for s in plan] == [20.0, BASELINE_DURATION_S] == [20.0, 20.0]


def test_pong_plan_is_one_parallel_emg_step() -> None:
    (step,) = plan_for("pong")
    assert (step.id, step.kind, step.signals) == ("emg", "cycle", ("emg_left", "emg_right"))
    assert step.title == "Калибровка ЭМГ"
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


def test_texts_never_say_hand() -> None:
    for text in (TEXT_WEAK, TEXT_NO_SIGNAL, NO_EEG_DATA, EEG_FAILED, CONNECT_TIMEOUT):
        assert "рук" not in text.lower() and "мозг" not in text.lower()


# --- порядок: подключение, отсчёт, шаг ---


def test_fresh_run_resets_then_counts_down_then_starts_the_first_step_only() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))  # остатки прежнего участника
    run = CalibrationRun(plan_for("darts"), fresh=True)
    assert drive(run, link, 0.0) == [Reset()]
    assert link.calls == [("reset",)]  # `calibrate` до окончания отсчёта не уходит
    assert drive(run, link, CD - 0.1) == []
    assert drive(run, link, CD) == [Calibrate("emg", "cycle")]
    assert drive(run, link, CD + 0.1) == []  # шаг идёт, ЭЭГ ждёт своей очереди


def test_stages_follow_connecting_countdown_running_countdown_running_review() -> None:
    link = live({"eeg": "connecting", "emg": "connected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.view(link.view()).stage == "connecting"
    link.states["eeg"] = "connected"
    drive(run, link, 1.0)
    view = run.view(link.view())
    assert (view.stage, view.current) == ("countdown", "emg")
    assert view.steps[0].stage == "countdown" and view.steps[1].stage == "waiting"
    assert drive(run, link, 1.0 + CD) == [Calibrate("emg", "cycle")]
    assert run.view(link.view()).stage == "running"
    link.finish("emg", "cycle")
    assert drive(run, link, 8.0) == []
    view = run.view(link.view())
    assert (view.stage, view.current) == ("countdown", "eeg")
    assert view.steps[0].stage == "done"
    assert drive(run, link, 8.0 + CD) == [Calibrate("eeg", "baseline")]
    assert run.view(link.view()).stage == "running"
    link.finish("eeg", "baseline")
    drive(run, link, 20.0)
    view = run.view(link.view())
    assert (view.stage, view.ready, view.current) == ("review", True, None)


def test_countdown_shows_five_down_to_one_and_names_the_step() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    seen = []
    for second in range(COUNTDOWN_S):
        assert drive(run, link, float(second)) == []
        step = run.view(link.view()).steps[0]
        seen.append(step.countdown_s)
        assert (step.id, step.title, step.stage, step.phase) == (
            "emg",
            "Калибровка ЭМГ",
            "countdown",
            "countdown",
        )
    assert seen == [5, 4, 3, 2, 1]
    assert drive(run, link, CD) == [Calibrate("emg", "cycle")]
    started = run.view(link.view()).steps[0]
    assert started.countdown_s is None and started.stage == "running"


def test_countdown_starts_only_after_connection_is_complete() -> None:
    link = live({"eeg": "connecting", "emg": "connected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == [] and drive(run, link, 20.0) == []
    assert run.view(link.view()).steps[0].countdown_s is None
    link.states["eeg"] = "connected"
    drive(run, link, 21.0)
    assert run.view(link.view()).steps[0].countdown_s == 5


def test_connected_sensors_pass_the_connecting_phase_instantly() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    view = run.view(link.view())
    assert view.stage == "countdown"
    assert [s.status for s in view.sensors] == ["connected", "connected"]


def test_not_fresh_run_keeps_calibration_and_skips_ready_steps() -> None:
    link = live(DARTS, calibrated=("emg",))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert begin(run, link) == [Calibrate("eeg", "baseline")]
    assert ("reset",) not in link.calls


def test_not_fresh_with_everything_calibrated_is_ready_without_commands() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert drive(run, link, 0.0) == []
    view = run.view(link.view())
    assert view.ready and view.current is None and view.stage == "review"
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
    assert begin(run, link) == [Calibrate("emg", "cycle")]
    link.running("emg", "cycle", 0.4, segment=2, phase="relax", phase_left_s=3.0)
    view = run.view(link.view())
    emg = view.steps[0]
    assert (emg.status, emg.segment, emg.phase, emg.phase_left_s) == ("running", 2, "relax", 3.0)
    assert emg.progress == pytest.approx(0.4)
    assert view.current == "emg" and not view.ready
    link.finish("emg", "cycle")
    assert drive(run, link, 8.0) == []
    assert drive(run, link, 8.0 + CD) == [Calibrate("eeg", "baseline")]
    link.finish("eeg", "baseline")
    assert drive(run, link, 30.0) == []
    view = run.view(link.view())
    assert view.ready and view.current is None


def test_pong_calibrates_both_players_at_once_and_reports_them_separately() -> None:
    link = live(PONG)
    run = CalibrationRun(plan_for("pong"), fresh=False)
    assert begin(run, link) == [
        Calibrate("emg_left", "cycle"),
        Calibrate("emg_right", "cycle"),
    ]
    link.running("emg_left", "cycle", 0.5, segment=3, phase="tense", phase_left_s=2.0)
    link.running("emg_right", "cycle", 0.25, segment=2, phase="relax", phase_left_s=1.0)
    link.fail("emg_right", "cycle", "сокращение слабое, нет отличия от покоя")
    link.finish("emg_left", "cycle")
    drive(run, link, CD + 3.0)
    step = run.view(link.view()).steps[0]
    assert step.status == "failed"
    assert [(p.signal, p.status) for p in step.parts] == [
        ("emg_left", "done"),
        ("emg_right", "failed"),
    ]
    assert step.reason_text == TEXT_WEAK
    assert step.parts[1].reason_text == TEXT_WEAK
    assert not run.view(link.view()).ready


def test_pong_retry_of_one_player_keeps_the_other_and_counts_down_first() -> None:
    link = live(PONG, calibrated=("emg_left",))
    run = CalibrationRun(plan_for("pong"), fresh=False)
    begin(run, link)
    link.fail("emg_right", "cycle", "нет данных в покое")
    drive(run, link, 6.0)
    assert run.retry("emg_right", link.view(), 7.0) == []
    assert drive(run, link, 7.0) == []  # отсчёт перед повтором
    step = run.view(link.view()).steps[0]
    assert [p.status for p in step.parts] == ["done", "pending"]
    assert (step.stage, step.countdown_s) == ("countdown", 5)
    assert drive(run, link, 7.0 + CD) == [Calibrate("emg_right", "cycle")]
    assert run.view(link.view()).steps[0].parts[1].status == "running"


def test_failed_step_waits_for_a_retry_and_blocks_the_next() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    begin(run, link)
    link.fail("emg", "cycle", "сокращение слабое, нет отличия от покоя")
    assert drive(run, link, 8.0) == []  # ЭЭГ не стартует, пока ЭМГ провалена
    assert link.calls == [("calibrate", "emg", "cycle")]
    view = run.view(link.view())
    assert view.steps[0].status == "failed" and view.current == "emg"
    assert run.retry("muscle", link.view(), 9.0) == []  # прежнее имя шага тоже понимается
    assert drive(run, link, 9.0) == []
    assert run.view(link.view()).steps[0].countdown_s == 5
    assert drive(run, link, 9.0 + CD) == [Calibrate("emg", "cycle")]
    assert run.view(link.view()).steps[0].status == "running"


@pytest.mark.parametrize("key", ["eeg", "brain"])
def test_retry_only_eeg_keeps_emg_done(key: str) -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.retry(key, link.view(), 1.0) == []
    assert drive(run, link, 1.0) == []
    view = run.view(link.view())
    assert [s.status for s in view.steps] == ["done", "pending"]
    assert (view.stage, view.current, view.steps[1].countdown_s) == ("countdown", "eeg", 5)
    assert not view.ready
    assert drive(run, link, 1.0 + CD) == [Calibrate("eeg", "baseline")]
    assert [s.status for s in run.view(link.view()).steps] == ["done", "running"]


def test_retry_by_signal_and_unknown_key() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.retry("nonsense", link.view(), 1.0) == []
    assert drive(run, link, 1.0) == []
    assert run.view(link.view()).ready
    run.retry("emg", link.view(), 2.0)  # имя шага совпадает с именем сигнала
    drive(run, link, 2.0)
    assert [s.status for s in run.view(link.view()).steps] == ["pending", "done"]


def test_restart_resets_then_connects_and_counts_down_again() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.restart(link.view(), 1.0) == [Reset()]
    link.reset()
    assert run.view(link.view()).stage == "connecting"
    assert drive(run, link, 1.0) == []
    assert drive(run, link, 1.0 + CD) == [Calibrate("emg", "cycle")]


def test_bridge_error_reason_is_shown_as_is() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    begin(run, link)
    link.fail("emg", "cycle", "датчик отключён")
    drive(run, link, 7.0)
    assert run.view(link.view()).steps[0].reason_text == "датчик отключён"


# --- подключение датчиков ---


def test_connecting_lists_each_needed_sensor_with_its_status() -> None:
    link = live({"eeg": "connecting", "emg": "disconnected"})
    link.batteries["eeg"] = 70
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    sensors = run.view(link.view()).sensors
    assert [(s.signal, s.title, s.status) for s in sensors] == [
        ("emg", "ЭМГ", "connecting"),
        ("eeg", "ЭЭГ", "connecting"),
    ]
    drive(run, link, MISSING_AFTER_S)
    by_signal = {s.signal: s for s in run.view(link.view()).sensors}
    assert by_signal["emg"].status == "missing"  # выключенный датчик: не найден
    assert by_signal["eeg"].status == "connecting"
    assert by_signal["eeg"].battery == 70


def test_connect_timeout_gives_an_error_and_retry_extends_the_wait() -> None:
    link = live({"eeg": "connecting", "emg": "connected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, CONNECT_WAIT_S - 0.1)
    assert run.view(link.view()).connect_error is None
    drive(run, link, CONNECT_WAIT_S)
    view = run.view(link.view())
    assert view.connect_error == CONNECT_TIMEOUT and view.stage == "connecting"
    assert {s.signal: s.status for s in view.sensors}["eeg"] == "missing"
    assert link.calls == []  # калибровка не стартовала
    assert run.retry("connect", link.view(), CONNECT_WAIT_S + 1) == []
    assert run.view(link.view()).connect_error is None
    drive(run, link, CONNECT_WAIT_S + 2)
    assert run.view(link.view()).connect_error is None
    drive(run, link, 2 * CONNECT_WAIT_S + 1)
    assert run.view(link.view()).connect_error == CONNECT_TIMEOUT


def test_sensor_that_connects_after_the_timeout_still_starts_the_scenario() -> None:
    link = live({"eeg": "connecting", "emg": "connected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, CONNECT_WAIT_S + 1)
    link.states["eeg"] = "connected"
    drive(run, link, CONNECT_WAIT_S + 2)
    view = run.view(link.view())
    assert view.connect_error is None and view.stage == "countdown"


def test_restart_gives_connection_a_new_window() -> None:
    link = live({"eeg": "connecting", "emg": "connected"})
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, CONNECT_WAIT_S)
    run.restart(link.view(), CONNECT_WAIT_S + 1)
    drive(run, link, CONNECT_WAIT_S + 2)
    assert run.view(link.view()).connect_error is None


def test_pong_connecting_lists_both_players_sensors() -> None:
    link = live({"emg_left": "connected", "emg_right": "connecting"})
    run = CalibrationRun(plan_for("pong"), fresh=False)
    drive(run, link, 0.0)
    view = run.view(link.view())
    assert [(s.signal, s.title, s.status) for s in view.sensors] == [
        ("emg_left", "ЭМГ игрока 1 (слева)", "connected"),
        ("emg_right", "ЭМГ игрока 2 (справа)", "connecting"),
    ]
    assert view.stage == "connecting"


def test_nothing_is_sent_while_the_link_is_not_live() -> None:
    link = FakeLink()
    run = CalibrationRun(plan_for("darts"), fresh=True)
    assert drive(run, link, 0.0) == []
    assert [s.status for s in run.view(link.view()).sensors] == ["connecting", "connecting"]
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
    assert run.retry("emg", link.view(), LINK_WAIT_S + 1) == []
    drive(run, link, LINK_WAIT_S + 2)
    assert run.view(link.view()).steps[0].status == "pending"
    drive(run, link, 2 * LINK_WAIT_S + 1)
    assert run.view(link.view()).steps[0].status == "failed"


def test_silent_bridge_that_appears_later_starts_the_scenario() -> None:
    link = FakeLink()
    run = CalibrationRun(plan_for("darts"), fresh=True)
    drive(run, link, 0.0)
    drive(run, link, 30.0)
    link.go_live(DARTS)
    assert drive(run, link, 31.0) == [Reset()]
    assert drive(run, link, 31.0 + CD) == [Calibrate("emg", "cycle")]
    assert run.view(link.view()).steps[0].status == "running"


def test_sensor_lost_during_the_countdown_fails_the_step_after_the_wait() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    link.states["emg"] = "disconnected"
    assert drive(run, link, CD) == []  # отсчёт закончен, датчика нет: ждём
    assert run.view(link.view()).steps[0].stage == "waiting"
    drive(run, link, CD + SENSOR_WAIT_S)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", SENSOR_MISSING)


# --- тайм-ауты и ЭЭГ ---


def test_running_step_times_out_when_the_bridge_goes_quiet() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    begin(run, link)  # шаг ушёл в мост в момент CD
    drive(run, link, CD + 44.9)
    assert run.view(link.view()).steps[0].status == "running"
    drive(run, link, CD + 45.1)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", BRIDGE_SILENT)


def eeg_run() -> tuple[CalibrationRun, FakeLink]:
    """ЭМГ готова, ЭЭГ ушла в мост в момент `CD` (после подключения и отсчёта)."""
    link = live(DARTS, calibrated=("emg",))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert begin(run, link) == [Calibrate("eeg", "baseline")]
    return run, link


def test_eeg_without_any_bridge_progress_fails_after_five_seconds() -> None:
    run, link = eeg_run()
    drive(run, link, CD + EEG_NO_DATA_S - 0.1)
    assert run.view(link.view()).steps[1].status == "running"
    drive(run, link, CD + EEG_NO_DATA_S + 0.1)
    step = run.view(link.view()).steps[1]
    assert (step.status, step.reason_text) == ("failed", NO_EEG_DATA)


def test_eeg_window_is_measured_by_the_launcher_clock() -> None:
    run, link = eeg_run()
    link.running("eeg", "baseline", 0.0)  # мост ответил, но прогресс стоит
    drive(run, link, CD + BASELINE_DURATION_S / 2)
    step = run.view(link.view()).steps[1]
    assert step.status == "running"
    assert step.progress == pytest.approx(0.5)
    assert step.phase_left_s == pytest.approx(BASELINE_DURATION_S / 2)
    drive(run, link, CD + 40.0)
    assert run.view(link.view()).steps[1].status == "failed"


def test_eeg_that_does_not_finish_in_the_window_fails_with_a_clear_reason() -> None:
    run, link = eeg_run()
    link.running("eeg", "baseline", 0.3)
    drive(run, link, CD + BASELINE_DURATION_S + EEG_GRACE_S - 0.1)
    assert run.view(link.view()).steps[1].status == "running"
    drive(run, link, CD + BASELINE_DURATION_S + EEG_GRACE_S + 0.1)
    step = run.view(link.view()).steps[1]
    assert (step.status, step.reason_text) == ("failed", EEG_FAILED)


def test_only_eeg_is_retried_after_a_failure_and_it_counts_down_again() -> None:
    run, link = eeg_run()
    link.fail("eeg", "baseline", "плохой сигнал")
    drive(run, link, CD + 3.0)
    assert run.retry("eeg", link.view(), CD + 4.0) == []
    assert drive(run, link, CD + 4.0) == []
    view = run.view(link.view())
    assert [s.status for s in view.steps] == ["done", "pending"]
    assert (view.stage, view.steps[1].countdown_s) == ("countdown", 5)
    assert drive(run, link, CD + 4.0 + CD) == [Calibrate("eeg", "baseline")]
    assert link.calls.count(("calibrate", "emg", "cycle")) == 0
    assert run.view(link.view()).steps[1].status == "running"


def test_losing_the_link_fails_the_running_step() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    begin(run, link)
    link.running("emg", "cycle", 0.3)
    link.drop()
    drive(run, link, CD + 3.0)
    step = run.view(link.view()).steps[0]
    assert (step.status, step.reason_text) == ("failed", LINK_DROPPED)
    assert not run.view(link.view()).ready


def test_bridge_restart_keeps_done_steps_and_rereads_the_rest() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    begin(run, link)
    link.finish("emg", "cycle")
    drive(run, link, 8.0)
    drive(run, link, 8.0 + CD)  # ЭЭГ идёт
    link.drop()
    drive(run, link, 16.0)
    assert [s.status for s in run.view(link.view()).steps] == ["done", "failed"]
    # мост перезапустился и восстановил ЭМГ с диска
    link.go_live(DARTS, calibrated=("emg",), eeg_method="alpha")
    assert drive(run, link, 20.0) == []  # ЭЭГ провалена: ждёт повтора
    assert [s.status for s in run.view(link.view()).steps] == ["done", "failed"]
    assert run.retry("eeg", link.view(), 21.0) == []
    assert drive(run, link, 21.0) == []
    assert drive(run, link, 21.0 + CD) == [Calibrate("eeg", "baseline")]


def test_restored_bridge_that_forgot_a_signal_makes_its_step_pending_again() -> None:
    link = live(DARTS, calibrated=("emg", "eeg"))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    assert run.view(link.view()).ready
    link.drop()
    link.go_live(DARTS, calibrated=("emg",), eeg_method="emotions")  # emotions не восстановился
    assert drive(run, link, 5.0) == []
    assert drive(run, link, 5.0 + CD) == [Calibrate("eeg", "baseline")]
    assert [s.status for s in run.view(link.view()).steps] == ["done", "running"]


def test_stale_failed_status_from_the_bridge_is_ignored_until_we_ask() -> None:
    link = live(DARTS)
    link.progress["emg"] = StepProgress("cycle", "failed", 0.0, "старая причина")
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert begin(run, link) == [Calibrate("emg", "cycle")]


def test_failed_send_restarts_the_countdown_instead_of_sending_instantly() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    (command,) = run.update(link.view(), CD)
    run.command_failed(command)
    assert run.update(link.view(), CD + 0.1) == []
    assert run.view(link.view()).steps[0].countdown_s == 5
    assert run.update(link.view(), 2 * CD + 0.1) == [Calibrate("emg", "cycle")]


def test_bridge_reason_for_eeg_is_kept_and_a_bare_failure_gets_the_general_text() -> None:
    run, link = eeg_run()
    link.progress["eeg"] = StepProgress("baseline", "failed", 0.0, "плохой контакт")
    drive(run, link, CD + 3.0)
    assert run.view(link.view()).steps[1].reason_text == "плохой контакт"
    run, link = eeg_run()
    link.progress["eeg"] = StepProgress("baseline", "failed", 0.0, None)
    drive(run, link, CD + 3.0)
    assert run.view(link.view()).steps[1].reason_text == EEG_FAILED


def test_sensor_lost_during_countdown_resets_it_and_it_restarts_from_five() -> None:
    link = live(DARTS, calibrated=("emg",))
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 2.0)
    assert run.view(link.view()).steps[1].countdown_s == 3
    link.states["eeg"] = "disconnected"
    for second in (3.0, 6.0, 7.0):
        assert drive(run, link, second) == []  # цифры не доходят до нуля, `calibrate` не уходит
    step = run.view(link.view()).steps[1]
    assert (step.stage, step.countdown_s) == ("waiting", None)
    link.states["eeg"] = "connected"
    assert drive(run, link, 8.0) == []
    assert run.view(link.view()).steps[1].countdown_s == 5
    assert drive(run, link, 8.0 + CD - 0.1) == []
    assert drive(run, link, 8.0 + CD) == [Calibrate("eeg", "baseline")]


def test_bridge_lost_during_countdown_restarts_it_after_return() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 3.0)
    link.drop()
    drive(run, link, 4.0)
    link.go_live(DARTS, eeg_method="alpha")
    drive(run, link, 5.0)
    assert run.view(link.view()).steps[0].countdown_s == 5
    assert drive(run, link, 5.0 + CD - 0.1) == []
    assert drive(run, link, 5.0 + CD) == [Calibrate("emg", "cycle")]


def test_pong_with_one_sensor_gone_waits_for_both_before_counting() -> None:
    link = live(PONG)
    run = CalibrationRun(plan_for("pong"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 2.0)
    link.states["emg_right"] = "disconnected"
    assert drive(run, link, 3.0) == []
    assert run.view(link.view()).steps[0].stage == "waiting"
    assert drive(run, link, 3.0 + CD + 1) == []  # одного датчика мало: идти нельзя
    link.states["emg_right"] = "connected"
    drive(run, link, 20.0)
    assert run.view(link.view()).steps[0].countdown_s == 5
    assert drive(run, link, 20.0 + CD) == [
        Calibrate("emg_left", "cycle"),
        Calibrate("emg_right", "cycle"),
    ]


def test_eeg_duration_is_sent_only_when_the_bridge_declares_the_feature() -> None:
    run, link = eeg_run()
    assert link.durations["eeg"] is None  # у `FakeLink` по умолчанию возможности нет
    link = live(DARTS, calibrated=("emg",))
    assert link.hello is not None
    link.hello = Hello(link.hello.signals, ("calibration_state", "baseline_duration"), "alpha")
    run = CalibrationRun(plan_for("darts"), fresh=False)
    assert begin(run, link) == [Calibrate("eeg", "baseline", BASELINE_DURATION_S)]
    assert link.durations["eeg"] == BASELINE_DURATION_S


def test_retry_during_countdown_restarts_it_and_is_ignored_while_the_step_runs() -> None:
    link = live(DARTS)
    run = CalibrationRun(plan_for("darts"), fresh=False)
    drive(run, link, 0.0)
    drive(run, link, 3.0)
    assert run.view(link.view()).steps[0].countdown_s == 2
    assert run.retry("emg", link.view(), 3.0) == []
    drive(run, link, 3.0)
    assert run.view(link.view()).steps[0].countdown_s == 5
    assert drive(run, link, 3.0 + CD) == [Calibrate("emg", "cycle")]
    link.running("emg", "cycle", 0.4)
    assert run.retry("emg", link.view(), 10.0) == []
    assert run.retry("muscle", link.view(), 10.0) == []
    assert drive(run, link, 10.1) == []
    step = run.view(link.view()).steps[0]
    assert (step.status, step.stage) == ("running", "running")
    assert link.calls.count(("calibrate", "emg", "cycle")) == 1
