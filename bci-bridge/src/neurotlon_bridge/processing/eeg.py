"""Обработка ЭЭГ (BrainBit): сосредоточение 0…1 одним из двух методов.

Метод спрятан за `EegEngine`: `processing/emotions.py` (библиотека Emotions) и
`processing/alpha.py` (относительная альфа). Логика тестируется с подделкой.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from ..source import EEG_STEPS, CalibrationProgress, CalibrationStep, Reading


@dataclass(frozen=True)
class EegConfig:
    sampling_rate: int = 250
    process_win_freq: int = 25
    fft_window: int = 1000
    n_first_sec_skipped: int = 4
    num_wins_for_quality_avg: int = 125
    ampl_art_extremum_border: int = 25
    calibration_s: int = 20
    skip_wins_after_artifact: int = 10


@dataclass(frozen=True)
class EegResult:
    concentration: float  # 0..1, высокое значение - сосредоточен
    has_data: bool  # есть актуальное значение после калибровки (нет: окно не набрано, обрыв)
    artifact: bool  # артефакты: значение использовать нельзя


class EegEngine(Protocol):
    """Метод расчёта сосредоточения. Калибровка делается один раз на объект."""

    @property
    def calibrated(self) -> bool: ...

    @property
    def progress(self) -> float:
        """Ход калибровки 0…1."""
        ...

    @property
    def failure(self) -> str | None:
        """Причина провала калибровки (по-русски) или None."""
        ...

    def start_calibration(self, duration_s: float) -> None: ...

    def push(self, volts: NDArray[np.float64]) -> None:
        """Форма (n, 4), столбцы O1, O2, T3, T4, вольты."""

    def result(self) -> EegResult: ...

    def close(self) -> None: ...


@runtime_checkable
class PersistentEngine(Protocol):
    """Движок, чью калибровку можно сохранить и вернуть (`alpha`; `emotions` внутри библиотеки)."""

    def export_bounds(self) -> tuple[float, float] | None:
        """(low, high) готовой калибровки; нет - None."""
        ...

    def restore_bounds(self, low: float, high: float) -> None: ...


class EegProcessor:
    """Один канал ЭЭГ. Не потокобезопасен: вызывающий сериализует доступ."""

    def __init__(self, factory: Callable[[], EegEngine], calibration_s: float = 20.0) -> None:
        self._factory = factory
        self._calibration_s = calibration_s
        self._engine: EegEngine | None = None
        self._status: CalibrationProgress | None = None
        self._result: EegResult | None = None

    def start_calibration(self, step: CalibrationStep, duration_s: float | None = None) -> None:
        """`duration_s=None` — длительность из настроек (`EegConfig.calibration_s`)."""
        if step not in EEG_STEPS:
            raise ValueError(f"шаг {step} не подходит для ЭЭГ")
        self._close_engine()  # новый объект на каждую калибровку
        engine = self._factory()
        engine.start_calibration(self._calibration_s if duration_s is None else duration_s)
        self._engine = engine
        self._result = None
        self._status = CalibrationProgress("baseline", "running", 0.0)

    def push(self, volts: NDArray[np.float64]) -> None:
        engine = self._engine
        if engine is None or len(volts) == 0:
            return
        engine.push(volts)
        failure = engine.failure
        if failure is not None:
            self._status = CalibrationProgress("baseline", "failed", 0.0, failure)
            self._close_engine()
            return
        self._result = engine.result()
        if engine.calibrated:
            self._status = CalibrationProgress("baseline", "done", 1.0)
        else:
            progress = min(1.0, max(0.0, engine.progress))
            self._status = CalibrationProgress("baseline", "running", progress)

    @property
    def calibrated(self) -> bool:
        engine = self._engine
        return engine is not None and engine.calibrated

    def export_calibration(self) -> tuple[float, float] | None:
        """Границы шкалы для сохранения; движок не умеет или не откалиброван - None."""
        engine = self._engine
        if engine is None or not engine.calibrated or not isinstance(engine, PersistentEngine):
            return None
        return engine.export_bounds()

    def restore_calibration(self, low: float, high: float) -> bool:
        """Новый движок с готовой шкалой; False, если метод не умеет восстанавливаться."""
        engine = self._factory()
        if not isinstance(engine, PersistentEngine):
            engine.close()
            return False
        try:
            engine.restore_bounds(low, high)
        except ValueError:
            engine.close()
            return False
        self._close_engine()
        self._engine = engine
        self._result = None
        self._status = None
        return True

    def abort_calibration(self, reason: str) -> None:
        if self._status is not None and self._status.status == "running":
            self._status = CalibrationProgress("baseline", "failed", 0.0, reason)
            self._close_engine()

    def calibration_status(self) -> CalibrationProgress | None:
        return self._status

    def reading(self) -> Reading:
        engine = self._engine
        if engine is None or not engine.calibrated:
            return Reading(0.0, False, "not_calibrated")
        res = self._result
        if res is None or not res.has_data:
            return Reading(0.0, False, "stale")
        if res.artifact:
            return Reading(res.concentration, False, "artifact")
        return Reading(res.concentration)

    def reset(self) -> None:
        self._close_engine()
        self._status = None
        self._result = None

    def close(self) -> None:
        self.reset()

    def _close_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.close()
