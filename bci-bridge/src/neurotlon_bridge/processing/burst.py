"""Детектор резкого сокращения мышцы по откалиброванному уровню 0…1.

Чистый код: без потоков и часов. Время — номер точки (одна точка = один шаг RMS, 20 мс):
BLE отдаёт отсчёты пачками, и время прихода пачки для момента события не годится.

Условие срабатывания на точке `i`:

- взведено: в `arm_window_ms` до начала окна роста уровень был ниже `arm_level`;
- прирост за `rise_window_ms` (текущий уровень минус минимум окна) не меньше `min_rise`;
- уровень не ниже `fire_level`;
- всё это выполнено `confirm_points` точек подряд (одиночный выброс не считается).

После события следующее возможно, когда уровень `release_ms` подряд был ниже `release_level`
и прошло `min_interval_ms` с прошлого события. Недействительные данные, отсутствие калибровки,
переподключение и оседание фильтров сбрасывают взвод (`skip`, `reset`): после них нужно снова
набрать окно спокойного уровня, поэтому старт сразу с высокого уровня события не даёт.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

EPS = 1e-9


@dataclass(frozen=True)
class BurstConfig:
    """Пороги детектора (`[burst]` в `bridge.toml`). Подбираются на стенде."""

    arm_level: float = 0.3
    arm_window_ms: float = 400.0
    rise_window_ms: float = 150.0
    min_rise: float = 0.4
    fire_level: float = 0.5
    confirm_points: int = 3
    release_level: float = 0.3
    release_ms: float = 200.0
    min_interval_ms: float = 400.0
    rise_ref: float = 0.8

    def __post_init__(self) -> None:
        for name in ("arm_window_ms", "rise_window_ms", "release_ms", "rise_ref"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name}: нужно положительное число")
        if self.min_interval_ms < 0:
            raise ValueError("min_interval_ms: нужно число не меньше нуля")
        if self.confirm_points < 1:
            raise ValueError("confirm_points: нужно целое число не меньше 1")
        for name in ("arm_level", "min_rise", "fire_level", "release_level"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name}: нужно число от 0 до 1")


@dataclass(frozen=True)
class BurstHit:
    """Срабатывание: номер точки (с нуля с момента создания) и крутизна роста 0…1."""

    index: int
    rise: float


class BurstDetector:
    """Детектор с состоянием; один экземпляр на один канал."""

    def __init__(self, cfg: BurstConfig, step_ms: float) -> None:
        if step_ms <= 0:
            raise ValueError("step_ms: нужно положительное число")
        self._cfg = cfg
        self._arm_pts = _points(cfg.arm_window_ms, step_ms)
        self._rise_pts = _points(cfg.rise_window_ms, step_ms)
        self._release_pts = _points(cfg.release_ms, step_ms)
        self._interval_pts = round(cfg.min_interval_ms / step_ms)
        self._need = self._arm_pts + self._rise_pts + 1
        self._history: deque[float] = deque(maxlen=self._need)
        self._count = 0
        self._last_hit: int | None = None
        self._calm_run = 0
        self._ready = True
        self._confirm = 0
        self._confirm_rise = 0.0

    @property
    def count(self) -> int:
        """Сколько точек уже принято (номер следующей точки)."""
        return self._count

    def push(self, levels: Sequence[float]) -> list[BurstHit]:
        """Принять точки уровня подряд; вернуть сработавшие события."""
        hits: list[BurstHit] = []
        for level in levels:
            hit = self._step(level)
            if hit is not None:
                hits.append(hit)
        return hits

    def skip(self, points: int) -> None:
        """Данных нет или они негодны: время идёт, взвод сбрасывается."""
        self._drop_arm()
        self._count += max(0, points)

    def reset(self) -> None:
        """Новый участник, переподключение, оседание фильтров: забыть всё, кроме номера точки."""
        self._drop_arm()
        self._last_hit = None

    def _drop_arm(self) -> None:
        self._history.clear()
        self._calm_run = 0
        self._ready = True
        self._confirm = 0

    def _step(self, level: float) -> BurstHit | None:
        index = self._count
        self._count += 1
        self._history.append(level)
        if not self._ready:
            self._try_release(level, index)
            return None
        rise = self._instant_rise()
        if rise is None or level + EPS < self._cfg.fire_level:
            self._confirm = 0
            return None
        self._confirm += 1
        self._confirm_rise = max(self._confirm_rise if self._confirm > 1 else 0.0, rise)
        if self._confirm < self._cfg.confirm_points:
            return None
        self._confirm = 0
        self._ready = False
        self._calm_run = 0
        self._last_hit = index
        return BurstHit(index, min(1.0, max(0.0, self._confirm_rise / self._cfg.rise_ref)))

    def _instant_rise(self) -> float | None:
        """Прирост, если на этой точке взведено и он достаточен, иначе None."""
        history = self._history
        if len(history) < self._need:
            return None  # окно спокойного уровня ещё не набрано
        values = list(history)
        window = values[-(self._rise_pts + 1) :]
        before = values[: len(values) - self._rise_pts]  # arm_pts точек до начала окна роста
        if max(before) + EPS >= self._cfg.arm_level:
            return None
        rise = window[-1] - min(window)
        return rise if rise + EPS >= self._cfg.min_rise else None

    def _try_release(self, level: float, index: int) -> None:
        self._calm_run = self._calm_run + 1 if level + EPS < self._cfg.release_level else 0
        since = index - (self._last_hit if self._last_hit is not None else index)
        if self._calm_run >= self._release_pts and since >= self._interval_pts:
            self._ready = True


def _points(ms: float, step_ms: float) -> int:
    return max(1, round(ms / step_ms))
