"""Состояние станции в виде JSON для веб-интерфейса.

Только чтение: машина не меняется. Поле `kind` называет экран; остальное — данные для него.
Тексты ошибок и подсказок приходят уже по-русски из машины, подписи интерфейса рисует клиент.
"""

from __future__ import annotations

from typing import Any

from .machine import (
    DONE_SECONDS,
    Blocked,
    Candidate,
    Checking,
    Confirm,
    Done,
    Idle,
    Playing,
    RejectedList,
    Starting,
    StationMachine,
    TechnicalProblem,
)
from .status import StationStatus


def candidate_view(candidate: Candidate) -> dict[str, Any]:
    team = candidate.team
    return {
        "code": candidate.code,
        "display_name": candidate.display_name,
        "team": {"number": team.number, "name": team.name, "color": team.color} if team else None,
        "issues": list(candidate.issues),
        "offline": candidate.offline,
        "warned": candidate.warned,
    }


def _candidates(items: tuple[Candidate, ...]) -> list[dict[str, Any]]:
    return [candidate_view(c) for c in items]


def state_view(machine: StationMachine) -> dict[str, Any]:
    state = machine.state
    match state:
        case Idle():
            return {
                "kind": "idle",
                "input": state.input,
                "notice": state.notice,
                "taken": _candidates(state.taken),
            }
        case Checking():
            return {"kind": "checking", "code": state.code, "taken": _candidates(state.taken)}
        case Confirm():
            return {
                "kind": "confirm",
                "candidate": candidate_view(state.candidate),
                "taken": _candidates(state.taken),
                "notice": state.notice,
                "is_last": len(state.taken) + 1 >= machine.players_needed,
            }
        case Starting():
            return {"kind": "starting", "players": _candidates(state.players)}
        case Playing():
            return {
                "kind": "playing",
                "players": _candidates(state.players),
                "offline": state.offline,
                "default_limit": state.default_limit,
            }
        case Done():
            return {
                "kind": "done",
                "lines": list(state.lines),
                "seconds_left": round(max(0.0, machine.done_seconds_left()), 1),
                "seconds_total": DONE_SECONDS,
            }
        case TechnicalProblem():
            return {
                "kind": "problem",
                "reason": state.reason,
                "players": _candidates(state.players),
            }
        case Blocked():
            return {"kind": "blocked", "message": state.message}
        case RejectedList():
            return {
                "kind": "rejected",
                "items": [
                    {"session_id": i.session_id, "codes": list(i.codes), "error": i.error}
                    for i in state.items
                ],
                "exported_to": state.exported_to,
            }
    raise AssertionError(f"unknown state: {state!r}")


def snapshot(machine: StationMachine, status: StationStatus) -> dict[str, Any]:
    return {
        "discipline": machine.discipline,
        "players_needed": machine.players_needed,
        "status": {
            "pending": status.pending,
            "rejected": status.rejected,
            "online": status.online,
        },
        "state": state_view(machine),
    }
