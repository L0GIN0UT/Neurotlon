"""Эмулятор датчиков: значения задаются «нажатыми клавишами», без pygame."""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass

from .processing.burst import BurstConfig, BurstDetector
from .processing.cycle import CycleTimeline, default_segments
from .processing.eeg import EegConfig
from .processing.emg import EmgConfig
from .source import (
    MAX_PENDING_BURSTS,
    PROFILES,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    Reading,
    Segment,
    SensorState,
    steps_for,
)

EEG_RATE_PER_S = 0.5
EMG_RISE_TAU_S = 0.15
EMG_DECAY_TAU_S = 0.25
EMG_STEP_S = 0.02  # шаг уровня для детектора резких сокращений, как шаг RMS на железе
CALIBRATION_DURATION_S: dict[CalibrationStep, float] = {
    "rest": 5.0,
    "contract": 12.0,
    "baseline": float(EegConfig().calibration_s),
}
FAIL_KEY = "calib_fail"  # клавиша: идущая калибровка завершается сбоем


@dataclass
class _Run:
    step: CalibrationStep
    started: float
    duration_s: float  # в секундах калибровки, до умножения на скорость
    timeline: CycleTimeline | None = None
    failed: str | None = None


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
        emg: EmgConfig | None = None,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile: {profile}")
        self._signals = PROFILES[profile]
        self._clock = clock
        self._speed = speed
        self._lock = threading.Lock()
        self._keys: frozenset[str] = frozenset()
        self._values = {s: (0.5 if s == "eeg" else 0.0) for s in self._signals}
        self._runs: dict[str, _Run] = {}
        self._emg = emg or EmgConfig()
        cfg = burst or BurstConfig()
        emg_signals = [s for s in self._signals if s != "eeg"]
        self._detectors = {s: BurstDetector(cfg, EMG_STEP_S * 1000.0) for s in emg_signals}
        self._bursts: dict[str, deque[BurstEvent]] = {
            s: deque(maxlen=MAX_PENDING_BURSTS) for s in emg_signals
        }
        self._phase_s = 0.0  # сколько прошло от последней точки уровня

    def signals(self) -> tuple[str, ...]:
        return self._signals

    def set_keys(self, pressed: set[str]) -> None:
        with self._lock:
            self._keys = frozenset(pressed)
            if FAIL_KEY in self._keys:
                for run in self._runs.values():
                    if run.failed is None and self._progress(run) < 1.0:
                        run.failed = "сбой калибровки (клавиша эмулятора)"

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
        calibrating = self._calibrating(name)
        while offset <= dt_s + 1e-12:
            if calibrating:  # во время калибровки событий нет
                detector.skip(1)
                offset += EMG_STEP_S
                continue
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

    def start_calibration(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self._check(signal)
        timeline: CycleTimeline | None = None
        if step == "cycle":
            cfg = self._emg
            default = default_segments(cfg.cycle_tense_s, cfg.cycle_relax_s, cfg.cycle_repeats)
            timeline = CycleTimeline(segments or default)
            duration = timeline.total_s
        elif step == "baseline" and duration_s is not None:
            duration = duration_s
        else:
            duration = CALIBRATION_DURATION_S[step]
        with self._lock:
            self._runs[signal] = _Run(step, self._clock(), duration, timeline)

    def _calibrating(self, signal: str) -> bool:
        run = self._runs.get(signal)
        return (
            run is not None
            and run.failed is None
            and run.step in steps_for(signal)
            and self._progress(run) < 1.0
        )

    def _progress(self, run: _Run) -> float:
        return self._elapsed_s(run) / run.duration_s

    def _elapsed_s(self, run: _Run) -> float:
        return (self._clock() - run.started) * self._speed

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        self._check(signal)
        with self._lock:
            run = self._runs.get(signal)
            if run is None:
                return None
            step = run.step
            if step not in steps_for(signal):
                reason = f"шаг {step} не подходит для {signal}"
                return CalibrationProgress(step, "failed", 0.0, reason)
            if run.failed is not None:
                return CalibrationProgress(step, "failed", 0.0, run.failed)
            progress = self._progress(run)
            if progress >= 1.0:
                return CalibrationProgress(step, "done", 1.0)
            if run.timeline is None:
                return CalibrationProgress(step, "running", max(0.0, progress))
            pos = run.timeline.at(max(0.0, self._elapsed_s(run)))
            return CalibrationProgress(
                step, "running", max(0.0, progress), None, pos.segment, pos.phase, pos.phase_left_s
            )

    def is_calibrated(self, signal: str) -> bool:
        self._check(signal)
        return False  # калибровка не нужна: сигналы эмулятора действительны всегда

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
