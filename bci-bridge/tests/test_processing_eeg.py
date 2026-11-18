import numpy as np
import pytest
from numpy.typing import NDArray

from neurotlon_bridge.processing.eeg import EegProcessor, EmotionsResult


class FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.percent = 0
        self.pushed = 0
        self.closed = False
        self.res = EmotionsResult(0.5, True, False)

    @property
    def calibrated(self) -> bool:
        return self.started and self.percent >= 100

    @property
    def calibration_percent(self) -> int:
        return self.percent

    def start_calibration(self) -> None:
        self.started = True

    def push(self, volts: NDArray[np.float64]) -> None:
        self.pushed += len(volts)

    def result(self) -> EmotionsResult:
        return self.res

    def close(self) -> None:
        self.closed = True


def make() -> tuple[EegProcessor, list[FakeEngine]]:
    engines: list[FakeEngine] = []

    def factory() -> FakeEngine:
        engines.append(FakeEngine())
        return engines[-1]

    return EegProcessor(factory), engines


DATA = np.zeros((25, 4))


def test_not_calibrated_before_baseline() -> None:
    proc, engines = make()
    reading = proc.reading()
    assert (reading.valid, reading.reason) == (False, "not_calibrated")
    assert engines == []
    assert proc.calibration_status() is None


def test_calibration_progress_then_done() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    assert proc.calibration_status().progress == 0.0  # type: ignore[union-attr]
    engines[0].percent = 40
    proc.push(DATA)
    status = proc.calibration_status()
    assert status is not None
    assert (status.step, status.status, status.progress) == ("baseline", "running", 0.4)
    assert proc.reading().reason == "not_calibrated"
    engines[0].percent = 100
    proc.push(DATA)
    done = proc.calibration_status()
    assert done is not None
    assert (done.status, done.progress) == ("done", 1.0)
    assert engines[0].pushed == 50


def test_calm_maps_to_value() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    engines[0].res = EmotionsResult(0.73, True, False)
    proc.push(DATA)
    reading = proc.reading()
    assert reading.valid
    assert reading.value == pytest.approx(0.73)


def test_artifact_is_invalid() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    engines[0].res = EmotionsResult(0.9, True, True)
    proc.push(DATA)
    reading = proc.reading()
    assert (reading.valid, reading.reason) == (False, "artifact")


def test_no_windows_yet_is_stale() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    engines[0].res = EmotionsResult(0.0, False, False)
    proc.push(DATA)
    assert proc.reading().reason == "stale"


def test_recalibration_uses_new_engine_and_closes_old() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    proc.start_calibration("baseline")
    assert len(engines) == 2
    assert engines[0].closed
    assert not engines[1].closed


def test_reset_closes_engine_and_clears_state() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    proc.push(DATA)
    proc.reset()
    assert engines[0].closed
    assert proc.calibration_status() is None
    assert proc.reading().reason == "not_calibrated"


def test_abort_marks_running_calibration_failed() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    proc.abort_calibration("датчик отключён")
    status = proc.calibration_status()
    assert status is not None
    assert (status.status, status.reason) == ("failed", "датчик отключён")
    assert engines[0].closed


def test_abort_does_not_touch_finished_calibration() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    proc.push(DATA)
    proc.abort_calibration("x")
    assert proc.calibration_status().status == "done"  # type: ignore[union-attr]
    assert not engines[0].closed


def test_wrong_step_rejected() -> None:
    proc, _ = make()
    with pytest.raises(ValueError):
        proc.start_calibration("rest")


def test_empty_push_is_ignored() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    proc.push(np.zeros((0, 4)))
    assert engines[0].pushed == 0
