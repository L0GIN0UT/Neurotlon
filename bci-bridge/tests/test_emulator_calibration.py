"""Калибровка эмулятора по времени: шаг `cycle`, длительность `baseline`, сбой по клавише."""

import pytest

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.processing.emg import EmgConfig
from neurotlon_bridge.source import CalibrationProgress, Segment


class FakeClock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


def make(
    profile: str = "darts", speed: float = 1.0, emg: EmgConfig | None = None
) -> tuple[EmulatedSource, FakeClock]:
    clock = FakeClock()
    return EmulatedSource(profile, clock, speed, emg=emg), clock


def status(src: EmulatedSource, signal: str = "emg") -> CalibrationProgress:
    result = src.calibration_status(signal)
    assert result is not None
    return result


def test_cycle_follows_the_default_rhythm() -> None:
    src, clock = make()
    src.start_calibration("emg", "cycle")
    first = status(src)
    assert (first.status, first.step, first.progress) == ("running", "cycle", 0.0)
    assert (first.segment, first.phase, first.phase_left_s) == (1, "tense", 5.0)
    clock.now += 7.0
    second = status(src)
    assert (second.segment, second.phase) == (2, "relax")
    assert second.phase_left_s == pytest.approx(3.0)
    assert second.progress == pytest.approx(0.35)
    clock.now += 8.0  # 15 с
    third = status(src)
    assert (third.segment, third.phase) == (4, "relax")
    clock.now += 5.0
    done = status(src)
    assert (done.status, done.progress) == ("done", 1.0)


def test_cycle_takes_a_custom_rhythm() -> None:
    src, clock = make()
    rhythm = (Segment("relax", 2.0), Segment("tense", 4.0))
    src.start_calibration("emg", "cycle", segments=rhythm)
    clock.now += 3.0
    mid = status(src)
    assert (mid.segment, mid.phase) == (2, "tense")
    assert mid.progress == pytest.approx(0.5)
    assert mid.phase_left_s == pytest.approx(3.0)
    clock.now += 3.0
    assert status(src).status == "done"


def test_cycle_rhythm_default_comes_from_emg_config() -> None:
    src, clock = make(emg=EmgConfig(cycle_tense_s=2.0, cycle_relax_s=3.0, cycle_repeats=1))
    src.start_calibration("emg", "cycle")
    clock.now += 4.0
    assert status(src).phase == "relax"
    clock.now += 1.0
    assert status(src).status == "done"


def test_cycle_speed_scales_time_and_phase_counter() -> None:
    src, clock = make(speed=4.0)
    src.start_calibration("emg", "cycle")
    clock.now += 2.0  # 8 с калибровки
    mid = status(src)
    assert (mid.segment, mid.phase) == (2, "relax")
    assert mid.phase_left_s == pytest.approx(2.0)
    clock.now += 3.0
    assert status(src).status == "done"


def test_pong_signals_get_independent_cycles() -> None:
    src, clock = make("pong")
    src.start_calibration("emg_left", "cycle")
    clock.now += 12.0
    src.start_calibration("emg_right", "cycle")
    assert status(src, "emg_left").segment == 3
    assert status(src, "emg_right").segment == 1


def test_cycle_is_wrong_for_eeg() -> None:
    src, _ = make()
    src.start_calibration("eeg", "cycle")
    assert status(src, "eeg").status == "failed"


def test_baseline_takes_twenty_seconds_by_default() -> None:
    src, clock = make()
    src.start_calibration("eeg", "baseline")
    clock.now += 19.0
    running = status(src, "eeg")
    assert running.status == "running"
    assert running.progress == pytest.approx(19 / 20)
    assert (running.segment, running.phase, running.phase_left_s) == (None, None, None)
    clock.now += 1.0
    assert status(src, "eeg").status == "done"


@pytest.mark.parametrize("duration", [5.0, 15.0, 30.0])
def test_baseline_duration_is_taken_from_the_request(duration: float) -> None:
    src, clock = make()
    src.start_calibration("eeg", "baseline", duration_s=duration)
    clock.now += duration - 0.5
    assert status(src, "eeg").status == "running"
    clock.now += 0.5
    assert status(src, "eeg").status == "done"


def test_baseline_duration_respects_speed() -> None:
    src, clock = make(speed=3.0)
    src.start_calibration("eeg", "baseline", duration_s=15.0)
    clock.now += 4.0
    assert status(src, "eeg").status == "running"
    clock.now += 1.0
    assert status(src, "eeg").status == "done"


def test_duration_and_segments_are_ignored_by_other_steps() -> None:
    src, clock = make()
    src.start_calibration("emg", "rest", segments=(Segment("tense", 2.0),), duration_s=30.0)
    clock.now += 5.0
    assert status(src).status == "done"


def test_fail_key_ends_the_running_step_with_failure() -> None:
    src, clock = make()
    src.start_calibration("emg", "cycle")
    clock.now += 3.0
    src.set_keys({"calib_fail"})
    failed = status(src)
    assert failed.status == "failed"
    assert failed.reason
    src.set_keys(set())
    clock.now += 30.0
    assert status(src).status == "failed"  # сбой не пропадает после отпускания клавиши


def test_fail_key_hits_every_running_signal() -> None:
    src, _ = make()
    src.start_calibration("emg", "cycle")
    src.start_calibration("eeg", "baseline")
    src.set_keys({"calib_fail"})
    assert status(src).status == "failed"
    assert status(src, "eeg").status == "failed"


def test_fail_key_does_not_break_a_finished_step() -> None:
    src, clock = make()
    src.start_calibration("emg", "rest")
    clock.now += 6.0
    src.set_keys({"calib_fail"})
    assert status(src).status == "done"


def test_fail_key_does_not_affect_a_step_started_after_it_was_released() -> None:
    src, clock = make()
    src.start_calibration("emg", "cycle")
    src.set_keys({"calib_fail"})
    src.set_keys(set())
    src.start_calibration("emg", "cycle")
    clock.now += 1.0
    assert status(src).status == "running"


def test_reset_clears_cycle() -> None:
    src, _ = make()
    src.start_calibration("emg", "cycle")
    src.reset()
    assert src.calibration_status("emg") is None
