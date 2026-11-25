"""Запуск игры по `shared/game-launch.md`: launch.json → процесс → result.json."""

from __future__ import annotations

import json
import logging
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

from jsonschema import ValidationError

from neurotlon_contracts.contract import result_problem

from .proc import ManagedProcess
from .schema import launch_validator

log = logging.getLogger(__name__)

PROTOCOL = 1
GRACE_S = 420.0  # на калибровку и обучение перед игрой (в играх они идут до отсчёта duration_s)
# начала сообщений `Crashed`: по ним `neurotlon-game-check` отличает причины
DETAIL_START_FAILED = "не удалось запустить игру"
DETAIL_TIMEOUT = "игра не завершилась вовремя"
DETAIL_EXIT_CODE = "игра завершилась с кодом"
DETAIL_BRIDGE_SILENT = "мост датчиков не отвечает: перезапустите стенд (Ctrl+Q и ярлык)"
NAME_MAX = 24
SIDES = ("left", "right")


def session_dir(data_dir: Path, session_id: uuid.UUID | str) -> Path:
    return data_dir.resolve() / "sessions" / str(session_id)


@dataclass(frozen=True)
class Player:
    code: str
    display_name: str | None = None


@dataclass(frozen=True)
class GameRequest:
    session_id: uuid.UUID
    discipline: str
    duration_s: int
    players: tuple[Player, ...]
    max_points: int | None = None  # лимит очков за секцию; нет у понга и без связи


@dataclass(frozen=True)
class GameEntry:
    participant_code: str
    outcome: str  # completed | not_completed
    points: int | None = None
    wins: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Finished:
    entries: tuple[GameEntry, ...]


@dataclass(frozen=True)
class Aborted:
    reason: str


@dataclass(frozen=True)
class Crashed:
    detail: str


GameOutcome = Finished | Aborted | Crashed


class GameRunner(Protocol):
    """Неблокирующий запуск: `start`, затем `poll` до результата."""

    def start(self, request: GameRequest) -> None: ...

    def poll(self) -> GameOutcome | None:
        """`None`, пока игра идёт."""
        ...

    def stop(self) -> None:
        """Прервать игру, если она идёт (закрытие лаунчера)."""
        ...


def launch_document(
    request: GameRequest,
    result_path: Path,
    bridge_host: str,
    bridge_port: int,
    *,
    fullscreen: bool = True,
) -> dict[str, Any]:
    participants: list[dict[str, Any]] = []
    for index, player in enumerate(request.players):
        item: dict[str, Any] = {
            "code": player.code,
            "display_name": player.display_name[:NAME_MAX] if player.display_name else None,
        }
        if request.discipline == "pong":
            item["side"] = SIDES[index]
        participants.append(item)
    launch: dict[str, Any] = {
        "protocol": PROTOCOL,
        "session_id": str(request.session_id),
        "discipline": request.discipline,
        "duration_s": request.duration_s,
        "participants": participants,
        "bridge": {"host": bridge_host, "port": bridge_port},
        "result_path": str(result_path),
        "language": "ru",
        "fullscreen": fullscreen,
    }
    if request.max_points is not None and request.discipline != "pong":
        launch["max_points"] = request.max_points
    return launch


