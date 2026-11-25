"""Фото игроков на экране: только в памяти, пока участник на экране.

Фото — персональные данные (решение 36): на диск, в журнал и в логи оно не попадает.
"""

from __future__ import annotations

from collections.abc import Iterable


class PhotoCache:
    """Код участника → JPEG. Не потокобезопасен: вызывается под замком станции."""

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}
        self._missing: set[str] = set()  # «нет фото» и ошибки: не спрашиваем сервер снова

    def get(self, code: str) -> bytes | None:
        return self._items.get(code)

    def put(self, code: str, data: bytes) -> None:
        self._items[code] = data

    def is_missing(self, code: str) -> bool:
        return code in self._missing

    def put_missing(self, code: str) -> None:
        self._missing.add(code)

    def keep(self, codes: Iterable[str]) -> None:
        """Оставить фото только тех, кто ещё на экране; остальных забыть."""
        wanted = set(codes)
        self._missing &= wanted
        for code in [c for c in self._items if c not in wanted]:
            del self._items[code]

    def __len__(self) -> int:
        return len(self._items)
