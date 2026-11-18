"""Запуск игры по `shared/game-launch.md`: launch.json → процесс → result.json."""

from __future__ import annotations

import json
import logging
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
GRACE_S = 120.0
# начала сообщений `Crashed`: по ним `neurotlon-game-check` отличает причины
DETAIL_START_FAILED = "не удалось запустить игру"
DETAIL_TIMEOUT = "игра не завершилась вовремя"
DETAIL_EXIT_CODE = "игра завершилась с кодом"
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
    points: float | None = None
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
            entries.append(
                GameEntry(code, "completed", float(raw["points"]), raw.get("wins"), None)
            )
        else:
            entries.append(GameEntry(code, "not_completed", None, None, raw.get("reason", "other")))
    return Finished(tuple(entries))


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

    def poll(self) -> GameOutcome | None:
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
        if code != 0:
            return Crashed(f"{DETAIL_EXIT_CODE} {code}")
        return parse_result(result_path, request)

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
