"""Таймер игры: время считается по `dt` кадров, поэтому пауза — просто не звать `tick`."""

from __future__ import annotations


class Timer:
    def __init__(self, duration_s: float) -> None:
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._duration_s = float(duration_s)
        self._elapsed_s = 0.0

    @property
    def duration_s(self) -> float:
        return self._duration_s

    @property
    def elapsed_s(self) -> float:
        return min(self._elapsed_s, self._duration_s)

    @property
    def remaining_s(self) -> float:
        return max(0.0, self._duration_s - self._elapsed_s)

    @property
    def expired(self) -> bool:
        return self._elapsed_s >= self._duration_s

    def tick(self, dt: float) -> None:
        if dt > 0:
            self._elapsed_s += dt

    def label(self) -> str:
        """`м:сс`, остаток округляется вверх, чтобы «0:00» значило конец."""
        seconds = int(self.remaining_s + 0.999)
        return f"{seconds // 60}:{seconds % 60:02d}"
