import numpy as np
import pytest
from numpy.typing import NDArray

from neurotlon_bridge.processing.eeg import EegProcessor, EegResult


class FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.percent = 0
        self.fail: str | None = None
        self.duration_s: float | None = None
        self.pushed = 0
        self.closed = False
        self.res = EegResult(0.5, True, False)

    @property
    def calibrated(self) -> bool:
        return self.started and self.percent >= 100

    @property
    def progress(self) -> float:
        return self.percent / 100.0

    @property
    def failure(self) -> str | None:
        return self.fail

    def start_calibration(self, duration_s: float) -> None:
        self.started = True
        self.duration_s = duration_s

    def push(self, volts: NDArray[np.float64]) -> None:
        self.pushed += len(volts)

    def result(self) -> EegResult:
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
    engines[0].res = EegResult(0.73, True, False)
    proc.push(DATA)
    reading = proc.reading()
    assert reading.valid
    assert reading.value == pytest.approx(0.73)


def test_artifact_is_invalid() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    engines[0].res = EegResult(0.9, True, True)
    proc.push(DATA)
    reading = proc.reading()
    assert (reading.valid, reading.reason) == (False, "artifact")


def test_no_windows_yet_is_stale() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].percent = 100
    engines[0].res = EegResult(0.0, False, False)
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


def test_default_duration_comes_from_settings_and_can_be_overridden() -> None:
    engines: list[FakeEngine] = []

    def factory() -> FakeEngine:
        engines.append(FakeEngine())
        return engines[-1]

    proc = EegProcessor(factory, calibration_s=12.0)
    proc.start_calibration("baseline")
    proc.start_calibration("baseline", 15.0)
    assert [e.duration_s for e in engines] == [12.0, 15.0]


def test_engine_failure_fails_calibration_and_closes_engine() -> None:
    proc, engines = make()
    proc.start_calibration("baseline")
    engines[0].fail = "мало значений"
    proc.push(DATA)
    status = proc.calibration_status()
    assert status is not None
    assert (status.status, status.reason) == ("failed", "мало значений")
    assert engines[0].closed
    assert proc.reading().reason == "not_calibrated"


def test_pyem_passes_whole_seconds_to_the_library() -> None:
    from typing import Any

    from neurotlon_bridge.processing.emotions import Pyem

    calls: list[tuple[str, int | None]] = []

    class FakeMath:
        def set_calibration_length(self, seconds: int) -> None:
            calls.append(("length", seconds))

        def start_calibration(self) -> None:
            calls.append(("start", None))

    pyem = Pyem.__new__(Pyem)  # без загрузки библиотеки
    em: Any = FakeMath()
    pyem._em = em
    pyem.start_calibration(12.4)
    assert calls == [("length", 12), ("start", None)]


def test_emotions_output_is_attention_not_relaxation() -> None:
    """`emotions`: eeg = rel_attention / 100, как у `alpha` высокое значение - сосредоточен."""
    from types import SimpleNamespace

    from neurotlon_bridge.processing.emotions import Pyem

    class FakeLib:
        def calibration_finished(self) -> bool:
            return True

        def read_mental_data_arr_size(self) -> int:
            return 1

        def read_average_mental_data(self, _n: int) -> SimpleNamespace:
            return SimpleNamespace(rel_attention=80.0, rel_relaxation=20.0)

        def is_both_sides_artifacted(self) -> bool:
            return False

    engine = object.__new__(Pyem)
    engine._em = FakeLib()
    engine._started = True
    result = engine.result()
    assert result.has_data and not result.artifact
    assert result.concentration == pytest.approx(0.8)
