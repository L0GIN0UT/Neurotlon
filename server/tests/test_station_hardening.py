from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.models import GameSession, Pair, SectionResult

from .conftest import login_as, make_user
from .station_helpers import API, SESSION_A, darts_body, make_station, pong_body, seed_people
from .test_draw_api import check_in

BEAT = {"state": "idle", "queue_length": 0, "sensors": {}}


def beat_status(client: TestClient, beat: dict[str, Any], headers: dict[str, str]) -> int:
    return client.post(f"{API}/stations/me/heartbeat", json=beat, headers=headers).status_code


def _rows(db: Session) -> int:
    db.expire_all()
    return (db.scalar(select(func.count()).select_from(SectionResult)) or 0) + (
        db.scalar(select(func.count()).select_from(GameSession)) or 0
    )


@pytest.mark.parametrize("points", [1000.5, 10**30, -0.1])
def test_points_out_of_range_is_422(client: TestClient, db: Session, points: float) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = darts_body()
    body["entries"][0]["points"] = points
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 422
    assert _rows(db) == 0


def test_points_upper_bound_accepted(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = darts_body()
    body["entries"][0]["points"] = 1000
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 201


def test_huge_ints_are_422(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    body = pong_body()
    body["entries"][0]["wins"] = 10**30
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 422
    beat = {**BEAT, "queue_length": 10**30}
    assert beat_status(client, beat, headers) == 422
    beat["queue_length"] = 100001
    assert beat_status(client, beat, headers) == 422


def test_replay_by_other_caller_is_409(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    _, first = make_station(db, "d1", "darts")
    _, second = make_station(db, "d2", "darts")
    assert client.post(f"{API}/results", json=darts_body(), headers=first).status_code == 201
    response = client.post(f"{API}/results", json=darts_body(), headers=second)
    assert response.status_code == 409
    assert response.json()["code"] == "session_conflict"
    assert client.post(f"{API}/results", json=darts_body(), headers=first).status_code == 200


def test_volunteer_replay_by_other_volunteer_is_409(app: FastAPI, db: Session) -> None:
    seed_people(db)
    make_user(db, "v1", role="volunteer", discipline="darts")
    make_user(db, "v2", role="volunteer", discipline="darts")
    body = {**darts_body(), "section": "physical"}
    assert login_as(app, "v1").post(f"{API}/results", json=body).status_code == 201
    assert login_as(app, "v2").post(f"{API}/results", json=body).status_code == 409


@pytest.mark.parametrize(
    "finished_at",
    [
        "2027-01-04T09:00:01+00:00",  # more than 2 days ahead
        "2026-12-29T09:00:00+00:00",  # more than 2 days back
        "0001-01-01T00:00:00+14:00",  # would overflow when moved to UTC
        "9999-12-31T23:59:59-12:00",
    ],
)
def test_finished_at_out_of_window_is_422(
    client: TestClient, db: Session, finished_at: str
) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = {**darts_body(), "finished_at": finished_at}
    response = client.post(f"{API}/results", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert _rows(db) == 0


def test_finished_at_inside_window_is_accepted(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = {**darts_body(), "finished_at": "2026-12-30T10:00:00+00:00"}
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 201


def test_sensors_limited(client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    for sensors in ({"mouse": "connected"}, {f"k{i}": "connected" for i in range(9)}):
        beat = {**BEAT, "sensors": sensors}
        assert beat_status(client, beat, headers) == 422
    ok = {**BEAT, "sensors": {"eeg": "connected", "emg_left": "connecting"}}
    assert beat_status(client, ok, headers) == 204


def _wins_case(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    body = pong_body()
    for entry, patch in zip(body["entries"], (a, b), strict=True):
        for key in ("points", "wins"):
            entry.pop(key, None)
        entry.update(patch)
    return body


COMPLETED = {"outcome": "completed", "points": 5}
GONE = {"outcome": "not_completed", "reason": "health"}


@pytest.mark.parametrize(
    ("a", "b", "ok"),
    [
        ({**COMPLETED, "wins": 1}, {**COMPLETED, "wins": 0}, True),
        ({**COMPLETED, "wins": 0}, {**COMPLETED, "wins": 1}, True),
        ({**COMPLETED, "wins": 1}, {**COMPLETED, "wins": 1}, False),
        ({**COMPLETED, "wins": 0}, {**COMPLETED, "wins": 0}, False),
        (COMPLETED, {**COMPLETED, "wins": 1}, False),
        (COMPLETED, COMPLETED, False),
        ({**COMPLETED, "wins": 1}, GONE, True),
        (COMPLETED, GONE, True),
        (GONE, GONE, True),
    ],
)
def test_pong_wins_rules(
    client: TestClient, db: Session, a: dict[str, Any], b: dict[str, Any], ok: bool
) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    response = client.post(f"{API}/results", json=_wins_case(a, b), headers=headers)
    if ok:
        assert response.status_code == 201
    else:
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_entries"
        assert _rows(db) == 0


def test_wins_not_allowed_outside_pong(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/results", json=darts_body(wins=1), headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_entries"


def test_parallel_start_replay_after_integrity_error(
    client: TestClient, app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates losing the insert race: the row appears, then the flush fails."""
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = {"session_id": SESSION_A, "discipline": "darts", "participant_codes": ["NT01"]}
    assert client.post(f"{API}/sessions", json=body, headers=headers).status_code == 201

    import neurotlon_server.station_api as api

    real_get = Session.get
    calls = {"n": 0}

    def fake_get(self: Session, entity: Any, ident: Any, **kw: Any) -> Any:
        if entity is GameSession and calls["n"] == 0:
            calls["n"] += 1
            return None  # first look says "no such session", the insert then collides
        return real_get(self, entity, ident, **kw)

    monkeypatch.setattr(Session, "get", fake_get)
    assert api.start_session is not None
    same = client.post(f"{API}/sessions", json=body, headers=headers)
    assert same.status_code == 200
    calls["n"] = 0
    other = {**body, "participant_codes": ["NT02"]}
    conflict = client.post(f"{API}/sessions", json=other, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "session_conflict"


def test_results_integrity_error_without_row_is_not_masked(
    app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import neurotlon_server.station_api as api

    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    calls = {"n": 0}

    def boom(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        raise IntegrityError("stmt", {}, Exception("boom"))

    monkeypatch.setattr(api, "submit_result", boom)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        response = c.post(f"{API}/results", json=darts_body(), headers=headers)
    assert response.status_code == 500
    assert calls["n"] == 1


def test_draw_never_gives_one_participant_two_pairs(app: FastAPI, db: Session) -> None:
    make_user(db, "boss", role="admin")
    check_in(db, 8, 8)
    assert login_as(app, "boss").post(f"{API}/draw", json={"m": 2, "seed": 3}).status_code == 200
    db.expire_all()
    ids = [x for p in db.scalars(select(Pair)) for x in (p.participant_a_id, p.participant_b_id)]
    assert ids
    assert len(ids) == len(set(ids))
