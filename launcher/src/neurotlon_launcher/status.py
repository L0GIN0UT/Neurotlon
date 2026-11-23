"""Что интерфейс показывает о связи и очереди отправки."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StationStatus:
    pending: int = 0  # результатов ждёт отправки
    rejected: int = 0  # результатов сервер не принял
    online: bool | None = None  # `None` — heartbeat ещё не отправлялся
