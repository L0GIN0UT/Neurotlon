"""Подставные API, буфер и игра для тестов (без сети, процессов и экрана)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from neurotlon_launcher.api import DisciplineConfig, Eligibility, Team
from neurotlon_launcher.bridge_link import (
    BurstRecord,
    Hello,
    LinkState,
    LinkView,
    SampleRecord,
    SignalBatch,
    StepProgress,
)
from neurotlon_launcher.game import GameOutcome, GameRequest
from neurotlon_launcher.outbox import ActiveSession, OutboxItem

_T = TypeVar("_T")


def eligibility(code: str, *issues: str, name: str | None = None) -> Eligibility:
    return Eligibility(code, name, Team(1, "Alpha", "#aa00bb"), tuple(issues))


class FakeApi:
    def __init__(self) -> None:
        self.people: dict[str, Eligibility | Exception] = {}
        self.config: DisciplineConfig | Exception = DisciplineConfig("darts", "bci", 90)
        self.start_error: Exception | None = None
        self.eligibility_calls: list[str] = []
        self.started: list[tuple[uuid.UUID, str, list[str]]] = []

    def get_config(self) -> DisciplineConfig:
        if isinstance(self.config, Exception):
            raise self.config
        return self.config

    def eligibility(self, code: str, discipline: str, section: str) -> Eligibility:
        self.eligibility_calls.append(code)
        found = self.people.get(code) or eligibility(code)
        if isinstance(found, Exception):
            raise found
        return found

    def start_session(
        self, session_id: uuid.UUID, discipline: str, participant_codes: list[str]
    ) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started.append((session_id, discipline, participant_codes))

    def submit_result(self, payload: dict[str, Any]) -> None:
        raise AssertionError("the machine never submits directly")

    def heartbeat(
        self,
        state: str,
        session_id: uuid.UUID | None,
        queue_length: int,
        sensors: dict[str, str],
    ) -> None:
        raise AssertionError("the machine never sends heartbeats")


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.active: ActiveSession | None = None
        self.rejected_items: list[OutboxItem] = []
        self.exports = 0

    def add(self, payload: dict[str, Any]) -> None:
        self.items.append(payload)

    def pending_count(self) -> int:
        return len(self.items)

    def rejected(self) -> list[OutboxItem]:
        return self.rejected_items

    def export_rejected(self) -> Path:
        self.exports += 1
        return Path("rejected.json")

    def set_active(self, active: ActiveSession) -> None:
        self.active = active

    def clear_active(self) -> None:
        self.active = None


class FakeRunner:
    """`poll` отдаёт заранее заданные исходы по одному; пока их нет — игра «идёт»."""

    def __init__(self, *outcomes: GameOutcome) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[GameRequest] = []
        self.running = False
        self.stopped = False

    def start(self, request: GameRequest) -> None:
        self.requests.append(request)
        self.running = True

    def poll(self) -> GameOutcome | None:
        if self.running and self.outcomes:
            self.running = False
            return self.outcomes.pop(0)
        return None

    def stop(self) -> None:
        self.stopped = True


class Time:
    """Управляемые часы: wall-time для finished_at и monotonic для таймеров."""

    def __init__(self) -> None:
        self.wall = datetime(2027, 4, 12, 11, 5, tzinfo=UTC)
        self.mono = 1000.0

    def clock(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono


class Ids:
    """Предсказуемые session_id: 1, 2, 3…"""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> uuid.UUID:
        self.n += 1
        return uuid.UUID(int=self.n)


class SyncExecutor(Executor):
    """Исполнитель без потоков: задача выполняется сразу, в вызывающем потоке."""

    def submit(self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> Future[_T]:
        future: Future[_T] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


class FakeLink:
    """Подставная связь с мостом: состояние задаёт тест, команды записываются."""

    def __init__(self) -> None:
        self.link: LinkState = "connecting"
        self.hello: Hello | None = None
        self.states: dict[str, str] = {}
        self.batteries: dict[str, int | None] = {}
        self.calibrated: set[str] = set()
        self.progress: dict[str, StepProgress] = {}
        self.generation = 0
        self.calls: list[tuple[str, ...]] = []
        self.durations: dict[str, float | None] = {}
        self.closed = False
        self.samples: list[SampleRecord] = []
        self.bursts: list[BurstRecord] = []

    def view(self) -> LinkView:
        return LinkView(
            self.link,
            self.hello,
            dict(self.states),
            dict(self.batteries),
            frozenset(self.calibrated),
            dict(self.progress),
            self.generation,
        )

    def calibrate(self, signal: str, step: str, duration_s: float | None = None) -> bool:
        self.calls.append(("calibrate", signal, step))
        self.durations[signal] = duration_s
        self.calibrated.discard(signal)
        self.progress.pop(signal, None)
        return self.link == "live"

    def reset(self) -> bool:
        self.calls.append(("reset",))
        self.calibrated.clear()
        self.progress.clear()
        return self.link == "live"

    def recent(self, after_seq: int, after_burst: int, limit: int) -> SignalBatch:
        fresh = [s for s in self.samples if s.seq > after_seq][-limit:]
        cursor = fresh[-1].seq if fresh else after_seq
        return SignalBatch(
            cursor,
            tuple(fresh),
            tuple(b for b in self.bursts if b.n > after_burst),
            self.generation,
        )

    def close(self) -> None:
        self.closed = True

    # --- действия «моста» в тестах ---

    def go_live(
        self,
        states: dict[str, str],
        calibrated: tuple[str, ...] = (),
        eeg_method: str | None = None,
    ) -> None:
        self.link = "live"
        self.generation += 1
        self.states = dict(states)
        self.calibrated = set(calibrated)
        self.progress = {}
        self.hello = Hello(tuple(states.items()), ("calibration_state",), eeg_method, calibrated)

    def drop(self) -> None:
        self.link = "lost"

    def running(self, signal: str, step: str, progress: float, **extra: object) -> None:
        self.progress[signal] = StepProgress(step, "running", progress, **extra)  # type: ignore[arg-type]

    def finish(self, signal: str, step: str) -> None:
        self.progress[signal] = StepProgress(step, "done", 1.0)
        self.calibrated.add(signal)

    def fail(self, signal: str, step: str, reason: str) -> None:
        self.progress[signal] = StepProgress(step, "failed", 0.0, reason)
        self.calibrated.discard(signal)