def parse_result(path: Path, request: GameRequest) -> GameOutcome:
    """Прочитать и проверить result.json; любое несоответствие — `Crashed`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Crashed("игра вышла без result.json")
    except (OSError, ValueError) as exc:
        return Crashed(f"result.json не читается: {exc}")
    codes = [p.code for p in request.players]
    problem = result_problem(
        data,
        session_id=str(request.session_id),
        discipline=request.discipline,
        codes=codes,
        max_points=request.max_points,
    )
    if problem:
        return Crashed(problem)
    if data["status"] == "aborted":
        return Aborted(str(data["reason"]))
    by_code = {e["participant_code"]: e for e in data["entries"]}
    entries: list[GameEntry] = []
    for code in codes:
        raw = by_code[code]
        if raw["outcome"] == "completed":
            entries.append(GameEntry(code, "completed", int(raw["points"]), raw.get("wins"), None))
        else:
            entries.append(GameEntry(code, "not_completed", None, None, raw.get("reason", "other")))
    return Finished(tuple(entries))


BRIDGE_WAIT_S = 20.0


HELLO_WAIT_S = 1.0
HELLO_MAX_BYTES = 4096


def bridge_answers(host: str, port: int) -> bool:
    """Мост готов принять игру: на подключение он ответил сообщением `hello`.

    Простого принятого соединения мало: мост пускает одного клиента и закрывает лишнее без слов,
    так что пока слот занят (например, лаунчером на экране калибровки), `hello` не придёт.
    """
    deadline = time.monotonic() + HELLO_WAIT_S  # один срок на всю операцию, не на каждый recv
    try:
        with socket.create_connection((host, port), timeout=HELLO_WAIT_S) as probe:
            received = b""
            while b"\n" not in received and len(received) < HELLO_MAX_BYTES:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                probe.settimeout(left)
                chunk = probe.recv(HELLO_MAX_BYTES)
                if not chunk:
                    return False
                received += chunk
    except OSError:
        return False
    try:
        message = json.loads(received.split(b"\n", 1)[0])
    except ValueError:
        return False
    return isinstance(message, dict) and message.get("type") == "hello"


class SubprocessGameRunner:
    def __init__(
        self,
        command: tuple[str, ...],
        workdir: Path | None,
        data_dir: Path,
        bridge_host: str,
        bridge_port: int,
        *,
        fullscreen: bool = True,
        grace_s: float = GRACE_S,
        monotonic: Callable[[], float] = time.monotonic,
        bridge_ready: Callable[[], bool] | None = None,
        bridge_wait_s: float = BRIDGE_WAIT_S,
    ) -> None:
        self._command = command
        self._workdir = workdir
        self._data_dir = data_dir
        self._bridge = (bridge_host, bridge_port)
        self._fullscreen = fullscreen
        self._grace_s = grace_s
        self._monotonic = monotonic
        self._request: GameRequest | None = None
        self._proc: ManagedProcess | None = None
        self._log: IO[bytes] | None = None
        self._result_path: Path | None = None
        self._deadline = 0.0
        self._early: GameOutcome | None = None
        self._bridge_ready = bridge_ready
        self._bridge_wait_s = bridge_wait_s
        self._spawn_after: Callable[[], None] | None = None
        self._wait_started = 0.0

    def start(self, request: GameRequest) -> None:
        self._request = request
        self._early = None
        folder = session_dir(self._data_dir, request.session_id)
        folder.mkdir(parents=True, exist_ok=True)
        self._result_path = folder / "result.json"
        # повтор той же сессии: результат прошлой попытки читать нельзя
        self._result_path.unlink(missing_ok=True)
        launch_path = folder / "launch.json"
        document = launch_document(
            request, self._result_path, *self._bridge, fullscreen=self._fullscreen
        )
        try:
            launch_validator("Launch").validate(document)
        except ValidationError as exc:
            self._early = Crashed(f"launch.json не проходит схему: {exc.message}")
            return
        launch_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self._spawn_after = lambda: self._spawn(folder, launch_path, request)
        self._wait_started = self._monotonic()
        if self._bridge_ready is None or self._bridge_ready():
            self._spawn_pending()

    def _spawn_pending(self) -> None:
        spawn, self._spawn_after = self._spawn_after, None
        if spawn is not None:
            spawn()

    def _spawn(self, folder: Path, launch_path: Path, request: GameRequest) -> None:
        waited = self._monotonic() - self._wait_started
        if waited > 0.5:
            log.info("bridge answered after %.1f s", waited)
        self._log = (folder / "game.log").open("wb")
        try:
            self._proc = ManagedProcess(
                [*self._command, "--launch", str(launch_path)], self._workdir, self._log
            )
        except OSError as exc:
            self._close_log()
            self._early = Crashed(f"{DETAIL_START_FAILED}: {exc}")
            return
        self._deadline = self._monotonic() + request.duration_s + self._grace_s
        log.info("game started: %s, session %s", self._command, request.session_id)

    def poll(self) -> GameOutcome | None:
        if self._spawn_after is not None:
            # Мост (PyInstaller, первый запуск после установки) может подниматься десятки секунд:
            # игра ждёт связи с ним всего 15 с, поэтому стартуем её, когда мост ответил.
            waited = self._monotonic() - self._wait_started
            if (
                self._bridge_ready is not None
                and not self._bridge_ready()
                and waited < self._bridge_wait_s
            ):
                return None
            if waited >= self._bridge_wait_s:
                # Игра без моста всё равно сдастся через 15 с: сразу говорим, в чём дело.
                log.warning("bridge did not answer in %.0f s, the game is not started", waited)
                self._spawn_after = None
                self._early = Crashed(DETAIL_BRIDGE_SILENT)
            else:
                self._spawn_pending()
        if self._early is not None:
            outcome, self._early = self._early, None
            return outcome
        proc, request, result_path = self._proc, self._request, self._result_path
        if proc is None or request is None or result_path is None:
            return None
        code = proc.poll()
        if code is None:
            if self._monotonic() <= self._deadline:
                return None
            log.warning("game did not exit in time, killing it")
            self.stop()
            return Crashed(DETAIL_TIMEOUT)
        self._finish_process()
        log.info("game exited with code %s, result %s", code, result_path)
        if code != 0:
            return Crashed(f"{DETAIL_EXIT_CODE} {code}")
        outcome = parse_result(result_path, request)
        if isinstance(outcome, Aborted):
            log.warning("game aborted: %s", outcome.reason)
        return outcome

    def stop(self) -> None:
        self._finish_process()

    def _finish_process(self) -> None:
        if self._proc is not None:
            self._proc.kill()  # и живую игру, и потомков, оставшихся после выхода
        self._proc = None
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None
