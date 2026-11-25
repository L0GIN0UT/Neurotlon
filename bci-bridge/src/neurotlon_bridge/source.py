"""Интерфейс источника сигналов моста: датчики или эмулятор."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

SensorState = Literal["connecting", "connected", "disconnected", "emulated"]
InvalidReason = Literal["artifact", "no_contact", "disconnected", "stale", "not_calibrated"]
CalibrationStep = Literal["rest", "contract", "cycle", "baseline"]
CalibrationStatus = Literal["running", "done", "failed"]
Phase = Literal["tense", "relax"]
EegMethod = Literal["emotions", "alpha"]
Feature = Literal["burst", "emg_cycle", "baseline_duration"]

# Границы `calibrate.segments` и `calibrate.duration_s` (shared/bridge-protocol.schema.json;
# сумму длин схема выразить не может, её проверяет `protocol.calibrate_problem`).
SEGMENTS_MIN_COUNT = 2
SEGMENTS_MAX_COUNT = 8
SEGMENT_MIN_S = 2.0
SEGMENT_MAX_S = 15.0
SEGMENTS_MAX_TOTAL_S = 60.0
BASELINE_MIN_S = 5.0
BASELINE_MAX_S = 30.0

Clock = Callable[[], float]
"""Монотонные секунды."""

PROFILES: dict[str, tuple[str, ...]] = {
    "darts": ("eeg", "emg"),
    "football": ("eeg", "emg"),
    "pong": ("emg_left", "emg_right"),
}


@dataclass(frozen=True)
class Reading:
    """Значение сигнала от нуля до единицы; если valid ложно, использовать нельзя."""

    value: float
    valid: bool = True
    reason: InvalidReason | None = None


@dataclass(frozen=True)
class BurstEvent:
    """Резкое сокращение: `t_s` на шкале `Clock` источника, `rise` 0…1 только для показа."""

    t_s: float
    rise: float


@dataclass(frozen=True)
class Segment:
    """Отрезок шага `cycle`: напряжение или расслабление заданной длины."""

    phase: Phase
    s: float


@dataclass(frozen=True)
class CalibrationProgress:
    step: CalibrationStep
    status: CalibrationStatus
    progress: float = 0.0
    reason: str | None = None
    segment: int | None = None
    phase: Phase | None = None
    phase_left_s: float | None = None


class SignalSource(Protocol):
    def signals(self) -> tuple[str, ...]: ...

    def read(self, now_ms: int) -> dict[str, Reading]: ...

    def state(self, signal: str) -> SensorState: ...

    def battery(self, signal: str) -> int | None:
        """Заряд датчика в процентах; None, если неизвестен."""
        ...

    def start_calibration(self, signal: str, step: CalibrationStep) -> None: ...

    def calibration_status(self, signal: str) -> CalibrationProgress | None: ...

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        """События резкого сокращения с прошлого вызова; у сигналов без ЭМГ пусто."""
        ...

    def reset(self) -> None: ...
