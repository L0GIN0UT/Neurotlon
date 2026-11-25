import numpy as np
import pytest

from neurotlon_bridge.processing.burst import BurstConfig, BurstDetector, BurstHit

STEP_MS = 20.0
QUIET = 60  # точек спокойного уровня перед фронтом: больше окна взвода (28 точек)


def detector(**over: float) -> BurstDetector:
    return BurstDetector(BurstConfig(**over), STEP_MS)  # type: ignore[arg-type]


def edge(low: float = 0.0, high: float = 1.0, quiet: int = QUIET, held: int = 20) -> list[float]:
    return [low] * quiet + [high] * held


def indices(hits: list[BurstHit]) -> list[int]:
    return [h.index for h in hits]


def test_sharp_edge_gives_exactly_one_event() -> None:
    hits = detector().push(edge())
    assert indices(hits) == [QUIET + 2]  # третья подтверждающая точка фронта


def test_event_is_not_repeated_while_level_stays_high() -> None:
    assert len(detector().push(edge(held=500))) == 1


def test_slow_rise_to_full_scale_gives_nothing() -> None:
    ramp = [float(v) for v in np.linspace(0.0, 1.0, 50)] + [1.0] * 50  # секунда на подъём
    assert detector().push([0.0] * QUIET + ramp) == []


def test_slow_rise_does_not_fire_even_if_it_starts_from_calm_and_is_long() -> None:
    ramp = [float(v) for v in np.linspace(0.0, 1.0, 200)]
    assert detector().push([0.0] * QUIET + ramp) == []


def test_rise_exactly_at_threshold_fires_and_slightly_below_does_not() -> None:
    cfg = {"fire_level": 0.0}
    assert len(detector(**cfg).push(edge(0.1, 0.5))) == 1  # прирост 0,4 = min_rise
    assert detector(**cfg).push(edge(0.1, 0.49)) == []  # 0,39 < 0,4


def test_level_exactly_at_fire_level_fires_and_below_does_not() -> None:
    cfg = {"min_rise": 0.1}
    assert len(detector(**cfg).push(edge(0.0, 0.5))) == 1
    assert detector(**cfg).push(edge(0.0, 0.49)) == []


def test_single_point_spike_is_ignored() -> None:
    assert detector().push([0.0] * QUIET + [1.0] + [0.0] * QUIET) == []


def test_two_point_spike_is_ignored_with_default_confirmation() -> None:
    assert detector().push([0.0] * QUIET + [1.0, 1.0] + [0.0] * QUIET) == []


def test_confirm_points_one_accepts_a_spike() -> None:
    hits = detector(confirm_points=1).push([0.0] * QUIET + [1.0] + [0.0] * QUIET)
    assert indices(hits) == [QUIET]


def test_jitter_around_release_level_does_not_repeat() -> None:
    chatter = [0.35, 0.25] * 60
    spikes = [0.9, 0.9, 0.9, 0.2, 0.2, 0.35] * 20
    hits = detector().push(edge(held=10) + chatter + spikes)
    assert len(hits) == 1


def test_two_sharp_contractions_with_short_pause_give_one_event() -> None:
    pause = 15  # 300 мс: мышца не успела вернуться в покой на окно взвода
    levels = edge(held=25) + [0.0] * pause + [1.0] * 25
    assert len(detector().push(levels)) == 1


def test_two_sharp_contractions_with_long_pause_give_two_events() -> None:
    pause = 40  # 800 мс
    levels = edge(held=25) + [0.0] * pause + [1.0] * 25
    assert len(detector().push(levels)) == 2


def test_min_interval_alone_blocks_a_quick_second_event() -> None:
    quick = {"arm_window_ms": 20.0, "release_ms": 20.0}
    levels = edge(held=10) + [0.0] * 15 + [1.0] * 15
    assert len(detector(min_interval_ms=1000.0, **quick).push(levels)) == 1
    assert len(detector(min_interval_ms=100.0, **quick).push(levels)) == 2


