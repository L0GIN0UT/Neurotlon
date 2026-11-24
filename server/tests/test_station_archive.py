import json
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings
from neurotlon_server.models import AuditLog, GameSession, Station
from neurotlon_server.security import hash_token

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, SESSION_A, darts_body, seed_people
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


def test_archive_audit_has_no_secrets(boss: TestClient, db: Session, clock: FakeClock) -> None:
    station = _create(boss)
    boss.delete(f"{API}/stations/{station['id']}")
    row = db.scalars(select(AuditLog).where(AuditLog.action == "station.archive")).one()
    assert (row.object_type, row.object_id) == ("station", str(station["id"]))
    assert row.before == {"name": "Darts-1"}
    assert row.after == {
        "name": f"Darts-1 [удалена {station['id']} {int(clock.now.timestamp())}]",
        "archived_at": clock.now.isoformat(),
        "closed_sessions": 0,
    }
    dump = json.dumps([row.before, row.after])
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


def _open_session(db: Session, station_id: int, clock: FakeClock) -> GameSession:
    session = GameSession(
        session_id=SESSION_A,
        station_id=station_id,
        discipline="darts",
        started_at=clock.now,
    )
    db.add(session)
    db.commit()
    return session


def test_live_session_blocks_archive(
    boss: TestClient, client: TestClient, db: Session, clock: FakeClock
) -> None:
    station = _create(boss)
    headers = {"Authorization": f"Bearer {station['token']}"}
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    _open_session(db, int(station["id"]), clock)
    response = boss.delete(f"{API}/stations/{station['id']}")
    assert response.status_code == 409
    assert "rotate its token" in response.json()["detail"]
    # nothing changed: still listed, token still works, session still open
    assert len(boss.get(f"{API}/stations").json()) == 1
    beat = client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    assert beat.status_code == 204
    db.expire_all()
    assert db.get(GameSession, SESSION_A).closed_at is None  # type: ignore[union-attr]


def test_abandoned_session_is_closed_on_archive(
    boss: TestClient, client: TestClient, db: Session, clock: FakeClock
) -> None:
    station = _create(boss)
    headers = {"Authorization": f"Bearer {station['token']}"}
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    _open_session(db, int(station["id"]), clock)
    clock.advance(minutes=10)  # heartbeat is stale
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204
    db.expire_all()
    assert db.get(GameSession, SESSION_A).closed_at == clock.now  # type: ignore[union-attr]
    row = db.scalars(select(AuditLog).where(AuditLog.action == "station.archive")).one()
    assert row.after is not None
    assert row.after["closed_sessions"] == 1


def test_session_of_never_seen_station_does_not_block(
    boss: TestClient, db: Session, clock: FakeClock
) -> None:
    station = _create(boss)
    _open_session(db, int(station["id"]), clock)
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204


def test_name_collision_with_archive_suffix_is_not_a_500(
    boss: TestClient, clock: FakeClock
) -> None:
    target = _create(boss, "S")
    ts = int(clock.now.timestamp())
    _create(boss, f"S [удалена {target['id']} {ts}]")
    response = boss.delete(f"{API}/stations/{target['id']}")
    assert response.status_code == 409
    assert len(boss.get(f"{API}/stations").json()) == 2


def test_superuser_can_archive(app: FastAPI, db: Session, boss: TestClient) -> None:
    station = _create(boss)
    make_user(db, "root", role="superuser")
    assert login_as(app, "root").delete(f"{API}/stations/{station['id']}").status_code == 204


def test_station_token_cannot_archive(boss: TestClient, client: TestClient) -> None:
    station = _create(boss)
    headers = {"Authorization": f"Bearer {station['token']}"}
    assert client.delete(f"{API}/stations/{station['id']}", headers=headers).status_code == 401


def test_archived_token_is_rejected_everywhere(
    boss: TestClient, client: TestClient, db: Session
) -> None:
    seed_people(db)
    station = _create(boss)
    headers = {"Authorization": f"Bearer {station['token']}"}
    assert boss.delete(f"{API}/stations/{station['id']}").status_code == 204
    query = {"discipline": "darts", "section": "bci"}
    body = {"session_id": SESSION_A, "discipline": "darts", "participant_codes": ["NT01"]}
    codes = (
        client.get(f"{API}/me/config", headers=headers).status_code,
        client.get(
            f"{API}/participants/NT01/eligibility", params=query, headers=headers
        ).status_code,
        client.post(f"{API}/sessions", json=body, headers=headers).status_code,
    )
    assert codes == (401, 401, 401)


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


def test_downgrade_keeps_history(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'd.db'}"
    config = _alembic_config(url)
    command.upgrade(config, "head")
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO station (name, discipline, token_hash, queue_length, archived_at) "
                f"VALUES ('s1', 'darts', 'h1', 0, '{NOW}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO audit_log (at, action, object_type, object_id, station_id) "
                "VALUES (:at, 'a', 't', '1', 1)"
            ),
            {"at": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO game_session (session_id, station_id, discipline, started_at) "
                "VALUES ('s', 1, 'darts', :at)"
            ),
            {"at": NOW},
        )
    command.downgrade(config, "0008")
    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("station")}
        counts = [
            conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            for table in ("station", "audit_log", "game_session")
        ]
    assert "archived_at" not in columns
    assert counts == [1, 1, 1]
    engine.dispose()
