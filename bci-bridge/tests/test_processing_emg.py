import numpy as np
import pytest

from neurotlon_bridge.processing.emg import EmgConfig, EmgProcessor, EmgRms

FS = 1000
CHUNK = 20  # 20 мс, как рабочий поток
REST_SIGMA = 3.0
BURST_SIGMA = 100.0


def fast_config(**over: float) -> EmgConfig:
    base = {"settle_s": 0.0, "calib_rest_s": 2.0, "calib_contractions": 3}
    base.update(over)
    return EmgConfig(**base)  # type: ignore[arg-type]


class Rig:
    """Подаёт в процессор синтетический сигнал кусками по 20 мс с чистым временем."""

    def __init__(self, proc: EmgProcessor, seed: int = 0) -> None:
        self.proc = proc
        self.rng = np.random.default_rng(seed)
        self.t = 0.0

    def feed(self, seconds: float, sigma: float) -> None:
        for _ in range(round(seconds * FS / CHUNK)):
            self.t += CHUNK / FS
            self.proc.push(self.rng.normal(0.0, sigma, CHUNK), self.t)
        self.proc.update(self.t)

    def calibrate(self) -> None:
        cfg = self.proc.cfg
        self.proc.start_calibration("rest", self.t)
        self.feed(cfg.calib_rest_s + 0.1, REST_SIGMA)
        assert self.proc.calibration_status() is not None
        assert self.proc.calibration_status().status == "done"  # type: ignore[union-attr]
        self.proc.start_calibration("contract", self.t)
        for _ in range(cfg.calib_contractions):
            self.feed(cfg.calib_contraction_s, BURST_SIGMA)
            self.feed(cfg.calib_pause_s, REST_SIGMA)
        self.feed(0.1, REST_SIGMA)


def test_rms_of_white_noise_tracks_sigma() -> None:
    rms = EmgRms(EmgConfig(), FS)
    out = rms.process(np.random.default_rng(1).normal(0, 50.0, 5 * FS))
    steady = out[50:]
    # полоса 20-450 Гц из 500 Гц: RMS около 0,93 sigma
    assert np.mean(steady) == pytest.approx(46.0, rel=0.1)
    assert len(out) == 5 * FS // CHUNK


def test_notch_removes_50_hz() -> None:
    t = np.arange(4 * FS) / FS
    mains = 100.0 * np.sin(2 * np.pi * 50.0 * t)
    with_notch = EmgRms(EmgConfig(), FS).process(mains)[100:]
    without = EmgRms(EmgConfig(notch_hz=0.0), FS).process(mains)[100:]
    assert np.mean(without) > 50.0
    assert np.mean(with_notch) < 0.1 * np.mean(without)


def test_streaming_is_independent_of_chunking() -> None:
    x = np.random.default_rng(2).normal(0, 20.0, 2 * FS)
    whole = EmgRms(EmgConfig(), FS).process(x)
    chunked_rms = EmgRms(EmgConfig(), FS)
    parts = [chunked_rms.process(x[i : i + 37]) for i in range(0, x.size, 37)]
    np.testing.assert_allclose(np.concatenate(parts), whole)


def test_rms_reset_clears_filter_state() -> None:
    rms = EmgRms(EmgConfig(), FS)
    x = np.random.default_rng(3).normal(0, 20.0, FS)
    first = rms.process(x)
    rms.reset()
    np.testing.assert_allclose(rms.process(x), first)


def test_500_hz_device_uses_lower_band() -> None:
    rms = EmgRms(EmgConfig(), 500)
    out = rms.process(np.random.default_rng(4).normal(0, 50.0, 2000))
    assert np.all(np.isfinite(out))


def test_before_data_reading_is_stale() -> None:
    reading = EmgProcessor(fast_config()).reading()
    assert (reading.valid, reading.reason) == (False, "stale")


def test_without_calibration_reading_is_not_calibrated() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.feed(1.0, REST_SIGMA)
    reading = rig.proc.reading()
    assert (reading.valid, reading.reason) == (False, "not_calibrated")


def test_calibration_flow_and_levels() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.calibrate()
    assert rig.proc.calibrated
    rig.feed(1.0, REST_SIGMA)
    resting = rig.proc.reading()
    assert resting.valid
    assert resting.value < 0.15
    rig.feed(1.0, BURST_SIGMA)
    burst = rig.proc.reading()
    assert burst.valid
    assert 0.6 < burst.value <= 1.0


