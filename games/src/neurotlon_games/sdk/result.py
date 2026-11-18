"""`result.json`: сборка, проверка теми же правилами, что у лаунчера и сервера, атомарная запись."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from neurotlon_contracts.contract import PROTOCOL, RESULT_REASON_MAX, result_problem

from .launch import LaunchInfo

Reason = Literal["participant_refused", "health", "equipment", "no_show", "other"]


class ResultError(ValueError):
    """Результат нарушает контракт: файл не записан."""


@dataclass(frozen=True)
class ResultEntry:
    participant_code: str
    outcome: Literal["completed", "not_completed"]
    points: int | None = None
    wins: int | None = None
    reason: Reason | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"participant_code": self.participant_code, "outcome": self.outcome}
        if self.points is not None:
            out["points"] = self.points
        if self.wins is not None:
            out["wins"] = self.wins
        if self.reason is not None:
            out["reason"] = self.reason
        return out


def completed(code: str, points: int, wins: int | None = None) -> ResultEntry:
    """Участник доиграл. `wins` только в понге: 1 у победителя, 0 у проигравшего.

    `points` — целое число (решение 28); дробное значение — `ResultError`.
    """
    if isinstance(points, bool) or not isinstance(points, (int, float)) or points != int(points):
        raise ResultError(f"points должны быть целым числом, а не {points!r}")
    points = int(points)
    return ResultEntry(code, "completed", points=points, wins=wins)


def not_completed(code: str, reason: Reason = "equipment") -> ResultEntry:
    return ResultEntry(code, "not_completed", reason=reason)


class ResultWriter:
    def __init__(self, launch: LaunchInfo) -> None:
        self._launch = launch

    def write_finished(self, entries: Sequence[ResultEntry]) -> None:
        self._write(
            {
                "protocol": PROTOCOL,
                "session_id": self._launch.session_id,
                "status": "finished",
                "entries": [e.to_dict() for e in entries],
            }
        )

    def write_aborted(self, reason: str) -> None:
        self._write(
            {
                "protocol": PROTOCOL,
                "session_id": self._launch.session_id,
                "status": "aborted",
                "entries": [],
                "reason": (reason or "прервано")[:RESULT_REASON_MAX],
            }
        )

    def _write(self, data: dict[str, Any]) -> None:
        launch = self._launch
        problem = result_problem(
            data,
            session_id=launch.session_id,
            discipline=launch.discipline,
            codes=[p.code for p in launch.participants],
            max_points=launch.max_points,
        )
        if problem:
            raise ResultError(problem)
        path = launch.result_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
