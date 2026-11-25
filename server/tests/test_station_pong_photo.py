from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from neurotlon_server.models import GameSession, Pair, Participant

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, SESSION_A, make_station, pong_body, seed_people
from .test_jpeg import make_jpeg

JPEG = make_jpeg(scan=b"STATION-PHOTO" * 10)
PHOTO = f"{API}/station/participants/NT01/photo"


def eligibility(
    client: TestClient, headers: dict[str, str], code: str, opponent: str | None, d: str = "pong"
) -> dict[str, Any]:
    extra = "" if opponent is None else f"&with={opponent}"
    response = client.get(
        f"{API}/participants/{code}/eligibility?discipline={d}&section=bci{extra}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def session(codes: list[str], session_id: str = SESSION_A, d: str = "pong") -> dict[str, Any]:
    return {"session_id": session_id, "discipline": d, "participant_codes": codes}


# --- pong duel only between the pair from the grid ---


def test_pair_is_opponents(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert eligibility(client, headers, "NT04", "NT03")["issues"] == []
    assert eligibility(client, headers, "nt-3", "nt4")["issues"] == []


def test_not_a_pair_is_not_opponents(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert eligibility(client, headers, "NT03", "NT01")["issues"] == ["not_opponents"]
    assert eligibility(client, headers, "NT03", "NT03")["issues"] == ["not_opponents"]


def test_same_team_is_not_opponents(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    first = db.scalars(select(Participant).where(Participant.code == "NT01")).one()
    third = db.scalars(select(Participant).where(Participant.code == "NT03")).one()
    third.team_id = first.team_id
    db.commit()
    assert eligibility(client, headers, "NT03", "NT01")["issues"] == ["not_opponents"]
    response = client.post(f"{API}/sessions", json=session(["NT01", "NT03"]), headers=headers)
    assert response.status_code == 409


def test_unknown_second_code_is_not_opponents(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert eligibility(client, headers, "NT03", "NT99")["issues"] == ["not_opponents"]
    assert eligibility(client, headers, "NT03", "xyz")["issues"] == ["not_opponents"]


def test_without_with_nothing_is_checked(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert eligibility(client, headers, "NT03", None)["issues"] == []


def test_player_without_pair_keeps_no_pair_assigned(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert eligibility(client, headers, "NT05", "NT03")["issues"] == [
        "no_pair_assigned",
        "not_opponents",
    ]
    assert eligibility(client, headers, "NT05", None)["issues"] == ["no_pair_assigned"]


def test_darts_ignores_with(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert eligibility(client, headers, "NT01", "NT03", "darts")["issues"] == []


def test_session_of_a_pair_starts_and_replays(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    first = client.post(f"{API}/sessions", json=session(["NT03", "NT04"]), headers=headers)
    again = client.post(f"{API}/sessions", json=session(["NT04", "NT03"]), headers=headers)
    assert (first.status_code, again.status_code) == (201, 200)


def test_session_of_strangers_is_409_not_opponents(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    for codes in (["NT01", "NT03"], ["NT02", "NT04"], ["NT05", "NT01"], ["NT01", "NT05"]):
        response = client.post(f"{API}/sessions", json=session(codes), headers=headers)
        assert response.status_code == 409, codes
        assert response.json()["code"] == "not_opponents"
    assert db.scalar(select(func.count()).select_from(GameSession)) == 0


def test_replay_survives_when_the_grid_changes_later(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    assert (
        client.post(f"{API}/sessions", json=session(["NT03", "NT04"]), headers=headers).status_code
        == 201
    )
    for pair in db.scalars(select(Pair)):
        db.delete(pair)
    db.commit()
    again = client.post(f"{API}/sessions", json=session(["NT03", "NT04"]), headers=headers)
    assert again.status_code == 200


def test_darts_session_is_not_limited(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/sessions", json=session(["NT05"], d="darts"), headers=headers)
    assert response.status_code == 201


def test_problem_code_is_in_the_contract(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    response = client.post(f"{API}/sessions", json=session(["NT01", "NT03"]), headers=headers)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "pair" in response.json()["detail"]


# --- photo on the station confirmation screen ---


def checked(client: TestClient, headers: dict[str, str], code: str = "NT01") -> None:
    """The launcher asks eligibility first; that opens the photo for this station."""
    eligibility(client, headers, code, None, "darts")


@pytest.fixture
def photo_admin(app: FastAPI, db: Session) -> TestClient:
    seed_people(db)
    make_user(db, "boss", role="admin")
    admin = login_as(app, "boss")
    response = admin.put(
        f"{API}/participants/NT01/photo", content=JPEG, headers={"Content-Type": "image/jpeg"}
    )
    assert response.status_code == 204
    return admin


def test_eligibility_tells_about_photo(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    _, headers = make_station(db, "d1", "darts")
    with_photo = eligibility(client, headers, "NT01", None, "darts")
    assert with_photo["has_photo"] is True
    assert isinstance(with_photo["photo_version"], int)
    without = eligibility(client, headers, "NT02", None, "darts")
    assert (without["has_photo"], without["photo_version"]) == (False, None)


def test_station_gets_photo_with_hardened_headers(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    _, headers = make_station(db, "d1", "darts")
    checked(client, headers)
    response = client.get(PHOTO, headers=headers)
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["content-disposition"].startswith("inline")


def test_code_is_normalized(photo_admin: TestClient, client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    checked(client, headers)
    assert client.get(f"{API}/station/participants/nt-1/photo", headers=headers).status_code == 200


def test_photo_without_token_is_401(photo_admin: TestClient, client: TestClient) -> None:
    assert client.get(PHOTO).status_code == 401
    assert client.get(PHOTO, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_photo_missing_is_404(photo_admin: TestClient, client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    checked(client, headers, "NT02")
    missing = client.get(f"{API}/station/participants/NT02/photo", headers=headers)
    unknown = client.get(f"{API}/station/participants/NT99/photo", headers=headers)
    assert (missing.status_code, unknown.status_code) == (404, 404)
    assert missing.json()["code"] == "no_photo"


def test_volunteer_and_admin_sessions_are_refused(
    photo_admin: TestClient, app: FastAPI, db: Session
) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    assert login_as(app, "vol").get(PHOTO).status_code == 403
    assert photo_admin.get(PHOTO).status_code == 403


def test_archived_station_is_refused(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    station_id, headers = make_station(db, "d1", "darts")
    checked(client, headers)
    assert client.get(PHOTO, headers=headers).status_code == 200
    assert photo_admin.delete(f"{API}/stations/{station_id}").status_code == 204
    assert client.get(PHOTO, headers=headers).status_code == 401


def test_there_is_no_listing(photo_admin: TestClient, client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    assert client.get(f"{API}/station/participants", headers=headers).status_code in (404, 405)
    assert client.get(f"{API}/station/participants/photo", headers=headers).status_code == 404


def test_photo_without_a_preceding_eligibility_is_404(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    _, headers = make_station(db, "d1", "darts")
    response = client.get(PHOTO, headers=headers)
    assert response.status_code == 404
    assert response.json()["code"] == "no_photo"
    checked(client, headers)
    assert client.get(PHOTO, headers=headers).status_code == 200


def test_photo_grant_expires_after_120_seconds(
    photo_admin: TestClient, client: TestClient, db: Session, clock: FakeClock
) -> None:
    _, headers = make_station(db, "d1", "darts")
    checked(client, headers)
    clock.advance(seconds=119)
    assert client.get(PHOTO, headers=headers).status_code == 200
    clock.advance(seconds=2)
    assert client.get(PHOTO, headers=headers).status_code == 404
    checked(client, headers)  # a new scan opens it again
    assert client.get(PHOTO, headers=headers).status_code == 200


def test_another_station_cannot_use_the_grant(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    _, mine = make_station(db, "d1", "darts")
    _, other = make_station(db, "d2", "darts")
    checked(client, mine)
    assert client.get(PHOTO, headers=other).status_code == 404
    assert client.get(PHOTO, headers=mine).status_code == 200


def test_photo_requests_are_limited_per_station_and_minute(
    photo_admin: TestClient, client: TestClient, db: Session, clock: FakeClock
) -> None:
    _, headers = make_station(db, "d1", "darts")
    _, other = make_station(db, "d2", "darts")
    checked(client, headers)
    statuses = [client.get(PHOTO, headers=headers).status_code for _ in range(21)]
    assert statuses == [200] * 20 + [429]
    assert client.get(f"{API}/station/participants/NT02/photo", headers=headers).status_code == 429
    checked(client, other)
    assert client.get(PHOTO, headers=other).status_code == 200  # the other station is not limited
    clock.advance(seconds=61)
    checked(client, headers)
    assert client.get(PHOTO, headers=headers).status_code == 200


def test_enumeration_by_a_stolen_token_gets_nothing(
    photo_admin: TestClient, client: TestClient, db: Session
) -> None:
    _, headers = make_station(db, "d1", "darts")
    codes = [f"NT{n:02d}" for n in range(1, 30)]
    statuses = {
        client.get(f"{API}/station/participants/{c}/photo", headers=headers).status_code
        for c in codes
    }
    assert statuses <= {404, 429}
    assert 200 not in statuses


# --- hardening of the pong checks ---


def test_pong_session_needs_exactly_two_players(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    response = client.post(f"{API}/sessions", json=session(["NT03"]), headers=headers)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(GameSession)) == 0


def test_pong_result_of_strangers_is_accepted_with_a_warning(
    client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    body = pong_body()
    body["entries"][0]["participant_code"] = "NT01"  # NT01 and NT04 are not a pair
    receipt = client.post(f"{API}/results", json=body, headers=headers)
    assert receipt.status_code == 201
    assert {"participant_code": "NT01", "code": "not_opponents"} in receipt.json()["warnings"]
    assert {"participant_code": "NT04", "code": "not_opponents"} in receipt.json()["warnings"]


def test_pong_result_of_a_pair_has_no_such_warning(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    receipt = client.post(f"{API}/results", json=pong_body(), headers=headers)
    assert receipt.status_code == 201
    assert all(w["code"] != "not_opponents" for w in receipt.json()["warnings"])
