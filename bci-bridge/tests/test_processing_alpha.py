import numpy as np
import pytest
from numpy.typing import NDArray

from neurotlon_bridge.processing.alpha import (
    AlphaConfig,
    AlphaEngine,
    calibration_bounds,
    calm_value,
    relative_alpha,
    window_artifact,
)
from neurotlon_bridge.processing.eeg import EegProcessor

FS = 250
CFG = AlphaConfig()
Signal = NDArray[np.float64]


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def tone(hz: float, seconds: float, amp_uv: float = 20.0, noise_uv: float = 2.0) -> Signal:
    """Сигнал (n, 4) в вольтах: одинаковый синус и шум в каждом канале."""
    rng = np.random.default_rng(1)
    t = np.arange(round(seconds * FS)) / FS
    wave = amp_uv * np.sin(2 * np.pi * hz * t)[:, None] + rng.normal(0, noise_uv, (t.size, 4))
    return np.asarray(wave * 1e-6, dtype=np.float64)


def calibrating_signal(seconds: float) -> Signal:
    """Альфа 10 Гц с медленно меняющейся амплитудой на фоне 20 Гц: разброс для перцентилей."""
    rng = np.random.default_rng(3)
    t = np.arange(round(seconds * FS)) / FS
    alpha_amp = 5 + 15 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 4.0))
    wave = alpha_amp * np.sin(2 * np.pi * 10 * t) + 8 * np.sin(2 * np.pi * 20 * t)
    data = wave[:, None] + rng.normal(0, 1.5, (t.size, 4))
    return np.asarray(data * 1e-6, dtype=np.float64)


def feed(engine: AlphaEngine, clock: FakeClock, data: Signal, batch: int = 10) -> None:
    for i in range(0, len(data), batch):
        clock.now += batch / FS
        engine.push(data[i : i + batch])


def make_engine() -> tuple[AlphaEngine, FakeClock]:
    clock = FakeClock()
    return AlphaEngine(CFG, FS, clock), clock


def calibrated_engine(duration_s: float = 12.0) -> tuple[AlphaEngine, FakeClock]:
    engine, clock = make_engine()
    engine.start_calibration(duration_s)
    feed(engine, clock, calibrating_signal(duration_s + 1.0))
    assert engine.calibrated
    return engine, clock


def test_relative_alpha_high_for_10hz_low_for_20hz() -> None:
    t = np.arange(2 * FS) / FS
    alpha = relative_alpha(20 * np.sin(2 * np.pi * 10 * t), FS, CFG)
    beta = relative_alpha(20 * np.sin(2 * np.pi * 20 * t), FS, CFG)
    assert alpha > 0.8
    assert beta < 0.1


@pytest.mark.parametrize("bad", [np.zeros(2 * FS), np.zeros(3), np.full(2 * FS, np.nan)])
def test_relative_alpha_nan_without_data(bad: Signal) -> None:
    assert np.isnan(relative_alpha(bad, FS, CFG))


def test_window_artifact_ptp_and_jump() -> None:
    assert window_artifact(np.zeros((500, 2)), CFG) is None
    wide = np.zeros((500, 2))
    wide[250:, :] = 160.0
    assert window_artifact(wide, CFG) == "ptp"
    spike = np.zeros((500, 2))
    spike[100, 0] = 90.0  # размах 90 < 150, скачок 90 > 80
    assert window_artifact(spike, CFG) == "jump"


def test_calibration_bounds_percentiles_and_errors() -> None:
    values = [float(v) for v in range(1, 101)]
    low, high = calibration_bounds(values, CFG)
    assert low == pytest.approx(np.percentile(values, 5))
    assert high == pytest.approx(np.percentile(values, 50))
    with pytest.raises(ValueError, match="мало"):
        calibration_bounds([0.5] * 9, CFG)
    with pytest.raises(ValueError, match="разброса"):
        calibration_bounds([0.5] * 20, CFG)


def test_too_few_values_message_tells_what_to_do() -> None:
    with pytest.raises(ValueError, match="Расслабьтесь, смотрите на точку, повторите"):
        calibration_bounds([0.5] * 3, CFG)


def test_engine_rejects_band_above_nyquist() -> None:
    with pytest.raises(ValueError, match="половины"):
        AlphaEngine(AlphaConfig(band_high_hz=130.0), FS, FakeClock())


def test_calm_value_clipped() -> None:
    assert calm_value(0.2, 0.2, 0.6) == 0.0
    assert calm_value(0.4, 0.2, 0.6) == pytest.approx(0.5)
    assert calm_value(0.9, 0.2, 0.6) == 1.0
    assert calm_value(0.0, 0.2, 0.6) == 0.0


