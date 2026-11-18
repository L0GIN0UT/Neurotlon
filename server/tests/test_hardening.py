from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from neurotlon_server import admin, auth, security, users
from neurotlon_server.auth import (
    MAX_FAILED_ATTEMPTS,
    THROTTLE_WINDOW,
    LoginThrottle,
    current_station,
)
from neurotlon_server.models import Station

from .conftest import PASSWORD, FakeClock, login_as, make_user

LOGIN = "/api/v1/auth/login"
NEW_USER = {"login": "judy", "password": "password-1", "role": "judge"}


@pytest.fixture
def root(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "root", role="superuser")
    return login_as(app, "root")


def test_parallel_failures_reach_password_check_at_most_five_times(
    app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user(db, "alice")
    checks: list[int] = []
    real_verify = security.verify_password

    def counting_verify(password_hash: str, password: str) -> bool:
        checks.append(1)
        return real_verify(password_hash, password)

    monkeypatch.setattr(auth, "verify_password", counting_verify)

    def attempt(_: int) -> int:
        client = TestClient(app, base_url="https://testserver")
        return client.post(LOGIN, json={"login": "alice", "password": "wrong-password"}).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert len(checks) <= MAX_FAILED_ATTEMPTS
    assert codes.count(429) >= MAX_FAILED_ATTEMPTS


def test_throttle_prunes_expired_entries_and_caps_size(clock: FakeClock) -> None:
    throttle = LoginThrottle(clock)
    for i in range(LoginThrottle.MAX_ENTRIES + 10):
        assert throttle.try_attempt(f"user{i}")
    assert len(throttle._state) == LoginThrottle.MAX_ENTRIES
    assert "user0" not in throttle._state  # oldest dropped
    assert f"user{LoginThrottle.MAX_ENTRIES + 9}" in throttle._state
    clock.advance(seconds=THROTTLE_WINDOW.total_seconds() + 1)
    assert throttle.try_attempt("fresh")
    assert list(throttle._state) == ["fresh"]


def test_validation_error_does_not_echo_password(root: TestClient) -> None:
    response = root.post("/api/v1/users", json={**NEW_USER, "password": "pw-Zq7"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "invalid_request"
    assert "pw-Zq7" not in response.text
    assert all(set(e) == {"loc", "msg", "type"} for e in body["errors"])


def test_unknown_fields_are_rejected(root: TestClient, client: TestClient) -> None:
    assert root.patch("/api/v1/users/1", json={"role": "superuser"}).status_code == 422
    assert root.post("/api/v1/users", json={**NEW_USER, "is_active": False}).status_code == 422
    assert (
        root.post("/api/v1/stations", json={"name": "S", "discipline": "pong", "x": 1}).status_code
        == 422
    )
    assert client.post(LOGIN, json={"login": "a", "password": "b", "x": 1}).status_code == 422


def test_superuser_cannot_deactivate_self(root: TestClient, db: Session) -> None:
    me_id = users_id(db, "root")
    response = root.patch(f"/api/v1/users/{me_id}", json={"is_active": False})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert root.get("/api/v1/auth/me").status_code == 200


def users_id(db: Session, login: str) -> int:
    from sqlalchemy import select

    from neurotlon_server.models import User

    return db.scalars(select(User.id).where(User.login == login)).one()


def test_user_create_race_returns_409(root: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert root.post("/api/v1/users", json=NEW_USER).status_code == 201
    monkeypatch.setattr(users, "_login_exists", lambda db, login: False)  # skip pre-check
    response = root.post("/api/v1/users", json=NEW_USER)
    assert response.status_code == 409
    assert root.get("/api/v1/auth/me").status_code == 200  # session still usable


def test_station_create_race_returns_409(root: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"name": "S1", "discipline": "pong"}
    assert root.post("/api/v1/stations", json=payload).status_code == 201
    monkeypatch.setattr(admin, "_station_name_taken", lambda db, name: False)
    assert root.post("/api/v1/stations", json=payload).status_code == 409


def test_logins_are_normalized(app: FastAPI, root: TestClient) -> None:
    created = root.post("/api/v1/users", json={**NEW_USER, "login": "  Admin  "})
    assert created.status_code == 201
    assert created.json()["login"] == "admin"
    assert root.post("/api/v1/users", json={**NEW_USER, "login": "ADMIN"}).status_code == 409
    client = TestClient(app, base_url="https://testserver")
    response = client.post(LOGIN, json={"login": "Admin", "password": "password-1"})
    assert response.status_code == 204
    assert root.post("/api/v1/users", json={**NEW_USER, "login": "   "}).status_code == 422


def test_throttle_key_is_normalized(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    for name in ("alice", "ALICE", " Alice", "alice", "Alice"):
        assert (
            client.post(LOGIN, json={"login": name, "password": "wrong-password"}).status_code
            == 401
        )
    assert client.post(LOGIN, json={"login": "aLiCe", "password": PASSWORD}).status_code == 429


def test_no_store_on_secret_responses(app: FastAPI, root: TestClient, db: Session) -> None:
    created = root.post("/api/v1/stations", json={"name": "S1", "discipline": "pong"})
    assert created.headers["cache-control"] == "no-store"
    rotated = root.post(f"/api/v1/stations/{created.json()['id']}/rotate-token")
    assert rotated.headers["cache-control"] == "no-store"
    make_user(db, "alice")
    client = TestClient(app, base_url="https://testserver")
    login = client.post(LOGIN, json={"login": "alice", "password": PASSWORD})
    assert login.headers["cache-control"] == "no-store"


def test_cross_site_cookie_requests_are_rejected(root: TestClient) -> None:
    for site in ("cross-site", "same-site"):
        response = root.post("/api/v1/users", json=NEW_USER, headers={"Sec-Fetch-Site": site})
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    ok = root.post("/api/v1/users", json=NEW_USER, headers={"Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 201
    other = {**NEW_USER, "login": "judy2"}
    assert (
        root.post("/api/v1/users", json=other, headers={"Sec-Fetch-Site": "none"}).status_code
        == 201
    )
    assert root.get("/api/v1/auth/me", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_station_bearer_requests_exempt_from_csrf_check(app: FastAPI, root: TestClient) -> None:
    @app.post("/_probe")
    def probe(station: Annotated[Station, Depends(current_station)]) -> dict[str, str]:
        return {"name": station.name}

    token = root.post("/api/v1/stations", json={"name": "S1", "discipline": "pong"}).json()["token"]
    anon = TestClient(app, base_url="https://testserver")
    response = anon.post(
        "/_probe", headers={"Authorization": f"Bearer {token}", "Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 200
