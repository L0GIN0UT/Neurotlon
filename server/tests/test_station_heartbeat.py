from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from neurotlon_server.models import Station

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, SESSION_A, make_station

BEAT = {
    "state": "playing",
    "session_id": SESSION_A,
    "queue_length": 3,
    "sensors": {"eeg": "connected", "emg": "emulated"},
}


def test_heartbeat_updates_station(client: TestClient, db: Session, clock: FakeClock) -> None:
    station_id, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    assert response.status_code == 204
    db.expire_all()
    station = db.get(Station, station_id)
    assert station is not None
    assert station.last_heartbeat_at == clock.now
    assert station.last_state == "playing"
    assert station.queue_length == 3


def test_heartbeat_rejects_bad_body(client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    for bad in (
        {**BEAT, "state": "dancing"},
        {**BEAT, "queue_length": -1},
        {**BEAT, "sensors": {"eeg": "broken"}},
        {**BEAT, "extra": 1},
    ):
        response = client.post(f"{API}/stations/me/heartbeat", json=bad, headers=headers)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"


def test_volunteer_cannot_heartbeat(app: FastAPI, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    response = login_as(app, "vol").post(f"{API}/stations/me/heartbeat", json=BEAT)
    assert response.status_code == 403
