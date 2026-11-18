from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, darts_body, make_station, seed_people

QUERY = "discipline=darts&section=bci"
BEAT = {"state": "playing", "queue_length": 0, "sensors": {}}


def eligibility(client: TestClient, headers: dict[str, str], code: str = "NT01") -> dict[str, Any]:
    response = client.get(f"{API}/participants/{code}/eligibility?{QUERY}", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_clean_participant_has_no_issues_and_team(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert eligibility(client, headers) == {
        "code": "NT01",
        "display_name": "Name 1",
        "team": {"number": 1, "name": "Alpha", "color": "#aa00bb"},
        "issues": [],
    }


def test_code_is_normalized_and_category_never_returned(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = eligibility(client, headers, "nt-1")
    assert body["code"] == "NT01"
    assert "category" not in body
    assert "ovz" not in str(body)


def test_no_team_before_draw(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert eligibility(client, headers, "NT02")["team"] is None


def test_unknown_or_malformed_is_404(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    for code in ("NT99", "XYZ", "NT00"):
        response = client.get(f"{API}/participants/{code}/eligibility?{QUERY}", headers=headers)
        assert response.status_code == 404
        assert response.json()["code"] == "unknown_participant"


def test_not_checked_in_and_no_pair(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert eligibility(client, headers, "NT06")["issues"] == ["not_checked_in", "no_pair_assigned"]
    assert eligibility(client, headers, "NT05")["issues"] == ["no_pair_assigned"]


def test_already_completed_only_for_same_participant(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert client.post(f"{API}/results", json=darts_body(), headers=headers).status_code == 201
    assert eligibility(client, headers)["issues"] == ["already_completed"]
    assert eligibility(client, headers, "NT02")["issues"] == []


def test_busy_on_other_live_station_but_not_stale(
    client: TestClient, db: Session, clock: FakeClock
) -> None:
    seed_people(db)
    _, other = make_station(db, "d2", "darts")
    _, mine = make_station(db, "d3", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=other)
    start = {
        "session_id": "0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10",
        "discipline": "darts",
        "participant_codes": ["NT01"],
    }
    assert client.post(f"{API}/sessions", json=start, headers=other).status_code == 201

    clock.advance(seconds=10)
    assert eligibility(client, mine)["issues"] == ["busy_on_other_station"]
    # a station is not blocked by its own session
    assert eligibility(client, other)["issues"] == []

    clock.advance(seconds=25)  # 35 s since the last heartbeat: stale
    assert eligibility(client, mine)["issues"] == []
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=other)
    assert eligibility(client, mine)["issues"] == ["busy_on_other_station"]


def test_wrong_discipline_or_section_is_403(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    for query in ("discipline=pong&section=bci", "discipline=darts&section=physical"):
        response = client.get(f"{API}/participants/NT01/eligibility?{query}", headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "wrong_discipline"
    make_user(db, "vol", role="volunteer", discipline="football")
    vol = login_as(app, "vol")
    wrong = vol.get(f"{API}/participants/NT01/eligibility?discipline=darts&section=physical")
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "wrong_discipline"
    assert vol.get(f"{API}/participants/NT01/eligibility?{QUERY}").status_code == 403
    ok = vol.get(f"{API}/participants/NT01/eligibility?discipline=football&section=physical")
    assert ok.status_code == 200


def test_invalid_query_is_422(client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    response = client.get(f"{API}/participants/NT01/eligibility?discipline=chess", headers=headers)
    assert response.status_code == 422
