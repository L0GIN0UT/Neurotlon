from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog, CorrectionRequest, SectionResult

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API, SESSION_A, SESSION_B, darts_body, make_station, seed_people


def football_body(session_id: str = SESSION_A, code: str = "NT01") -> dict[str, object]:
    body = darts_body(session_id, code)
    body["discipline"] = "football"
    body["section"] = "physical"
    return body


def setup_volunteer(app: FastAPI, db: Session, login: str = "vol") -> TestClient:
    make_user(db, login, role="volunteer", discipline="football")
    return login_as(app, login)


def audit_actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


def test_undo_within_window_voids_rows(app: FastAPI, db: Session, clock: FakeClock) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    assert vol.post(f"{API}/results", json=football_body()).status_code == 201
    clock.advance(seconds=30)
    response = vol.post(f"{API}/results/{SESSION_A}/undo")
    assert response.status_code == 204
    db.expire_all()
    row = db.scalars(select(SectionResult)).one()
    assert row.voided_at is not None
    assert row.void_reason == "undo"
    assert row.voided_by is not None
    assert "result.undo" in audit_actions(db)


def test_undo_frees_participant_for_new_result(app: FastAPI, db: Session, clock: FakeClock) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    vol.post(f"{API}/results/{SESSION_A}/undo")
    response = vol.get(f"{API}/participants/NT01/eligibility?discipline=football&section=physical")
    assert "already_completed" not in response.json()["issues"]


def test_undo_after_window_is_409(app: FastAPI, db: Session, clock: FakeClock) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    clock.advance(seconds=31)
    response = vol.post(f"{API}/results/{SESSION_A}/undo")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    db.expire_all()
    assert db.scalars(select(SectionResult)).one().voided_at is None


def test_undo_twice_is_409(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    assert vol.post(f"{API}/results/{SESSION_A}/undo").status_code == 204
    assert vol.post(f"{API}/results/{SESSION_A}/undo").status_code == 409


def test_undo_by_other_user_is_403(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    other = setup_volunteer(app, db, "vol2")
    vol.post(f"{API}/results", json=football_body())
    assert other.post(f"{API}/results/{SESSION_A}/undo").status_code == 403


def test_undo_unknown_session_and_roles(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    assert vol.post(f"{API}/results/{SESSION_B}/undo").status_code == 404
    assert client.post(f"{API}/results/{SESSION_A}/undo").status_code == 401
    make_user(db, "judge1", role="judge")
    judge = login_as(app, "judge1")
    assert judge.post(f"{API}/results/{SESSION_A}/undo").status_code == 403


def test_undo_of_station_result_is_403(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    vol = setup_volunteer(app, db)
    assert vol.post(f"{API}/results/{SESSION_A}/undo").status_code == 403


def test_volunteer_creates_correction_for_own_session(
    app: FastAPI, db: Session, clock: FakeClock
) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    clock.advance(minutes=5)
    response = vol.post(
        f"{API}/corrections", json={"session_id": SESSION_A, "comment": "Не те очки"}
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["session_id"], body["comment"], body["status"]) == (
        SESSION_A,
        "Не те очки",
        "open",
    )
    assert body["participant_codes"] == ["NT01"]
    db.expire_all()
    assert db.scalars(select(CorrectionRequest)).one().status == "open"
    assert "correction.create" in audit_actions(db)


def test_correction_rules(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    other = setup_volunteer(app, db, "vol2")
    vol.post(f"{API}/results", json=football_body())
    ok = {"session_id": SESSION_A, "comment": "x"}
    assert other.post(f"{API}/corrections", json=ok).status_code == 403
    assert vol.post(f"{API}/corrections", json={**ok, "session_id": SESSION_B}).status_code == 404
    assert vol.post(f"{API}/corrections", json={**ok, "comment": "я" * 201}).status_code == 422
    assert vol.post(f"{API}/corrections", json={**ok, "comment": ""}).status_code == 422
    assert vol.post(f"{API}/corrections", json={**ok, "comment": "я" * 200}).status_code == 201
    make_user(db, "judge1", role="judge")
    judge = login_as(app, "judge1")
    assert judge.post(f"{API}/corrections", json=ok).status_code == 403


def test_list_and_resolve(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    other = setup_volunteer(app, db, "vol2")
    vol.post(f"{API}/results", json=football_body())
    created = vol.post(f"{API}/corrections", json={"session_id": SESSION_A, "comment": "c"}).json()

    assert [c["id"] for c in vol.get(f"{API}/corrections?status=open").json()] == [created["id"]]
    assert other.get(f"{API}/corrections?status=open").json() == []
    assert client.get(f"{API}/corrections").status_code == 401

    for role in ("judge", "admin", "superuser"):
        make_user(db, role, role=role)
        assert len(login_as(app, role).get(f"{API}/corrections?status=open").json()) == 1

    assert vol.post(f"{API}/corrections/{created['id']}/done").status_code == 403
    judge = login_as(app, "judge")
    response = judge.post(f"{API}/corrections/{created['id']}/done")
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert judge.get(f"{API}/corrections?status=open").json() == []
    assert len(judge.get(f"{API}/corrections?status=done").json()) == 1
    assert judge.post(f"{API}/corrections/{created['id']}/done").status_code == 409
    assert judge.post(f"{API}/corrections/999/done").status_code == 404
    db.expire_all()
    row = db.scalars(select(CorrectionRequest)).one()
    assert row.resolved_by is not None
    assert row.resolved_at is not None
    assert "correction.done" in audit_actions(db)
