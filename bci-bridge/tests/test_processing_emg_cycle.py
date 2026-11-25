"""Шаг `cycle` калибровки ЭМГ: фазы, статистика без переходов, сбои."""

import numpy as np
import pytest

from neurotlon_bridge.processing.emg import EmgConfig, EmgProcessor
from neurotlon_bridge.source import Segment

FS = 1000
CHUNK = 20
REST_SIGMA = 3.0
STRONG_SIGMA = 100.0
RHYTHM = (
    Segment("tense", 3.0),
    Segment("relax", 3.0),
    Segment("tense", 3.0),
    Segment("relax", 3.0),
)


def config(**over: float) -> EmgConfig:
    base: dict[str, float] = {"settle_s": 0.0, "transition_s": 1.0}
    base.update(over)
    return EmgConfig(**base)  # type: ignore[arg-type]


class Rig:
    def __init__(self, cfg: EmgConfig | None = None, seed: int = 0) -> None:
        self.proc = EmgProcessor(cfg or config())
        self.rng = np.random.default_rng(seed)
        self.t = 0.0

    def feed(self, seconds: float, sigma: float) -> None:
        for _ in range(round(seconds * FS / CHUNK)):
            self.t += CHUNK / FS
            self.proc.push(self.rng.normal(0.0, sigma, CHUNK), self.t)
        self.proc.update(self.t)

    def run_cycle(
        self,
        tense_sigma: float = STRONG_SIGMA,
        relax_sigma: float = REST_SIGMA,
        segments: tuple[Segment, ...] = RHYTHM,
    ) -> None:
        self.proc.start_calibration("cycle", self.t, segments)
        for seg in segments:
            self.feed(seg.s, tense_sigma if seg.phase == "tense" else relax_sigma)
        self.feed(0.1, relax_sigma)

    def status(self) -> tuple[str, str | None]:
        s = self.proc.calibration_status()
        assert s is not None
        return s.status, s.reason


def test_cycle_gives_rest_and_peak_and_done() -> None:
    rig = Rig()
    rig.run_cycle()
    assert rig.status() == ("done", None)
    assert rig.proc.calibrated
    assert rig.proc.rest is not None and rig.proc.peak is not None
    assert rig.proc.rest == pytest.approx(0.93 * REST_SIGMA, rel=0.2)
    assert rig.proc.peak == pytest.approx(0.93 * STRONG_SIGMA, rel=0.2)


def test_levels_after_cycle_match_rest_and_tension() -> None:
    rig = Rig()
    rig.run_cycle()
    rig.feed(1.0, REST_SIGMA)
    assert rig.proc.reading().value < 0.15
    rig.feed(1.0, STRONG_SIGMA)
    assert rig.proc.reading().value > 0.6


def test_default_rhythm_comes_from_config_and_lasts_twenty_seconds() -> None:
    rig = Rig(config())
    rig.proc.start_calibration("cycle", rig.t)
    rig.feed(19.0, STRONG_SIGMA)
    status = rig.proc.calibration_status()
    assert status is not None and status.status == "running"
    assert status.progress == pytest.approx(0.95, abs=0.03)
    rig.feed(1.2, REST_SIGMA)
    assert rig.status()[0] in {"done", "failed"}  # шаг закончился ровно за 20 с


def test_rhythm_from_config_is_used() -> None:
    rig = Rig(config(cycle_tense_s=2.0, cycle_relax_s=3.0, cycle_repeats=1))
    rig.proc.start_calibration("cycle", rig.t)
    rig.feed(1.0, STRONG_SIGMA)
    status = rig.proc.calibration_status()
    assert status is not None
    assert (status.segment, status.phase) == (1, "tense")
    assert status.phase_left_s == pytest.approx(1.0, abs=0.1)
    rig.feed(1.5, REST_SIGMA)
    status = rig.proc.calibration_status()
    assert status is not None
    assert (status.segment, status.phase) == (2, "relax")


def test_status_reports_segment_phase_and_time_left() -> None:
    rig = Rig()
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    first = rig.proc.calibration_status()
    assert first is not None
    assert (first.segment, first.phase, first.phase_left_s) == (1, "tense", 3.0)
    seen: list[tuple[int | None, str | None]] = []
    for seg in RHYTHM:
        rig.feed(seg.s / 2, STRONG_SIGMA if seg.phase == "tense" else REST_SIGMA)
        status = rig.proc.calibration_status()
        assert status is not None and status.status == "running"
        seen.append((status.segment, status.phase))
        assert status.phase_left_s == pytest.approx(seg.s / 2, abs=0.1)
        rig.feed(seg.s / 2, STRONG_SIGMA if seg.phase == "tense" else REST_SIGMA)
    assert seen == [(1, "tense"), (2, "relax"), (3, "tense"), (4, "relax")]


