"""Обработка ЭМГ (Callibri): фильтры с состоянием, RMS, калибровка, уровень 0…1.

Порт из neuro-biathlon (проверено на железе). Чистый код: без SDK, потоков и часов;
время передаёт вызывающий (`now`, секунды любой монотонной шкалы).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import signal as sps

from ..source import CalibrationProgress, CalibrationStep, Reading

Floats = NDArray[np.float64]

EMG_STEPS: frozenset[CalibrationStep] = frozenset({"rest", "contract"})
MIN_REST_POINTS = 5
NO_DATA_GRACE_S = 5.0


@dataclass(frozen=True)
class EmgConfig:
    fs_nominal: int = 1000
    band_low_hz: float = 20.0
    band_high_hz: float = 450.0
    band_high_hz_500: float = 240.0
    notch_hz: float = 50.0
    notch_q: float = 30.0
    rms_window_ms: float = 100.0
    rms_step_ms: float = 20.0
    settle_s: float = 5.0
    calib_rest_s: float = 5.0
    calib_contractions: int = 3
    calib_contraction_s: float = 3.0
    calib_pause_s: float = 1.0
    calib_min_ratio: float = 1.0


def build_filters(cfg: EmgConfig, fs: float) -> tuple[Floats, Floats | None]:
    """Полосовой фильтр и режекция сети в виде SOS (режекции нет, если 50 Гц выше Найквиста)."""
    high = cfg.band_high_hz_500 if fs <= 600 else cfg.band_high_hz
    high = min(float(high), fs / 2 - 1.0)
    bandpass = sps.butter(4, [cfg.band_low_hz, high], btype="bandpass", fs=fs, output="sos")
    notch = None
    if 0 < cfg.notch_hz < fs / 2:
        b, a = sps.iirnotch(cfg.notch_hz, cfg.notch_q, fs=fs)
        notch = np.asarray(sps.tf2sos(b, a), dtype=float)
    return np.asarray(bandpass, dtype=float), notch


class EmgRms:
    """Потоковый фильтр 20-450 Гц + режекция 50 Гц + RMS в скользящем окне.

    Состояние фильтров сохраняется между вызовами `process`.
    """

    def __init__(self, cfg: EmgConfig, fs: float) -> None:
        self.fs = float(fs)
        self._bandpass, self._notch = build_filters(cfg, self.fs)
        self._win = max(1, round(self.fs * cfg.rms_window_ms / 1000.0))
        self._step = max(1, round(self.fs * cfg.rms_step_ms / 1000.0))
        self.reset()

    def reset(self) -> None:
        self._zi_bp: Floats = np.zeros((self._bandpass.shape[0], 2))
        self._zi_notch: Floats | None = (
            None if self._notch is None else np.zeros((self._notch.shape[0], 2))
        )
        self._tail: Floats = np.zeros(0)
        self._since_step = 0

    def process(self, samples_uv: Floats) -> Floats:
        """Отсчёты в микровольтах -> RMS (мкВ) по одному значению на шаг `rms_step_ms`."""
        x = np.asarray(samples_uv, dtype=float).ravel()
        if x.size == 0:
            return np.zeros(0)
        y, self._zi_bp = sps.sosfilt(self._bandpass, x, zi=self._zi_bp)
        if self._notch is not None and self._zi_notch is not None:
            y, self._zi_notch = sps.sosfilt(self._notch, y, zi=self._zi_notch)
        full = np.concatenate([self._tail, y])
        offset = self._tail.size
        out: list[float] = []
        pos = self._step - self._since_step
        while pos <= y.size:
            end = offset + pos
            seg = full[max(0, end - self._win) : end]
            out.append(float(np.sqrt(np.mean(seg * seg))))
            pos += self._step
        self._since_step = (self._since_step + y.size) % self._step
        self._tail = full[-self._win :].copy()
        return np.asarray(out, dtype=float)


@dataclass
class _Run:
    step: CalibrationStep
    requested: float
    duration: float
    started: float | None = None
    points: list[tuple[float, float]] | None = None


class EmgProcessor:
    """Один канал ЭМГ: RMS, калибровка (покой + сокращения), уровень усилия.

    Не потокобезопасен: вызывающий сериализует доступ. Состояние одного канала
    никогда не делится с другим (у каждого Callibri свой экземпляр).
    """

    def __init__(self, cfg: EmgConfig, fs: float | None = None) -> None:
        self.cfg = cfg
        self._rms = EmgRms(cfg, fs or cfg.fs_nominal)
        self.rest: float | None = None
        self.peak: float | None = None
        self._run: _Run | None = None
        self._status: CalibrationProgress | None = None
        self._last_rms: float | None = None
        self._settle_left = 0
        self._start_settle()

    @property
    def fs(self) -> float:
        return self._rms.fs

    @property
    def calibrated(self) -> bool:
        return self.rest is not None and self.peak is not None

    def set_fs(self, fs: float) -> None:
        """Фактическая частота устройства отличается от номинальной: пересобрать фильтры."""
        if fs != self._rms.fs:
            self._rms = EmgRms(self.cfg, fs)
            self._last_rms = None
            self._start_settle()

    def reset_stream(self) -> None:
        """Связь прервалась и вернулась: фильтры с нуля, сигнал снова оседает."""
        self._rms.reset()
        self._last_rms = None
        self._start_settle()
        self.abort_calibration("связь с датчиком прервалась")

    def reset(self) -> None:
        """Новый участник: калибровка стирается."""
        self.rest = None
        self.peak = None
        self._run = None
        self._status = None

    def _start_settle(self) -> None:
        self._settle_left = round(self.cfg.settle_s * self._rms.fs)

    # --- калибровка ---
    def start_calibration(self, step: CalibrationStep, now: float) -> None:
        if step not in EMG_STEPS:
            raise ValueError(f"шаг {step} не подходит для ЭМГ")
        if step == "contract" and self.rest is None:
            self._run = None
            self._status = CalibrationProgress(step, "failed", 0.0, "сначала шаг rest")
            return
        self.peak = None  # любая новая калибровка делает старый максимум недействительным
        if step == "rest":
            self.rest = None
            duration = self.cfg.calib_rest_s
        else:
            duration = self.cfg.calib_contractions * self._segment_s()
        self._run = _Run(step, now, duration, None, [])
        self._status = CalibrationProgress(step, "running", 0.0)

    def abort_calibration(self, reason: str) -> None:
        if self._run is not None:
            self._status = CalibrationProgress(self._run.step, "failed", 0.0, reason)
            self._run = None

    def calibration_status(self) -> CalibrationProgress | None:
        return self._status

    def _segment_s(self) -> float:
        return self.cfg.calib_contraction_s + self.cfg.calib_pause_s

    # --- поток данных ---
    def push(self, samples_uv: Floats, now: float) -> None:
        """Добавить пачку отсчётов (мкВ), пришедшую в момент `now`."""
        x = np.asarray(samples_uv, dtype=float).ravel()
        if x.size == 0:
            return
        values = self._rms.process(x)
        if self._settle_left > 0:
            # пока фильтр оседает, RMS отбрасываем: дрейф после подключения ложно «сокращает»
            self._settle_left -= min(self._settle_left, x.size)
            return
        if values.size == 0:
            return
        self._last_rms = float(values[-1])
        run = self._run
        if run is not None and run.points is not None:
            if run.started is None:
                run.started = now
            step_s = self.cfg.rms_step_ms / 1000.0
            for k, v in enumerate(values):
                run.points.append((now - (values.size - 1 - k) * step_s, float(v)))
        self.update(now)

    def update(self, now: float) -> None:
        """Продвинуть калибровку по времени (вызывать и без данных)."""
        run = self._run
        if run is None:
            return
        if run.started is None:
            if now - run.requested > run.duration + self.cfg.settle_s + NO_DATA_GRACE_S:
                self.abort_calibration("нет данных от датчика")
            return
        progress = (now - run.started) / run.duration
        if progress < 1.0:
            self._status = CalibrationProgress(run.step, "running", max(0.0, progress))
            return
        self._run = None
        self._finish(run)

    def _finish(self, run: _Run) -> None:
        points = run.points or []
        if run.step == "rest":
            if len(points) < MIN_REST_POINTS:
                self._status = CalibrationProgress("rest", "failed", 0.0, "нет данных в покое")
                return
            self.rest = float(np.median([v for _, v in points]))
            self._status = CalibrationProgress("rest", "done", 1.0)
            return
        assert run.started is not None
        assert self.rest is not None
        peaks: list[float] = []
        seg = self._segment_s()
        for i in range(self.cfg.calib_contractions):
            lo = run.started + i * seg
            part = [v for t, v in points if lo <= t < lo + seg]
            if part:
                peaks.append(max(part))
        if not peaks:
            self._status = CalibrationProgress("contract", "failed", 0.0, "нет данных")
            return
        peak = float(np.median(peaks))
        if peak <= self.rest * self.cfg.calib_min_ratio:
            reason = "слабое сокращение или плохой контакт"
            self._status = CalibrationProgress("contract", "failed", 0.0, reason)
            return
        self.peak = peak
        self._status = CalibrationProgress("contract", "done", 1.0)

    # --- выход ---
    def reading(self) -> Reading:
        if self._last_rms is None:
            return Reading(0.0, False, "stale")
        if self.rest is None or self.peak is None:
            return Reading(0.0, False, "not_calibrated")
        level = (self._last_rms - self.rest) / (self.peak - self.rest)
        return Reading(float(min(1.0, max(0.0, level))))
