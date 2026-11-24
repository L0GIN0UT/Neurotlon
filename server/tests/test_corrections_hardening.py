import pytest
from fastapi import FastAPI
from sqlalchemy import false, select, update
from sqlalchemy.orm import Session

from neurotlon_server import corrections_api
from neurotlon_server.models import AuditLog, SectionResult

from .conftest import login_as, make_user
from .station_helpers import API, SESSION_A, seed_people
from .test_corrections import audit_actions, football_body, setup_volunteer


def test_undo_audit_has_before_state(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    vol.post(f"{API}/results/{SESSION_A}/undo")
    db.expire_all()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "result.undo")).one()
    assert entry.before is not None
    assert [(r["status"], r["points"], r["outcome"], r["wins"]) for r in entry.before["rows"]] == [
        ("confirmed", 4, "completed", None)
    ]


def test_undo_of_locked_result_is_409(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    db.scalars(select(SectionResult)).one().status = "locked"
    db.commit()
    assert vol.post(f"{API}/results/{SESSION_A}/undo").status_code == 409
    db.expire_all()
    assert db.scalars(select(SectionResult)).one().voided_at is None


def test_concurrent_undo_loses_the_guarded_update(
    app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())

    def losing_update(model: type) -> object:
        return update(model).where(false())  # another request voided the rows first

    monkeypatch.setattr(corrections_api, "update", losing_update)
    assert vol.post(f"{API}/results/{SESSION_A}/undo").status_code == 409
    db.expire_all()
    assert db.scalars(select(SectionResult)).one().voided_at is None
    assert "result.undo" not in audit_actions(db)


def test_replay_of_undone_session_is_409_result_voided(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    assert vol.post(f"{API}/results", json=football_body()).status_code == 201
    vol.post(f"{API}/results/{SESSION_A}/undo")
    response = vol.post(f"{API}/results", json=football_body())
    assert response.status_code == 409
    assert response.json()["code"] == "result_voided"


def test_correction_for_voided_session_is_409(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    vol.post(f"{API}/results/{SESSION_A}/undo")
    response = vol.post(f"{API}/corrections", json={"session_id": SESSION_A, "comment": "x"})
    assert response.status_code == 409


def test_second_open_correction_is_409_until_done(app: FastAPI, db: Session) -> None:
    seed_people(db)
    vol = setup_volunteer(app, db)
    vol.post(f"{API}/results", json=football_body())
    ok = {"session_id": SESSION_A, "comment": "x"}
    first = vol.post(f"{API}/corrections", json=ok).json()
    assert vol.post(f"{API}/corrections", json=ok).status_code == 409
    make_user(db, "admin1", role="admin")
    login_as(app, "admin1").post(f"{API}/corrections/{first['id']}/done")
    assert vol.post(f"{API}/corrections", json=ok).status_code == 201
