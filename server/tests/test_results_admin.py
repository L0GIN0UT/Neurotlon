import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog, CorrectionRequest, Participant, SectionResult

from .conftest import login_as, make_user
from .station_helpers import (
    API,
    SESSION_A,
    SESSION_B,
    darts_body,
    make_station,
    pong_body,
    seed_people,
)

Seeded = dict[str, dict[str, str]]
FIX = {"points": 5, "change_reason": "admin recount"}


@pytest.fixture
def seeded(client: TestClient, db: Session) -> Seeded:
    seed_people(db)
    _, darts = make_station(db, "d1", "darts")
    _, pong = make_station(db, "p1", "pong")
    assert client.post(f"{API}/results", json=darts_body(), headers=darts).status_code == 201
    assert client.post(f"{API}/results", json=pong_body(), headers=pong).status_code == 201
    return {"darts": darts, "pong": pong}


def edit(client: TestClient, url: str, **fields: object) -> Response:
    return client.patch(url, json={**fields, "change_reason": "r"})


def staff(app: FastAPI, db: Session, role: str) -> TestClient:
    make_user(db, role, role=role)
    return login_as(app, role)


def row_of(db: Session, code: str, discipline: str) -> SectionResult:
    db.expire_all()
    return db.scalars(
        select(SectionResult)
        .join(Participant, Participant.id == SectionResult.participant_id)
        .where(Participant.code == code, SectionResult.discipline == discipline)
    ).one()


