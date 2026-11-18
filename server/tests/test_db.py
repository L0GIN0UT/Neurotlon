from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings
from neurotlon_server.models import AuditLog, Base, Station

SERVER_DIR = Path(__file__).resolve().parents[1]
NOW = "2027-01-01 00:00:00.000000"  # SQLAlchemy storage format for UTC datetimes


def _alembic_config(url: str) -> Config:
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(params=["migration", "create_all"])
def engine(request: pytest.FixtureRequest, url: str) -> Iterator[Engine]:
    if request.param == "migration":
        command.upgrade(_alembic_config(url), "head")
    else:
        schema_engine = create_engine_from_settings(Settings(database_url=url))
        Base.metadata.create_all(schema_engine)
        with schema_engine.begin() as conn:  # seed rows live in the migration only
            conn.execute(
                text(
                    "INSERT INTO discipline "
                    "(code, name, modalities, game_duration_s, physical_duration_s) "
                    "VALUES ('darts', 'D', '[]', 120, 300), "
                    "('football', 'F', '[]', 120, 300), ('pong', 'P', '[]', 120, 300)"
                )
            )
        schema_engine.dispose()
    engine = create_engine_from_settings(Settings(database_url=url))
    yield engine
    engine.dispose()


def _insert(engine: Engine, table: str, **values: Any) -> None:
    columns = ", ".join(f'"{c}"' for c in values)
    params = ", ".join(f":{c}" for c in values)
    with engine.begin() as conn:
        conn.execute(text(f'INSERT INTO "{table}" ({columns}) VALUES ({params})'), values)


def _participant(engine: Engine, code: str = "NT07", **extra: Any) -> None:
    _insert(engine, "participant", code=code, **extra)


def _result(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "session_id": "s1",
        "participant_id": 1,
        "discipline": "darts",
        "section": "bci",
        "outcome": "completed",
        "points": 10.0,
        "source": "station",
        "finished_at": NOW,
        "created_at": NOW,
    }
    row.update(overrides)
    return row


def test_settings_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEUROTLON_DATABASE_URL", raising=False)
    assert Settings().database_url == "sqlite:///./neurotlon.db"
    monkeypatch.setenv("NEUROTLON_DATABASE_URL", "sqlite:///x.db")
    assert Settings().database_url == "sqlite:///x.db"


def test_upgrade_and_downgrade(url: str) -> None:
    config = _alembic_config(url)
    command.upgrade(config, "head")
    engine = create_engine_from_settings(Settings(database_url=url))
    assert {"participant", "audit_log", "section_result"} <= set(inspect(engine).get_table_names())
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def test_pragmas_are_set(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1


def test_models_match_migration(engine: Engine) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_disciplines_seeded(url: str) -> None:
    command.upgrade(_alembic_config(url), "head")
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT code, name, modalities, game_duration_s, physical_duration_s "
                "FROM discipline ORDER BY code"
            )
        ).all()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("darts", "Дартс", '["eeg", "emg"]'),
        ("football", "Футбол", '["eeg", "emg"]'),
        ("pong", "Понг", '["emg"]'),
    ]
    assert all((r[3], r[4]) == (120, 300) for r in rows)


def test_audit_log_is_append_only(engine: Engine) -> None:
    _insert(engine, "audit_log", at=NOW, action="a", object_type="t", object_id="1")
    with engine.begin() as conn, pytest.raises(IntegrityError, match="append-only"):
        conn.execute(text("UPDATE audit_log SET action = 'b'"))
    with engine.begin() as conn, pytest.raises(IntegrityError, match="append-only"):
        conn.execute(text("DELETE FROM audit_log"))


@pytest.mark.parametrize("code", ["NT07", "NT99", "NT01"])
def test_participant_code_valid(engine: Engine, code: str) -> None:
    _participant(engine, code)


@pytest.mark.parametrize("code", ["NT00", "NT7", "nt07", "NT007", "XX07", "NTAB"])
def test_participant_code_invalid(engine: Engine, code: str) -> None:
    with pytest.raises(IntegrityError):
        _participant(engine, code)


def test_participant_code_unique(engine: Engine) -> None:
    _participant(engine)
    with pytest.raises(IntegrityError):
        _participant(engine)


def test_participant_category(engine: Engine) -> None:
    _participant(engine, "NT01", category="general")
    _participant(engine, "NT02")  # null until check-in
    with pytest.raises(IntegrityError):
        _participant(engine, "NT03", category="other")


def test_team_color_and_number(engine: Engine) -> None:
    _insert(engine, "team", number=1, name="A", color="#1a2B3c", order=1)
    for number, color in ((2, "red"), (3, "#12345"), (0, "#112233")):
        with pytest.raises(IntegrityError):
            _insert(engine, "team", number=number, name="X", color=color, order=number)


def test_team_slot_unique(engine: Engine) -> None:
    _insert(engine, "team", number=1, name="A", color="#112233", order=1)
    _participant(engine, "NT01", team_id=1, number_in_team=1)
    with pytest.raises(IntegrityError):
        _participant(engine, "NT02", team_id=1, number_in_team=1)


