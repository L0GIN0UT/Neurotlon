import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from neurotlon_server.backup import (
    BackupError,
    DatabaseInUseError,
    backup_once,
    restore,
    run_loop,
)
from neurotlon_server.cli import main


def make_db(path: Path, rows: int = 3) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row {i}",) for i in range(rows)])
    # sqlite3's context manager commits but does not close
    conn.close()


def count_rows(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT count(*) FROM t").fetchone()[0])
    finally:
        conn.close()


class Ticker:
    def __init__(self) -> None:
        self.now = datetime(2027, 1, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=60)
        return self.now


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "neurotlon.db"
    path.parent.mkdir()
    make_db(path)
    return path


def test_backup_once_writes_consistent_timestamped_copy(db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    result = backup_once(db_path, dest, keep=5, now=Ticker())
    assert result.parent == dest
    assert result.name == "neurotlon-20270101-090100.db"
    assert count_rows(result) == 3
    assert [p.name for p in dest.iterdir()] == [result.name]  # no leftover tmp file


def test_backup_sees_uncheckpointed_wal_data(db_path: Path, tmp_path: Path) -> None:
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO t (v) VALUES ('late')")
    writer.commit()
    try:
        result = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    finally:
        writer.close()
    assert count_rows(result) == 4


def test_backup_keeps_only_last_n(db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    ticker = Ticker()
    names = [backup_once(db_path, dest, keep=3, now=ticker).name for _ in range(5)]
    assert sorted(p.name for p in dest.iterdir()) == sorted(names[-3:])


def test_retention_ignores_foreign_files(db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    dest.mkdir()
    (dest / "notes.txt").write_text("keep me")
    ticker = Ticker()
    for _ in range(3):
        backup_once(db_path, dest, keep=1, now=ticker)
    assert (dest / "notes.txt").exists()
    assert len([p for p in dest.iterdir() if p.suffix == ".db"]) == 1


def test_backup_removes_stale_tmp_files(db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    dest.mkdir()
    stale = dest / ".neurotlon-old.db.tmp"
    stale.write_bytes(b"half written")
    backup_once(db_path, dest, keep=5, now=Ticker())
    assert not stale.exists()


def test_backup_missing_db_raises_and_creates_nothing(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="not found"):
        backup_once(tmp_path / "none.db", tmp_path / "backup", keep=5)
    assert not (tmp_path / "none.db").exists()


def test_backup_failure_leaves_no_partial_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a database" * 100)
    dest = tmp_path / "backup"
    with pytest.raises(BackupError):
        backup_once(broken, dest, keep=5)
    assert list(dest.iterdir()) == []


def test_backup_rejects_bad_keep(db_path: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep"):
        backup_once(db_path, tmp_path / "b", keep=0)


def test_loop_runs_until_stopped_and_survives_errors(db_path: Path, tmp_path: Path) -> None:
    dest = tmp_path / "backup"
    calls = {"n": 0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> bool:
        sleeps.append(seconds)
        calls["n"] += 1
        if calls["n"] == 1:
            db_path.rename(db_path.with_name("moved.db"))  # next round fails
        elif calls["n"] == 2:
            db_path.with_name("moved.db").rename(db_path)
        return calls["n"] >= 3  # True = stop

    run_loop(db_path, dest, every=60, keep=5, sleep=sleep, now=Ticker())
    assert sleeps == [60, 60, 60]
    assert len(list(dest.glob("neurotlon-*.db"))) == 2  # rounds 1 and 3 succeeded


def test_restore_replaces_db_and_keeps_old_copy(db_path: Path, tmp_path: Path) -> None:
    snapshot = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM t")
    conn.close()
    assert count_rows(db_path) == 0
    restore(snapshot, db_path, now=Ticker())
    assert count_rows(db_path) == 3
    kept = list(db_path.parent.glob("neurotlon.db.before-restore-*"))
    assert len(kept) == 1
    assert count_rows(kept[0]) == 0
    assert not db_path.with_name("neurotlon.db-wal").exists()


def test_restore_into_empty_place(db_path: Path, tmp_path: Path) -> None:
    snapshot = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    target = tmp_path / "spare" / "neurotlon.db"
    restore(snapshot, target)
    assert count_rows(target) == 3
    journal = sqlite3.connect(target).execute("PRAGMA journal_mode").fetchone()[0]
    assert journal == "wal"


def test_restore_removes_stale_wal_of_old_db(db_path: Path, tmp_path: Path) -> None:
    snapshot = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    wal = db_path.with_name("neurotlon.db-wal")
    wal.write_bytes(b"stale frames from the dead server")
    restore(snapshot, db_path)
    assert count_rows(db_path) == 3  # stale WAL would corrupt or hide the restored data


def test_restore_refuses_when_db_is_in_use(db_path: Path, tmp_path: Path) -> None:
    snapshot = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    server = sqlite3.connect(db_path)  # an open connection, like the running server
    server.execute("PRAGMA journal_mode=WAL")
    server.execute("SELECT count(*) FROM t").fetchall()
    try:
        with pytest.raises(DatabaseInUseError):
            restore(snapshot, db_path)
        assert count_rows(db_path) == 3  # untouched
    finally:
        server.close()


def test_restore_refuses_corrupt_source(db_path: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"garbage" * 1000)
    with pytest.raises(BackupError):
        restore(bad, db_path)
    assert count_rows(db_path) == 3


def test_restore_refuses_missing_source(db_path: Path, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="not found"):
        restore(tmp_path / "nope.db", db_path)


def test_cli_backup_once_and_restore(
    db_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "backup"
    assert main(["backup", "--db", str(db_path), "--to", str(dest), "--once", "--keep", "2"]) == 0
    (snapshot,) = dest.glob("neurotlon-*.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM t")
    conn.close()
    assert main(["restore", "--from", str(snapshot), "--db", str(db_path)]) == 0
    assert count_rows(db_path) == 3
    assert "Restored" in capsys.readouterr().out


def test_cli_backup_once_fails_with_nonzero_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["backup", "--db", str(tmp_path / "x.db"), "--to", str(tmp_path / "b"), "--once"])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_cli_restore_in_use_exits_nonzero(
    db_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = backup_once(db_path, tmp_path / "backup", keep=5, now=Ticker())
    server = sqlite3.connect(db_path)
    server.execute("PRAGMA journal_mode=WAL")
    server.execute("SELECT count(*) FROM t").fetchall()
    try:
        assert main(["restore", "--from", str(snapshot), "--db", str(db_path)]) == 1
    finally:
        server.close()
    assert "in use" in capsys.readouterr().err
