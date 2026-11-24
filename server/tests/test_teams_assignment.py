from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog, Duel, Pair, Participant, SectionResult, Team

from .conftest import login_as, make_user

API = "/api/v1"


@pytest.fixture
def admin(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "boss", role="admin")
    return login_as(app, "boss")


def people(db: Session, count: int = 6, *, absent: tuple[int, ...] = ()) -> None:
    for i in range(1, count + 1):
        db.add(
            Participant(
                code=f"NT{i:02d}",
                category="general",
                checked_in_at=None if i in absent else datetime(2027, 1, 1, tzinfo=UTC),
            )
        )
    db.commit()


def put(client: TestClient, red: list[str], blue: list[str]) -> object:
    return client.put(
        f"{API}/teams/assignment",
        json={"teams": [{"number": 1, "members": red}, {"number": 2, "members": blue}]},
    )


def pairs_of(db: Session) -> list[tuple[int, str, str]]:
    code = {p.id: p.code for p in db.scalars(select(Participant))}
    db.expire_all()
    return [
        (p.k, code[p.participant_a_id], code[p.participant_b_id])
        for p in db.scalars(select(Pair).order_by(Pair.k))
    ]


def test_first_assignment_creates_the_two_teams_and_pairs_by_position(
    admin: TestClient, db: Session
) -> None:
    people(db)
    response = put(admin, ["NT01", "NT02", "NT03"], ["NT04", "NT05", "NT06"])
    assert response.status_code == 200  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert [t["name"] for t in body["teams"]] == ["Красные", "Синие"]
    assert [m["code"] for m in body["teams"][0]["members"]] == ["NT01", "NT02", "NT03"]
    assert [m["number_in_team"] for m in body["teams"][1]["members"]] == [1, 2, 3]
    assert pairs_of(db) == [(1, "NT01", "NT04"), (2, "NT02", "NT05"), (3, "NT03", "NT06")]
    assert len(list(db.scalars(select(Team)))) == 2
    assert len(list(db.scalars(select(Duel)))) == 1


