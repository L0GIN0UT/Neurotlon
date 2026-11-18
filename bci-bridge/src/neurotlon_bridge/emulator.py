"""Эмулятор датчиков: значения задаются «нажатыми клавишами», без pygame."""

from __future__ import annotations

import math
import threading

from .source import (
    PROFILES,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    Reading,
    SensorState,
)

EEG_RATE_PER_S = 0.5
EMG_RISE_TAU_S = 0.15
EMG_DECAY_TAU_S = 0.25
CALIBRATION_DURATION_S: dict[CalibrationStep, float] = {
    "rest": 5.0,
    "contract": 3.0,
    "baseline": 8.0,
}
_EEG_STEPS: frozenset[CalibrationStep] = frozenset({"baseline"})
_EMG_STEPS: frozenset[CalibrationStep] = frozenset({"rest", "contract"})


def _approach(value: float, target: float, dt_s: float, tau_s: float) -> float:
    return target + (value - target) * math.exp(-dt_s / tau_s)


class EmulatedSource:
    """Потокобезопасен: окно вызывает `set_keys`/`tick`, сервер — `read`."""

    def __init__(self, profile: str, clock: Clock, speed: float = 1.0) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile: {profile}")
        self._signals = PROFILES[profile]
        self._clock = clock
        self._speed = speed
        self._lock = threading.Lock()
        self._keys: frozenset[str] = frozenset()
        self._values = {s: (0.5 if s == "eeg" else 0.0) for s in self._signals}
        self._runs: dict[str, tuple[CalibrationStep, float]] = {}

    def signals(self) -> tuple[str, ...]:
        return self._signals

    def set_keys(self, pressed: set[str]) -> None:
        with self._lock:
            self._keys = frozenset(pressed)

    def tick(self, dt_s: float) -> None:
        with self._lock:
            for name in self._signals:
                if name == "eeg":
                    direction = ("eeg_up" in self._keys) - ("eeg_down" in self._keys)
                    value = self._values[name] + direction * EEG_RATE_PER_S * dt_s
                    self._values[name] = min(1.0, max(0.0, value))
                else:
                    held = name in self._keys
                    tau = EMG_RISE_TAU_S if held else EMG_DECAY_TAU_S
                    target = 1.0 if held else 0.0
                    self._values[name] = _approach(self._values[name], target, dt_s, tau)

    def read(self, now_ms: int) -> dict[str, Reading]:
        with self._lock:
            out: dict[str, Reading] = {}
            for name in self._signals:
                value = min(1.0, max(0.0, self._values[name]))
                if name == "eeg" and "eeg_artifact" in self._keys:
                    out[name] = Reading(value, False, "artifact")
                else:
                    out[name] = Reading(value)
            return out

    def state(self, signal: str) -> SensorState:
        self._check(signal)
        return "emulated"

    def start_calibration(self, signal: str, step: CalibrationStep) -> None:
        self._check(signal)
        with self._lock:
            self._runs[signal] = (step, self._clock())

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        self._check(signal)
        with self._lock:
            run = self._runs.get(signal)
        if run is None:
            return None
        step, started = run
        allowed = _EEG_STEPS if signal == "eeg" else _EMG_STEPS
        if step not in allowed:
            return CalibrationProgress(step, "failed", 0.0, f"шаг {step} не подходит для {signal}")
        progress = (self._clock() - started) * self._speed / CALIBRATION_DURATION_S[step]
        if progress >= 1.0:
            return CalibrationProgress(step, "done", 1.0)
        return CalibrationProgress(step, "running", max(0.0, progress))

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()

    def _check(self, signal: str) -> None:
        if signal not in self._signals:
            raise ValueError(f"unknown signal: {signal}")
