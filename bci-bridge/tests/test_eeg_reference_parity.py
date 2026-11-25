"""Аудит ЭЭГ: `AlphaEngine` даёт те же значения, что рабочая реализация из neuro-biathlon
(выход моста - сосредоточение, то есть 1 минус `calm` эталона).

Эталон воспроизведён здесь по формулам neuro-biathlon (`signal/eeg_alpha.py`, `config.toml`
`[eeg_alpha]`) без импорта чужого репозитория. На записях BrainBit из neuro-biathlon (мкВ, смещение
0,2-0,4 В, 250 Гц) обе реализации совпали до 1e-9; тут то же самое на синтетическом сигнале.
"""

import numpy as np
from numpy.typing import NDArray
from scipy import signal as sps

from neurotlon_bridge.processing.alpha import AlphaConfig, AlphaEngine

FS = 250
STEP = 50  # 0,2 с
WINDOW = 500  # 2 с
CALIB_S = 12
DC_UV = (240_000.0, 340_000.0, 245_000.0, 250_000.0)  # как у настоящего BrainBit, мкВ

Signal = NDArray[np.float64]


class FakeClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def brain_like(seconds: float, alpha_scale: float = 1.0, seed: int = 5) -> Signal:
    """Сигнал (n, 4) в мкВ: медленно меняющаяся альфа 10 Гц, бета 20 Гц, шум и большое смещение."""
    rng = np.random.default_rng(seed)
    t = np.arange(round(seconds * FS)) / FS
    amp = alpha_scale * (6 + 14 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 5.0)))
    wave = amp * np.sin(2 * np.pi * 10 * t) + 7 * np.sin(2 * np.pi * 20 * t)
    data = wave[:, None] + rng.normal(0, 2.0, (t.size, 4)) + np.asarray(DC_UV)[None, :]
    return np.asarray(data, dtype=np.float64)


# --- эталон из neuro-biathlon -------------------------------------------------------------------


def _ref_sos() -> NDArray[np.float64]:
    band = sps.butter(4, [1, 40], btype="bandpass", fs=FS, output="sos")
    b, a = sps.iirnotch(50, 30, fs=FS)
    return np.asarray(np.vstack([band, sps.tf2sos(b, a)]))