def test_not_calibrated_has_no_result() -> None:
    engine, clock = make_engine()
    feed(engine, clock, tone(10, 4))
    result = engine.result()
    assert (result.has_data, result.artifact) == (False, False)
    assert not engine.calibrated
    assert engine.progress == 0.0
    assert engine.failure is None


def test_progress_counts_samples_not_time() -> None:
    engine, clock = make_engine()
    engine.start_calibration(10.0)
    clock.now += 1000.0  # часы на ход калибровки не влияют
    engine.push(tone(10, 2.5))
    assert engine.progress == pytest.approx(0.25, abs=0.02)
    assert not engine.calibrated


def test_calibration_done_after_duration_samples_and_scale_direction() -> None:
    engine, clock = calibrated_engine(12.0)
    assert engine.progress == 1.0
    assert engine.failure is None
    feed(engine, clock, tone(10, 3.0, amp_uv=25, noise_uv=1))
    relaxed = engine.result()
    assert relaxed.has_data and not relaxed.artifact
    assert relaxed.calm == pytest.approx(1.0)  # много альфы: расслаблен
    feed(engine, clock, tone(20, 3.0, amp_uv=25, noise_uv=1))
    tense = engine.result()
    assert tense.has_data and not tense.artifact
    assert tense.calm == pytest.approx(0.0)  # альфы нет


def test_too_few_values_fails_calibration() -> None:
    engine, clock = make_engine()
    engine.start_calibration(3.0)  # окно 2 с набирается, значений выходит меньше 10
    feed(engine, clock, tone(10, 3.2))
    assert engine.failure is not None
    assert "мало" in engine.failure
    assert not engine.calibrated


def test_restart_calibration_clears_previous_state() -> None:
    engine, _ = calibrated_engine()
    engine.start_calibration(6.0)
    assert not engine.calibrated
    assert engine.failure is None
    assert engine.progress == 0.0


def test_large_swing_is_artifact() -> None:
    engine, clock = calibrated_engine()
    feed(engine, clock, tone(10, 2.0))
    swing = tone(10, 0.4)
    swing[40:90, :] += 400e-6  # размах далеко за 150 мкВ
    feed(engine, clock, swing)
    result = engine.result()
    assert (result.has_data, result.artifact) == (True, True)


def test_artifact_leaves_the_window_after_two_seconds() -> None:
    engine, clock = calibrated_engine()
    spike = tone(10, 0.4)
    spike[50, :] += 400e-6
    feed(engine, clock, spike)
    assert engine.result().artifact
    feed(engine, clock, tone(10, 2.6))
    assert not engine.result().artifact


def test_data_gap_restarts_window_and_gives_no_value() -> None:
    engine, clock = calibrated_engine()
    feed(engine, clock, tone(10, 3.0))
    assert engine.result().has_data
    clock.now += 0.31  # дольше 300 мс без данных
    engine.push(tone(10, 0.2))
    result = engine.result()
    assert (result.has_data, result.artifact) == (False, False)
    feed(engine, clock, tone(10, 2.5))  # окно набралось снова
    assert engine.result().has_data


def test_short_pause_does_not_restart_window() -> None:
    engine, clock = calibrated_engine()
    feed(engine, clock, tone(10, 3.0))
    clock.now += 0.25
    engine.push(tone(10, 0.2))
    assert engine.result().has_data


def test_wrong_shape_and_empty_push_ignored() -> None:
    engine, _ = make_engine()
    engine.push(np.zeros((0, 4)))
    engine.push(np.zeros((10, 2)))
    engine.close()
    assert engine.progress == 0.0


def test_processor_with_alpha_engine_reports_stale_and_failed() -> None:
    clock = FakeClock()
    proc = EegProcessor(lambda: AlphaEngine(CFG, FS, clock), calibration_s=12.0)
    proc.start_calibration("baseline")
    signal = calibrating_signal(13.0)
    for i in range(0, len(signal), 10):
        clock.now += 10 / FS
        proc.push(signal[i : i + 10])
    status = proc.calibration_status()
    assert status is not None and status.status == "done"
    clock.now += 0.31
    proc.push(tone(10, 0.2))
    assert proc.reading().reason == "stale"

    proc.start_calibration("baseline", 5.0)  # нулевой сигнал: значений для калибровки нет
    for _ in range(0, 5 * FS + 100, 10):
        clock.now += 10 / FS
        proc.push(np.zeros((10, 4)))
    failed = proc.calibration_status()
    assert failed is not None and failed.status == "failed"
    assert proc.reading().reason == "not_calibrated"
