"""Database backup and restore (docs/architecture.md, section 2).

A backup is a consistent copy made with the SQLite Backup API, so it is safe while the server
writes. It is written to a temporary file and renamed, so the folder never holds a half-written
`neurotlon-*.db`. Restore refuses to touch a database that another process has open.
"""

import logging
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("neurotlon.backup")

_NAME = re.compile(r"^neurotlon-\d{8}-\d{6}\.db$")
_STALE_TMP = ".neurotlon-*.db.tmp"


class BackupError(Exception):
    """The backup or restore could not be done; the message says why."""


class DatabaseInUseError(BackupError):
    """Another process has the database open (the server is still running)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)


def _copy(source: Path, target: Path) -> None:
    """Consistent copy through the Backup API into a self-contained single file."""
    with closing(_open_readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
        check = dst.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise BackupError(f"copy of {source} failed the integrity check")


def _backups(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and _NAME.match(p.name))


def backup_once(db: Path, to: Path, keep: int, now: Callable[[], datetime] = _utcnow) -> Path:
    """Write one timestamped copy of `db` into `to`; keep only the newest `keep` copies."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not db.is_file():
        raise BackupError(f"database file not found: {db}")
    name = f"neurotlon-{now():%Y%m%d-%H%M%S}.db"
    tmp = to / f".{name}.tmp"
    try:
        to.mkdir(parents=True, exist_ok=True)
        for stale in to.glob(_STALE_TMP):
            stale.unlink(missing_ok=True)
        try:
            _copy(db, tmp)
            os.replace(tmp, to / name)
        finally:
            tmp.unlink(missing_ok=True)
        for old in _backups(to)[:-keep]:
            old.unlink(missing_ok=True)
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"backup of {db} to {to} failed: {exc}") from exc
    return to / name


def _default_sleep(stop: threading.Event) -> Callable[[float], bool]:
    return stop.wait


def run_loop(
    db: Path,
    to: Path,
    every: float,
    keep: int,
    *,
    sleep: Callable[[float], bool] | None = None,
    now: Callable[[], datetime] = _utcnow,
    stop: threading.Event | None = None,
) -> None:
    """Back up every `every` seconds until `sleep` returns True (stop requested).

    A failed round (unplugged disk, database not created yet) is logged and retried next round:
    a backup service that exits would stay silent until someone looks.
    """
    wait = sleep or _default_sleep(stop or threading.Event())
    while True:
        try:
            path = backup_once(db, to, keep, now)
            log.info("backup written: %s", path)
        except BackupError as exc:
            log.error("%s", exc)
        if wait(every):
            return


def _ensure_not_in_use(db: Path) -> None:
    """Exclusive access to the WAL index succeeds only when no other process has the DB open."""
    conn = sqlite3.connect(db, timeout=0)
    try:
        conn.execute("PRAGMA locking_mode=EXCLUSIVE")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchall()
        conn.execute("BEGIN EXCLUSIVE")
        conn.rollback()
    except sqlite3.OperationalError as exc:
        raise DatabaseInUseError(
            f"database {db} is in use: stop the server first (docker compose stop server web)"
        ) from exc
    finally:
        conn.close()


def _verify(source: Path) -> None:
    try:
        with closing(_open_readonly(source)) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f"{source} is not a usable database: {exc}") from exc
    if result is None or result[0] != "ok":
        raise BackupError(f"{source} failed the integrity check")


def restore(source: Path, db: Path, now: Callable[[], datetime] = _utcnow) -> Path | None:
    """Replace `db` with the backup `source`.

    The old file, if any, is kept next to it as `<name>.before-restore-<time>`. Returns its path.
    """
    if not source.is_file():
        raise BackupError(f"backup file not found: {source}")
    _verify(source)
    kept: Path | None = None
    tmp = db.with_name(f".{db.name}.restore.tmp")
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        if db.exists():
            _ensure_not_in_use(db)
        _copy(source, tmp)
        with closing(sqlite3.connect(tmp)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
        if db.exists():
            kept = db.with_name(f"{db.name}.before-restore-{now():%Y%m%d-%H%M%S}")
            os.replace(db, kept)
        for suffix in ("-wal", "-shm"):  # leftovers of the old database must not meet the new one
            db.with_name(db.name + suffix).unlink(missing_ok=True)
        os.replace(tmp, db)
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"restore into {db} failed: {exc}") from exc
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
    return kept