def _ref_rel_alpha(x: Signal) -> float:
    f, p = sps.welch(x, fs=FS, nperseg=FS, noverlap=FS // 2, detrend="constant")
    total = p[(f >= 4) & (f <= 30)].sum()
    return float(p[(f >= 8) & (f <= 13)].sum() / total)


def reference_calm(uv: Signal, calib_s: int) -> tuple[tuple[float, float], list[float]]:
    """Границы калибровки и `calm` по окнам, закончившимся после калибровки (пригодные окна)."""
    sos = _ref_sos()
    zi = sps.sosfilt_zi(sos)[:, :, None] * uv[0][None, None, :]
    filt, _ = sps.sosfilt(sos, uv, axis=0, zi=zi)
    ends = list(range(WINDOW, len(uv) + 1, STEP))
    rel: dict[int, float] = {}
    for end in ends:
        w = filt[end - WINDOW : end, :2]
        if np.max(np.ptp(w, axis=0)) > 150 or np.max(np.abs(np.diff(w, axis=0))) > 80:
            continue
        rel[end] = float(np.mean([_ref_rel_alpha(w[:, 0]), _ref_rel_alpha(w[:, 1])]))
    calib_end = calib_s * FS
    values = [v for end, v in rel.items() if end <= calib_end]
    low, high = float(np.percentile(values, 5)), float(np.percentile(values, 50))
    calm = [float(np.clip((v - low) / (high - low), 0, 1)) for e, v in rel.items() if e > calib_end]
    return (low, high), calm


def run_engine(uv: Signal, batch: int) -> tuple[AlphaEngine, list[float]]:
    clock = FakeClock()
    engine = AlphaEngine(AlphaConfig(), FS, clock)
    engine.start_calibration(CALIB_S)
    calm: list[float] = []
    for i in range(0, len(uv), batch):
        clock.now += batch / FS
        before = engine.calibrated
        engine.push(uv[i : i + batch] * 1e-6)
        if before and (i + batch) % STEP < batch:  # шаг окна пройден в этой пачке
            res = engine.result()
            assert res.has_data and not res.artifact
            calm.append(res.concentration)
    return engine, calm


def test_engine_matches_reference_algorithm_on_the_same_input() -> None:
    uv = brain_like(40)
    (ref_low, ref_high), ref_calm = reference_calm(uv, CALIB_S)
    engine, calm = run_engine(uv, batch=50)
    bounds = engine.export_bounds()
    assert bounds is not None
    np.testing.assert_allclose(bounds, (ref_low, ref_high), rtol=1e-6)
    assert len(calm) == len(ref_calm)
    # выход моста - сосредоточение: инверсия эталонного calm (расслабления)
    np.testing.assert_allclose(calm, 1.0 - np.asarray(ref_calm), atol=1e-6)


def test_result_does_not_depend_on_batch_size() -> None:
    """Пачки BrainBit приходят по 1-2 отсчёта и пачками побольше: итог тот же."""
    uv = brain_like(30)
    bounds = {b: run_engine(uv, batch=b)[0].export_bounds() for b in (1, 2, 7, 50)}
    reference = bounds[50]
    assert reference is not None
    for b in (1, 2, 7):
        got = bounds[b]
        assert got is not None
        np.testing.assert_allclose(got, reference, rtol=1e-9)


def test_only_o1_and_o2_are_analysed() -> None:
    """Столбцы T3 и T4 (2 и 3) не влияют на альфу: считаются O1 и O2 (0 и 1)."""
    uv = brain_like(30)
    spoiled = uv.copy()
    spoiled[:, 2:] = np.random.default_rng(9).normal(0, 500.0, (len(uv), 2)) + 250_000.0
    a = run_engine(uv, batch=50)[0].export_bounds()
    b = run_engine(spoiled, batch=50)[0].export_bounds()
    assert a is not None and b is not None
    np.testing.assert_allclose(a, b, rtol=1e-12)


def test_dc_offset_of_the_sensor_is_irrelevant() -> None:
    """Смещение 0,3 В у настоящего BrainBit не должно менять шкалу (фильтр и detrend)."""
    uv = brain_like(30)
    shifted = uv + 50_000.0
    a = run_engine(uv, batch=50)[0].export_bounds()
    b = run_engine(shifted, batch=50)[0].export_bounds()
    assert a is not None and b is not None
    np.testing.assert_allclose(a, b, rtol=1e-4)


def test_more_alpha_gives_lower_concentration() -> None:
    """Направление шкалы: больше альфа-ритма (закрытые глаза) - ниже сосредоточение."""
    baseline = brain_like(CALIB_S + 2)
    clock = FakeClock()
    engine = AlphaEngine(AlphaConfig(), FS, clock)
    engine.start_calibration(CALIB_S)
    levels: dict[float, float] = {}
    stream = [baseline] + [brain_like(6, alpha_scale=s, seed=11) for s in (0.2, 1.0, 2.0)]
    scales = (None, 0.2, 1.0, 2.0)
    for scale, chunk in zip(scales, stream, strict=True):
        calm: list[float] = []
        for i in range(0, len(chunk), 50):
            clock.now += 0.2
            engine.push(chunk[i : i + 50] * 1e-6)
            if scale is not None and i >= 2 * FS:  # окно уже целиком из этого куска
                calm.append(engine.result().concentration)
        if scale is not None:
            levels[scale] = float(np.mean(calm))
    assert levels[0.2] > levels[1.0] > levels[2.0]
    assert levels[0.2] > 0.8  # альфа подавлена (как при концентрации): шкала почти упирается в 1
    assert levels[2.0] < 0.2  # много альфы: сосредоточения нет


def test_calibration_uses_5th_percentile_and_median() -> None:
    """Калибровка: 5-й перцентиль даёт 0, медиана даёт 1 (не 90-й: на рубеже было бы ~0,25)."""
    uv = brain_like(CALIB_S + 1)
    (low, high), _ = reference_calm(uv, CALIB_S)
    engine, _ = run_engine(uv, batch=50)
    bounds = engine.export_bounds()
    assert bounds is not None
    np.testing.assert_allclose(bounds, (low, high), rtol=1e-6)
    cfg = AlphaConfig()
    assert (cfg.calib_low_pct, cfg.calib_high_pct) == (5.0, 50.0)
