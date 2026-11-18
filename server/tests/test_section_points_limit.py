"""Per-discipline limit of section points: darts and football, not pong."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog, SectionResult

from .conftest import login_as, make_user
from .station_helpers import API, SESSION_A, darts_body, make_station, pong_body, seed_people


def football_body(points: float, session_id: str = SESSION_A) -> dict[str, object]:
    body = darts_body(session_id, "NT01", points=points)
    body["discipline"] = "football"
    body["section"] = "physical"
    return body


def test_station_result_above_limit_is_422(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/results", json=darts_body(points=10.5), headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_entries"
    assert "10" in response.json()["detail"]
    assert db.scalars(select(SectionResult)).all() == []


def test_result_at_the_limit_is_accepted(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/results", json=darts_body(points=10), headers=headers)
    assert response.status_code == 201


def test_volunteer_football_above_limit_is_422(app: FastAPI, db: Session) -> None:
    seed_people(db)
    make_user(db, "vol", role="volunteer", discipline="football")
    vol = login_as(app, "vol")
    assert vol.post(f"{API}/results", json=football_body(11)).status_code == 422
    assert vol.post(f"{API}/results", json=football_body(10)).status_code == 201


def test_pong_points_are_not_limited(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    body = pong_body()
    body["entries"][0]["points"] = 500
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 201


def test_raised_limit_allows_more_points(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    make_user(db, "adm", role="admin")
    admin = login_as(app, "adm")
    raised = admin.patch(f"{API}/disciplines/darts", json={"max_section_points": 20})
    assert raised.status_code == 200
    _, headers = make_station(db, "d1", "darts")
    assert (
        client.post(f"{API}/results", json=darts_body(points=20), headers=headers).status_code
        == 201
    )
    other = darts_body("0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e11", "NT02", points=21)
    assert client.post(f"{API}/results", json=other, headers=headers).status_code == 422


@pytest.mark.parametrize("role", ["superuser", "admin", "judge"])
def test_limit_is_editable_and_audited(app: FastAPI, db: Session, role: str) -> None:
    make_user(db, role, role=role)
    response = login_as(app, role).patch(
        f"{API}/disciplines/football", json={"max_section_points": 7}
    )
    assert response.status_code == 200
    assert response.json()["max_section_points"] == 7
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "discipline.update")).one()
    assert entry.before == {"max_section_points": 10}
    assert entry.after == {"max_section_points": 7}


def test_volunteer_cannot_change_the_limit(app: FastAPI, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="football")
    response = login_as(app, "vol").patch(
        f"{API}/disciplines/football", json={"max_section_points": 99}
    )
    assert response.status_code == 403


def test_judge_patch_above_limit_is_422_and_pong_is_free(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, darts = make_station(db, "d1", "darts")
    _, pong = make_station(db, "p1", "pong")
    client.post(f"{API}/results", json=darts_body(points=5), headers=darts)
    client.post(f"{API}/results", json=pong_body(), headers=pong)
    make_user(db, "judge", role="judge")
    judge = login_as(app, "judge")
    rows = judge.get(f"{API}/results").json()["items"]
    darts_id = next(r["id"] for r in rows if r["discipline"] == "darts")
    pong_id = next(r["id"] for r in rows if r["participant_code"] == "NT03")
    over = judge.patch(f"{API}/results/{darts_id}", json={"points": 11, "change_reason": "typo"})
    assert over.status_code == 422
    assert over.json()["code"] == "invalid_entries"
    fixed = judge.patch(f"{API}/results/{darts_id}", json={"points": 10, "change_reason": "ok"})
    assert fixed.status_code == 200
    free = judge.patch(f"{API}/results/{pong_id}", json={"points": 300, "change_reason": "ok"})
    assert free.status_code == 200


def test_replay_of_stored_session_ignores_a_lowered_limit(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    first = client.post(f"{API}/results", json=darts_body(points=9), headers=headers)
    assert first.status_code == 201
    make_user(db, "adm", role="admin")
    lowered = login_as(app, "adm").patch(f"{API}/disciplines/darts", json={"max_section_points": 5})
    assert lowered.status_code == 200
    replay = client.post(f"{API}/results", json=darts_body(points=9), headers=headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()


def test_judge_patch_without_points_ignores_a_lowered_limit(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(points=9), headers=headers)
    make_user(db, "judge", role="judge")
    judge = login_as(app, "judge")
    judge.patch(f"{API}/disciplines/darts", json={"max_section_points": 5})
    row_id = judge.get(f"{API}/results").json()["items"][0]["id"]
    ok = judge.patch(f"{API}/results/{row_id}", json={"comment": "note", "change_reason": "c"})
    assert ok.status_code == 200
    bad = judge.patch(f"{API}/results/{row_id}", json={"points": 6, "change_reason": "c"})
    assert bad.status_code == 422