def test_reordering_changes_the_pairs(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02", "NT03"], ["NT04", "NT05", "NT06"])
    assert put(admin, ["NT03", "NT01", "NT02"], ["NT04", "NT05", "NT06"]).status_code == 200  # type: ignore[attr-defined]
    assert pairs_of(db) == [(1, "NT03", "NT04"), (2, "NT01", "NT05"), (3, "NT02", "NT06")]


def test_moving_between_teams_and_uneven_teams(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02", "NT03"], ["NT04", "NT05", "NT06"])
    # NT03 goes to the other team; the red team is now shorter
    assert put(admin, ["NT01", "NT02"], ["NT04", "NT05", "NT06", "NT03"]).status_code == 200  # type: ignore[attr-defined]
    assert pairs_of(db) == [(1, "NT01", "NT04"), (2, "NT02", "NT05")]  # no partner, no pair


def test_removing_a_player_returns_them_to_the_pool(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    put(admin, ["NT01"], ["NT03", "NT04"])
    db.expire_all()
    nt02 = db.scalar(select(Participant).where(Participant.code == "NT02"))
    assert nt02 is not None
    assert nt02.team_id is None
    assert nt02.number_in_team is None


def test_same_assignment_again_changes_nothing_and_is_not_audited_twice(
    admin: TestClient, db: Session
) -> None:
    people(db)
    put(admin, ["NT01"], ["NT02"])
    put(admin, ["NT01"], ["NT02"])
    entries = list(db.scalars(select(AuditLog).where(AuditLog.action == "teams.assign")))
    assert len(entries) == 1


@pytest.mark.parametrize(
    ("red", "blue", "status"),
    [
        (["NT01", "NT01"], [], 422),  # twice in one team
        (["NT01"], ["NT01"], 422),  # in both teams
        (["NT01"], ["NT09"], 404),  # unknown
        (["NT01"], ["zzz"], 422),  # not a code
        (["NT01"], ["NT05"], 422),  # not checked in
    ],
)
def test_invalid_lineups(
    admin: TestClient, db: Session, red: list[str], blue: list[str], status: int
) -> None:
    people(db, absent=(5,))
    assert put(admin, red, blue).status_code == status  # type: ignore[attr-defined]


def test_only_the_two_teams_are_accepted(admin: TestClient, db: Session) -> None:
    people(db)
    response = admin.put(
        f"{API}/teams/assignment",
        json={"teams": [{"number": 1, "members": []}, {"number": 3, "members": []}]},
    )
    assert response.status_code == 422
    response = admin.put(f"{API}/teams/assignment", json={"teams": [{"number": 1, "members": []}]})
    assert response.status_code == 422


def add_result(db: Session, code: str, pair_id: int | None = None) -> None:
    person = db.scalar(select(Participant).where(Participant.code == code))
    assert person is not None
    db.add(
        SectionResult(
            session_id=f"s-{code}",
            participant_id=person.id,
            pair_id=pair_id,
            discipline="darts",
            section="bci",
            outcome="completed",
            points=5,
            wins=0,
            source="admin",
            finished_at=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()


def test_a_player_with_a_result_cannot_be_moved(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    add_result(db, "NT01")
    # to another team, to another position, out of the teams: all refused
    assert put(admin, ["NT02"], ["NT03", "NT04", "NT01"]).status_code == 409  # type: ignore[attr-defined]
    assert put(admin, ["NT02", "NT01"], ["NT03", "NT04"]).status_code == 409  # type: ignore[attr-defined]
    assert put(admin, ["NT02"], ["NT03", "NT04"]).status_code == 409  # type: ignore[attr-defined]
    assert pairs_of(db) == [(1, "NT01", "NT03"), (2, "NT02", "NT04")]  # nothing changed


def test_others_can_be_moved_around_a_player_with_a_result(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    add_result(db, "NT01")
    assert put(admin, ["NT01", "NT05"], ["NT03", "NT02"]).status_code == 200  # type: ignore[attr-defined]
    assert pairs_of(db) == [(1, "NT01", "NT03"), (2, "NT05", "NT02")]


def test_a_dissolved_pair_is_forgotten_by_the_results_played_in_it(
    admin: TestClient, db: Session
) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    pair = db.scalars(select(Pair).where(Pair.k == 1)).one()
    add_result(db, "NT01", pair.id)
    # the partner leaves: the pair disappears but the result stays
    assert put(admin, ["NT01", "NT02"], []).status_code == 200  # type: ignore[attr-defined]
    db.expire_all()
    result = db.scalars(select(SectionResult)).one()
    assert result.pair_id is None


def test_a_voided_result_does_not_lock_the_player(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01"], ["NT02"])
    add_result(db, "NT01")
    result = db.scalars(select(SectionResult)).one()
    result.voided_at = datetime(2027, 1, 2, tzinfo=UTC)
    db.commit()
    assert put(admin, [], ["NT02"]).status_code == 200  # type: ignore[attr-defined]


def test_judge_cannot_assign(app: FastAPI, db: Session) -> None:
    make_user(db, "jd", role="judge")
    assert put(login_as(app, "jd"), [], []).status_code == 403  # type: ignore[attr-defined]


def test_a_player_without_a_team_who_has_a_result_does_not_block(
    admin: TestClient, db: Session
) -> None:
    people(db)
    add_result(db, "NT05")  # the result was accepted before any line-up
    assert put(admin, ["NT01"], ["NT02"]).status_code == 200  # type: ignore[attr-defined]
    assert put(admin, ["NT01", "NT05"], ["NT02"]).status_code == 200  # type: ignore[attr-defined]
    # once placed, the player is locked
    assert put(admin, ["NT01"], ["NT02"]).status_code == 409  # type: ignore[attr-defined]


def legacy_four_teams(db: Session) -> None:
    for number in (3, 4):
        db.add(Team(number=number, name=f"T{number}", color="#112233", order=number))
    db.commit()


def test_a_draw_for_more_than_two_teams_blocks_manual_assignment(
    admin: TestClient, db: Session
) -> None:
    people(db)
    legacy_four_teams(db)
    response = put(admin, ["NT01"], ["NT02"])
    assert response.status_code == 409  # type: ignore[attr-defined]
    assert response.json()["code"] == "conflict"  # type: ignore[attr-defined]
    assert "more than two teams" in response.json()["detail"]  # type: ignore[attr-defined]
    db.expire_all()
    assert db.scalar(select(Team).where(Team.number == 1)) is None  # nothing was created


def test_more_than_one_duel_blocks_manual_assignment(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01"], ["NT02"])
    teams = list(db.scalars(select(Team).order_by(Team.number)))
    db.add(Duel(team_a_id=teams[1].id, team_b_id=teams[0].id, order=2))
    db.commit()
    assert put(admin, ["NT01"], ["NT02"]).status_code == 409  # type: ignore[attr-defined]


def test_teams_payload_skips_a_pair_with_a_missing_participant(
    admin: TestClient, db: Session
) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    nt02 = db.scalar(select(Participant).where(Participant.code == "NT02"))
    assert nt02 is not None
    nt02.team_id = None
    nt02.number_in_team = None
    db.commit()
    response = admin.get(f"{API}/teams")
    assert response.status_code == 200
    assert [p["k"] for p in response.json()["duels"][0]["pairs"]] == [1]


def test_a_database_lock_gives_409_and_changes_nothing(
    admin: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    people(db)
    put(admin, ["NT01"], ["NT02"])

    def locked(self: Session) -> None:
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(Session, "commit", locked)
    response = put(admin, ["NT03"], ["NT04"])
    monkeypatch.undo()
    assert response.status_code == 409  # type: ignore[attr-defined]
    assert response.json()["code"] == "conflict"  # type: ignore[attr-defined]
    assert pairs_of(db) == [(1, "NT01", "NT02")]
    assert admin.get(f"{API}/teams").json()["teams"][0]["members"][0]["code"] == "NT01"


def test_a_changed_partner_resets_the_pair_and_forgets_its_results(
    admin: TestClient, db: Session
) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    pair = db.scalars(select(Pair).where(Pair.k == 1)).one()
    pair.zone_statuses = {"darts": "done"}
    db.commit()
    add_result(db, "NT01", pair.id)
    assert put(admin, ["NT01", "NT02"], ["NT05", "NT04"]).status_code == 200  # type: ignore[attr-defined]
    db.expire_all()
    assert db.scalars(select(SectionResult)).one().pair_id is None
    assert db.scalars(select(Pair).where(Pair.k == 1)).one().zone_statuses == {}


def test_an_unchanged_pair_keeps_its_results(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    pair = db.scalars(select(Pair).where(Pair.k == 1)).one()
    pair_id = pair.id
    add_result(db, "NT01", pair_id)
    assert put(admin, ["NT01", "NT05"], ["NT03", "NT04"]).status_code == 200  # type: ignore[attr-defined]
    db.expire_all()
    assert db.scalars(select(SectionResult)).one().pair_id == pair_id


def test_audit_lists_pairs_and_cleared_results(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03", "NT04"])
    pair = db.scalars(select(Pair).where(Pair.k == 1)).one()
    add_result(db, "NT01", pair.id)
    put(admin, ["NT01", "NT02"], ["NT05", "NT04"])
    db.expire_all()
    entry = list(
        db.scalars(select(AuditLog).where(AuditLog.action == "teams.assign").order_by(AuditLog.id))
    )[-1]
    assert entry.object_id == "all"
    assert entry.after is not None
    assert entry.after["pairs"] == [[1, "NT01", "NT05"], [2, "NT02", "NT04"]]
    assert entry.after["cleared_pair_results"] == 1
    assert "category" not in str(entry.after) and "general" not in str(entry.after)


def test_volunteer_cannot_assign(app: FastAPI, db: Session) -> None:
    make_user(db, "vl", role="volunteer", discipline="darts")
    assert put(login_as(app, "vl"), [], []).status_code == 403  # type: ignore[attr-defined]


def test_an_entirely_empty_team_is_listed_correctly(admin: TestClient, db: Session) -> None:
    people(db)
    assert put(admin, ["NT01", "NT02"], []).status_code == 200  # type: ignore[attr-defined]
    response = admin.get(f"{API}/teams")
    assert response.status_code == 200
    body = response.json()
    assert [m["code"] for m in body["teams"][0]["members"]] == ["NT01", "NT02"]
    assert body["teams"][1]["members"] == []
    assert body["duels"][0]["pairs"] == []


def test_a_huge_code_is_rejected_without_echo(admin: TestClient, db: Session) -> None:
    people(db)
    huge = "X" * 200000
    response = admin.put(
        f"{API}/teams/assignment",
        json={"teams": [{"number": 1, "members": ["NT01", huge]}, {"number": 2, "members": []}]},
    )
    assert response.status_code == 422
    assert "XXXX" not in response.text


def test_a_bad_code_error_names_the_position_only(admin: TestClient, db: Session) -> None:
    people(db)
    response = put(admin, ["NT01", "zzz"], [])
    assert response.status_code == 422  # type: ignore[attr-defined]
    assert "teams[0].members[1]" in response.text  # type: ignore[attr-defined]
    assert "zzz" not in response.text  # type: ignore[attr-defined]


@pytest.mark.parametrize("number", [True, "2", 3, 1.0])
def test_team_number_must_be_a_strict_one_or_two(
    admin: TestClient, db: Session, number: object
) -> None:
    people(db)
    response = admin.put(
        f"{API}/teams/assignment",
        json={"teams": [{"number": 1, "members": []}, {"number": number, "members": []}]},
    )
    assert response.status_code == 422


def test_a_player_with_a_result_and_no_check_in_is_still_accepted(
    admin: TestClient, db: Session
) -> None:
    people(db)
    put(admin, ["NT01", "NT02"], ["NT03"])
    add_result(db, "NT01")
    nt01 = db.scalar(select(Participant).where(Participant.code == "NT01"))
    assert nt01 is not None
    nt01.checked_in_at = None  # the check-in was cancelled
    db.commit()
    assert put(admin, ["NT01"], ["NT03"]).status_code == 200  # type: ignore[attr-defined]
    # someone without a result and without a check-in is still refused
    nt06 = db.scalar(select(Participant).where(Participant.code == "NT06"))
    assert nt06 is not None
    nt06.checked_in_at = None
    db.commit()
    assert put(admin, ["NT01", "NT06"], ["NT03"]).status_code == 422  # type: ignore[attr-defined]


def test_audit_lists_the_ids_of_cleared_results(admin: TestClient, db: Session) -> None:
    people(db)
    put(admin, ["NT01"], ["NT02"])
    pair = db.scalars(select(Pair)).one()
    add_result(db, "NT01", pair.id)
    result_id = db.scalars(select(SectionResult)).one().id
    put(admin, ["NT01"], ["NT03"])
    db.expire_all()
    entry = list(db.scalars(select(AuditLog).where(AuditLog.action == "teams.assign")))[-1]
    assert entry.after is not None
    assert entry.after["cleared_result_ids"] == [result_id]
