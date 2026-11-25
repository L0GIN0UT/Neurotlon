"""Машина состояний стенда. Без ввода-вывода: API, буфер, игра и часы приходят снаружи.

События (`enter_code`, `confirm`, ...) меняют состояние сразу; сетевые шаги и опрос игры
выполняет `tick()`, так что экран успевает показать «Проверяем…» и «Запускаем…».
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from . import texts
from .api import (
    ApiProblem,
    Busy,
    Eligibility,
    NotOpponents,
    Offline,
    StationApi,
    Team,
    Unauthorized,
    UnknownParticipant,
    is_station_photo,
)
from .bridge_link import BridgeLink, BridgeLinkFactory, LinkView
from .calibration import (
    Calibrate,
    CalibrationRun,
    CalibrationView,
    Command,
    plan_for,
)
from .calibration import Reset as ResetCommand
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

log = logging.getLogger(__name__)
_T = TypeVar("_T")

SECTION = "bci"
# Если конфиг дисциплины ни разу не получен (нет связи и нет кэша).
DEFAULT_DURATION_S = 240
DEFAULT_MAX_POINTS = 10  # section points limit when the server has never been reached
DONE_SECONDS = 5.0
INPUT_MAX = 12


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
    def has_photo(self) -> bool:
        return self.eligibility is not None and self.eligibility.has_photo

    @property
    def photo_version(self) -> int | None:
        return self.eligibility.photo_version if self.eligibility else None

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
    """Только сеть: настройки дисциплины и `start_session`."""

    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    fresh: bool = True  # новая сессия участника; `False` — «Повторить» в той же сессии


@dataclass(frozen=True)
class Calibrating:
    """Калибровка датчиков через мост; данные нужны, чтобы после неё запустить игру."""

    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    duration: int
    max_points: int | None
    offline: bool
    default_limit: bool
    fresh: bool


@dataclass(frozen=True)
class Playing:
    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    offline: bool = False
    default_limit: bool = False  # the points limit is the documented default, not from the server


@dataclass(frozen=True)
class Done:
    lines: tuple[str, ...]
    until: float


@dataclass(frozen=True)
class TechnicalProblem:
    session_id: uuid.UUID
    players: tuple[Candidate, ...]
    reason: str


@dataclass(frozen=True)
class Blocked:
    """Работа невозможна до исправления настроек; из этого состояния выхода нет."""

    message: str


@dataclass(frozen=True)
class CalibrationScreen:
    """Что показывает экран калибровки: связь с мостом и ход шагов."""

    link: LinkView
    run: CalibrationView


@dataclass(frozen=True)
class RejectedEntry:
    session_id: str
    codes: tuple[str, ...]
    error: str


@dataclass(frozen=True)
class RejectedList:
    items: tuple[RejectedEntry, ...]
    exported_to: str | None = None


State = (
    Idle
    | Checking
    | Confirm
    | Starting
    | Calibrating
    | Playing
    | Done
    | TechnicalProblem
    | Blocked
    | RejectedList
)


def _error_name(exc: Exception) -> str:
    return exc.code if isinstance(exc, ApiProblem) else type(exc).__name__


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
        fallback_duration_s: int = DEFAULT_DURATION_S,
        executor: Executor | None = None,
        bridge_link: BridgeLinkFactory | None = None,
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
        self._fallback_duration_s = fallback_duration_s
        self._owns_executor = executor is None
        self._executor: Executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="machine-io"
        )
        self._pending: Future[Any] | None = None
        # Без фабрики связи калибровка не нужна (мост не используется): сразу к игре.
        self._link_factory = bridge_link
        self._link: BridgeLink | None = None
        self._run: CalibrationRun | None = None
        self._link_epoch = 0  # номер связи: поток значений начинается заново на новой

    @property
    def players_needed(self) -> int:
        return 2 if self.discipline == "pong" else 1

    def done_seconds_left(self) -> float:
        """Сколько секунд осталось показывать экран «Готово» (0 вне этого экрана)."""
        state = self.state
        return max(0.0, state.until - self._monotonic()) if isinstance(state, Done) else 0.0

    def heartbeat_view(self) -> tuple[str, uuid.UUID | None]:
        """Состояние и session_id для heartbeat (значения из openapi `StationState`)."""
        match self.state:
            case Confirm():
                return "confirming", None
            case Starting(session_id=sid) | Calibrating(session_id=sid):
                return "calibrating", sid
            case Playing(session_id=sid):
                return "playing", sid
            case Done():
                return "sending", None
            case _:
                return "idle", None

    def photo_codes(self) -> frozenset[str]:
        """ID, чьё фото сейчас может понадобиться окну: игроки на экране, у кого оно есть."""
        state = self.state
        shown: tuple[Candidate, ...]
        match state:
            case Confirm():
                shown = (*state.taken, state.candidate)
            case Idle(taken=taken) | Checking(taken=taken):
                shown = taken
            case Starting(players=players) | Calibrating(players=players):
                shown = players
            case Playing(players=players) | TechnicalProblem(players=players):
                shown = players
            case _:
                shown = ()
        return frozenset(c.code for c in shown if c.has_photo)

    def fetch_photo(self, code: str) -> bytes | None:
        """Запрос фото на сервере: блокирует до таймаута, вызывать без замка станции."""
        data = self._api.photo(code)
        return data if data is not None and is_station_photo(data) else None

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
            # тот же session_id: на сервере одна сессия, повтор startSession безопасен;
            # калибровка участника сохраняется (reset только в новой сессии)
            self.state = Starting(self.state.session_id, self.state.players, fresh=False)

    def back(self) -> None:
        """Шаг назад с любого экрана после ввода кода: проверка, подтверждение, игра, проблема.

        Игру, если она идёт, останавливаем; результат не отправляется. Сессия на сервере
        остаётся открытой: повторный вход того же участника продолжит её (startSession
        идемпотентен). Из экрана игры и проблемы возвращаемся к подтверждению последнего игрока
        (после свежей проверки): там можно начать снова или выбрать «Это не я».
        """
        match self.state:
            case Checking(taken=taken) | Confirm(taken=taken):
                self._drop_pending()
                self.state = Idle(taken=taken)
            case (
                Starting(players=players)
                | Calibrating(players=players)
                | Playing(players=players)
                | TechnicalProblem(players=players)
            ):
                self._drop_pending()
                self._close_link(wait=False)
                self._runner.stop()
                self._outbox.clear_active()
                # Данные игрока берём с сервера заново: после перезапуска стенда в сохранённой
                # сессии нет команды, и экран подтверждения остался бы без неё.
                self.state = Checking(players[-1].code, players[:-1])
            case _:
                pass

    def _drop_pending(self) -> None:
        """Забыть незавершённый сетевой шаг: его ответ уже никому не нужен."""
        self._pending = None

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

    def block(self, message: str) -> None:
        self.state = Blocked(message)

    def show_rejected(self) -> None:
        state = self.state
        if isinstance(state, Idle) and not state.input and not state.taken:
            items = tuple(
                RejectedEntry(
                    item.session_id,
                    tuple(e["participant_code"] for e in item.payload.get("entries", [])),
                    item.last_error or "",
                )
                for item in self._outbox.rejected()
            )
            self.state = RejectedList(items)

    def export_rejected(self) -> None:
        state = self.state
        if isinstance(state, RejectedList):
            path = self._outbox.export_rejected()
            self.state = RejectedList(state.items, str(path))

    def close_rejected(self) -> None:
        if isinstance(self.state, RejectedList):
            self.state = Idle()

    def close(self) -> None:
        self._close_link()
        self._runner.stop()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # --- шаги по времени и сети --------------------------------------------------------

    def tick(self) -> None:
        match self.state:
            case Checking():
                self._check(self.state)
            case Starting():
                self._start(self.state)
            case Calibrating():
                self._calibrate(self.state)
            case Playing():
                outcome = self._runner.poll()
                if outcome is not None:
                    self._game_exited(self.state, outcome)
            case Done(until=until) if self._monotonic() >= until:
                self.state = Idle()
            case _:
                pass

    def _await(self, job: Callable[[], _T]) -> Future[_T] | None:
        """Запустить сетевой шаг в рабочем потоке; вернуть его, когда он готов."""
        if self._pending is None:
            self._pending = self._executor.submit(job)
        if not self._pending.done():
            return None
        future, self._pending = self._pending, None
        return future

    def _check_job(self, code: str, opponent: str | None) -> Eligibility | None:
        try:
            return self._api.eligibility(code, self.discipline, SECTION, opponent)
        except Offline:
            if opponent is not None:
                # Политика владельца: без сервера играть можно, но пару проверить нечем.
                log.warning("pong pair is not verified: the server is unreachable")
            return None

    def _check(self, state: Checking) -> None:
        opponent = state.taken[0].code if self.discipline == "pong" and state.taken else None
        future = self._await(lambda: self._check_job(state.code, opponent))
        if future is None:
            return
        try:
            eligibility = future.result()
        except UnknownParticipant:
            self.state = Idle("", texts.UNKNOWN_PARTICIPANT, state.taken)
            return
        except Unauthorized:
            self.state = Idle("", texts.UNAUTHORIZED, state.taken)
            return
        except Exception as exc:
            log.warning("eligibility check failed: %s", exc)
            self.state = Idle("", texts.server_error(_error_name(exc)), state.taken)
            return
        if eligibility is not None and "not_opponents" in eligibility.issues:
            self.state = Idle("", texts.NOT_OPPONENTS, state.taken)
            return
        self.state = Confirm(Candidate(state.code, eligibility), state.taken)

    def _back_to_confirm(self, state: Starting, notice: str) -> None:
        self.state = Confirm(state.players[-1], state.players[:-1], notice)

    def _start_job(self, state: Starting) -> tuple[int, int | None, bool, bool]:
        """Настройки и startSession: (время, лимит очков, не было связи, лимит по умолчанию)."""
        offline = False
        default_limit = False
        max_points: int | None = None
        try:
            config = self._api.get_config()
            duration, max_points = config.duration_s, config.max_points
        except Offline:
            duration, offline = self._fallback_duration_s, True
            if self.discipline != "pong":
                max_points, default_limit = DEFAULT_MAX_POINTS, True
                log.warning(
                    "section points limit unknown (no config cache), using %d", DEFAULT_MAX_POINTS
                )
        try:
            self._api.start_session(
                state.session_id, self.discipline, [p.code for p in state.players]
            )
        except Offline:
            offline = True
        return duration, max_points, offline, default_limit

    def _start(self, state: Starting) -> None:
        future = self._await(lambda: self._start_job(state))
        if future is None:
            return
        try:
            duration, max_points, offline, default_limit = future.result()
        except Busy:
            self._back_to_confirm(state, texts.BUSY)
            return
        except NotOpponents:
            # Обход проверки кода: сервер не пустил пару, просим другого второго игрока.
            self.state = Idle("", texts.NOT_OPPONENTS, state.players[:-1])
            return
        except Unauthorized:
            self._back_to_confirm(state, texts.UNAUTHORIZED)
            return
        except Exception as exc:
            log.warning("session start failed: %s", exc)
            self._back_to_confirm(state, texts.server_error(_error_name(exc)))
            return
        ready = Calibrating(
            state.session_id,
            state.players,
            duration,
            max_points,
            offline,
            default_limit,
            state.fresh,
        )
        if self._link_factory is None:
            self._launch(ready)
        else:
            self._open_link(ready)

    # --- калибровка ---

    def _open_link(self, state: Calibrating) -> None:
        self._close_link()
        self._link = self._link_factory() if self._link_factory else None
        self._run = CalibrationRun(plan_for(self.discipline), fresh=state.fresh)
        self._link_epoch += 1
        self.state = state

    def _close_link(self, *, wait: bool = True) -> None:
        """Закрыть связь с мостом. `wait` — дождаться закрытия сокета (слот моста нужен игре);
        без ожидания закрытие уходит в рабочий поток и не держит замок станции."""
        link, self._link, self._run = self._link, None, None
        if link is None:
            return
        if wait:
            link.close()
        else:
            self._executor.submit(link.close)

    def _calibrate(self, state: Calibrating) -> None:
        link, run = self._link, self._run
        if link is None or run is None:
            return
        view = link.view()
        if view.emulated:  # эмулятору калибровка не нужна
            self._launch(state)
            return
        self._apply(link, run, run.update(view, self._monotonic()))

    @staticmethod
    def _apply(link: BridgeLink, run: CalibrationRun, commands: list[Command]) -> None:
        for command in commands:
            sent = True
            match command:
                case ResetCommand():
                    sent = link.reset()
                case Calibrate(signal=signal, step=step):
                    sent = link.calibrate(signal, step)
            if not sent:  # связь оборвалась между проверкой и отправкой
                run.command_failed(command)

    def calibration_continue(self) -> None:
        """«Дальше к игре»: только когда все датчики откалиброваны."""
        state, link, run = self.state, self._link, self._run
        if (
            isinstance(state, Calibrating)
            and link is not None
            and run is not None
            and run.view(link.view()).ready
        ):
            self._launch(state)

    def calibration_restart(self) -> None:
        """«Всё заново»: калибровка стирается, шаги идут с начала."""
        link, run = self._link, self._run
        if isinstance(self.state, Calibrating) and link is not None and run is not None:
            self._apply(link, run, run.restart(link.view(), self._monotonic()))

    def calibration_retry(self, key: str) -> None:
        """Повтор шага (по id) или одного сигнала."""
        link, run = self._link, self._run
        if isinstance(self.state, Calibrating) and link is not None and run is not None:
            self._apply(link, run, run.retry(key, link.view(), self._monotonic()))

    def calibration_screen(self) -> CalibrationScreen | None:
        link, run = self._link, self._run
        if not isinstance(self.state, Calibrating) or link is None or run is None:
            return None
        view = link.view()
        return CalibrationScreen(view, run.view(view))

    @property
    def signal_link(self) -> tuple[int, BridgeLink] | None:
        """Связь с мостом, пока идёт калибровка, и её номер (для потока `/api/signals`)."""
        if isinstance(self.state, Calibrating) and self._link is not None:
            return self._link_epoch, self._link
        return None

    def _launch(self, state: Calibrating) -> None:
        """Связь с мостом закрыта; запускаем игру. Сбой не должен оставлять станцию на экране."""
        self._close_link()
        request = GameRequest(
            state.session_id,
            self.discipline,
            state.duration,
            tuple(Player(p.code, p.display_name) for p in state.players),
            state.max_points,
        )
        try:
            self._outbox.set_active(
                ActiveSession(
                    str(state.session_id),
                    self.discipline,
                    state.duration,
                    tuple((p.code, p.display_name) for p in state.players),
                    state.max_points,
                )
            )
            self._runner.start(request)
        except Exception:
            log.exception("game launch failed")
            self._runner.stop()
            self.state = TechnicalProblem(state.session_id, state.players, texts.LAUNCH_FAILED)
            return
        self.state = Playing(state.session_id, state.players, state.offline, state.default_limit)

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
