from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from neurotlon_server.app import create_app
from neurotlon_server.models import User, WebSession
from neurotlon_server.security import hash_token

from .conftest import PASSWORD, FakeClock, login_as, make_user

LOGIN = "/api/v1/auth/login"


def _login(client: TestClient, login: str = "alice", password: str = PASSWORD) -> int:
    return client.post(LOGIN, json={"login": login, "password": password}).status_code


def test_login_sets_session_cookie_with_flags(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    response = client.post(LOGIN, json={"login": "alice", "password": PASSWORD})
    assert response.status_code == 204
    header = response.headers["set-cookie"]
    assert header.startswith("neurotlon_session=")
    lowered = header.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=strict" in lowered
    assert "path=/" in lowered
    assert "max-age=86400" in lowered


def test_raw_session_token_is_not_stored(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    client.post(LOGIN, json={"login": "alice", "password": PASSWORD})
    token = client.cookies["neurotlon_session"]
    stored = db.scalars(select(WebSession)).all()
    assert [s.token_hash for s in stored] == [hash_token(token)]


def test_me_returns_profile(client: TestClient, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="pong")
    _login(client, "vol")
    response = client.get("/api/v1/auth/me")
    assert response.json() == {"login": "vol", "role": "volunteer", "discipline": "pong"}


def test_me_without_cookie_is_401_problem(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "unauthorized"


def test_bad_credentials_have_identical_response(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    make_user(db, "gone")
    db.execute(update(User).where(User.login == "gone").values(is_active=False))
    db.commit()
    responses = [
        client.post(LOGIN, json={"login": "alice", "password": "wrong-password"}),
        client.post(LOGIN, json={"login": "nobody", "password": PASSWORD}),
        client.post(LOGIN, json={"login": "gone", "password": PASSWORD}),
    ]
    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1
    assert responses[0].json()["code"] == "unauthorized"
    assert all("set-cookie" not in r.headers for r in responses)


def test_throttle_blocks_after_five_failures_and_resets(
    client: TestClient, db: Session, clock: FakeClock
) -> None:
    make_user(db, "alice")
    for _ in range(5):
        assert _login(client, password="wrong-password") == 401
    blocked = client.post(LOGIN, json={"login": "alice", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_attempts"
    clock.advance(minutes=4, seconds=59)
    assert _login(client) == 429
    clock.advance(seconds=2)
    assert _login(client) == 204


def test_throttle_is_per_login_and_cleared_by_success(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    make_user(db, "bob")
    for _ in range(4):
        _login(client, password="wrong-password")
    assert _login(client, "bob") == 204
    assert _login(client) == 204  # 4 failures, success resets the counter
    for _ in range(4):
        _login(client, password="wrong-password")
    assert _login(client) == 204


def test_throttle_state_is_per_app(app: FastAPI, clock: FakeClock) -> None:
    other = create_app(app.state.settings, clock=clock)
    assert other.state.throttle is not app.state.throttle


def test_expired_session_rejected(client: TestClient, db: Session, clock: FakeClock) -> None:
    make_user(db, "alice")
    _login(client)
    clock.advance(hours=23, minutes=59)
    assert client.get("/api/v1/auth/me").status_code == 200
    clock.advance(minutes=2)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_session_and_clears_cookie(client: TestClient, db: Session) -> None:
    make_user(db, "alice")
    _login(client)
    token = client.cookies["neurotlon_session"]
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    client.cookies.set("neurotlon_session", token)  # replay the old cookie
    assert client.get("/api/v1/auth/me").status_code == 401
    db.expire_all()
    assert db.scalars(select(WebSession)).one().revoked_at is not None


def test_logout_requires_session(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_garbage_cookie_rejected(client: TestClient) -> None:
    client.cookies.set("neurotlon_session", "garbage")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_validation_error_for_missing_fields(client: TestClient) -> None:
    assert client.post(LOGIN, json={"login": "x"}).status_code == 422


def test_session_of_deactivated_user_rejected(app: FastAPI, db: Session) -> None:
    uid = make_user(db, "alice")
    alice = login_as(app, "alice")
    db.execute(update(User).where(User.id == uid).values(is_active=False))
    db.commit()
    assert alice.get("/api/v1/auth/me").status_code == 401
