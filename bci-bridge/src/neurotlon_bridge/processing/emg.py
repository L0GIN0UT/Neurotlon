"""Обработка ЭМГ (Callibri): фильтры с состоянием, RMS, калибровка, уровень 0…1.

Порт из neuro-biathlon (проверено на железе). Чистый код: без SDK, потоков и часов;
время передаёт вызывающий (`now`, секунды любой монотонной шкалы).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import signal as sps

from ..source import (
    EMG_STEPS,
    MAX_PENDING_BURSTS,
    SEGMENT_MAX_S,
    SEGMENT_MIN_S,
    SEGMENTS_MAX_COUNT,
    SEGMENTS_MAX_TOTAL_S,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Reading,
    Segment,
)
from .burst import BurstConfig, BurstDetector
from .cycle import CycleTimeline, default_segments

Floats = NDArray[np.float64]

MIN_REST_POINTS = 5
NO_DATA_GRACE_S = 5.0
PEAK_PERCENTILE = 90.0
MAD_TO_SIGMA = 1.4826
WEAK_REASON = "сокращение слабое, нет отличия от покоя"


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
    calib_min_ratio: float = 2.0
    calib_noise_k: float = 4.0
    cycle_tense_s: float = 5.0
    cycle_relax_s: float = 5.0
    cycle_repeats: int = 2
    transition_s: float = 1.5

    def __post_init__(self) -> None:
        if self.cycle_tense_s <= 0 or self.cycle_relax_s <= 0:
            raise ValueError("cycle_tense_s и cycle_relax_s: нужны положительные числа")
        if self.cycle_repeats < 1:
            raise ValueError("cycle_repeats: нужно целое число не меньше 1")
        if not 0 <= self.transition_s < SEGMENT_MIN_S:
            raise ValueError(
                f"transition_s: нужно число от 0 до {SEGMENT_MIN_S:g} с (короче сегмента)"
            )
        if self.calib_noise_k < 0:
            raise ValueError("calib_noise_k: нужно число не меньше нуля")
        for name in ("cycle_tense_s", "cycle_relax_s"):
            if not SEGMENT_MIN_S <= getattr(self, name) <= SEGMENT_MAX_S:
                raise ValueError(
                    f"{name}: сегмент должен быть от {SEGMENT_MIN_S:g} до {SEGMENT_MAX_S:g} с"
                )
        if 2 * self.cycle_repeats > SEGMENTS_MAX_COUNT:
            raise ValueError(
                f"cycle_repeats: не больше {SEGMENTS_MAX_COUNT // 2} (по два сегмента)"
            )
        total = self.cycle_repeats * (self.cycle_tense_s + self.cycle_relax_s)
        if total > SEGMENTS_MAX_TOTAL_S:
            raise ValueError(f"шаг cycle длиннее {SEGMENTS_MAX_TOTAL_S:g} с: уменьшите ритм")


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
    timeline: CycleTimeline | None = None


class EmgProcessor:
    """Один канал ЭМГ: RMS, калибровка (покой + сокращения), уровень усилия.

    Не потокобезопасен: вызывающий сериализует доступ. Состояние одного канала
    никогда не делится с другим (у каждого Callibri свой экземпляр).
    """

    def __init__(
        self, cfg: EmgConfig, fs: float | None = None, burst: BurstConfig | None = None
    ) -> None:
        self.cfg = cfg
        self._rms = EmgRms(cfg, fs or cfg.fs_nominal)
        self._detector = BurstDetector(burst or BurstConfig(), cfg.rms_step_ms)
        self._bursts: deque[BurstEvent] = deque(maxlen=MAX_PENDING_BURSTS)
        self._contact = True
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

    def export_calibration(self) -> tuple[float, float] | None:
        """(rest, peak) готовой шкалы для сохранения на диск; нет калибровки - None."""
        if self.rest is None or self.peak is None:
            return None
        return self.rest, self.peak

    def restore_calibration(self, rest: float, peak: float) -> None:
        """Применить шкалу, прочитанную с диска; значения должны быть проверены (`peak > rest`)."""
        if not (math.isfinite(rest) and math.isfinite(peak) and 0 <= rest < peak):
            raise ValueError("шкала ЭМГ: нужны конечные числа и 0 <= rest < peak")
        self.rest = rest
        self.peak = peak
        self._run = None
        self._status = None

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
        self._drop_bursts()

    def set_contact(self, ok: bool) -> None:
        """Датчик отключён или нет контакта: события резкого сокращения не выдаются."""
        self._contact = ok
        if not ok:
            self._detector.skip(0)  # старые уровни не должны участвовать во взводе после возврата

    def drain_bursts(self) -> list[BurstEvent]:
        """События резкого сокращения с прошлого вызова."""
        out = list(self._bursts)
        self._bursts.clear()
        return out

    def _drop_bursts(self) -> None:
        self._detector.reset()
        self._bursts.clear()

    def _start_settle(self) -> None:
        self._settle_left = round(self.cfg.settle_s * self._rms.fs)
        self._drop_bursts()

    # --- калибровка ---
    def start_calibration(
        self,
        step: CalibrationStep,
        now: float,
        segments: tuple[Segment, ...] | None = None,
    ) -> None:
        """`segments` — ритм шага `cycle`; без него берётся ритм из настроек."""
        if step not in EMG_STEPS:
            raise ValueError(f"шаг {step} не подходит для ЭМГ")
        if step == "contract" and self.rest is None:
            self._run = None
            self._status = CalibrationProgress(step, "failed", 0.0, "сначала шаг rest")
            return
        self.peak = None  # любая новая калибровка делает старый максимум недействительным
        timeline: CycleTimeline | None = None
        if step == "rest":
            self.rest = None
            duration = self.cfg.calib_rest_s
        elif step == "cycle":
            self.rest = None
            timeline = CycleTimeline(segments or self._default_segments())
            duration = timeline.total_s
        else:
            duration = self.cfg.calib_contractions * self._segment_s()
        self._run = _Run(step, now, duration, None, [], timeline)
        self._status = self._running(self._run, 0.0, 0.0)

    def abort_calibration(self, reason: str) -> None:
        if self._run is not None:
            self._status = CalibrationProgress(self._run.step, "failed", 0.0, reason)
            self._run = None

    def calibration_status(self) -> CalibrationProgress | None:
        return self._status

    def _segment_s(self) -> float:
        return self.cfg.calib_contraction_s + self.cfg.calib_pause_s

    def _default_segments(self) -> tuple[Segment, ...]:
        cfg = self.cfg
        return default_segments(cfg.cycle_tense_s, cfg.cycle_relax_s, cfg.cycle_repeats)

    @staticmethod
    def _running(run: _Run, progress: float, elapsed_s: float) -> CalibrationProgress:
        """Ход шага; у `cycle` ещё номер сегмента, фаза и сколько секунд до её конца."""
        if run.timeline is None:
            return CalibrationProgress(run.step, "running", progress)
        pos = run.timeline.at(elapsed_s)
        return CalibrationProgress(
            run.step, "running", progress, None, pos.segment, pos.phase, pos.phase_left_s
        )

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
            self._detector.skip(values.size)
            return
        if values.size == 0:
            return
        self._last_rms = float(values[-1])
        self._detect_bursts(values, now)
        run = self._run
        if run is not None and run.points is not None:
            if run.started is None:
                run.started = now
            step_s = self.cfg.rms_step_ms / 1000.0
            for k, v in enumerate(values):
                run.points.append((now - (values.size - 1 - k) * step_s, float(v)))
        self.update(now)

    def _detect_bursts(self, values: Floats, now: float) -> None:
        """Точки RMS одной пачки -> события; время события — по номеру точки, не по приходу."""
        rest, peak = self.rest, self.peak
        if not self._contact or rest is None or peak is None or peak <= rest:
            self._detector.skip(values.size)
            return
        first = self._detector.count
        levels = np.clip((values - rest) / (peak - rest), 0.0, 1.0)
        step_s = self.cfg.rms_step_ms / 1000.0
        for hit in self._detector.push([float(v) for v in levels]):
            behind = values.size - 1 - (hit.index - first)
            self._bursts.append(BurstEvent(now - behind * step_s, hit.rise))

    def update(self, now: float) -> None:
        """Продвинуть калибровку по времени (вызывать и без данных)."""
        run = self._run
        if run is None:
            return
        if run.started is None:
            if now - run.requested > run.duration + self.cfg.settle_s + NO_DATA_GRACE_S:
                self.abort_calibration("нет данных от датчика")
            return
        elapsed = now - run.started
        progress = elapsed / run.duration
        if progress < 1.0:
            self._status = self._running(run, max(0.0, progress), max(0.0, elapsed))
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
        if run.step == "cycle":
            self._finish_cycle(run, points)
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

    def _finish_cycle(self, run: _Run, points: list[tuple[float, float]]) -> None:
        """Покой — медиана по расслаблениям, максимум — 90-й перцентиль по напряжениям.

        Сбой, если максимум не выше покоя в `calib_min_ratio` раз или отличается от покоя меньше,
        чем на `calib_noise_k` разбросов покоя: иначе шум без сокращения прошёл бы калибровку.

        Первые `transition_s` каждого сегмента (мышца ещё меняет состояние) в расчёт не идут.
        """
        assert run.started is not None
        assert run.timeline is not None
        relax: list[float] = []
        tense: list[float] = []
        for span in run.timeline.spans:
            lo = run.started + span.start_s + self.cfg.transition_s
            hi = run.started + span.end_s
            part = [v for t, v in points if lo <= t < hi]
            (relax if span.phase == "relax" else tense).extend(part)
        if len(relax) < MIN_REST_POINTS:
            self._status = CalibrationProgress("cycle", "failed", 0.0, "нет данных в покое")
            return
        if not tense:
            self._status = CalibrationProgress("cycle", "failed", 0.0, "нет данных при напряжении")
            return
        rest = float(np.median(relax))
        peak = float(np.percentile(tense, PEAK_PERCENTILE))
        spread = MAD_TO_SIGMA * float(np.median(np.abs(np.asarray(relax) - rest)))
        too_close = peak - rest < self.cfg.calib_noise_k * spread
        if peak <= rest * self.cfg.calib_min_ratio or too_close:
            self._status = CalibrationProgress("cycle", "failed", 0.0, WEAK_REASON)
            return
        self.rest = rest
        self.peak = peak
        self._status = CalibrationProgress("cycle", "done", 1.0)

    # --- выход ---
    def reading(self) -> Reading:
        if self._last_rms is None:
            return Reading(0.0, False, "stale")
        if self.rest is None or self.peak is None:
            return Reading(0.0, False, "not_calibrated")
        level = (self._last_rms - self.rest) / (self.peak - self.rest)
        return Reading(float(min(1.0, max(0.0, level))))