def test_progress_grows_over_the_whole_step() -> None:
    rig = Rig()
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    last = -1.0
    for _ in range(4):
        rig.feed(2.9, STRONG_SIGMA)
        status = rig.proc.calibration_status()
        assert status is not None and status.status == "running"
        assert status.progress > last
        last = status.progress


def test_transition_at_segment_start_is_not_counted() -> None:
    """Первые `transition_s` сегмента не влияют ни на покой, ни на максимум."""
    rig = Rig(config(transition_s=1.0))
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    for seg in RHYTHM:
        if seg.phase == "tense":
            rig.feed(0.5, 1000.0)  # переход: выброс при сжатии (запас 0,5 с на затухание фильтров)
            rig.feed(seg.s - 0.5, STRONG_SIGMA)
        else:
            rig.feed(0.5, 30.0)  # переход: мышца ещё не расслабилась
            rig.feed(seg.s - 0.5, REST_SIGMA)
    rig.feed(0.1, REST_SIGMA)
    assert rig.status() == ("done", None)
    assert rig.proc.rest == pytest.approx(0.93 * REST_SIGMA, rel=0.25)
    assert rig.proc.peak == pytest.approx(0.93 * STRONG_SIGMA, rel=0.25)


def test_without_transition_cut_the_outliers_would_spoil_the_result() -> None:
    rig = Rig(config(transition_s=0.0))
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    for seg in RHYTHM:
        if seg.phase == "tense":
            rig.feed(1.0, 5000.0)
            rig.feed(seg.s - 1.0, STRONG_SIGMA)
        else:
            rig.feed(1.0, 400.0)
            rig.feed(seg.s - 1.0, REST_SIGMA)
    rig.feed(0.1, REST_SIGMA)
    assert rig.proc.peak is not None and rig.proc.peak > 1000.0


def test_peak_is_the_90th_percentile_so_a_short_spike_does_not_set_it() -> None:
    rig = Rig()
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    for seg in RHYTHM:
        if seg.phase == "tense":
            rig.feed(1.2, STRONG_SIGMA)
            rig.feed(0.02, STRONG_SIGMA * 10)  # одиночный выброс
            rig.feed(seg.s - 1.22, STRONG_SIGMA)
        else:
            rig.feed(seg.s, REST_SIGMA)
    rig.feed(0.1, REST_SIGMA)
    assert rig.status() == ("done", None)
    assert rig.proc.peak is not None
    assert rig.proc.peak < 2.0 * 0.93 * STRONG_SIGMA


def test_weak_squeeze_fails() -> None:
    rig = Rig(config(calib_min_ratio=3.0))
    rig.run_cycle(tense_sigma=REST_SIGMA * 1.5)
    status, reason = rig.status()
    assert status == "failed"
    assert reason
    assert not rig.proc.calibrated
    assert rig.proc.reading().reason == "not_calibrated"


def test_tension_below_rest_fails_even_with_default_ratio() -> None:
    rig = Rig()
    rig.run_cycle(tense_sigma=1.0, relax_sigma=10.0)
    assert rig.status()[0] == "failed"
    assert not rig.proc.calibrated


def test_threshold_ratio_is_configurable() -> None:
    passes = Rig(config(calib_min_ratio=2.0))
    passes.run_cycle(tense_sigma=REST_SIGMA * 4)
    assert passes.status()[0] == "done"
    fails = Rig(config(calib_min_ratio=8.0))
    fails.run_cycle(tense_sigma=REST_SIGMA * 4)
    assert fails.status()[0] == "failed"


def test_interrupted_step_fails() -> None:
    rig = Rig()
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    rig.feed(4.0, STRONG_SIGMA)
    rig.proc.abort_calibration("датчик отключён")
    assert rig.status() == ("failed", "датчик отключён")
    assert not rig.proc.calibrated


def test_reconnect_in_the_middle_fails_the_step() -> None:
    rig = Rig()
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    rig.feed(4.0, STRONG_SIGMA)
    rig.proc.reset_stream()
    assert rig.status()[0] == "failed"


def test_step_without_data_times_out() -> None:
    proc = EmgProcessor(config())
    proc.start_calibration("cycle", 0.0)
    proc.update(500.0)
    status = proc.calibration_status()
    assert status is not None and status.status == "failed"


def test_too_few_points_in_relax_fails() -> None:
    rig = Rig(config(transition_s=1.95))  # от расслабления в 2 с остаётся 0,05 с: 2-3 точки
    rig.run_cycle(segments=(Segment("tense", 2.0), Segment("relax", 2.0)))
    assert rig.status() == ("failed", "нет данных в покое")


def test_config_rejects_transition_not_shorter_than_a_segment() -> None:
    with pytest.raises(ValueError, match="transition_s"):
        EmgConfig(transition_s=2.0)
    EmgConfig(transition_s=1.99)


