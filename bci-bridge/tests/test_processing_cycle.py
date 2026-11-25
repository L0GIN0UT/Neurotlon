import pytest

from neurotlon_bridge.processing.cycle import CycleTimeline, default_segments
from neurotlon_bridge.source import Segment


def test_default_segments_alternate_starting_with_tension() -> None:
    assert default_segments(5.0, 4.0, 2) == (
        Segment("tense", 5.0),
        Segment("relax", 4.0),
        Segment("tense", 5.0),
        Segment("relax", 4.0),
    )


def test_timeline_total_and_spans() -> None:
    timeline = CycleTimeline(default_segments(5.0, 5.0, 2))
    assert timeline.total_s == 20.0
    assert [(s.phase, s.start_s, s.end_s) for s in timeline.spans] == [
        ("tense", 0.0, 5.0),
        ("relax", 5.0, 10.0),
        ("tense", 10.0, 15.0),
        ("relax", 15.0, 20.0),
    ]


@pytest.mark.parametrize(
    ("elapsed", "segment", "phase", "left"),
    [
        (0.0, 1, "tense", 5.0),
        (1.5, 1, "tense", 3.5),
        (4.99, 1, "tense", 0.01),
        (5.0, 2, "relax", 5.0),
        (12.0, 3, "tense", 3.0),
        (19.5, 4, "relax", 0.5),
    ],
)
def test_position_inside_the_cycle(elapsed: float, segment: int, phase: str, left: float) -> None:
    pos = CycleTimeline(default_segments(5.0, 5.0, 2)).at(elapsed)
    assert (pos.segment, pos.phase) == (segment, phase)
    assert pos.phase_left_s == pytest.approx(left)


def test_position_is_clamped_to_the_ends() -> None:
    timeline = CycleTimeline(default_segments(5.0, 5.0, 2))
    before = timeline.at(-3.0)
    assert (before.segment, before.phase, before.phase_left_s) == (1, "tense", 5.0)
    after = timeline.at(99.0)
    assert (after.segment, after.phase, after.phase_left_s) == (4, "relax", 0.0)


def test_custom_rhythm_with_uneven_segments() -> None:
    timeline = CycleTimeline((Segment("relax", 2.0), Segment("tense", 7.5)))
    assert timeline.total_s == 9.5
    assert timeline.at(3.0).phase == "tense"
    assert timeline.at(3.0).phase_left_s == pytest.approx(6.5)


@pytest.mark.parametrize("segments", [(), (Segment("tense", 0.0),), (Segment("relax", -1.0),)])
def test_timeline_rejects_empty_or_non_positive(segments: tuple[Segment, ...]) -> None:
    with pytest.raises(ValueError):
        CycleTimeline(segments)
