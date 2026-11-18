import json
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.auth import current_station
from neurotlon_server.models import AuditLog, Station, User
from neurotlon_server.security import hash_token

from .conftest import PASSWORD, login_as, make_user

NEW_USER = {"login": "judy", "password": "password-1", "role": "judge"}


@pytest.fixture
def root(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "root", role="superuser")
    return login_as(app, "root")


@pytest.mark.parametrize(
    ("role", "discipline"), [("admin", None), ("judge", None), ("volunteer", "darts")]
)
def test_non_superuser_cannot_manage_users(
    app: FastAPI, db: Session, role: str, discipline: str | None
) -> None:
    make_user(db, "staff", role=role, discipline=discipline)
    staff = login_as(app, "staff")
    response = staff.post("/api/v1/users", json=NEW_USER)
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "forbidden"
    assert staff.post("/api/v1/users/1/revoke-sessions").status_code == 403
    assert staff.patch("/api/v1/users/1", json={"is_active": False}).status_code == 403


def test_user_management_requires_login(client: TestClient) -> None:
    assert client.post("/api/v1/users", json=NEW_USER).status_code == 401


def test_superuser_creates_user_who_can_log_in(app: FastAPI, root: TestClient, db: Session) -> None:
    response = root.post("/api/v1/users", json=NEW_USER)
    assert response.status_code == 201
    body = response.json()
    assert body == {"id": body["id"], "login": "judy", "role": "judge", "discipline": None}
    user = db.get(User, body["id"])
    assert user is not None
    assert user.password_hash.startswith("$argon2")
    judy = TestClient(app, base_url="https://testserver")
    login = judy.post("/api/v1/auth/login", json={"login": "judy", "password": "password-1"})
    assert login.status_code == 204


def test_duplicate_login_is_409(root: TestClient) -> None:
    assert root.post("/api/v1/users", json=NEW_USER).status_code == 201
    response = root.post("/api/v1/users", json=NEW_USER)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


@pytest.mark.parametrize(
    "patch",
    [
        {"password": "short"},
        {"role": "superuser"},
        {"role": "volunteer"},
        {"role": "judge", "discipline": "darts"},
        {"role": "volunteer", "discipline": "chess"},
        {"login": ""},
    ],
)
def test_user_create_validation(root: TestClient, patch: dict[str, str]) -> None:
    assert root.post("/api/v1/users", json={**NEW_USER, **patch}).status_code == 422


def test_volunteer_gets_discipline(root: TestClient) -> None:
    body = {"login": "vol", "password": "password-1", "role": "volunteer", "discipline": "pong"}
    response = root.post("/api/v1/users", json=body)
    assert response.status_code == 201
    assert response.json()["discipline"] == "pong"


def test_revoke_sessions_kills_all_sessions(app: FastAPI, root: TestClient, db: Session) -> None:
    uid = make_user(db, "alice")
    tablet1, tablet2 = login_as(app, "alice"), login_as(app, "alice")
    assert root.post(f"/api/v1/users/{uid}/revoke-sessions").status_code == 204
    assert tablet1.get("/api/v1/auth/me").status_code == 401
    assert tablet2.get("/api/v1/auth/me").status_code == 401
    assert login_as(app, "alice").get("/api/v1/auth/me").status_code == 200  # can log in again
    assert root.get("/api/v1/auth/me").status_code == 200


def test_revoke_sessions_unknown_user_is_404(root: TestClient) -> None:
    assert root.post("/api/v1/users/999/revoke-sessions").status_code == 404


def test_deactivation_revokes_sessions_and_blocks_login(
    app: FastAPI, root: TestClient, db: Session
) -> None:
    uid = make_user(db, "alice")
    tablet = login_as(app, "alice")
    assert root.patch(f"/api/v1/users/{uid}", json={"is_active": False}).status_code == 200
    assert tablet.get("/api/v1/auth/me").status_code == 401
    retry = tablet.post("/api/v1/auth/login", json={"login": "alice", "password": PASSWORD})
    assert retry.status_code == 401
    assert root.patch(f"/api/v1/users/{uid}", json={"is_active": True}).status_code == 200
    assert login_as(app, "alice").get("/api/v1/auth/me").status_code == 200


