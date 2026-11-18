from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog, GameSession, Pair, SectionResult

from .conftest import FakeClock, login_as, make_user
from .station_helpers import (
    API,
    SESSION_A,
    SESSION_B,
    darts_body,
    make_station,
    pong_body,
    seed_people,
)

BEAT = {"state": "playing", "queue_length": 0, "sensors": {}}


def count(db: Session, model: type) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_darts_single_result(client: TestClient, db: Session) -> None:
    seed_people(db)
    station_id, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/results", json=darts_body(), headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == SESSION_A
    assert [(r["participant_code"], r["status"]) for r in body["results"]] == [
        ("NT01", "confirmed")
    ]
    assert body["warnings"] == []
    row = db.scalars(select(SectionResult)).one()
    assert (row.points, row.source, row.station_id, row.section) == (
        4,
        "station",
        station_id,
        "bci",
    )
    assert row.finished_at.isoformat() == "2027-01-01T09:05:00+00:00"
    session = db.get(GameSession, SESSION_A)
    assert session is not None
    assert session.closed_at is not None
    assert session.payload_hash


def test_pong_pair_with_pair_id(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    response = client.post(f"{API}/results", json=pong_body(), headers=headers)
    assert response.status_code == 201
    assert len(response.json()["results"]) == 2
    pair = db.scalars(select(Pair).where(Pair.k == 2)).one()
    rows = db.scalars(select(SectionResult)).all()
    assert {r.pair_id for r in rows} == {pair.id}
    assert sorted(r.wins or 0 for r in rows) == [0, 1]


def test_not_completed(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = darts_body()
    body["entries"] = [
        {"participant_code": "NT01", "outcome": "not_completed", "reason": "equipment"}
    ]
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 201
    row = db.scalars(select(SectionResult)).one()
    assert (row.outcome, row.reason, row.points, row.wins) == (
        "not_completed",
        "equipment",
        None,
        None,
    )


def test_pair_id_is_null_without_pair(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    response = client.post(f"{API}/results", json=darts_body(code="NT05"), headers=headers)
    assert response.status_code == 201
    assert db.scalars(select(SectionResult)).one().pair_id is None
    assert response.json()["warnings"] == [{"participant_code": "NT05", "code": "no_pair_assigned"}]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["entries"][0].pop("points"),
        lambda b: b["entries"][0].update(reason="health"),
        lambda b: b["entries"][0].update(outcome="not_completed", reason="health"),
        lambda b: b["entries"][0].update(outcome="not_completed"),
        lambda b: b["entries"][0].update(points=-1),
        lambda b: b["entries"][0].update(category="ovz"),
        lambda b: b["entries"][0].update(participant_code="nt01"),
        lambda b: b["entries"][0].update(comment="x" * 201),
        lambda b: b.update(finished_at="2027-01-01T13:05:00"),
        lambda b: b.update(session_id="not-a-uuid"),
        lambda b: b.update(extra=1),
        lambda b: b.update(entries=[]),
        lambda b: b.update(discipline="chess"),
    ],
)
def test_schema_violations_422_and_nothing_written(
    client: TestClient, db: Session, mutate: Any
) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    body = darts_body()
    mutate(body)
    response = client.post(f"{API}/results", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "ovz" not in response.text and "nt01" not in response.text
    assert count(db, SectionResult) == 0
    assert count(db, GameSession) == 0
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "result.submit")
        )
        == 0
    )