def test_calibration_progress_is_reported() -> None:
    rig = Rig(EmgProcessor(fast_config(calib_rest_s=4.0)))
    rig.proc.start_calibration("rest", rig.t)
    assert rig.proc.calibration_status().progress == 0.0  # type: ignore[union-attr]
    rig.feed(2.0, REST_SIGMA)
    status = rig.proc.calibration_status()
    assert status is not None
    assert (status.step, status.status) == ("rest", "running")
    assert 0.3 < status.progress < 0.7
    rig.feed(2.1, REST_SIGMA)
    done = rig.proc.calibration_status()
    assert done is not None
    assert (done.status, done.progress) == ("done", 1.0)


def test_level_is_clipped_to_unit_range() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.calibrate()
    rig.feed(1.0, BURST_SIGMA * 20)
    assert rig.proc.reading().value == 1.0


def test_contract_before_rest_fails() -> None:
    proc = EmgProcessor(fast_config())
    proc.start_calibration("contract", 0.0)
    status = proc.calibration_status()
    assert status is not None
    assert (status.status, status.reason) == ("failed", "сначала шаг rest")


def test_weak_contraction_fails() -> None:
    rig = Rig(EmgProcessor(fast_config(calib_min_ratio=3.0)))
    rig.proc.start_calibration("rest", rig.t)
    rig.feed(2.1, REST_SIGMA)
    rig.proc.start_calibration("contract", rig.t)
    rig.feed(12.1, REST_SIGMA * 1.5)  # руку не напрягали
    status = rig.proc.calibration_status()
    assert status is not None
    assert status.status == "failed"
    assert not rig.proc.calibrated
    assert rig.proc.reading().reason == "not_calibrated"


def test_new_rest_invalidates_old_peak() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.calibrate()
    rig.proc.start_calibration("rest", rig.t)
    assert not rig.proc.calibrated


def test_rest_without_data_times_out() -> None:
    proc = EmgProcessor(fast_config())
    proc.start_calibration("rest", 0.0)
    proc.update(100.0)
    status = proc.calibration_status()
    assert status is not None
    assert status.status == "failed"


def test_settling_samples_are_not_used() -> None:
    rig = Rig(EmgProcessor(fast_config(settle_s=2.0)))
    rig.feed(1.0, REST_SIGMA)
    assert rig.proc.reading().reason == "stale"
    rig.feed(1.5, REST_SIGMA)
    assert rig.proc.reading().reason == "not_calibrated"


def test_unknown_step_rejected() -> None:
    with pytest.raises(ValueError):
        EmgProcessor(fast_config()).start_calibration("baseline", 0.0)


def test_reset_clears_calibration() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.calibrate()
    rig.proc.reset()
    assert not rig.proc.calibrated
    assert rig.proc.calibration_status() is None


def test_reset_stream_keeps_calibration_but_restarts_filters() -> None:
    rig = Rig(EmgProcessor(fast_config(settle_s=1.0)))
    rig.feed(1.1, REST_SIGMA)
    rig.proc.start_calibration("rest", rig.t)
    rig.feed(2.1, REST_SIGMA)
    rig.proc.start_calibration("contract", rig.t)
    rig.feed(5.0, BURST_SIGMA)
    rig.proc.reset_stream()  # связь пропала посреди калибровки
    status = rig.proc.calibration_status()
    assert status is not None
    assert (status.step, status.status) == ("contract", "failed")
    assert rig.proc.rest is not None
    assert rig.proc.reading().reason == "stale"
    rig.feed(0.5, REST_SIGMA)
    assert rig.proc.reading().reason == "stale"  # снова оседает


def test_set_fs_rebuilds_filters() -> None:
    proc = EmgProcessor(fast_config())
    proc.set_fs(500)
    assert proc.fs == 500
    proc.push(np.random.default_rng(5).normal(0, 5.0, 500), 1.0)
    assert proc.reading().reason == "not_calibrated"


def test_default_min_ratio_requires_peak_twice_the_rest() -> None:
    assert EmgConfig().calib_min_ratio == 2.0
    rig = Rig(EmgProcessor(fast_config()))
    rig.proc.start_calibration("rest", rig.t)
    rig.feed(2.1, REST_SIGMA)
    rig.proc.start_calibration("contract", rig.t)
    rig.feed(12.1, REST_SIGMA * 1.5)
    assert rig.proc.calibration_status().status == "failed"  # type: ignore[union-attr]


def test_contract_progress_covers_twelve_second_window() -> None:
    rig = Rig(EmgProcessor(fast_config()))
    rig.proc.start_calibration("rest", rig.t)
    rig.feed(2.1, REST_SIGMA)
    rig.proc.start_calibration("contract", rig.t)
    rig.feed(6.0, BURST_SIGMA)
    status = rig.proc.calibration_status()
    assert status is not None
    assert status.progress == pytest.approx(0.5, abs=0.03)
    rig.feed(6.2, REST_SIGMA)
    assert rig.proc.calibration_status().status == "done"  # type: ignore[union-attr]
