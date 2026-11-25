"""Эмулятор датчиков: значения задаются «нажатыми клавишами», без pygame."""

from __future__ import annotations

import math
import threading
from collections import deque

from .processing.burst import BurstConfig, BurstDetector
from .source import (
    PROFILES,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    Reading,
    SensorState,
)

EEG_RATE_PER_S = 0.5
EMG_RISE_TAU_S = 0.15
EMG_DECAY_TAU_S = 0.25
EMG_STEP_S = 0.02  # шаг уровня для детектора резких сокращений, как шаг RMS на железе
MAX_PENDING_BURSTS = 64
CALIBRATION_DURATION_S: dict[CalibrationStep, float] = {
    "rest": 5.0,
    "contract": 12.0,
    "baseline": 8.0,
}
_EEG_STEPS: frozenset[CalibrationStep] = frozenset({"baseline"})
_EMG_STEPS: frozenset[CalibrationStep] = frozenset({"rest", "contract"})


def _approach(value: float, target: float, dt_s: float, tau_s: float) -> float:
    return target + (value - target) * math.exp(-dt_s / tau_s)


class EmulatedSource:
    """Потокобезопасен: окно вызывает `set_keys`/`tick`, сервер — `read`."""

    def __init__(
        self,
        profile: str,
        clock: Clock,
        speed: float = 1.0,
        burst: BurstConfig | None = None,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile: {profile}")
        self._signals = PROFILES[profile]
        self._clock = clock
        self._speed = speed
        self._lock = threading.Lock()
        self._keys: frozenset[str] = frozenset()
        self._values = {s: (0.5 if s == "eeg" else 0.0) for s in self._signals}
        self._runs: dict[str, tuple[CalibrationStep, float]] = {}
        cfg = burst or BurstConfig()
        emg = [s for s in self._signals if s != "eeg"]
        self._detectors = {s: BurstDetector(cfg, EMG_STEP_S * 1000.0) for s in emg}
        self._bursts: dict[str, deque[BurstEvent]] = {
            s: deque(maxlen=MAX_PENDING_BURSTS) for s in emg
        }
        self._phase_s = 0.0  # сколько прошло от последней точки уровня

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
                    self._tick_emg(name, dt_s)
            self._phase_s = (self._phase_s + dt_s) % EMG_STEP_S

    def _tick_emg(self, name: str, dt_s: float) -> None:
        """Уровень за `dt_s`; детектору отдаём точки через каждые `EMG_STEP_S`, как на железе."""
        held = name in self._keys
        tau = EMG_RISE_TAU_S if held else EMG_DECAY_TAU_S
        target = 1.0 if held else 0.0
        start = self._values[name]
        detector = self._detectors[name]
        now = self._clock()
        offset = EMG_STEP_S - self._phase_s  # до первой точки
        while offset <= dt_s + 1e-12:
            hits = detector.push([_approach(start, target, offset, tau)])
            for hit in hits:
                self._bursts[name].append(BurstEvent(now - (dt_s - offset), hit.rise))
            offset += EMG_STEP_S
        self._values[name] = _approach(start, target, dt_s, tau)

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        self._check(signal)
        with self._lock:
            queue = self._bursts.get(signal)
            if queue is None:
                return []
            out = list(queue)
            queue.clear()
            return out

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

    def battery(self, signal: str) -> int | None:
        self._check(signal)
        return None

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
            for detector in self._detectors.values():
                detector.reset()
            for queue in self._bursts.values():
                queue.clear()

    def _check(self, signal: str) -> None:
        if signal not in self._signals:
            raise ValueError(f"unknown signal: {signal}")
