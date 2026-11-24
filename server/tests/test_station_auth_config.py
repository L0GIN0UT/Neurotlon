import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .conftest import login_as, make_user
from .station_helpers import API, make_station


def test_config_for_station_uses_game_duration(client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    response = client.get(f"{API}/me/config", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "discipline": "darts",
        "section": "bci",
        "duration_s": 120,
        "max_points": 10,
    }


def test_config_for_volunteer_uses_physical_duration(app: FastAPI, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="football")
    response = login_as(app, "vol").get(f"{API}/me/config")
    assert response.status_code == 200
    assert response.json() == {
        "discipline": "football",
        "section": "physical",
        "duration_s": 300,
        "max_points": 10,
    }


def test_config_max_points_is_null_for_pong_and_follows_the_limit(
    client: TestClient, db: Session
) -> None:
    from neurotlon_server.models import Discipline

    _, pong = make_station(db, "p1", "pong")
    assert client.get(f"{API}/me/config", headers=pong).json()["max_points"] is None
    _, darts = make_station(db, "d1", "darts")
    row = db.get(Discipline, "darts")
    assert row is not None
    row.max_section_points = 25
    db.commit()
    assert client.get(f"{API}/me/config", headers=darts).json()["max_points"] == 25


def test_config_change_applies_to_next_read(client: TestClient, db: Session) -> None:
    from neurotlon_server.models import Discipline

    _, headers = make_station(db, "d1", "darts")
    row = db.get(Discipline, "darts")
    assert row is not None
    row.game_duration_s = 90
    db.commit()
    assert client.get(f"{API}/me/config", headers=headers).json()["duration_s"] == 90


def test_no_auth_is_401(client: TestClient) -> None:
    for method, url in (
        ("GET", f"{API}/me/config"),
        ("GET", f"{API}/participants/NT01/eligibility?discipline=darts&section=bci"),
        ("POST", f"{API}/sessions"),
        ("POST", f"{API}/results"),
        ("POST", f"{API}/stations/me/heartbeat"),
    ):
        response = client.request(method, url, json={})
        assert response.status_code == 401, url
        assert response.json()["code"] == "unauthorized"


def test_bad_token_is_401(client: TestClient) -> None:
    response = client.get(f"{API}/me/config", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize("role", ["admin", "superuser"])
def test_other_roles_are_403(app: FastAPI, db: Session, role: str) -> None:
    make_user(db, "someone", role=role)
    client = login_as(app, "someone")
    for method, url in (
        ("GET", f"{API}/me/config"),
        ("GET", f"{API}/participants/NT01/eligibility?discipline=darts&section=bci"),
        ("POST", f"{API}/results"),
        ("POST", f"{API}/sessions"),
        ("POST", f"{API}/stations/me/heartbeat"),
    ):
        response = client.request(method, url, json={})
        assert response.status_code == 403, url
        assert response.json()["code"] == "forbidden"