def test_password_change_revokes_sessions_and_applies(
    app: FastAPI, root: TestClient, db: Session
) -> None:
    uid = make_user(db, "alice")
    tablet = login_as(app, "alice")
    patched = root.patch(f"/api/v1/users/{uid}", json={"password": "new-password-1"})
    assert patched.status_code == 200
    assert tablet.get("/api/v1/auth/me").status_code == 401
    client = TestClient(app, base_url="https://testserver")
    old = client.post("/api/v1/auth/login", json={"login": "alice", "password": PASSWORD})
    new = client.post("/api/v1/auth/login", json={"login": "alice", "password": "new-password-1"})
    assert (old.status_code, new.status_code) == (401, 204)


def test_patch_unknown_user_is_404_and_short_password_422(root: TestClient) -> None:
    assert root.patch("/api/v1/users/999", json={"is_active": False}).status_code == 404
    assert root.patch("/api/v1/users/1", json={"password": "short"}).status_code == 422


def test_admin_can_create_station_and_only_hash_is_stored(app: FastAPI, db: Session) -> None:
    make_user(db, "boss", role="admin")
    boss = login_as(app, "boss")
    response = boss.post("/api/v1/stations", json={"name": "Darts-1", "discipline": "darts"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name", "discipline", "token"}
    station = db.get(Station, body["id"])
    assert station is not None
    assert station.token_hash == hash_token(body["token"])
    assert body["token"] != station.token_hash


def test_station_creation_forbidden_for_judge_and_duplicate_name(
    app: FastAPI, root: TestClient, db: Session
) -> None:
    make_user(db, "judy", role="judge")
    judy = login_as(app, "judy")
    payload = {"name": "S1", "discipline": "pong"}
    assert judy.post("/api/v1/stations", json=payload).status_code == 403
    assert root.post("/api/v1/stations", json=payload).status_code == 201
    assert root.post("/api/v1/stations", json=payload).status_code == 409
    assert root.post("/api/v1/stations", json={"name": "S2", "discipline": "x"}).status_code == 422


def test_station_token_auth_and_rotation(app: FastAPI, root: TestClient, db: Session) -> None:
    @app.get("/_probe")
    def probe(station: Annotated[Station, Depends(current_station)]) -> dict[str, str]:
        return {"name": station.name}

    created = root.post("/api/v1/stations", json={"name": "S1", "discipline": "pong"}).json()
    anon = TestClient(app, base_url="https://testserver")

    def probe_with(token: str) -> int:
        return anon.get("/_probe", headers={"Authorization": f"Bearer {token}"}).status_code

    assert probe_with(created["token"]) == 200
    rotated = root.post(f"/api/v1/stations/{created['id']}/rotate-token")
    assert rotated.status_code == 200
    new_token = rotated.json()["token"]
    assert new_token != created["token"]
    assert probe_with(created["token"]) == 401
    assert probe_with(new_token) == 200
    assert anon.get("/_probe").status_code == 401
    assert anon.get("/_probe", headers={"Authorization": "Basic abc"}).status_code == 401
    assert anon.get("/_probe", headers={"Authorization": "Bearer "}).status_code == 401
    db.expire_all()
    assert db.scalars(select(Station)).one().token_hash == hash_token(new_token)


def test_rotate_unknown_station_is_404(root: TestClient) -> None:
    assert root.post("/api/v1/stations/999/rotate-token").status_code == 404


def test_audit_rows_written_without_secrets(root: TestClient, db: Session) -> None:
    created = root.post("/api/v1/users", json=NEW_USER).json()
    root.patch(f"/api/v1/users/{created['id']}", json={"password": "another-pass-1"})
    root.post(f"/api/v1/users/{created['id']}/revoke-sessions")
    station = root.post("/api/v1/stations", json={"name": "S1", "discipline": "pong"}).json()
    rotated = root.post(f"/api/v1/stations/{station['id']}/rotate-token").json()

    rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [r.action for r in rows] == [
        "user.create",  # root, from make_user
        "user.create",
        "user.update",
        "user.revoke_sessions",
        "station.create",
        "station.rotate_token",
    ]
    root_id = db.scalars(select(User.id).where(User.login == "root")).one()
    assert all(r.user_id == root_id for r in rows[1:])
    assert rows[1].after == {"login": "judy", "role": "judge", "discipline": None}
    dump = json.dumps([[r.action, r.object_type, r.object_id, r.after] for r in rows])
    for secret in (
        "password-1",
        "another-pass-1",
        PASSWORD,
        "argon2",
        station["token"],
        rotated["token"],
        hash_token(station["token"]),
        hash_token(rotated["token"]),
        "token_hash",
        "password_hash",
    ):
        assert secret not in dump
