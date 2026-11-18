"""Восстановление после перезапуска лаунчера посреди игры."""

from __future__ import annotations

import uuid
from pathlib import Path

from . import texts
from .game import Crashed, GameRequest, Player, parse_result, session_dir
from .machine import StationMachine
from .outbox import Outbox


def recover_active(machine: StationMachine, outbox: Outbox, data_dir: Path) -> None:
    """Есть активная сессия: готовый result.json уходит в буфер, иначе «Техническая проблема»."""
    active = outbox.get_active()
    if active is None:
        return
    if outbox.has(active.session_id) or active.discipline != machine.discipline:
        outbox.clear_active()
        return
    request = GameRequest(
        uuid.UUID(active.session_id),
        active.discipline,
        active.duration_s,
        tuple(Player(code, name) for code, name in active.players),
    )
    result_path = session_dir(data_dir, active.session_id) / "result.json"
    if result_path.exists():
        outcome = parse_result(result_path, request)
    else:
        outcome = Crashed(texts.RESTARTED)
    machine.recover(active, outcome)