def test_new_cycle_replaces_previous_calibration() -> None:
    rig = Rig()
    rig.run_cycle()
    assert rig.proc.calibrated
    rig.proc.start_calibration("cycle", rig.t, RHYTHM)
    assert not rig.proc.calibrated


def test_no_bursts_during_the_step_but_they_work_afterwards() -> None:
    rig = Rig()
    rig.run_cycle()
    assert rig.proc.drain_bursts() == []
    rig.feed(1.5, REST_SIGMA)
    rig.feed(0.5, STRONG_SIGMA)
    assert len(rig.proc.drain_bursts()) == 1


def test_old_steps_still_work_next_to_cycle() -> None:
    rig = Rig(config(calib_rest_s=2.0, calib_contractions=2, calib_contraction_s=1.0))
    rig.proc.start_calibration("rest", rig.t)
    rig.feed(2.1, REST_SIGMA)
    rig.proc.start_calibration("contract", rig.t)
    for _ in range(2):
        rig.feed(1.0, STRONG_SIGMA)
        rig.feed(1.0, REST_SIGMA)
    rig.feed(0.1, REST_SIGMA)
    assert rig.status() == ("done", None)
    assert rig.proc.calibrated
    final = rig.proc.calibration_status()
    assert final is not None
    assert final.segment is None


def test_config_rejects_nonsense_rhythm() -> None:
    with pytest.raises(ValueError):
        EmgConfig(cycle_tense_s=0.0)
    with pytest.raises(ValueError):
        EmgConfig(cycle_relax_s=-1.0)
    with pytest.raises(ValueError):
        EmgConfig(cycle_repeats=0)
    with pytest.raises(ValueError):
        EmgConfig(transition_s=-0.1)


NOISE_SIGMA = 10.0


@pytest.mark.parametrize("min_ratio", [2.0, 1.0], ids=["ratio_and_spread", "spread_alone"])
def test_noise_instead_of_contraction_fails_and_gives_no_false_bursts(min_ratio: float) -> None:
    """Участник не напряг мышцу: шум не должен пройти калибровку и усилиться до событий."""
    rig = Rig(config(calib_min_ratio=min_ratio), seed=3)
    rig.run_cycle(tense_sigma=NOISE_SIGMA, relax_sigma=NOISE_SIGMA)
    status, reason = rig.status()
    assert status == "failed"
    assert reason == "сокращение слабое, нет отличия от покоя"
    assert not rig.proc.calibrated
    rig.feed(60.0, NOISE_SIGMA)
    assert rig.proc.drain_bursts() == []


def test_spread_check_uses_the_resting_noise() -> None:
    """Нормальное сокращение проходит, даже если покой шумный."""
    rig = Rig(config(calib_min_ratio=1.0), seed=4)
    rig.run_cycle(tense_sigma=STRONG_SIGMA, relax_sigma=NOISE_SIGMA)
    assert rig.status() == ("done", None)


def test_noise_k_is_configurable() -> None:
    lenient = Rig(config(calib_min_ratio=1.0, calib_noise_k=0.0), seed=3)
    lenient.run_cycle(tense_sigma=NOISE_SIGMA * 1.5, relax_sigma=NOISE_SIGMA)
    assert lenient.status()[0] == "done"
    strict = Rig(config(calib_min_ratio=1.0, calib_noise_k=50.0), seed=3)
    strict.run_cycle(tense_sigma=NOISE_SIGMA * 1.5, relax_sigma=NOISE_SIGMA)
    assert strict.status()[0] == "failed"


def test_failed_cycle_erases_the_previous_result() -> None:
    rig = Rig()
    rig.run_cycle()
    assert rig.proc.calibrated
    rig.run_cycle(tense_sigma=NOISE_SIGMA, relax_sigma=NOISE_SIGMA)
    assert not rig.proc.calibrated
    assert rig.proc.rest is None and rig.proc.peak is None


@pytest.mark.parametrize(
    "over",
    [
        {"cycle_tense_s": 1.9},
        {"cycle_relax_s": 15.1},
        {"cycle_repeats": 5},
        {"cycle_tense_s": 15.0, "cycle_relax_s": 15.0, "cycle_repeats": 3},
        {"calib_noise_k": -1.0},
    ],
)
def test_config_rhythm_must_fit_protocol_limits(over: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        EmgConfig(**over)  # type: ignore[arg-type]


def test_config_rhythm_at_protocol_limits_is_accepted() -> None:
    EmgConfig(cycle_tense_s=2.0, cycle_relax_s=2.0, cycle_repeats=4)
    EmgConfig(cycle_tense_s=7.5, cycle_relax_s=7.5, cycle_repeats=4)
