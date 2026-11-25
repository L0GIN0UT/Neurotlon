"""Обработка ЭЭГ (BrainBit): расслабление 0…1 из библиотеки Emotions.

Сама библиотека спрятана за `EmotionsEngine`, поэтому логика тестируется с подделкой.
Реальная обёртка — `processing/emotions.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
    calibration_s: int = 12
    skip_wins_after_artifact: int = 10


@dataclass(frozen=True)
class EmotionsResult:
    calm: float  # 0..1
    has_data: bool  # есть хотя бы одно окно после калибровки
    artifact: bool  # артефакты с обеих сторон: значение использовать нельзя


class EmotionsEngine(Protocol):
    """Что нам нужно от Emotions. Калибровка делается один раз на объект."""

    @property
    def calibrated(self) -> bool: ...

    @property
    def calibration_percent(self) -> int: ...

    def set_calibration_length(self, seconds: int) -> None:
        """Длительность калибровки; вызывается до `start_calibration`."""
        ...

    def start_calibration(self) -> None: ...

    def push(self, volts: NDArray[np.float64]) -> None:
        """Форма (n, 4), столбцы O1, O2, T3, T4, вольты."""

    def result(self) -> EmotionsResult: ...

    def close(self) -> None: ...


class EegProcessor:
    """Один канал ЭЭГ. Не потокобезопасен: вызывающий сериализует доступ."""

    def __init__(self, factory: Callable[[], EmotionsEngine]) -> None:
        self._factory = factory
        self._engine: EmotionsEngine | None = None
        self._status: CalibrationProgress | None = None
        self._result: EmotionsResult | None = None

    def start_calibration(self, step: CalibrationStep, duration_s: float | None = None) -> None:
        """`duration_s=None` — длительность из настроек (`EegConfig.calibration_s`)."""
        if step not in EEG_STEPS:
            raise ValueError(f"шаг {step} не подходит для ЭЭГ")
        self._close_engine()  # новый объект на каждую калибровку
        engine = self._factory()
        if duration_s is not None:
            engine.set_calibration_length(max(1, round(duration_s)))
        engine.start_calibration()
        self._engine = engine
        self._result = None
        self._status = CalibrationProgress("baseline", "running", 0.0)

    def push(self, volts: NDArray[np.float64]) -> None:
        engine = self._engine
        if engine is None or len(volts) == 0:
            return
        engine.push(volts)
        self._result = engine.result()
        if engine.calibrated:
            self._status = CalibrationProgress("baseline", "done", 1.0)
        else:
            percent = min(100, max(0, engine.calibration_percent))
            self._status = CalibrationProgress("baseline", "running", percent / 100.0)

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
            return Reading(res.calm, False, "artifact")
        return Reading(res.calm)

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
