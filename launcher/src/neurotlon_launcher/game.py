"""Запуск игры по `shared/game-launch.md`: launch.json → процесс → result.json."""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

from jsonschema import ValidationError

from .schema import launch_validator

log = logging.getLogger(__name__)

PROTOCOL = 1
GRACE_S = 120.0
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
    return {
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


def parse_result(path: Path, request: GameRequest) -> GameOutcome:
    """Прочитать и проверить result.json; любое несоответствие — `Crashed`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Crashed("игра вышла без result.json")
    except (OSError, ValueError) as exc:
        return Crashed(f"result.json не читается: {exc}")
    try:
        launch_validator("Result").validate(data)
    except ValidationError as exc:
        return Crashed(f"result.json не проходит схему: {exc.message}")
    if data["session_id"] != str(request.session_id):
        return Crashed("session_id в result.json не совпадает с запущенной сессией")
    if data["status"] == "aborted":
        return Aborted(str(data["reason"]))
    return _finished(data["entries"], request)


def _finished(raw_entries: list[dict[str, Any]], request: GameRequest) -> GameOutcome:
    expected = [p.code for p in request.players]
    by_code = {e["participant_code"]: e for e in raw_entries}
    if len(by_code) != len(raw_entries) or set(by_code) != set(expected):
        return Crashed("записи result.json не соответствуют участникам сессии")
    entries: list[GameEntry] = []
    for code in expected:
        raw = by_code[code]
        if raw["outcome"] == "completed":
            if "points" not in raw:
                return Crashed(f"у {code} нет points при completed")
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
        self._proc: subprocess.Popen[bytes] | None = None
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
            self._proc = subprocess.Popen(
                [*self._command, "--launch", str(launch_path)],
                cwd=self._workdir,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._close_log()
            self._early = Crashed(f"не удалось запустить игру: {exc}")
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
            return Crashed("игра не завершилась вовремя")
        self._finish_process()
        if code != 0:
            return Crashed(f"игра завершилась с кодом {code}")
        return parse_result(result_path, request)

    def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        self._finish_process()

    def _finish_process(self) -> None:
        self._proc = None
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None