def test_duel_distinct_teams(engine: Engine) -> None:
    _insert(engine, "team", number=1, name="A", color="#112233", order=1)
    with pytest.raises(IntegrityError):
        _insert(engine, "duel", team_a_id=1, team_b_id=1, order=1)


def test_pair_distinct_participants(engine: Engine) -> None:
    _insert(engine, "team", number=1, name="A", color="#112233", order=1)
    _insert(engine, "team", number=2, name="B", color="#445566", order=2)
    _insert(engine, "duel", team_a_id=1, team_b_id=2, order=1)
    _participant(engine, "NT01")
    with pytest.raises(IntegrityError):
        _insert(
            engine,
            "pair",
            duel_id=1,
            k=1,
            participant_a_id=1,
            participant_b_id=1,
            zone_statuses="{}",
        )


def test_foreign_keys_enforced(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        _insert(engine, "station", name="s", discipline="nope", token_hash="h")
    with pytest.raises(IntegrityError):
        _insert(engine, "section_result", **_result(participant_id=999))


def test_station_stores_token_hash_with_defaults(engine: Engine) -> None:
    _insert(engine, "station", name="s", discipline="darts", token_hash="h")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT queue_length FROM station")).scalar() == 0


def test_section_result_defaults(engine: Engine) -> None:
    _participant(engine, "NT01")
    _insert(engine, "section_result", **_result())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status, version FROM section_result")).one() == (
            "entered",
            1,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"points": None},  # completed needs points
        {"reason": "health"},  # completed forbids reason
        {"points": -1.0},
        {"section": "other"},
        {"status": "done"},
        {"source": "robot"},
        {"outcome": "unknown"},
        {"outcome": "not_completed", "points": None, "reason": None},
        {"outcome": "not_completed", "points": 1.0, "reason": "health"},
        {"outcome": "not_completed", "points": None, "reason": "health", "wins": 1},
        {"outcome": "not_completed", "points": None, "reason": "bad"},
        {"wins": -1},
    ],
)
def test_section_result_rejects_invalid(engine: Engine, overrides: dict[str, Any]) -> None:
    _participant(engine, "NT01")
    with pytest.raises(IntegrityError):
        _insert(engine, "section_result", **_result(**overrides))


def test_section_result_not_completed_ok(engine: Engine) -> None:
    _participant(engine, "NT01")
    row = _result(outcome="not_completed", points=None, reason="equipment")
    _insert(engine, "section_result", **row)


def test_section_result_session_unique_but_duplicates_across_sessions_allowed(
    engine: Engine,
) -> None:
    _participant(engine, "NT01")
    _insert(engine, "section_result", **_result())
    _insert(engine, "section_result", **_result(session_id="s2"))  # offline-buffer duplicate
    with pytest.raises(IntegrityError):
        _insert(engine, "section_result", **_result())


@pytest.mark.parametrize(
    ("role", "discipline", "ok"),
    [
        ("volunteer", "darts", True),
        ("volunteer", None, False),
        ("judge", "darts", False),
        ("judge", None, True),
        ("admin", None, True),
        ("boss", None, False),
    ],
)
def test_user_volunteer_discipline(
    engine: Engine, role: str, discipline: str | None, ok: bool
) -> None:
    def add() -> None:
        _insert(engine, "user", login="u", password_hash="h", role=role, discipline=discipline)

    if ok:
        add()
    else:
        with pytest.raises(IntegrityError):
            add()


def test_datetime_roundtrip_normalizes_to_utc(engine: Engine) -> None:
    local = datetime(2027, 3, 5, 14, 30, tzinfo=timezone(timedelta(hours=4)))
    _insert(engine, "station", name="s", discipline="darts", token_hash="h")
    with Session(engine) as session:
        station = session.query(Station).one()
        station.last_heartbeat_at = local
        session.commit()
        session.expire_all()
        got = session.query(Station).one().last_heartbeat_at
    assert got == local
    assert got is not None
    assert got.tzinfo == UTC
    assert got.hour == 10


def test_naive_datetime_rejected(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(AuditLog(at=datetime(2027, 1, 1), action="a", object_type="t", object_id="1"))
        with pytest.raises(Exception, match="naive datetime"):
            session.flush()


def test_orm_reads_datetime_from_fixture_row(engine: Engine) -> None:
    _insert(engine, "audit_log", at=NOW, action="a", object_type="t", object_id="1")
    with Session(engine) as session:
        assert session.query(AuditLog).one().at == datetime(2027, 1, 1, tzinfo=UTC)


def test_audit_log_none_stored_as_sql_null(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            AuditLog(
                at=datetime(2027, 1, 1, tzinfo=UTC),
                action="a",
                object_type="t",
                object_id="1",
                before=None,
                after={"k": 1},
            )
        )
        session.commit()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT before IS NULL, after FROM audit_log")).one()
    assert row[0] == 1
    assert row[1] == '{"k": 1}'