def test_wrong_entry_count_is_invalid_entries(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, darts = make_station(db, "d1", "darts")
    _, pong = make_station(db, "p1", "pong")
    two = darts_body()
    two["entries"].append({"participant_code": "NT02", "outcome": "completed", "points": 1})
    one_pong = pong_body()
    one_pong["entries"].pop()
    same_pong = pong_body()
    same_pong["entries"][1]["participant_code"] = "NT03"
    for headers, body in ((darts, two), (pong, one_pong), (pong, same_pong)):
        response = client.post(f"{API}/results", json=body, headers=headers)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_entries"
    assert count(db, SectionResult) == 0
    assert count(db, GameSession) == 0


def test_unknown_participant_writes_nothing(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    body = pong_body()
    body["entries"][1]["participant_code"] = "NT99"
    response = client.post(f"{API}/results", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_participant"
    assert count(db, SectionResult) == count(db, GameSession) == 0


def test_replay_returns_same_receipt_and_no_extra_rows(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    first = client.post(f"{API}/results", json=pong_body(), headers=headers)
    audit_rows = count(db, AuditLog)
    # same data written differently: reordered entries, same instant in UTC
    replay_body = pong_body()
    replay_body["entries"].reverse()
    replay_body["finished_at"] = "2027-01-01T09:05:00+00:00"
    second = client.post(f"{API}/results", json=replay_body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert count(db, SectionResult) == 2
    assert count(db, GameSession) == 1
    assert count(db, AuditLog) == audit_rows


def test_conflicting_replay_is_409(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    other = darts_body()
    other["entries"][0]["points"] = 9
    response = client.post(f"{API}/results", json=other, headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "session_conflict"
    assert db.scalars(select(SectionResult)).one().points == 4


def test_session_opened_by_start_then_submitted(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    start = {"session_id": SESSION_A, "discipline": "darts", "participant_codes": ["NT01"]}
    client.post(f"{API}/sessions", json=start, headers=headers)
    response = client.post(f"{API}/results", json=darts_body(), headers=headers)
    assert response.status_code == 201
    assert count(db, GameSession) == 1
    session = db.get(GameSession, SESSION_A)
    assert session is not None
    assert session.closed_at is not None
    # closed session no longer makes the participant busy
    assert client.post(f"{API}/results", json=darts_body(), headers=headers).status_code == 200


def test_participants_mismatch_with_started_session_is_409(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    start = {"session_id": SESSION_A, "discipline": "darts", "participant_codes": ["NT02"]}
    client.post(f"{API}/sessions", json=start, headers=headers)
    response = client.post(f"{API}/results", json=darts_body(code="NT01"), headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "session_conflict"
    assert count(db, SectionResult) == 0


def test_offline_duplicate_is_accepted_with_warning(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    second = client.post(f"{API}/results", json=darts_body(SESSION_B), headers=headers)
    assert second.status_code == 201
    assert second.json()["warnings"] == [{"participant_code": "NT01", "code": "already_completed"}]
    assert count(db, SectionResult) == 2
    # the warning is stored and replayed
    again = client.post(f"{API}/results", json=darts_body(SESSION_B), headers=headers)
    assert again.status_code == 200
    assert again.json() == second.json()


def test_not_checked_in_and_busy_warnings(
    client: TestClient, db: Session, clock: FakeClock
) -> None:
    seed_people(db)
    _, other = make_station(db, "d2", "darts")
    _, mine = make_station(db, "d3", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=other)
    start = {"session_id": SESSION_B, "discipline": "darts", "participant_codes": ["NT06"]}
    client.post(f"{API}/sessions", json=start, headers=other)
    response = client.post(f"{API}/results", json=darts_body(code="NT06"), headers=mine)
    assert response.status_code == 201
    codes = [w["code"] for w in response.json()["warnings"]]
    assert codes == ["not_checked_in", "busy_on_other_station", "no_pair_assigned"]


def test_own_started_session_is_not_busy_warning(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/stations/me/heartbeat", json=BEAT, headers=headers)
    start = {"session_id": SESSION_A, "discipline": "darts", "participant_codes": ["NT01"]}
    client.post(f"{API}/sessions", json=start, headers=headers)
    response = client.post(f"{API}/results", json=darts_body(), headers=headers)
    assert response.json()["warnings"] == []


def test_volunteer_result_is_confirmed(app: FastAPI, db: Session) -> None:
    seed_people(db)
    user_id = make_user(db, "vol", role="volunteer", discipline="football")
    vol = login_as(app, "vol")
    body = darts_body()
    body["discipline"] = "football"
    body["section"] = "physical"
    response = vol.post(f"{API}/results", json=body)
    assert response.status_code == 201
    assert response.json()["results"][0]["status"] == "confirmed"
    row = db.scalars(select(SectionResult)).one()
    assert (row.status, row.source, row.user_id, row.station_id) == (
        "confirmed",
        "volunteer",
        user_id,
        None,
    )
    session = db.get(GameSession, SESSION_A)
    assert session is not None
    assert (session.user_id, session.station_id) == (user_id, None)


def test_wrong_discipline_and_section_are_403(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    make_user(db, "vol", role="volunteer", discipline="football")
    vol = login_as(app, "vol")
    wrong_discipline = {**darts_body(), "discipline": "pong"}
    wrong_section = darts_body()
    wrong_section["section"] = "physical"
    volunteer_bci = darts_body()
    volunteer_bci["discipline"] = "football"
    for who, body in (
        (client, wrong_discipline),
        (client, wrong_section),
        (vol, volunteer_bci),
        (vol, darts_body()),
    ):
        response = who.post(f"{API}/results", json=body, headers=headers if who is client else None)
        assert response.status_code == 403
        assert response.json()["code"] == "wrong_discipline"
    assert count(db, SectionResult) == 0


def test_audit_has_content_and_no_category(client: TestClient, db: Session) -> None:
    seed_people(db)
    station_id, headers = make_station(db, "p1", "pong")
    client.post(f"{API}/results", json=pong_body(), headers=headers)
    row = db.scalars(select(AuditLog).where(AuditLog.action == "result.submit")).one()
    assert (row.object_type, row.object_id, row.station_id) == (
        "game_session",
        SESSION_B,
        station_id,
    )
    assert row.after == {
        "discipline": "pong",
        "section": "bci",
        "entries": [
            {
                "participant_code": "NT03",
                "outcome": "completed",
                "points": 11,
                "wins": 1,
                "reason": None,
            },
            {
                "participant_code": "NT04",
                "outcome": "completed",
                "points": 7,
                "wins": 0,
                "reason": None,
            },
        ],
        "warnings": [],
    }
    dump = str(row.after) + str(row.before)
    assert "category" not in dump and "ovz" not in dump and "general" not in dump


def test_comment_is_stored(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(comment="ok"), headers=headers)
    assert db.scalars(select(SectionResult)).one().comment == "ok"
