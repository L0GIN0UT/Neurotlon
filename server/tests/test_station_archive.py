import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings
from neurotlon_server.models import AuditLog, GameSession, Station
from neurotlon_server.security import hash_token

from .conftest import login_as, make_user
from .station_helpers import API, darts_body, seed_people
from .test_db import NOW, _alembic_config
from .test_station_heartbeat import BEAT


@pytest.fixture
def boss(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "boss", role="admin")
    return login_as(app, "boss")


def _create(boss: TestClient, name: str = "Darts-1") -> dict[str, str | int]:
    response = boss.post(f"{API}/stations", json={"name": name, "discipline": "darts"})
    assert response.status_code == 201
    body: dict[str, str | int] = response.json()
    return body


def test_archive_removes_station_from_list(boss: TestClient) -> None:
    keep, gone = _create(boss, "keep"), _create(boss, "gone")
    assert boss.delete(f"{API}/stations/{gone['id']}").status_code == 204
    assert [s["id"] for s in boss.get(f"{API}/stations").json()] == [keep["id"]]


def test_archived_token_gets_401(boss: TestClient, client: TestClient, db: Session) -> None:
    seed_people(db)
    station = _create(boss)
    headers = {"Authorization": f"Bearer {station['token']}"}
    assert (
        client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers).status_code == 204
    )
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204
    beat = client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    result = client.post(f"{API}/results", json=darts_body(), headers=headers)
    assert (beat.status_code, result.status_code) == (401, 401)


def test_archive_audit_has_no_secrets(boss: TestClient, db: Session) -> None:
    station = _create(boss)
    boss.delete(f"{API}/stations/{station['id']}")
    row = db.scalars(select(AuditLog).where(AuditLog.action == "station.archive")).one()
    assert (row.object_type, row.object_id) == ("station", str(station["id"]))
    assert row.after == {"name": "Darts-1", "discipline": "darts"}
    dump = json.dumps(row.after)
    for secret in (str(station["token"]), hash_token(str(station["token"])), "token_hash"):
        assert secret not in dump


@pytest.mark.parametrize(("role", "discipline"), [("judge", None), ("volunteer", "darts")])
def test_staff_cannot_archive(
    app: FastAPI, db: Session, boss: TestClient, role: str, discipline: str | None
) -> None:
    station = _create(boss)
    make_user(db, "staff", role=role, discipline=discipline)
    response = login_as(app, "staff").delete(f"{API}/stations/{station['id']}")
    assert response.status_code == 403
    assert len(boss.get(f"{API}/stations").json()) == 1


def test_repeat_and_unknown_are_404(boss: TestClient) -> None:
    station = _create(boss)
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 404
    assert boss.delete(f"{API}/stations/999").status_code == 404
    assert boss.post(f"{API}/stations/{station['id']}/rotate-token").status_code == 404


def test_name_can_be_reused(boss: TestClient) -> None:
    old = _create(boss, "Darts-1")
    assert boss.delete(f"{API}/stations/{old['id']}").status_code == 204
    new = _create(boss, "Darts-1")
    assert new["id"] != old["id"]
    assert [s["name"] for s in boss.get(f"{API}/stations").json()] == ["Darts-1"]


def test_open_session_blocks_archive(boss: TestClient, db: Session) -> None:
    station = _create(boss)
    session = GameSession(
        session_id="0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10",
        station_id=int(station["id"]),
        discipline="darts",
        started_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    db.add(session)
    db.commit()
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 409
    session.closed_at = datetime(2027, 1, 1, 1, tzinfo=UTC)
    db.commit()
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204


def test_archived_station_with_history_keeps_row(boss: TestClient, db: Session) -> None:
    station = _create(boss)
    boss.delete(f"{API}/stations/{station['id']}")
    db.expire_all()
    archived = db.get(Station, station["id"])
    assert archived is not None
    assert archived.archived_at is not None


def test_migration_on_empty_and_filled_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "head")  # empty database
    command.downgrade(config, "0008")
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO station (name, discipline, token_hash, queue_length) "
                "VALUES ('s1', 'darts', 'h1', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO audit_log (at, action, object_type, object_id, station_id) "
                "VALUES (:at, 'a', 't', '1', 1)"
            ),
            {"at": NOW},
        )
    command.upgrade(config, "head")  # filled database
    with engine.connect() as conn:
        archived = conn.execute(text("SELECT archived_at FROM station")).scalars().all()
        audit = conn.execute(text("SELECT count(*) FROM audit_log")).scalar()
    assert archived == [None]
    assert audit == 1
    engine.dispose()
