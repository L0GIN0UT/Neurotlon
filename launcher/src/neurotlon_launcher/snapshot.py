"""Состояние станции в виде JSON для веб-интерфейса.

Только чтение: машина не меняется. Поле `kind` называет экран; остальное — данные для него.
Тексты ошибок и подсказок приходят уже по-русски из машины, подписи интерфейса рисует клиент.
"""

from __future__ import annotations

from typing import Any

from .calibration import StepView, sensors_view
from .machine import (
    DONE_SECONDS,
    Blocked,
    Calibrating,
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
from .sensors import BridgeStatus
from .status import StationStatus


def photo_url(candidate: Candidate) -> str | None:
    """Относительная ссылка на фото через прокси ядра; токен окна добавляет веб-код."""
    if not candidate.has_photo:
        return None
    return f"/api/photo/{candidate.code}?v={candidate.photo_version or 0}"


def candidate_view(candidate: Candidate) -> dict[str, Any]:
    team = candidate.team
    return {
        "code": candidate.code,
        "display_name": candidate.display_name,
        "team": {"number": team.number, "name": team.name, "color": team.color} if team else None,
        "issues": list(candidate.issues),
        "offline": candidate.offline,
        "warned": candidate.warned,
        "photo_url": photo_url(candidate),
    }


def _candidates(items: tuple[Candidate, ...]) -> list[dict[str, Any]]:
    return [candidate_view(c) for c in items]


def _step_view(step: StepView) -> dict[str, Any]:
    return {
        "id": step.id,
        "step": step.step,
        "signals": list(step.signals),
        "status": step.status,
        "progress": round(step.progress, 3),
        "segment": step.segment,
        "segments_total": step.segments_total,
        "phase": step.phase,
        "phase_left_s": None if step.phase_left_s is None else round(step.phase_left_s, 1),
        "reason_text": step.reason_text,
        "parts": [
            {
                "signal": part.signal,
                "status": part.status,
                "progress": round(part.progress, 3),
                "reason_text": part.reason_text,
            }
            for part in step.parts
        ],
    }


def calibrating_view(machine: StationMachine, players: tuple[Candidate, ...]) -> dict[str, Any]:
    screen = machine.calibration_screen()
    if screen is None:  # связи уже нет (состояние меняется): показываем «связи нет»
        return {
            "kind": "calibrating",
            "players": _candidates(players),
            "link": "connecting",
            "sensors": [],
            "eeg_method": None,
            "steps": [],
            "current": None,
            "ready": False,
        }
    link = screen.link
    return {
        "kind": "calibrating",
        "players": _candidates(players),
        "link": link.link,
        "sensors": sensors_view(link),
        "eeg_method": link.hello.eeg_method if link.hello else None,
        "steps": [_step_view(step) for step in screen.run.steps],
        "current": screen.run.current,
        "ready": screen.run.ready,
    }


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
        case Calibrating():
            return calibrating_view(machine, state.players)
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


def snapshot(
    machine: StationMachine,
    status: StationStatus,
    camera: str | None = None,
    sensors: BridgeStatus | None = None,
) -> dict[str, Any]:
    return {
        "camera": camera,
        "sensors": (
            {"mode": sensors.mode, "ok": sensors.ok, "error": sensors.error} if sensors else None
        ),
        "discipline": machine.discipline,
        "players_needed": machine.players_needed,
        "status": {
            "pending": status.pending,
            "rejected": status.rejected,
            "online": status.online,
        },
        "state": state_view(machine),
    }
