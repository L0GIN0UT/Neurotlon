"""Офлайн-буфер результатов: SQLite (WAL), переживает перезапуск лаунчера."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

State = Literal["pending", "sent", "rejected"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    session_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'sent', 'rejected')),
    created_at TEXT NOT NULL
)
"""


_ACTIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS active_session (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    data TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class ActiveSession:
    """Сессия, игра которой запущена и результат ещё не поставлен в буфер."""

    session_id: str
    discipline: str
    duration_s: int
    players: tuple[tuple[str, str | None], ...]  # (код, имя для табло)
    max_points: int | None = None


@dataclass(frozen=True)
class OutboxItem:
    session_id: str
    payload: dict[str, Any]
    attempts: int
    last_error: str | None
    state: State


class ResultQueue(Protocol):
    """Что нужно машине состояний от буфера."""

    def add(self, payload: dict[str, Any]) -> None: ...

    def set_active(self, active: ActiveSession) -> None: ...

    def clear_active(self) -> None: ...

    def rejected(self) -> list[OutboxItem]: ...

    def export_rejected(self) -> Path: ...

    def pending_count(self) -> int: ...


class Outbox:
    """Порядок отправки — порядок добавления (rowid). Повтор `session_id` не создаёт дубль."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._export_path = path.parent / "rejected.json"
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(_SCHEMA)
        self._db.execute(_ACTIVE_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def export_rejected(self) -> Path:
        """Записать отклонённые результаты в JSON рядом с базой (для судьи)."""
        items = [
            {
                "session_id": item.session_id,
                "participant_codes": [
                    e["participant_code"] for e in item.payload.get("entries", [])
                ],
                "error": item.last_error,
                "attempts": item.attempts,
                "payload": item.payload,
            }
            for item in self.rejected()
        ]
        tmp = self._export_path.with_name(self._export_path.name + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._export_path)
        return self._export_path

    def add(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO outbox (session_id, payload, created_at) VALUES (?, ?, ?)",
                (
                    str(payload["session_id"]),
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def _items(self, state: State) -> list[OutboxItem]:
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id, payload, attempts, last_error, state FROM outbox "
                "WHERE state = ? ORDER BY rowid",
                (state,),
            ).fetchall()
        return [OutboxItem(r[0], json.loads(r[1]), r[2], r[3], r[4]) for r in rows]

    def has(self, session_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM outbox WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def set_active(self, active: ActiveSession) -> None:
        data = json.dumps(
            {
                "session_id": active.session_id,
                "discipline": active.discipline,
                "duration_s": active.duration_s,
                "players": [list(p) for p in active.players],
                "max_points": active.max_points,
            },
            ensure_ascii=False,
        )
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO active_session (slot, data) VALUES (1, ?)", (data,)
            )

    def get_active(self) -> ActiveSession | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM active_session WHERE slot = 1").fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return ActiveSession(
            data["session_id"],
            data["discipline"],
            int(data["duration_s"]),
            tuple((p[0], p[1]) for p in data["players"]),
            data.get("max_points"),
        )

    def clear_active(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM active_session")

    def pending(self) -> list[OutboxItem]:
        return self._items("pending")

    def rejected(self) -> list[OutboxItem]:
        return self._items("rejected")

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM outbox WHERE state = 'pending'").fetchone()
        return int(row[0])

    def rejected_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM outbox WHERE state = 'rejected'"
            ).fetchone()
        return int(row[0])

    def mark_sent(self, session_id: str) -> None:
        self._update(session_id, "sent", None)

    def mark_rejected(self, session_id: str, error: str) -> None:
        self._update(session_id, "rejected", error)

    def record_failure(self, session_id: str, error: str) -> None:
        self._update(session_id, "pending", error)

    def _update(self, session_id: str, state: State, error: str | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE outbox SET state = ?, last_error = ?, attempts = attempts + 1 "
                "WHERE session_id = ?",
                (state, error, session_id),
            )
