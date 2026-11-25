"""Относительная альфа по O1 и O2: расслабление 0…1 без библиотеки Emotions.

Способ перенесён из проекта neuro-biathlon. Поток фильтруется (1-40 Гц, режекция 50 Гц), из
последних двух секунд берётся спектр Уэлча по каждому из каналов O1 и O2; мощность 8-13 Гц делится
на мощность 4-30 Гц, результат усредняется по двум каналам. Чем больше доля альфа-ритма, тем
спокойнее участник: значение растёт с расслаблением, как `rel_relaxation` у Emotions.

Калибровка идёт по числу отсчётов (а не по часам): за `duration_s` собирается столько значений
относительной альфы, сколько успело посчитаться. 5-й перцентиль уходит в 0, медиана в 1.
Расчёт спектра, артефактов и шкалы — чистые функции, класс `AlphaEngine` только держит состояние.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy import signal as sps

from ..source import Clock
from .eeg import EegResult

VOLTS_TO_MICROVOLTS = 1e6
CHANNELS = 4  # O1, O2, T3, T4; считаются только O1 и O2
ANALYSIS_CHANNELS = 2

Artifact = Literal["ptp", "jump"]


@dataclass(frozen=True)
class AlphaConfig:
    """Параметры из раздела `[alpha]` файла `bridge.toml`."""

    band_low_hz: float = 1.0
    band_high_hz: float = 40.0
    notch_hz: float = 50.0
    notch_q: float = 30.0
    window_s: float = 2.0
    step_s: float = 0.2
    alpha_low_hz: float = 8.0
    alpha_high_hz: float = 13.0
    total_low_hz: float = 4.0
    total_high_hz: float = 30.0
    artifact_ptp_uv: float = 150.0  # размах в окне после фильтрации
    artifact_jump_uv: float = 80.0  # скачок между соседними отсчётами
    gap_ms: float = 300.0  # обрыв данных: поток начинается заново
    calib_low_pct: float = 5.0  # перцентиль, дающий 0
    calib_high_pct: float = 50.0  # перцентиль (медиана), дающий 1
    calib_min_values: int = 10  # меньше значений калибровка не удалась

    def __post_init__(self) -> None:
        """Бессмысленные числа из `bridge.toml` оператор видит сразу, а не при калибровке."""
        if self.window_s <= 0 or self.step_s <= 0:
            raise ValueError("window_s и step_s должны быть больше нуля")
        if self.step_s > self.window_s:
            raise ValueError("step_s не может быть больше window_s")
        if not 0 < self.band_low_hz < self.band_high_hz:
            raise ValueError("band_low_hz должна быть больше нуля и меньше band_high_hz")
        if not self.alpha_low_hz < self.alpha_high_hz or not self.total_low_hz < self.total_high_hz:
            raise ValueError("границы диапазонов: нижняя должна быть меньше верхней")
        if not 0 <= self.calib_low_pct < self.calib_high_pct <= 100:
            raise ValueError("нужно 0 <= calib_low_pct < calib_high_pct <= 100")
        if self.gap_ms < 0:
            raise ValueError("gap_ms не может быть отрицательным")
        if self.calib_min_values < 1:
            raise ValueError("calib_min_values должно быть не меньше 1")


def relative_alpha(x_uv: NDArray[np.float64], fs: float, cfg: AlphaConfig) -> float:
    """Спектр Уэлча одного канала: мощность альфа ÷ мощность 4-30 Гц; не считается — `nan`."""
    x = np.asarray(x_uv, dtype=np.float64).ravel()
    if x.size < 8 or not bool(np.all(np.isfinite(x))):
        return float("nan")
    nperseg = min(x.size, int(fs))  # сегмент 1 с: разрешение 1 Гц
    freqs, power = sps.welch(x, fs=fs, nperseg=nperseg, noverlap=nperseg // 2, detrend="constant")
    total = float(power[(freqs >= cfg.total_low_hz) & (freqs <= cfg.total_high_hz)].sum())
    if not total > 0:
        return float("nan")
    alpha = float(power[(freqs >= cfg.alpha_low_hz) & (freqs <= cfg.alpha_high_hz)].sum())
    return alpha / total


def window_artifact(window_uv: NDArray[np.float64], cfg: AlphaConfig) -> Artifact | None:
    """Окно (n, 2) в мкВ после фильтра: большой размах или скачок между отсчётами."""
    if float(np.max(np.ptp(window_uv, axis=0))) > cfg.artifact_ptp_uv:
        return "ptp"
    if float(np.max(np.abs(np.diff(window_uv, axis=0)))) > cfg.artifact_jump_uv:
        return "jump"
    return None


def window_alpha(window_uv: NDArray[np.float64], fs: float, cfg: AlphaConfig) -> float:
    """Среднее относительной альфы по O1 и O2; не считается — `nan`."""
    values = [relative_alpha(window_uv[:, i], fs, cfg) for i in range(ANALYSIS_CHANNELS)]
    if not all(np.isfinite(values)):
        return float("nan")
    return float(np.mean(values))


def calibration_bounds(values: list[float], cfg: AlphaConfig) -> tuple[float, float]:
    """(low, high) по значениям спокойного состояния; нет значений или разброса - `ValueError`."""
    if len(values) < cfg.calib_min_values:
        raise ValueError(
            f"мало значений для калибровки: {len(values)} из {cfg.calib_min_values}. "
            "Расслабьтесь, смотрите на точку, повторите калибровку"
        )
    arr = np.asarray(values, dtype=np.float64)
    low = float(np.percentile(arr, cfg.calib_low_pct))
    high = float(np.percentile(arr, cfg.calib_high_pct))
    if not high > low:
        raise ValueError("нет разброса значений: расслабьтесь и смотрите на точку")
    return low, high


def calm_value(rel_alpha: float, low: float, high: float) -> float:
    """Шкала 0…1: `low` даёт 0, `high` даёт 1."""
    return float(np.clip((rel_alpha - low) / (high - low), 0.0, 1.0))


@dataclass(frozen=True)
class _Window:
    rel_alpha: float
    artifact: bool


class AlphaEngine:
    """Один поток ЭЭГ. Не потокобезопасен: вызывающий сериализует доступ (как `Pyem`)."""

    def __init__(self, cfg: AlphaConfig, fs: float, clock: Clock) -> None:
        if cfg.band_high_hz >= fs / 2:
            raise ValueError("band_high_hz должна быть меньше половины частоты дискретизации")
        self._cfg = cfg
        self._fs = float(fs)
        self._clock = clock
        self._window_n = round(cfg.window_s * self._fs)
        self._step_n = max(1, round(cfg.step_s * self._fs))
        self._gap_s = cfg.gap_ms / 1000.0
        band = sps.butter(
            4, [cfg.band_low_hz, cfg.band_high_hz], btype="bandpass", fs=self._fs, output="sos"
        )
        b, a = sps.iirnotch(cfg.notch_hz, cfg.notch_q, fs=self._fs)
        self._sos: NDArray[np.float64] = np.vstack([band, sps.tf2sos(b, a)])
        self._zi: NDArray[np.float64] | None = None
        self._buf: deque[NDArray[np.float64]] = deque(maxlen=self._window_n)
        self._since_step = 0
        self._last_push: float | None = None
        self._latest: _Window | None = None
        # калибровка
        self._target_n = 0
        self._seen_n = 0
        self._values: list[float] = []
        self._bounds: tuple[float, float] | None = None
        self._failure: str | None = None
        self._started = False

    @property
    def calibrated(self) -> bool:
        return self._bounds is not None

    @property
    def progress(self) -> float:
        if self._bounds is not None:
            return 1.0
        if not self._started or self._target_n == 0:
            return 0.0
        return min(1.0, self._seen_n / self._target_n)

    @property
    def failure(self) -> str | None:
        return self._failure

    def start_calibration(self, duration_s: float) -> None:
        self._target_n = max(1, round(duration_s * self._fs))
        self._seen_n = 0
        self._values = []
        self._bounds = None
        self._failure = None
        self._started = True

    def export_bounds(self) -> tuple[float, float] | None:
        return self._bounds

    def restore_bounds(self, low: float, high: float) -> None:
        if not (math.isfinite(low) and math.isfinite(high) and low < high):
            raise ValueError("границы калибровки: нужны конечные числа, low < high")
        self._bounds = (low, high)
        self._failure = None

    def push(self, volts: NDArray[np.float64]) -> None:
        """Форма (n, 4), столбцы O1, O2, T3, T4, вольты."""
        if len(volts) == 0 or volts.ndim != 2 or volts.shape[1] != CHANNELS:
            return
        now = self._clock()
        if self._last_push is not None and now - self._last_push > self._gap_s:
            self._restart_stream()
        self._last_push = now
        samples = np.asarray(volts[:, :ANALYSIS_CHANNELS], dtype=np.float64) * VOLTS_TO_MICROVOLTS
        if self._zi is None:
            # старт с установившегося состояния по первому отсчёту: меньше звона фильтра
            self._zi = sps.sosfilt_zi(self._sos)[:, :, None] * samples[0][None, None, :]
        start = 0
        while start < len(samples):
            take = min(len(samples) - start, self._step_n - self._since_step)
            chunk = samples[start : start + take]
            filtered, self._zi = sps.sosfilt(self._sos, chunk, axis=0, zi=self._zi)
            self._buf.extend(filtered)
            self._since_step += take
            start += take
            if self._started and not self.calibrated and self._failure is None:
                self._seen_n += take
            if self._since_step >= self._step_n:
                self._since_step = 0
                self._on_step()

    def result(self) -> EegResult:
        latest = self._latest
        if self._bounds is None or latest is None:
            return EegResult(0.0, False, False)
        if latest.artifact:
            return EegResult(0.0, True, True)
        if not np.isfinite(latest.rel_alpha):
            return EegResult(0.0, False, False)
        return EegResult(calm_value(latest.rel_alpha, *self._bounds), True, False)

    def close(self) -> None:
        """Нативных ресурсов нет."""

    def _restart_stream(self) -> None:
        """Обрыв данных: окно набирается заново, пока оно неполное, значения нет (`stale`)."""
        self._zi = None
        self._buf.clear()
        self._since_step = 0
        self._latest = None

    def _on_step(self) -> None:
        calibrating = self._started and self._bounds is None and self._failure is None
        if len(self._buf) >= self._window_n:
            window = np.asarray(self._buf)
            if window_artifact(window, self._cfg) is not None:
                self._latest = _Window(float("nan"), True)
            else:
                rel = window_alpha(window, self._fs, self._cfg)
                self._latest = _Window(rel, False)
                if calibrating and np.isfinite(rel):
                    self._values.append(rel)
        if calibrating and self._seen_n >= self._target_n:
            self._finish_calibration()

    def _finish_calibration(self) -> None:
        try:
            self._bounds = calibration_bounds(self._values, self._cfg)
        except ValueError as exc:
            self._failure = str(exc)
