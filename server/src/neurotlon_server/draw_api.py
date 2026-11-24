import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, func, select, update

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.draw import DrawResult, draw_options, run_draw
from neurotlon_server.errors import ProblemError, conflict, not_found
from neurotlon_server.models import (
    Draw,
    Duel,
    Pair,
    Participant,
    SectionResult,
    Team,
    User,
)

router = APIRouter(prefix="/api/v1", tags=["draw"])

Manager = Annotated[User, Depends(require_role("superuser", "admin"))]
Viewer = Annotated[User, Depends(require_role("superuser", "admin"))]

MAX_SEED = 2**63 - 1


class DrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    m: int = Field(ge=1)
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED)


class TeamPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


def _checked_in(db: Db) -> list[tuple[str, str]]:
    rows = db.execute(
        select(Participant.code, Participant.category).where(
            Participant.checked_in_at.is_not(None), Participant.category.is_not(None)
        )
    )
    return [(code, category) for code, category in rows if category is not None]


def _counts(people: list[tuple[str, str]]) -> tuple[int, int]:
    ovz = sum(1 for _, c in people if c == "ovz")
    return ovz, sum(1 for _, c in people if c == "general")


def _protocol(result: DrawResult) -> dict[str, Any]:
    return {
        "seed": result.seed,
        "m": result.m,
        "team_count": result.team_count,
        "teams": [
            {
                "number": t.number,
                "name": t.name,
                "color": t.color,
                "members": [
                    {"code": x.code, "number_in_team": x.number_in_team} for x in t.members
                ],
            }
            for t in result.teams
        ],
        "duels": [
            {
                "order": d.order,
                "team_a": d.team_a,
                "team_b": d.team_b,
                "pairs": [{"k": p.k, "a": p.code_a, "b": p.code_b} for p in d.pairs],
            }
            for d in result.duels
        ],
        "reserve_ovz": list(result.reserve_ovz),
        "reserve_general": list(result.reserve_general),
    }


@router.get("/draw/options")
def options(request: Request, db: Db, actor: Manager) -> list[dict[str, int]]:
    max_teams = request.app.state.settings.max_teams
    ovz, general = _counts(_checked_in(db))
    return [
        {
            "m": o.m,
            "team_count": o.team_count,
            "reserve_general": o.reserve_general,
            "reserve_ovz": o.reserve_ovz,
            "reserve_total": o.reserve_total,
        }
        for o in draw_options(ovz, general, max_teams)
    ]


@router.post("/draw")
def make_draw(
    request: Request, body: DrawRequest, db: Db, now: Now, actor: Manager
) -> dict[str, Any]:
    max_teams = request.app.state.settings.max_teams
    has_draw = (
        db.scalar(select(Draw.id).limit(1)) is not None
        or db.scalar(select(Team.id).limit(1)) is not None
    )
    if has_draw:
        if actor.role != "superuser":
            raise conflict("Draw already done; only a superuser can redo it")
        if db.scalar(select(func.count()).select_from(SectionResult)):
            raise conflict("Results already exist; the draw cannot be redone")

    people = _checked_in(db)
    ovz, general = _counts(people)
    if body.m not in {o.m for o in draw_options(ovz, general, max_teams)}:
        raise ProblemError(
            422, "invalid_request", "Invalid request", "m is not an available option"
        )
    seed = secrets.randbits(63) if body.seed is None else body.seed
    result = run_draw(people, body.m, seed, max_teams)

    if has_draw:
        db.execute(delete(Pair))
        db.execute(delete(Duel))
        db.execute(update(Participant).values(team_id=None, number_in_team=None))
        db.execute(delete(Team))
        db.flush()

    by_code = {p.code: p for p in db.scalars(select(Participant))}
    team_ids: dict[int, int] = {}
    for t in result.teams:
        team = Team(number=t.number, name=t.name, color=t.color, order=t.number)
        db.add(team)
        db.flush()
        team_ids[t.number] = team.id
        for member in t.members:
            participant = by_code[member.code]
            participant.team_id = team.id
            participant.number_in_team = member.number_in_team
    db.flush()
    for d in result.duels:
        duel = Duel(team_a_id=team_ids[d.team_a], team_b_id=team_ids[d.team_b], order=d.order)
        db.add(duel)
        db.flush()
        for p in d.pairs:
            db.add(
                Pair(
                    duel_id=duel.id,
                    k=p.k,
                    participant_a_id=by_code[p.code_a].id,
                    participant_b_id=by_code[p.code_b].id,
                    zone_statuses={},
                )
            )

    draw = Draw(
        seed=seed,
        m=result.m,
        team_count=result.team_count,
        created_at=now,
        user_id=actor.id,
        protocol=_protocol(result),
    )
    db.add(draw)
    db.flush()
    write_audit(
        db,
        action="draw.create",
        object_type="draw",
        object_id=draw.id,
        user_id=actor.id,
        after={"seed": seed, "m": result.m, "team_count": result.team_count},
    )
    db.commit()
    return {"id": draw.id, "seed": seed, "m": result.m, "team_count": result.team_count}


@router.get("/draw")
def get_draw(db: Db, actor: Manager) -> dict[str, Any]:
    draw = db.scalar(select(Draw).order_by(Draw.id.desc()).limit(1))
    if draw is None:
        raise not_found("No draw yet")
    return {"id": draw.id, "created_at": draw.created_at, **draw.protocol}


@router.get("/teams")
def get_teams(db: Db, user: Viewer) -> dict[str, Any]:
    teams = list(db.scalars(select(Team).order_by(Team.order)))
    members: dict[int, list[Participant]] = {t.id: [] for t in teams}
    by_id: dict[int, Participant] = {}
    for p in db.scalars(
        select(Participant)
        .where(Participant.team_id.is_not(None))
        .order_by(Participant.number_in_team)
    ):
        if p.team_id is not None:
            members[p.team_id].append(p)
            by_id[p.id] = p
    number_of = {t.id: t.number for t in teams}
    duels = []
    for d in db.scalars(select(Duel).order_by(Duel.order)):
        pairs = db.scalars(select(Pair).where(Pair.duel_id == d.id).order_by(Pair.k))
        duels.append(
            {
                "order": d.order,
                "team_a": number_of[d.team_a_id],
                "team_b": number_of[d.team_b_id],
                "pairs": [
                    {
                        "k": p.k,
                        "a": by_id[p.participant_a_id].code,
                        "b": by_id[p.participant_b_id].code,
                    }
                    for p in pairs
                ],
            }
        )
    return {
        "teams": [
            {
                "id": t.id,
                "number": t.number,
                "name": t.name,
                "color": t.color,
                "members": [
                    {
                        "code": p.code,
                        "display_name": p.display_name,
                        "number_in_team": p.number_in_team,
                    }
                    for p in members[t.id]
                ],
            }
            for t in teams
        ],
        "duels": duels,
    }


@router.patch("/teams/{team_id}")
def patch_team(team_id: int, body: TeamPatch, db: Db, actor: Manager) -> dict[str, Any]:
    """Name and colour of a team; the scoreboard cache is marked dirty by the write guard."""
    team = db.get(Team, team_id)
    if team is None:
        raise not_found("Team not found")
    before = {"name": team.name, "color": team.color}
    team.name = body.name
    team.color = body.color
    write_audit(
        db,
        action="team.update",
        object_type="team",
        object_id=team.id,
        user_id=actor.id,
        before=before,
        after={"name": team.name, "color": team.color},
    )
    db.commit()
    return {"id": team.id, "number": team.number, "name": team.name, "color": team.color}
