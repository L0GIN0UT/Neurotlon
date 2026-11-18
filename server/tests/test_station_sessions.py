from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from neurotlon_server.models import Discipline, GameSession, session_participant

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, SESSION_A, SESSION_B, make_station, seed_people

BEAT = {"state": "playing", "queue_length": 0, "sensors": {}}


def start(
    codes: list[str], session_id: str = SESSION_A, discipline: str = "darts"
) -> dict[str, Any]:
    return {"session_id": session_id, "discipline": discipline, "participant_codes": codes}


def test_start_creates_session_and_participants(client: TestClient, db: Session) -> None:
    seed_people(db)
    station_id, headers = make_station(db, "p1", "pong")
    response = client.post(
        f"{API}/sessions", json=start(["NT03", "NT04"], discipline="pong"), headers=headers
    )
    assert response.status_code == 201
    session = db.get(GameSession, SESSION_A)
    assert session is not None
    assert session.station_id == station_id
    assert session.closed_at is None
    assert db.scalar(select(func.count()).select_from(session_participant)) == 2


def test_start_is_idempotent(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert client.post(f"{API}/sessions", json=start(["NT01"]), headers=headers).status_code == 201
    assert client.post(f"{API}/sessions", json=start(["NT01"]), headers=headers).status_code == 200
    assert db.scalar(select(func.count()).select_from(GameSession)) == 1


def test_start_conflicting_replay_is_409(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/sessions", json=start(["NT01"]), headers=headers)
    response = client.post(f"{API}/sessions", json=start(["NT02"]), headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "session_conflict"


def test_start_unknown_participant_is_422(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/sessions", json=start(["NT01", "NT99"]), headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_participant"
    assert db.scalar(select(func.count()).select_from(GameSession)) == 0


def test_start_busy_on_live_other_station_only(
    client: TestClient, db: Session, clock: FakeClock
) -> None:
    seed_people(db)
    _, first = make_station(db, "d1", "darts")
    _, second = make_station(db, "d2", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=first)
    client.post(f"{API}/sessions", json=start(["NT01"]), headers=first)

    response = client.post(f"{API}/sessions", json=start(["NT01"], SESSION_B), headers=second)
    assert response.status_code == 409
    assert response.json()["code"] == "busy_on_other_station"

    clock.advance(seconds=31)  # the first station went silent
    ok = client.post(f"{API}/sessions", json=start(["NT01"], SESSION_B), headers=second)
    assert ok.status_code == 201


def test_abandoned_session_does_not_block_while_station_keeps_heartbeating(
    client: TestClient, db: Session, clock: FakeClock
) -> None:
    seed_people(db)
    _, first = make_station(db, "d1", "darts")
    _, second = make_station(db, "d2", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=first)
    client.post(f"{API}/sessions", json=start(["NT01"]), headers=first)
    duration = db.get(Discipline, "darts")
    assert duration is not None

    clock.advance(seconds=duration.game_duration_s + 299)
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=first)
    assert (
        client.post(f"{API}/sessions", json=start(["NT01"], SESSION_B), headers=second).status_code
        == 409
    )

    clock.advance(seconds=2)  # game time + 300 s passed, heartbeats are still alive
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=first)
    ok = client.post(f"{API}/sessions", json=start(["NT01"], SESSION_B), headers=second)
    assert ok.status_code == 201


def test_start_validation_and_wrong_discipline(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    for bad in (
        start([]),
        start(["NT01", "NT01"]),
        start(["NT1"]),
        start(["NT01", "NT02", "NT03"]),
    ):
        assert client.post(f"{API}/sessions", json=bad, headers=headers).status_code == 422
    response = client.post(
        f"{API}/sessions", json=start(["NT01"], discipline="pong"), headers=headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == "wrong_discipline"


def test_volunteer_cannot_start_session(app: FastAPI, db: Session) -> None:
    seed_people(db)
    make_user(db, "vol", role="volunteer", discipline="darts")
    response = login_as(app, "vol").post(f"{API}/sessions", json=start(["NT01"]))
    assert response.status_code == 403
