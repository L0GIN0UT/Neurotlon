import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, make_station

BEAT = {"state": "idle", "queue_length": 2, "sensors": {"eeg": "connected"}}


@pytest.mark.parametrize(
    ("role", "discipline", "status"),
    [
        ("superuser", None, 200),
        ("admin", None, 200),
        ("volunteer", "pong", 403),
    ],
)
def test_stations_role_matrix(
    app: FastAPI, db: Session, role: str, discipline: str | None, status: int
) -> None:
    make_user(db, "staff", role=role, discipline=discipline)
    assert login_as(app, "staff").get(f"{API}/stations").status_code == status


def test_stations_requires_login(client: TestClient) -> None:
    assert client.get(f"{API}/stations").status_code == 401


def test_station_status_follows_heartbeat(
    app: FastAPI, client: TestClient, db: Session, clock: FakeClock
) -> None:
    make_user(db, "adm", role="admin")
    make_station(db, "never", "football")
    _, headers = make_station(db, "darts-1", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    admin = login_as(app, "adm")

    rows = {s["name"]: s for s in admin.get(f"{API}/stations").json()}
    assert rows["never"]["online"] is False
    assert rows["never"]["last_heartbeat_at"] is None
    assert rows["darts-1"]["online"] is True
    assert rows["darts-1"]["last_state"] == "idle"
    assert rows["darts-1"]["queue_length"] == 2
    assert rows["darts-1"]["discipline"] == "darts"

    clock.advance(seconds=30)  # the boundary is still online
    assert {s["name"]: s["online"] for s in admin.get(f"{API}/stations").json()}["darts-1"]
    clock.advance(seconds=1)
    assert not {s["name"]: s["online"] for s in admin.get(f"{API}/stations").json()}["darts-1"]


def test_station_list_never_exposes_tokens(app: FastAPI, db: Session) -> None:
    make_user(db, "adm", role="admin")
    make_station(db, "darts-1", "darts")
    body = login_as(app, "adm").get(f"{API}/stations").text
    assert "token" not in body
    assert "hash" not in body


def test_station_last_beat_is_returned_as_time(
    app: FastAPI, client: TestClient, db: Session, clock: FakeClock
) -> None:
    make_user(db, "adm", role="admin")
    _, headers = make_station(db, "darts-1", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    clock.advance(seconds=5)
    row = login_as(app, "adm").get(f"{API}/stations").json()[0]
    assert row["last_heartbeat_at"].startswith("2027-01-01T09:00:00")


@pytest.mark.parametrize(
    ("role", "discipline", "status"),
    [
        ("superuser", None, 200),
        ("admin", None, 403),
        ("volunteer", "pong", 403),
    ],
)
def test_users_role_matrix(
    app: FastAPI, db: Session, role: str, discipline: str | None, status: int
) -> None:
    make_user(db, "staff", role=role, discipline=discipline)
    assert login_as(app, "staff").get(f"{API}/users").status_code == status


def test_users_requires_login(client: TestClient) -> None:
    assert client.get(f"{API}/users").status_code == 401


def test_users_list_fields_and_activity(app: FastAPI, db: Session) -> None:
    make_user(db, "root", role="superuser")
    make_user(db, "vol", role="volunteer", discipline="pong")
    root = login_as(app, "root")
    root.patch(f"{API}/users/2", json={"is_active": False})
    rows = root.get(f"{API}/users").json()
    assert rows == [
        {"id": 1, "login": "root", "role": "superuser", "discipline": None, "is_active": True},
        {"id": 2, "login": "vol", "role": "volunteer", "discipline": "pong", "is_active": False},
    ]
    assert "password" not in str(rows)
