from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from neurotlon_server.models import Duel, Pair, Participant, Station, Team
from neurotlon_server.security import hash_token, new_token

API = "/api/v1"
SESSION_A = "0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10"
SESSION_B = "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5"
FINISHED = "2027-01-01T13:05:00+04:00"


def make_station(db: Session, name: str, discipline: str) -> tuple[int, dict[str, str]]:
    token = new_token()
    station = Station(name=name, discipline=discipline, token_hash=hash_token(token))
    db.add(station)
    db.commit()
    return station.id, {"Authorization": f"Bearer {token}"}


def seed_people(db: Session) -> None:
    """NT01..NT04 paired and checked in (NT01 in team 1), NT05 checked in without a pair,
    NT06 not checked in."""
    team_a = Team(number=1, name="Alpha", color="#aa00bb", order=1)
    team_b = Team(number=2, name="Beta", color="#00ff00", order=2)
    db.add_all([team_a, team_b])
    db.flush()
    here = datetime(2027, 1, 1, 8, tzinfo=UTC)
    people = [
        Participant(
            code=f"NT0{i}",
            display_name=f"Name {i}",
            category="ovz" if i % 2 else "general",
            checked_in_at=None if i == 6 else here,
            team_id=team_a.id if i == 1 else None,
            number_in_team=1 if i == 1 else None,
        )
        for i in range(1, 7)
    ]
    db.add_all(people)
    duel = Duel(team_a_id=team_a.id, team_b_id=team_b.id, order=1)
    db.add(duel)
    db.flush()
    db.add(
        Pair(
            duel_id=duel.id,
            k=1,
            participant_a_id=people[0].id,
            participant_b_id=people[1].id,
            zone_statuses={},
        )
    )
    db.add(
        Pair(
            duel_id=duel.id,
            k=2,
            participant_a_id=people[2].id,
            participant_b_id=people[3].id,
            zone_statuses={},
        )
    )
    db.commit()


def darts_body(session_id: str = SESSION_A, code: str = "NT01", **entry: Any) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "discipline": "darts",
        "section": "bci",
        "finished_at": FINISHED,
        "entries": [{"participant_code": code, "outcome": "completed", "points": 4.5, **entry}],
    }


def pong_body(session_id: str = SESSION_B) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "discipline": "pong",
        "section": "bci",
        "finished_at": FINISHED,
        "entries": [
            {"participant_code": "NT03", "outcome": "completed", "points": 11, "wins": 1},
            {"participant_code": "NT04", "outcome": "completed", "points": 7, "wins": 0},
        ],
    }
