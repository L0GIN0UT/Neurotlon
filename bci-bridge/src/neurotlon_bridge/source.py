"""Интерфейс источника сигналов моста: датчики или эмулятор."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

SensorState = Literal["connecting", "connected", "disconnected", "emulated"]
InvalidReason = Literal["artifact", "no_contact", "disconnected", "stale", "not_calibrated"]
CalibrationStep = Literal["rest", "contract", "baseline"]
CalibrationStatus = Literal["running", "done", "failed"]

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
class CalibrationProgress:
    step: CalibrationStep
    status: CalibrationStatus
    progress: float = 0.0
    reason: str | None = None


class SignalSource(Protocol):
    def signals(self) -> tuple[str, ...]: ...

    def read(self, now_ms: int) -> dict[str, Reading]: ...

    def state(self, signal: str) -> SensorState: ...

    def start_calibration(self, signal: str, step: CalibrationStep) -> None: ...

    def calibration_status(self, signal: str) -> CalibrationProgress | None: ...

    def reset(self) -> None: ...
