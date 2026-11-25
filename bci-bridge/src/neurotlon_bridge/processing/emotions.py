"""Обёртка библиотеки Emotions (pyem-st-artifacts 1.0.5). Библиотека импортируется лениво.

Биполярный режим: Left = T3 - O1, Right = T4 - O2 (вольты); сосредоточение = rel_attention / 100.
Пригодность — только по флагам артефактов: при артефактах библиотека повторяет последние числа.
"""

from __future__ import annotations

import contextlib
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .eeg import EegConfig, EegResult


class Pyem:
    def __init__(self, cfg: EegConfig) -> None:
        from em_st_artifacts.emotional_math import EmotionalMath
        from em_st_artifacts.utils.lib_settings import (
            ArtifactDetectSetting,
            MathLibSetting,
            MentalAndSpectralSetting,
            ShortArtifactDetectSetting,
        )

        math_settings = MathLibSetting(
            sampling_rate=cfg.sampling_rate,
            process_win_freq=cfg.process_win_freq,
            fft_window=cfg.fft_window,
            n_first_sec_skipped=cfg.n_first_sec_skipped,
            bipolar_mode=True,
            squared_spectrum=True,
            channels_number=4,
            channel_for_analysis=0,
        )
        art = ArtifactDetectSetting(
            hanning_win_spectrum=True, num_wins_for_quality_avg=cfg.num_wins_for_quality_avg
        )
        short = ShortArtifactDetectSetting(ampl_art_extremum_border=cfg.ampl_art_extremum_border)
        em: Any = EmotionalMath(math_settings, art, short, MentalAndSpectralSetting())
        em.set_mental_estimation_mode(False)
        em.set_skip_wins_after_artifact(cfg.skip_wins_after_artifact)
        em.set_zero_spect_waves(True, 0, 1, 1, 1, 0)
        em.set_spect_normalization_by_bands_width(True)
        self._em: Any = em
        self._started = False

    @property
    def calibrated(self) -> bool:
        return self._started and bool(self._em.calibration_finished())

    @property
    def progress(self) -> float:
        percent = int(self._em.get_calibration_percents()) if self._started else 0
        return min(100, max(0, percent)) / 100.0

    @property
    def failure(self) -> str | None:
        return None

    def start_calibration(self, duration_s: float) -> None:
        self._em.set_calibration_length(max(1, round(duration_s)))
        self._em.start_calibration()
        self._started = True

    def push(self, volts: NDArray[np.float64]) -> None:
        from em_st_artifacts.utils.support_classes import RawChannels

        if len(volts) == 0:
            return
        left = volts[:, 2] - volts[:, 0]
        right = volts[:, 3] - volts[:, 1]
        self._em.push_data(
            [RawChannels(float(a), float(b)) for a, b in zip(left, right, strict=True)]
        )
        self._em.process_data_arr()

    def result(self) -> EegResult:
        em = self._em
        if not self.calibrated or em.read_mental_data_arr_size() == 0:
            return EegResult(0.0, False, False)
        data = em.read_average_mental_data(1)
        concentration = min(1.0, max(0.0, float(data.rel_attention) / 100.0))
        return EegResult(concentration, True, bool(em.is_both_sides_artifacted()))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._em.__del__()  # нативные ресурсы освобождаем явно