def test_noise_between_02_and_04_gives_nothing() -> None:
    noise = np.random.default_rng(3).uniform(0.2, 0.4, 2000)
    assert detector().push([float(v) for v in noise]) == []


def test_start_at_high_level_without_arming_gives_nothing() -> None:
    assert detector().push([0.9] * 100) == []


def test_after_high_start_the_detector_arms_once_the_level_drops() -> None:
    det = detector()
    assert det.push([0.9] * 30 + [0.0] * QUIET) == []
    assert len(det.push([1.0] * 20)) == 1


def test_first_event_needs_the_calm_window_after_start() -> None:
    assert detector().push([0.0] * 10 + [1.0] * 20) == []


def test_skip_in_the_middle_of_an_edge_drops_the_arm() -> None:
    det = detector()
    assert det.push([0.0] * QUIET + [1.0, 1.0]) == []
    det.skip(1)  # valid=false, not_calibrated, оседание фильтров
    assert det.push([1.0] * 30) == []


def test_reset_in_the_middle_of_an_edge_drops_the_arm() -> None:
    det = detector()
    assert det.push([0.0] * QUIET + [1.0, 1.0]) == []
    det.reset()  # переподключение, новый участник
    assert det.push([1.0] * 30) == []


def test_detector_works_again_after_skip_and_calm() -> None:
    det = detector()
    det.skip(10)
    assert len(det.push(edge())) == 1


def test_reset_forgets_the_previous_event() -> None:
    det = detector(min_interval_ms=10_000.0)
    assert len(det.push(edge(held=30))) == 1
    det.reset()
    assert len(det.push([0.0] * QUIET + [1.0] * 5)) == 1


def test_batches_of_any_size_give_the_same_result() -> None:
    levels = edge(held=25) + [0.0] * 50 + [1.0] * 25 + [0.0] * 30
    expected = detector().push(levels)
    assert len(expected) == 2
    rng = np.random.default_rng(7)
    for _ in range(20):
        det = detector()
        got: list[BurstHit] = []
        pos = 0
        while pos < len(levels):
            size = int(rng.integers(1, 40))
            got += det.push(levels[pos : pos + size])
            pos += size
        assert got == expected


def test_hit_indices_are_absolute_across_pushes_and_skips() -> None:
    det = detector()
    det.skip(100)
    assert det.count == 100
    hits = det.push(edge())
    assert indices(hits) == [100 + QUIET + 2]
    assert det.count == 100 + QUIET + 20


def test_rise_is_scaled_by_rise_ref_and_clipped() -> None:
    assert detector(rise_ref=0.8).push(edge(0.0, 1.0))[0].rise == 1.0
    assert detector(rise_ref=0.8).push(edge(0.1, 0.6))[0].rise == pytest.approx(0.625)
    assert detector(rise_ref=2.0).push(edge(0.0, 1.0))[0].rise == pytest.approx(0.5)


def test_rise_uses_the_largest_value_of_the_confirming_points() -> None:
    levels = [0.0] * QUIET + [0.5, 0.8, 1.0, 1.0]
    hit = detector(rise_ref=1.0).push(levels)[0]
    assert hit.rise == pytest.approx(1.0)


def test_empty_push_is_harmless() -> None:
    det = detector()
    assert det.push([]) == []
    assert det.count == 0


@pytest.mark.parametrize(
    "over",
    [
        {"arm_window_ms": 0.0},
        {"rise_window_ms": -1.0},
        {"release_ms": 0.0},
        {"rise_ref": 0.0},
        {"min_interval_ms": -1.0},
        {"confirm_points": 0},
        {"fire_level": 1.5},
        {"min_rise": -0.1},
    ],
)
def test_config_rejects_nonsense(over: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BurstConfig(**over)  # type: ignore[arg-type]


def test_detector_rejects_bad_step() -> None:
    with pytest.raises(ValueError):
        BurstDetector(BurstConfig(), 0.0)
