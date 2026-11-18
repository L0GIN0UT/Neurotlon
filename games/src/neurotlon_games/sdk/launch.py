"""`launch.json`: разбор и проверка (схема `Launch` из `shared/game-launch.schema.json`)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from neurotlon_bridge.source import PROFILES
from neurotlon_contracts.contract import schema_problem

Side = Literal["left", "right"]


class LaunchError(ValueError):
    """`launch.json` не читается или нарушает контракт."""


@dataclass(frozen=True)
class Participant:
    code: str
    display_name: str | None
    side: Side | None = None  # только понг


@dataclass(frozen=True)
class LaunchInfo:
    session_id: str
    discipline: str
    duration_s: int
    participants: tuple[Participant, ...]
    bridge_host: str
    bridge_port: int
    result_path: Path
    fullscreen: bool = True
    max_points: int | None = None  # лимит очков за секцию (дартс, футбол); нет у понга

    @property
    def signals(self) -> tuple[str, ...]:
        """Сигналы моста для дисциплины: eeg+emg или emg_left+emg_right."""
        return PROFILES[self.discipline]

    @property
    def is_pong(self) -> bool:
        return self.discipline == "pong"

    def by_side(self, side: Side) -> Participant:
        for participant in self.participants:
            if participant.side == side:
                return participant
        raise LookupError(side)

    def signal_of(self, participant: Participant) -> str:
        """Сигнал игрока в понге (`emg_left` / `emg_right`)."""
        if participant.side is None:
            raise LookupError(f"у {participant.code} нет стороны")
        return f"emg_{participant.side}"

    @classmethod
    def from_dict(cls, data: object) -> LaunchInfo:
        problem = schema_problem("Launch", data)
        if problem:
            raise LaunchError(f"launch.json не проходит схему: {problem}")
        assert isinstance(data, dict)
        participants = tuple(_participant(p) for p in data["participants"])
        discipline: str = data["discipline"]
        _check_participants(discipline, participants)
        bridge: dict[str, Any] = data["bridge"]
        return cls(
            session_id=data["session_id"],
            discipline=discipline,
            duration_s=data["duration_s"],
            participants=participants,
            bridge_host=bridge["host"],
            bridge_port=bridge["port"],
            result_path=Path(data["result_path"]),
            fullscreen=bool(data.get("fullscreen", True)),
            max_points=data.get("max_points"),
        )

    @classmethod
    def from_file(cls, path: Path) -> LaunchInfo:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaunchError(f"launch.json не читается: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_args(cls, argv: Sequence[str]) -> LaunchInfo:
        """Найти `--launch <путь>` (или `--launch=<путь>`) в аргументах и прочитать файл."""
        for i, arg in enumerate(argv):
            if arg == "--launch" and i + 1 < len(argv):
                return cls.from_file(Path(argv[i + 1]))
            if arg.startswith("--launch="):
                return cls.from_file(Path(arg.removeprefix("--launch=")))
        raise LaunchError("не передан аргумент --launch <путь к launch.json>")


def _participant(raw: dict[str, Any]) -> Participant:
    return Participant(raw["code"], raw["display_name"], raw.get("side"))


def _check_participants(discipline: str, participants: tuple[Participant, ...]) -> None:
    if discipline != "pong":
        if len(participants) != 1:
            raise LaunchError(f"{discipline}: нужен один участник, получено {len(participants)}")
        return
    sides = sorted(p.side or "" for p in participants)
    if sides != ["left", "right"]:
        raise LaunchError("pong: нужны два участника со сторонами left и right")
