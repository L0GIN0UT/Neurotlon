"""Ритм шага `cycle` калибровки ЭМГ: сегменты «напрячь / расслабить» и положение во времени.

Чистый код без часов: время (секунды от начала шага) передаёт вызывающий. Им пользуются
и обработчик датчика, и эмулятор, чтобы игра видела одинаковые `segment`, `phase`, `phase_left_s`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..source import Phase, Segment


def default_segments(tense_s: float, relax_s: float, repeats: int) -> tuple[Segment, ...]:
    """Напряжение и расслабление `repeats` раз подряд, начиная с напряжения."""
    return (Segment("tense", tense_s), Segment("relax", relax_s)) * repeats


@dataclass(frozen=True)
class CyclePosition:
    segment: int  # номер сегмента с 1
    phase: Phase
    phase_left_s: float


@dataclass(frozen=True)
class Span:
    """Сегмент на оси времени шага: `[start_s, end_s)`."""

    phase: Phase
    start_s: float
    end_s: float


class CycleTimeline:
    """Сегменты шага `cycle`, разложенные по времени."""

    def __init__(self, segments: Sequence[Segment]) -> None:
        if not segments or any(s.s <= 0 for s in segments):
            raise ValueError("нужен хотя бы один сегмент положительной длины")
        spans: list[Span] = []
        start = 0.0
        for segment in segments:
            spans.append(Span(segment.phase, start, start + segment.s))
            start += segment.s
        self.spans: tuple[Span, ...] = tuple(spans)
        self.total_s = start

    def at(self, elapsed_s: float) -> CyclePosition:
        """Положение в момент `elapsed_s` от начала шага; до начала и после конца — края."""
        t = min(max(elapsed_s, 0.0), self.total_s)
        for number, span in enumerate(self.spans, start=1):
            if t < span.end_s:
                return CyclePosition(number, span.phase, span.end_s - t)
        last = self.spans[-1]
        return CyclePosition(len(self.spans), last.phase, 0.0)
