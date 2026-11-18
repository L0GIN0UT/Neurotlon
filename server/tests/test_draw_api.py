import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from neurotlon_server.draw import run_draw
from neurotlon_server.models import (
    AuditLog,
    Draw,
    Duel,
    Pair,
    Participant,
    SectionResult,
    Team,
)

from .conftest import login_as, make_user

API = "/api/v1"


@pytest.fixture
def admin(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "boss", role="admin")
    return login_as(app, "boss")


@pytest.fixture
def root(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "root", role="superuser")
    return login_as(app, "root")


def check_in(db: Session, ovz: int, general: int) -> list[tuple[str, str]]:
    people = [(f"NT{i:02d}", "ovz" if i <= ovz else "general") for i in range(1, ovz + general + 1)]
    for code, category in people:
        db.add(
            Participant(
                code=code,
                category=category,
                checked_in_at=datetime(2027, 1, 1, tzinfo=UTC),
                display_name=f"Name {code}",
            )
        )
    db.commit()
    return people


def add_result(db: Session) -> None:
    pid = db.scalars(select(Participant.id)).first()
    db.add(
        SectionResult(
            session_id="s1",
            participant_id=pid,
            discipline="darts",
            section="bci",
            outcome="completed",
            points=1.0,
            wins=0,
            source="admin",
            finished_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()


def test_options(admin: TestClient, db: Session) -> None:
    check_in(db, 7, 9)
    # a participant without check-in is ignored
    db.add(Participant(code="NT20", category="ovz"))
    db.commit()
    body = admin.get(f"{API}/draw/options").json()
    assert body[0] == {
        "m": 3,
        "team_count": 2,
        "reserve_general": 3,
        "reserve_ovz": 1,
        "reserve_total": 4,
    }
    assert [o["m"] for o in body] == [3, 1, 2]


def test_options_empty(admin: TestClient) -> None:
    assert admin.get(f"{API}/draw/options").json() == []


def test_roles(app: FastAPI, db: Session, admin: TestClient) -> None:
    make_user(db, "judge", role="judge")
    make_user(db, "vol", role="volunteer", discipline="darts")
    anon = TestClient(app, base_url="https://testserver")
    judge = login_as(app, "judge")
    vol = login_as(app, "vol")
    assert anon.get(f"{API}/teams").status_code == 401
    assert anon.get(f"{API}/draw/options").status_code == 401
    for c in (judge, vol):
        assert c.get(f"{API}/draw/options").status_code == 403
        assert c.get(f"{API}/draw").status_code == 403
        assert c.post(f"{API}/draw", json={"m": 1}).status_code == 403
    assert vol.get(f"{API}/teams").status_code == 403
    assert judge.get(f"{API}/teams").status_code == 200
    assert admin.get(f"{API}/teams").status_code == 200


def test_draw_persists_pure_result(admin: TestClient, db: Session) -> None:
    people = check_in(db, 5, 5)
    check_in_extra = Participant(code="NT30", category=None)
    db.add(check_in_extra)
    db.commit()
    response = admin.post(f"{API}/draw", json={"m": 1, "seed": 7})
    assert response.status_code == 200
    expected = run_draw(people, 1, 7)
    assert response.json()["team_count"] == expected.team_count == 4

    db.expire_all()
    teams = list(db.scalars(select(Team).order_by(Team.number)))
    assert [t.number for t in teams] == [1, 2, 3, 4]
    assert [t.order for t in teams] == [1, 2, 3, 4]
    by_id = {p.id: p for p in db.scalars(select(Participant))}
    for team, exp in zip(teams, expected.teams, strict=True):
        assert (team.name, team.color) == (exp.name, exp.color)
        got = {p.number_in_team: p.code for p in by_id.values() if p.team_id == team.id}
        assert got == {m.number_in_team: m.code for m in exp.members}
    reserve = {p.code for p in by_id.values() if p.team_id is None}
    assert reserve == {"NT30", *expected.reserve_ovz, *expected.reserve_general}

    duels = list(db.scalars(select(Duel).order_by(Duel.order)))
    assert len(duels) == 2
    team_number = {t.id: t.number for t in teams}
    for duel, exp_duel in zip(duels, expected.duels, strict=True):
        assert (team_number[duel.team_a_id], team_number[duel.team_b_id]) == (
            exp_duel.team_a,
            exp_duel.team_b,
        )
        pairs = list(db.scalars(select(Pair).where(Pair.duel_id == duel.id).order_by(Pair.k)))
        assert [
            (p.k, by_id[p.participant_a_id].code, by_id[p.participant_b_id].code) for p in pairs
        ] == [(p.k, p.code_a, p.code_b) for p in exp_duel.pairs]
        assert all(p.zone_statuses == {} for p in pairs)

    draw = db.scalars(select(Draw)).one()
    assert (draw.seed, draw.m, draw.team_count) == (7, 1, 4)
    assert draw.protocol["reserve_ovz"] == list(expected.reserve_ovz)
    assert admin.get(f"{API}/draw").json()["seed"] == 7


def test_default_seed_is_random_and_returned(admin: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    body = admin.post(f"{API}/draw", json={"m": 1}).json()
    assert 0 <= body["seed"] < 2**63


def test_get_draw_without_draw(admin: TestClient) -> None:
    assert admin.get(f"{API}/draw").status_code == 404


@pytest.mark.parametrize("body", [{"m": 0}, {"m": -1}, {"m": 1, "seed": -1}, {"m": 1, "x": 1}])
def test_validation_422(admin: TestClient, db: Session, body: dict[str, int]) -> None:
    check_in(db, 4, 4)
    response = admin.post(f"{API}/draw", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_m_not_in_options_422(admin: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    response = admin.post(f"{API}/draw", json={"m": 3})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert db.scalar(select(func.count()).select_from(Draw)) == 0


def test_too_few_participants_422(admin: TestClient, db: Session) -> None:
    check_in(db, 1, 1)
    assert admin.post(f"{API}/draw", json={"m": 1}).status_code == 422


def test_admin_cannot_redraw(admin: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    assert admin.post(f"{API}/draw", json={"m": 1, "seed": 1}).status_code == 200
    response = admin.post(f"{API}/draw", json={"m": 1, "seed": 2})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_superuser_redraw_replaces(root: TestClient, db: Session) -> None:
    check_in(db, 5, 5)
    assert root.post(f"{API}/draw", json={"m": 1, "seed": 1}).status_code == 200
    assert root.post(f"{API}/draw", json={"m": 2, "seed": 2}).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Team)) == 2
    assert db.scalar(select(func.count()).select_from(Duel)) == 1
    assert db.scalar(select(func.count()).select_from(Pair)) == 4
    assert db.scalar(select(func.count()).select_from(Draw)) == 2
    placed = db.scalar(
        select(func.count()).select_from(Participant).where(Participant.team_id.is_not(None))
    )
    assert placed == 8
    teams = root.get(f"{API}/teams").json()
    assert len(teams["teams"]) == 2
    assert root.get(f"{API}/draw").json()["m"] == 2


def test_redraw_blocked_by_results(root: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    assert root.post(f"{API}/draw", json={"m": 1, "seed": 1}).status_code == 200
    add_result(db)
    assert root.post(f"{API}/draw", json={"m": 1, "seed": 2}).status_code == 409
    assert db.scalar(select(func.count()).select_from(Draw)) == 1


def test_audit_has_only_seed_m_team_count(admin: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    admin.post(f"{API}/draw", json={"m": 1, "seed": 9})
    row = db.scalars(select(AuditLog).where(AuditLog.action == "draw.create")).one()
    assert row.after == {"seed": 9, "m": 1, "team_count": 4}
    dump = json.dumps([row.after, row.object_type, row.object_id])
    assert "ovz" not in dump and "general" not in dump and "NT" not in dump


def test_teams_hide_category(admin: TestClient, db: Session) -> None:
    check_in(db, 4, 4)
    admin.post(f"{API}/draw", json={"m": 1, "seed": 9})
    response = admin.get(f"{API}/teams")
    assert response.status_code == 200
    assert "ovz" not in response.text and "general" not in response.text
    body = response.json()
    assert len(body["teams"]) == 4
    member = body["teams"][0]["members"][0]
    assert set(member) == {"code", "display_name", "number_in_team"}
    assert len(body["duels"]) == 2
    assert len(body["duels"][0]["pairs"]) == 2


def test_teams_empty(admin: TestClient) -> None:
    assert admin.get(f"{API}/teams").json() == {"teams": [], "duels": []}
