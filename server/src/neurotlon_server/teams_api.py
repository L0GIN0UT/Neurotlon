"""Manual team assignment: the admin places checked-in people into the two teams by hand.

This replaces the random draw for the event itself (`draw.py` and `/draw` stay in the code).

Why it is manual and why there are exactly two teams: the organisers choose the line-ups
themselves and the event has two teams (red and blue). A pair is the k-th player of team 1
against the k-th player of team 2, so the order inside a team is the pairing.

FUTURE: if the number of teams grows, `TEAM_NUMBERS` and the single duel below have to become
a real schedule of duels (team A against team B for every pairing of the event), and that is the
point where the random draw (`draw.py`, `POST /draw`) becomes useful again: it already builds
teams, duels and pairs for any even number of teams up to `Settings.max_teams`.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, require_role
from neurotlon_server.codes import normalize_code
from neurotlon_server.draw import DEFAULT_NAMES, PALETTE
from neurotlon_server.draw_api import teams_payload
from neurotlon_server.errors import ProblemError
from neurotlon_server.models import Duel, Pair, Participant, SectionResult, Team, User

router = APIRouter(prefix="/api/v1", tags=["teams"])

Manager = Annotated[User, Depends(require_role("superuser", "admin"))]

# The event has two teams. See the module docstring before raising this.
TEAM_NUMBERS: tuple[int, ...] = (1, 2)


class TeamLineup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    number: Literal[1, 2]
    members: list[Annotated[str, StringConstraints(max_length=8)]] = Field(max_length=99)


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teams: list[TeamLineup] = Field(min_length=2, max_length=2)


def _invalid(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_request", "Invalid request", detail)


def _locked(detail: str) -> ProblemError:
    return ProblemError(409, "conflict", "Conflict", detail)


def _ensure_teams(db: Db) -> dict[int, Team]:
    teams = {t.number: t for t in db.scalars(select(Team))}
    for number in TEAM_NUMBERS:
        if number not in teams:
            team = Team(
                number=number,
                name=DEFAULT_NAMES[number - 1],
                color=PALETTE[number - 1],
                order=number,
            )
            db.add(team)
            teams[number] = team
    db.flush()
    return teams


def _normalize(assignment: Assignment) -> dict[int, list[str]]:
    wanted: dict[int, list[str]] = {}
    for t, lineup in enumerate(assignment.teams):
        if lineup.number not in TEAM_NUMBERS or lineup.number in wanted:
            raise _invalid("Teams must be exactly " + ", ".join(map(str, TEAM_NUMBERS)))
        codes: list[str] = []
        for m, raw in enumerate(lineup.members):
            code = normalize_code(raw)
            if code is None:
                raise _invalid(f"Invalid participant code at teams[{t}].members[{m}]")
            codes.append(code)
        wanted[lineup.number] = codes
    if set(wanted) != set(TEAM_NUMBERS):
        raise _invalid("Teams must be exactly " + ", ".join(map(str, TEAM_NUMBERS)))
    flat = [code for codes in wanted.values() for code in codes]
    if len(flat) != len(set(flat)):
        raise _invalid("A participant can be in one team only")
    return wanted


def _clear_pair_results(db: Db, pair_id: int) -> list[int]:
    """Results only remember which pair they were played in; forget a pair that is gone."""
    ids = list(db.scalars(select(SectionResult.id).where(SectionResult.pair_id == pair_id)))
    db.execute(update(SectionResult).where(SectionResult.pair_id == pair_id).values(pair_id=None))
    return ids


def _rebuild_pairs(
    db: Db, teams: dict[int, Team], by_code: dict[str, Participant]
) -> tuple[list[list[int | str]], list[int]]:
    """Pair k is the k-th player of team 1 against the k-th player of team 2.

    Returns the resulting pairs as `[k, code_a, code_b]` and which results lost their pair (ids).
    """
    first, second = (teams[n] for n in TEAM_NUMBERS)
    duel = db.scalar(select(Duel).order_by(Duel.id).limit(1))
    if duel is None:
        duel = Duel(team_a_id=first.id, team_b_id=second.id, order=1)
        db.add(duel)
        db.flush()
    else:
        duel.team_a_id, duel.team_b_id = first.id, second.id
    side_a = {
        p.number_in_team: p for p in by_code.values() if p.team_id == first.id and p.number_in_team
    }
    side_b = {
        p.number_in_team: p for p in by_code.values() if p.team_id == second.id and p.number_in_team
    }
    existing = {p.k: p for p in db.scalars(select(Pair).where(Pair.duel_id == duel.id))}
    cleared: list[int] = []
    pairs: list[list[int | str]] = []
    for k in sorted(set(existing) | set(side_a) | set(side_b)):
        a, b = side_a.get(k), side_b.get(k)
        pair = existing.get(k)
        if a is None or b is None:
            if pair is not None:
                cleared.extend(_clear_pair_results(db, pair.id))
                db.execute(delete(Pair).where(Pair.id == pair.id))
            continue
        pairs.append([k, a.code, b.code])
        if pair is None:
            db.add(
                Pair(
                    duel_id=duel.id,
                    k=k,
                    participant_a_id=a.id,
                    participant_b_id=b.id,
                    zone_statuses={},
                )
            )
        elif (pair.participant_a_id, pair.participant_b_id) != (a.id, b.id):
            cleared.extend(_clear_pair_results(db, pair.id))
            pair.participant_a_id, pair.participant_b_id = a.id, b.id
            pair.zone_statuses = {}
    db.flush()
    return pairs, cleared


@router.put("/teams/assignment")
def assign_teams(body: Assignment, db: Db, actor: Manager) -> dict[str, Any]:
    """Set the whole line-up: the order of codes in each team is the order of play.

    Checked-in participants only (people who already have a result are exempt: they are
    already in the game). Those who already have a result stay where they are: the other
    people can be moved around them.

    Known policy gap: a player who has a result but no team can still be placed into either
    team; decide with the owner (docs/decisions.md).
    """
    wanted = _normalize(body)
    try:
        # Take the write lock before any read, so that "has a result" cannot change under us.
        db.execute(text("BEGIN IMMEDIATE"))
        _apply(db, actor, wanted)
        db.commit()
    except (OperationalError, IntegrityError):  # a parallel writer: "database is locked" etc.
        db.rollback()
        raise _locked("The database is busy. Try again") from None
    return teams_payload(db)


def _apply(db: Db, actor: User, wanted: dict[int, list[str]]) -> None:
    _refuse_other_draws(db)
    teams = _ensure_teams(db)
    everyone = list(db.scalars(select(Participant)))
    by_code = {p.code: p for p in everyone}
    played = set(
        db.scalars(select(SectionResult.participant_id).where(SectionResult.voided_at.is_(None)))
    )

    unknown = [c for codes in wanted.values() for c in codes if c not in by_code]
    if unknown:
        raise ProblemError(404, "unknown_participant", "Not found", f"Unknown: {unknown[0]}")
    absent = [
        c
        for codes in wanted.values()
        for c in codes
        if by_code[c].checked_in_at is None and by_code[c].id not in played
    ]
    if absent:
        raise _invalid(f"{absent[0]} is not checked in")

    team_number = {t.id: n for n, t in teams.items()}
    before = _layout(everyone, team_number)
    target = {
        code: (number, index + 1)
        for number, codes in wanted.items()
        for index, code in enumerate(codes)
    }
    for person in everyone:
        # Only people who are already in a team are locked by a result.
        if person.id not in played or person.team_id is None:
            continue
        here = (team_number.get(person.team_id), person.number_in_team)
        if target.get(person.code) != here:
            raise _locked(f"{person.code} already has a result and cannot be moved")

    # Two steps: the unique (team, number) constraint must not see a half-moved line-up.
    db.execute(
        update(Participant)
        .where(Participant.id.not_in(played))
        .values(team_id=None, number_in_team=None)
    )
    db.expire_all()
    for code, (number, position) in target.items():
        person = by_code[code]
        person.team_id = teams[number].id
        person.number_in_team = position
    db.flush()
    pairs, cleared = _rebuild_pairs(db, teams, by_code)

    after = _layout(everyone, team_number)
    if before != after:
        write_audit(
            db,
            action="teams.assign",
            object_type="team",
            object_id="all",
            user_id=actor.id,
            before={"teams": before},
            after={
                "teams": after,
                "pairs": pairs,
                "cleared_pair_results": len(cleared),
                "cleared_result_ids": cleared,
            },
        )


def _refuse_other_draws(db: Db) -> None:
    """A draw for more teams leaves duels and pairs that this screen cannot represent."""
    foreign = db.scalar(
        select(func.count()).select_from(Team).where(Team.number.not_in(TEAM_NUMBERS))
    )
    duels = db.scalar(select(func.count()).select_from(Duel))
    if foreign or (duels or 0) > 1:
        raise _locked(
            "Teams were drawn for more than two teams; manual assignment is not available"
        )


def _layout(everyone: list[Participant], team_number: dict[int, int]) -> dict[str, list[str]]:
    layout: dict[str, list[str]] = {str(n): [] for n in team_number.values()}
    placed = sorted(
        (p for p in everyone if p.team_id in team_number and p.number_in_team is not None),
        key=lambda p: p.number_in_team or 0,
    )
    for person in placed:
        layout[str(team_number[person.team_id or 0])].append(person.code)
    return layout
