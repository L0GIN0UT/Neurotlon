"""Проверки при старте лаунчера."""

from __future__ import annotations

from typing import Protocol

from . import texts
from .api import DisciplineConfig, StationApiError, Unauthorized


class ConfigApi(Protocol):
    def get_config(self) -> DisciplineConfig: ...


def check_discipline(api: ConfigApi, discipline: str) -> str | None:
    """Текст блокирующей ошибки или `None`. Нет связи — не блокируем: проверим позже."""
    try:
        config = api.get_config()
    except Unauthorized:
        return texts.UNAUTHORIZED
    except StationApiError:
        return None
    if config.discipline != discipline:
        return texts.discipline_mismatch(discipline, config.discipline)
    return None
