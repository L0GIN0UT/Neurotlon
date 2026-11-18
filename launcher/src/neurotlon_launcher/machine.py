"""Машина состояний стенда. Без ввода-вывода: API, буфер, игра и часы приходят снаружи.

События (`enter_code`, `confirm`, ...) меняют состояние сразу; сетевые шаги и опрос игры
выполняет `tick()`, так что экран успевает показать «Проверяем…» и «Запускаем…».
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import texts
from .api import (
    ApiProblem,
    Busy,
    Eligibility,
    Offline,
    StationApi,
    Team,
    Unauthorized,
    UnknownParticipant,
)
from .codes import normalize_code
from .game import (
    Aborted,
    Crashed,
    Finished,
    GameEntry,
    GameOutcome,
    GameRequest,
    GameRunner,
    Player,
)
from .outbox import ActiveSession, ResultQueue

SECTION = "bci"
# Если конфиг дисциплины ни разу не получен (нет связи и нет кэша).
DEFAULT_DURATION_S = 120
DONE_SECONDS = 5.0
INPUT_MAX = 12
GIVE_UP_REASON = "equipment"


@dataclass(frozen=True)
class Candidate:
    """Участник, прошедший проверку. `eligibility=None` — проверки не было (нет связи)."""

    code: str
    eligibility: Eligibility | None

    @property
    def offline(self) -> bool:
        return self.eligibility is None

    @property
    def display_name(self) -> str | None:
        return self.eligibility.display_name if self.eligibility else None

    @property
    def team(self) -> Team | None:
        return self.eligibility.team if self.eligibility else None

    @property
    def issues(self) -> tuple[str, ...]:
        return self.eligibility.issues if self.eligibility else ()

    @property
    def warned(self) -> bool:
        """Окно жёлтое: есть проблемы или проверка не выполнялась."""
        return self.offline or bool(self.issues)


@dataclass(frozen=True)
class Idle:
    input: str = ""
    notice: str | None = None
    taken: tuple[Candidate, ...] = ()  # уже подтверждённые игроки понга


@dataclass(frozen=True)
class Checking:
    code: str
    taken: tuple[Candidate, ...]


@dataclass(frozen=True)
class Confirm:
    candidate: Candidate
    taken: tuple[Candidate, ...] = ()
    notice: str | None = None


@dataclass(frozen=True)
class Starting:
    session_id: uuid.UUID
    players: tuple[Candidate, ...]


@dataclass(frozen=True)
class Playing:
    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    offline: bool = False


@dataclass(frozen=True)
class Done:
    lines: tuple[str, ...]
    until: float


@dataclass(frozen=True)
class TechnicalProblem:
    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    reason: str


State = Idle | Checking | Confirm | Starting | Playing | Done | TechnicalProblem


def _now() -> datetime:
    return datetime.now().astimezone()


class StationMachine:
    def __init__(
        self,
        discipline: str,
        api: StationApi,
        outbox: ResultQueue,
        runner: GameRunner,
        *,
        clock: Callable[[], datetime] = _now,
        monotonic: Callable[[], float] = time.monotonic,
        new_session_id: Callable[[], uuid.UUID] = uuid.uuid4,
        on_enqueue: Callable[[], None] | None = None,
    ) -> None:
        self.discipline = discipline
        self.state: State = Idle()
        self._api = api
        self._outbox = outbox
        self._runner = runner
        self._clock = clock
        self._monotonic = monotonic
        self._new_session_id = new_session_id
        self._on_enqueue = on_enqueue

    @property
    def players_needed(self) -> int:
        return 2 if self.discipline == "pong" else 1

    def heartbeat_view(self) -> tuple[str, uuid.UUID | None]:
        """Состояние и session_id для heartbeat (значения из openapi `StationState`)."""
        match self.state:
            case Confirm():
                return "confirming", None
            case Starting(session_id=sid):
                return "calibrating", sid
            case Playing(session_id=sid):
                return "playing", sid
            case Done():
                return "sending", None
            case _:
                return "idle", None

    # --- события ---------------------------------------------------------------------

    def type_char(self, char: str) -> None:
        if isinstance(self.state, Idle) and char.isalnum() and len(self.state.input) < INPUT_MAX:
            self.state = Idle(self.state.input + char, None, self.state.taken)

    def backspace(self) -> None:
        if isinstance(self.state, Idle):
            self.state = Idle(self.state.input[:-1], None, self.state.taken)

    def submit_input(self) -> None:
        if isinstance(self.state, Idle) and self.state.input:
            self.enter_code(self.state.input)

    def enter_code(self, raw: str) -> None:
        """Код из QR или с клавиатуры."""
        if not isinstance(self.state, Idle):
            return
        taken = self.state.taken
        code = normalize_code(raw)
        if code is None:
            self.state = Idle("", texts.BAD_CODE, taken)
        elif code in {c.code for c in taken}:
            self.state = Idle("", texts.ALREADY_PICKED, taken)
        else:
            self.state = Checking(code, taken)

    def confirm(self) -> None:
        state = self.state
        if not isinstance(state, Confirm):
            return
        players = (*state.taken, state.candidate)
        if len(players) < self.players_needed:
            self.state = Idle(taken=players)
        else:
            self.state = Starting(self._new_session_id(), players)

    def cancel(self) -> None:
        match self.state:
            case Confirm(taken=taken):
                self.state = Idle(taken=taken)
            case Idle(input=text, taken=taken) if text:
                self.state = Idle(taken=taken)
            case Idle(taken=taken) if taken:
                self.state = Idle(taken=taken[:-1])
            case _:
                pass

    def retry(self) -> None:
        if isinstance(self.state, TechnicalProblem):
            # тот же session_id: на сервере одна сессия, повтор startSession безопасен
            self.state = Starting(self.state.session_id, self.state.players)

    def give_up(self) -> None:
        state = self.state
        if not isinstance(state, TechnicalProblem):
            return
        entries = [
            {"participant_code": p.code, "outcome": "not_completed", "reason": GIVE_UP_REASON}
            for p in state.players
        ]
        self._enqueue(state.session_id, entries)
        self.state = Done((texts.DONE_GIVE_UP,), self._monotonic() + DONE_SECONDS)

    def recover(self, active: ActiveSession, outcome: GameOutcome) -> None:
        """После перезапуска: сессия была в игре. Результат есть — в буфер, иначе экран проблемы."""
        sid = uuid.UUID(active.session_id)
        players = tuple(
            Candidate(code, Eligibility(code, name, None, ())) for code, name in active.players
        )
        if isinstance(outcome, Finished):
            self._finish(sid, outcome, self._clock())
        else:
            reason = outcome.reason if isinstance(outcome, Aborted) else outcome.detail
            self.state = TechnicalProblem(sid, players, reason)

    def close(self) -> None:
        self._runner.stop()

    # --- шаги по времени и сети --------------------------------------------------------

    def tick(self) -> None:
        match self.state:
            case Checking():
                self._check(self.state)
            case Starting():
                self._start(self.state)
            case Playing():
                outcome = self._runner.poll()
                if outcome is not None:
                    self._game_exited(self.state, outcome)
            case Done(until=until) if self._monotonic() >= until:
                self.state = Idle()
            case _:
                pass

    def _check(self, state: Checking) -> None:
        try:
            eligibility: Eligibility | None = self._api.eligibility(
                state.code, self.discipline, SECTION
            )
        except Offline:
            eligibility = None
        except UnknownParticipant:
            self.state = Idle("", texts.UNKNOWN_PARTICIPANT, state.taken)
            return
        except Unauthorized:
            self.state = Idle("", texts.UNAUTHORIZED, state.taken)
            return
        except ApiProblem as exc:
            self.state = Idle("", texts.server_error(exc.code), state.taken)
            return
        self.state = Confirm(Candidate(state.code, eligibility), state.taken)

    def _back_to_confirm(self, state: Starting, notice: str) -> None:
        self.state = Confirm(state.players[-1], state.players[:-1], notice)

    def _start(self, state: Starting) -> None:
        offline = False
        try:
            duration = self._api.get_config().duration_s
        except Offline:
            duration, offline = DEFAULT_DURATION_S, True
        except Unauthorized:
            self._back_to_confirm(state, texts.UNAUTHORIZED)
            return
        except ApiProblem as exc:
            self._back_to_confirm(state, texts.server_error(exc.code))
            return
        try:
            self._api.start_session(
                state.session_id, self.discipline, [p.code for p in state.players]
            )
        except Offline:
            offline = True
        except Busy:
            self._back_to_confirm(state, texts.BUSY)
            return
        except Unauthorized:
            self._back_to_confirm(state, texts.UNAUTHORIZED)
            return
        except ApiProblem as exc:
            self._back_to_confirm(state, texts.server_error(exc.code))
            return
        request = GameRequest(
            state.session_id,
            self.discipline,
            duration,
            tuple(Player(p.code, p.display_name) for p in state.players),
        )
        self._outbox.set_active(
            ActiveSession(
                str(state.session_id),
                self.discipline,
                duration,
                tuple((p.code, p.display_name) for p in state.players),
            )
        )
        self._runner.start(request)
        self.state = Playing(state.session_id, state.players, offline)

    def _game_exited(self, state: Playing, outcome: GameOutcome) -> None:
        finished_at = self._clock()
        match outcome:
            case Finished():
                self._finish(state.session_id, outcome, finished_at)
            case Aborted(reason=reason):
                self.state = TechnicalProblem(state.session_id, state.players, reason)
            case Crashed(detail=detail):
                self.state = TechnicalProblem(state.session_id, state.players, detail)

    def _finish(self, session_id: uuid.UUID, outcome: Finished, finished_at: datetime) -> None:
        entries = outcome.entries
        self._enqueue(session_id, [_entry_payload(e) for e in entries], finished_at)
        lines = tuple(texts.points_line(e.participant_code, e.points, e.outcome) for e in entries)
        self.state = Done(lines, self._monotonic() + DONE_SECONDS)

    def _enqueue(
        self,
        session_id: uuid.UUID,
        entries: list[dict[str, Any]],
        finished_at: datetime | None = None,
    ) -> None:
        stamp = (finished_at or self._clock()).isoformat(timespec="seconds")
        self._outbox.add(
            {
                "session_id": str(session_id),
                "discipline": self.discipline,
                "section": SECTION,
                "finished_at": stamp,
                "entries": entries,
            }
        )
        self._outbox.clear_active()
        if self._on_enqueue is not None:
            self._on_enqueue()


def _entry_payload(entry: GameEntry) -> dict[str, Any]:
    """Запись игры → запись `ResultEntry` из openapi (только заполненные поля)."""
    payload: dict[str, Any] = {
        "participant_code": entry.participant_code,
        "outcome": entry.outcome,
    }
    for key in ("points", "wins", "reason"):
        value = getattr(entry, key)
        if value is not None:
            payload[key] = value
    return payload