def audit(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.mark.parametrize(
    ("role", "status"), [("superuser", 200), ("admin", 200), ("volunteer", 403)]
)
def test_search_role_matrix(
    app: FastAPI, db: Session, seeded: Seeded, role: str, status: int
) -> None:
    make_user(db, "u", role=role, discipline="darts" if role == "volunteer" else None)
    assert login_as(app, "u").get(f"{API}/results").status_code == status


def test_search_requires_login(client: TestClient) -> None:
    assert client.get(f"{API}/results").status_code == 401


def test_search_filters(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    assert admin.get(f"{API}/results").json()["total"] == 3
    rows = admin.get(f"{API}/results", params={"participant": "1"}).json()["items"]
    assert [(r["participant_code"], r["discipline"]) for r in rows] == [("NT01", "darts")]
    assert len(admin.get(f"{API}/results", params={"discipline": "pong"}).json()["items"]) == 2
    assert admin.get(f"{API}/results", params={"section": "physical"}).json() == {
        "total": 0,
        "items": [],
    }
    assert admin.get(f"{API}/results", params={"participant": "zzz"}).json() == {
        "total": 0,
        "items": [],
    }
    by_session = admin.get(f"{API}/results", params={"session_id": SESSION_B}).json()["items"]
    assert {r["participant_code"] for r in by_session} == {"NT03", "NT04"}
    assert admin.get(f"{API}/results", params={"discipline": "chess"}).status_code == 422


def test_search_marks_voided_rows(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    row.voided_at = row.created_at
    db.commit()
    found = admin.get(f"{API}/results", params={"participant": "NT01"}).json()["items"]
    assert found[0]["voided"] is True
    assert "category" not in str(found)


def test_admin_corrects_confirmed_result(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    response = admin.patch(f"{API}/results/{row.id}", json=FIX)
    assert response.status_code == 200
    body = response.json()
    assert (body["points"], body["version"], body["status"]) == (5, 2, "confirmed")
    assert body["participant_code"] == "NT01"
    entry = audit(db, "result.correct").pop()
    assert entry.reason == "admin recount"
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before["points"] == 4
    assert entry.after["points"] == 5
    assert entry.before["version"] == 1
    assert entry.after["version"] == 2
    assert "category" not in str(entry.before) + str(entry.after)
    assert "ovz" not in str(entry.after)


def test_fractional_points_in_a_correction_are_422(
    app: FastAPI, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    bad = admin.patch(f"{API}/results/{row.id}", json={**FIX, "points": 5.5})
    assert bad.status_code == 422
    assert row_of(db, "NT01", "darts").points == 4
    assert admin.patch(f"{API}/results/{row.id}", json={**FIX, "points": 6.0}).status_code == 200
    assert row_of(db, "NT01", "darts").points == 6


def test_correction_needs_a_change_reason(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    for bad in (
        {"points": 5},
        {"points": 5, "change_reason": ""},
        {"points": 5, "change_reason": "x" * 201},
    ):
        assert admin.patch(f"{API}/results/{row.id}", json=bad).status_code == 422
    assert admin.patch(f"{API}/results/{row.id}", json={"change_reason": "why"}).status_code == 422
    assert audit(db, "result.correct") == []


def test_unknown_and_extra_fields_rejected(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    assert (
        admin.patch(f"{API}/results/{row.id}", json={**FIX, "status": "entered"}).status_code == 422
    )
    assert admin.patch(f"{API}/results/{row.id}", json={**FIX, "points": -1}).status_code == 422
    assert admin.patch(f"{API}/results/999", json=FIX).status_code == 404


def test_volunteer_cannot_correct(app: FastAPI, db: Session, seeded: Seeded) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    row = row_of(db, "NT01", "darts")
    assert login_as(app, "vol").patch(f"{API}/results/{row.id}", json=FIX).status_code == 403


def test_correction_requires_login(client: TestClient, db: Session, seeded: Seeded) -> None:
    row = row_of(db, "NT01", "darts")
    assert client.patch(f"{API}/results/{row.id}", json=FIX).status_code == 401


def test_locked_result_only_admin_edits(app: FastAPI, db: Session, seeded: Seeded) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    volunteer = login_as(app, "vol")
    admin = staff(app, db, "admin")
    superuser = staff(app, db, "superuser")
    assert admin.post(f"{API}/results/lock").json() == {"locked": 3}
    row = row_of(db, "NT01", "darts")
    assert row.status == "locked"
    refused = volunteer.patch(f"{API}/results/{row.id}", json=FIX)
    assert refused.status_code == 403
    assert row_of(db, "NT01", "darts").points == 4
    assert admin.patch(f"{API}/results/{row.id}", json=FIX).status_code == 200
    changed = superuser.patch(f"{API}/results/{row.id}", json={**FIX, "points": 6})
    assert changed.status_code == 200
    after = row_of(db, "NT01", "darts")
    assert (after.points, after.version, after.status) == (6, 3, "locked")


def test_voided_result_cannot_be_corrected(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    row.voided_at = row.created_at
    db.commit()
    assert admin.patch(f"{API}/results/{row.id}", json=FIX).status_code == 409


def test_entered_result_cannot_be_corrected(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    row.status = "entered"
    db.commit()
    assert admin.patch(f"{API}/results/{row.id}", json=FIX).status_code == 409


def test_outcome_switch_follows_submission_rules(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    url = f"{API}/results/{row.id}"
    # not_completed needs a reason
    assert edit(admin, url, outcome="not_completed").status_code == 422
    done = admin.patch(
        url, json={"outcome": "not_completed", "reason": "health", "change_reason": "r"}
    )
    assert done.status_code == 200
    assert (done.json()["points"], done.json()["reason"]) == (None, "health")
    # points are forbidden while not completed
    assert edit(admin, url, points=3).status_code == 422
    # back to completed: points required, the reason is dropped
    assert edit(admin, url, outcome="completed").status_code == 422
    back = edit(admin, url, outcome="completed", points=9)
    assert back.json()["reason"] is None
    assert back.json()["version"] == 3
    # a completed result cannot carry a reason
    assert edit(admin, url, reason="health").status_code == 422


def test_wins_only_for_pong(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    darts = row_of(db, "NT01", "darts")
    assert edit(admin, f"{API}/results/{darts.id}", wins=1).status_code == 422


def test_new_pong_winner_demotes_the_other_player_atomically(
    app: FastAPI, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    winner, loser = row_of(db, "NT03", "pong"), row_of(db, "NT04", "pong")
    assert (winner.wins, loser.wins) == (1, 0)
    response = edit(admin, f"{API}/results/{loser.id}", wins=1)
    assert response.status_code == 200
    assert response.json()["wins"] == 1
    new_winner, new_loser = row_of(db, "NT04", "pong"), row_of(db, "NT03", "pong")
    assert (new_winner.wins, new_loser.wins) == (1, 0)
    assert (new_winner.version, new_loser.version) == (2, 2)
    entries = audit(db, "result.correct")
    assert len(entries) == 2
    assert {e.object_id for e in entries} == {str(winner.id), str(loser.id)}
    demoted = next(e for e in entries if e.object_id == str(winner.id))
    assert demoted.before is not None
    assert demoted.after is not None
    assert (demoted.before["wins"], demoted.after["wins"]) == (1, 0)
    assert demoted.reason == "r"


def test_pong_winner_cannot_be_removed_without_a_new_one(
    app: FastAPI, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    winner = row_of(db, "NT03", "pong")
    assert edit(admin, f"{API}/results/{winner.id}", wins=0).status_code == 422
    assert row_of(db, "NT03", "pong").wins == 1
    assert audit(db, "result.correct") == []
    # editing the winner's points keeps wins
    assert edit(admin, f"{API}/results/{winner.id}", points=5).status_code == 200
    assert row_of(db, "NT03", "pong").wins == 1


def test_pong_winner_edit_respects_locked_sibling(
    app: FastAPI, db: Session, seeded: Seeded
) -> None:
    make_user(db, "vol", role="volunteer", discipline="pong")
    volunteer = login_as(app, "vol")
    loser = row_of(db, "NT04", "pong")
    winner = row_of(db, "NT03", "pong")
    winner.status = "locked"
    db.commit()
    assert edit(volunteer, f"{API}/results/{loser.id}", wins=1).status_code == 403
    assert row_of(db, "NT03", "pong").wins == 1
    admin = staff(app, db, "admin")
    assert edit(admin, f"{API}/results/{loser.id}", wins=1).status_code == 200
    assert row_of(db, "NT03", "pong").wins == 0


def test_comment_can_be_set_and_cleared(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    url = f"{API}/results/{row.id}"
    assert edit(admin, url, comment="checked").json()["comment"] == "checked"
    assert edit(admin, url, comment="").json()["comment"] is None


def test_corrected_result_changes_the_scoreboard(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    admin.patch(f"{API}/results/{row.id}", json=FIX)
    assert client.get(f"{API}/scoreboard").json()["teams"][0]["total"] == 5


def test_station_replay_does_not_undo_a_correction(
    client: TestClient, app: FastAPI, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    admin.patch(f"{API}/results/{row.id}", json=FIX)
    replay = client.post(f"{API}/results", json=darts_body(SESSION_A), headers=seeded["darts"])
    assert replay.status_code == 200
    assert row_of(db, "NT01", "darts").points == 5


@pytest.mark.parametrize(
    ("role", "status"), [("superuser", 200), ("admin", 200), ("volunteer", 403)]
)
def test_lock_role_matrix(
    app: FastAPI, db: Session, seeded: Seeded, role: str, status: int
) -> None:
    make_user(db, "u", role=role, discipline="darts" if role == "volunteer" else None)
    assert login_as(app, "u").post(f"{API}/results/lock").status_code == status


def test_lock_requires_login(client: TestClient) -> None:
    assert client.post(f"{API}/results/lock").status_code == 401


def test_lock_skips_voided_and_is_repeatable(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    row.voided_at = row.created_at
    db.commit()
    ids = [row_of(db, "NT03", "pong").id, row_of(db, "NT04", "pong").id]
    assert admin.post(f"{API}/results/lock").json() == {"locked": 2}
    assert row_of(db, "NT01", "darts").status == "confirmed"
    assert admin.post(f"{API}/results/lock").json() == {"locked": 0}
    entries = audit(db, "result.lock")
    assert [e.after for e in entries] == [{"locked": 2, "ids": ids}, {"locked": 0, "ids": []}]
    assert all(e.user_id is not None for e in entries)


def test_locked_rows_still_count_on_the_scoreboard(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded
) -> None:
    staff(app, db, "admin").post(f"{API}/results/lock")
    assert client.get(f"{API}/scoreboard").json()["teams"][0]["total"] == 4


SESSION_DUP = "5d2f6a10-9b3c-4e1d-a7c8-0e4b1f2a3c6d"


def make_conflict(client: TestClient, seeded: Seeded) -> None:
    body = darts_body(SESSION_DUP, points=10)
    assert client.post(f"{API}/results", json=body, headers=seeded["darts"]).status_code == 201


def open_correction(db: Session, user_id: int) -> None:
    db.add(CorrectionRequest(session_id=SESSION_A, user_id=user_id, comment="fix"))
    db.commit()


def test_lock_blocked_by_conflict_and_open_correction(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    make_conflict(client, seeded)
    response = admin.post(f"{API}/results/lock")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert (body["conflicts"], body["open_corrections"]) == (1, 0)
    assert row_of_status(db) == {"confirmed"}
    assert audit(db, "result.lock") == []

    open_correction(db, 1)
    body = admin.post(f"{API}/results/lock").json()
    assert (body["conflicts"], body["open_corrections"]) == (1, 1)


def row_of_status(db: Session) -> set[str]:
    db.expire_all()
    return set(db.scalars(select(SectionResult.status)))


def test_lock_blocked_only_by_open_correction(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    open_correction(db, 1)
    body = admin.post(f"{API}/results/lock").json()
    assert (body["conflicts"], body["open_corrections"]) == (0, 1)


def test_done_correction_does_not_block(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    open_correction(db, 1)
    request = db.scalars(select(CorrectionRequest)).one()
    request.status = "done"
    db.commit()
    assert admin.post(f"{API}/results/lock").status_code == 200


def test_volunteer_cannot_lock_or_force(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded
) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    volunteer = login_as(app, "vol")
    admin = staff(app, db, "admin")
    make_conflict(client, seeded)
    assert volunteer.post(f"{API}/results/lock", json={"force": True}).status_code == 403
    assert volunteer.post(f"{API}/results/lock").status_code == 403
    assert admin.post(f"{API}/results/lock", json={"force": "x"}).status_code == 422
    assert row_of_status(db) == {"confirmed"}


@pytest.mark.parametrize("role", ["admin", "superuser"])
def test_admin_forces_lock_and_audit_records_it(
    app: FastAPI, client: TestClient, db: Session, seeded: Seeded, role: str
) -> None:
    boss = staff(app, db, role)
    make_conflict(client, seeded)
    open_correction(db, 1)
    response = boss.post(f"{API}/results/lock", json={"force": True})
    assert response.status_code == 200
    assert response.json() == {"locked": 4}
    entry = audit(db, "result.lock").pop()
    assert entry.after is not None
    assert entry.after.pop("ids") and entry.after == {
        "locked": 4,
        "force": True,
        "conflicts": 1,
        "open_corrections": 1,
    }


def test_force_without_blockers_is_a_normal_lock(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    assert admin.post(f"{API}/results/lock", json={"force": True}).json() == {"locked": 3}
    assert audit(db, "result.lock").pop().after == {
        "locked": 3,
        "ids": [1, 2, 3],
        "force": True,
        "conflicts": 0,
        "open_corrections": 0,
    }


def test_search_pagination_and_total(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    page = admin.get(f"{API}/results", params={"limit": 2}).json()
    assert (page["total"], len(page["items"])) == (3, 2)
    rest = admin.get(f"{API}/results", params={"limit": 2, "offset": 2}).json()
    assert (rest["total"], len(rest["items"])) == (3, 1)
    ids = [r["id"] for r in page["items"] + rest["items"]]
    assert len(set(ids)) == 3
    assert admin.get(f"{API}/results", params={"offset": 9}).json() == {"total": 3, "items": []}
    filtered = admin.get(f"{API}/results", params={"discipline": "pong", "limit": 1}).json()
    assert (filtered["total"], len(filtered["items"])) == (2, 1)


def test_search_limit_bounds(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    for params in ({"limit": 0}, {"limit": 1001}, {"offset": -1}):
        assert admin.get(f"{API}/results", params=params).status_code == 422
    assert admin.get(f"{API}/results", params={"limit": 1000}).status_code == 200


def test_change_reason_is_stripped(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    row = row_of(db, "NT01", "darts")
    url = f"{API}/results/{row.id}"
    blank = admin.patch(url, json={"points": 1, "change_reason": "   	 "})
    assert blank.status_code == 422
    assert admin.patch(url, json={"points": 1, "change_reason": "  recount  "}).status_code == 200
    assert audit(db, "result.correct").pop().reason == "recount"
    assert admin.patch(url, json={"points": 2, "change_reason": " " + "x" * 200}).status_code == 200


def test_pong_both_completed_needs_exactly_one_winner(
    app: FastAPI, db: Session, seeded: Seeded
) -> None:
    admin = staff(app, db, "admin")
    winner, loser = row_of(db, "NT03", "pong"), row_of(db, "NT04", "pong")
    # the loser drops out and comes back: wins must be given again
    assert (
        edit(
            admin, f"{API}/results/{loser.id}", outcome="not_completed", reason="health"
        ).status_code
        == 200
    )
    back = edit(admin, f"{API}/results/{loser.id}", outcome="completed", points=3)
    assert back.status_code == 422
    assert row_of(db, "NT04", "pong").outcome == "not_completed"
    # with wins=0 next to the winner: exactly one winner
    ok = edit(admin, f"{API}/results/{loser.id}", outcome="completed", points=3, wins=0)
    assert ok.status_code == 200
    assert (row_of(db, "NT03", "pong").wins, row_of(db, "NT04", "pong").wins) == (1, 0)
    assert winner.id != loser.id


def test_pong_two_losers_rejected(app: FastAPI, db: Session, seeded: Seeded) -> None:
    admin = staff(app, db, "admin")
    winner, loser = row_of(db, "NT03", "pong"), row_of(db, "NT04", "pong")
    # the winner leaves the match, the other stays completed with wins=0
    assert (
        edit(
            admin, f"{API}/results/{winner.id}", outcome="not_completed", reason="health"
        ).status_code
        == 200
    )
    # the former winner returns with wins=0 while the other has wins=0 too: nobody wins
    nobody = edit(admin, f"{API}/results/{winner.id}", outcome="completed", points=3, wins=0)
    assert nobody.status_code == 422
    assert row_of(db, "NT04", "pong").wins == 0
    assert loser.id != winner.id
