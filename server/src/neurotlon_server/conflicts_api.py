"""Duplicate results for one (participant, discipline, section): list and resolve."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.errors import ProblemError, conflict, forbidden, not_found
from neurotlon_server.models import Participant, SectionResult, User
from neurotlon_server.scoring import COUNTED_STATUSES

router = APIRouter(prefix="/api/v1/conflicts", tags=["conflicts"])

Resolver = Annotated[User, Depends(require_role("superuser", "admin", "volunteer"))]


class ConflictResultOut(BaseModel):
    id: int
    points: int | None
    wins: int | None
    outcome: str
    reason: str | None
    source: str
    finished_at: datetime
    created_at: datetime


class ConflictOut(BaseModel):
    participant_code: str
    discipline: str
    section: str
    results: list[ConflictResultOut]


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_result_id: int
    reason: str = Field(min_length=1, max_length=200)


def _may_touch(user: User, discipline: str) -> bool:
    return user.role != "volunteer" or user.discipline == discipline


def _live_rows(db: Db, participant_id: int, discipline: str, section: str) -> list[SectionResult]:
    return list(
        db.scalars(
            select(SectionResult)
            .where(
                SectionResult.participant_id == participant_id,
                SectionResult.discipline == discipline,
                SectionResult.section == section,
                SectionResult.voided_at.is_(None),
                SectionResult.status.in_(COUNTED_STATUSES),
            )
            .order_by(SectionResult.id)
        )
    )


@router.get("")
def list_conflicts(db: Db, user: Resolver) -> list[ConflictOut]:
    query = (
        select(SectionResult, Participant.code)
        .join(Participant, Participant.id == SectionResult.participant_id)
        .where(SectionResult.voided_at.is_(None), SectionResult.status.in_(COUNTED_STATUSES))
        .order_by(
            Participant.code, SectionResult.discipline, SectionResult.section, SectionResult.id
        )
    )
    if user.role == "volunteer":
        query = query.where(SectionResult.discipline == user.discipline)
    groups: dict[tuple[str, str, str], list[SectionResult]] = {}
    for row, code in db.execute(query):
        groups.setdefault((code, row.discipline, row.section), []).append(row)
    return [
        ConflictOut(
            participant_code=code,
            discipline=discipline,
            section=section,
            results=[
                ConflictResultOut(
                    id=r.id,
                    points=r.points,
                    wins=r.wins,
                    outcome=r.outcome,
                    reason=r.reason,
                    source=r.source,
                    finished_at=r.finished_at,
                    created_at=r.created_at,
                )
                for r in rows
            ],
        )
        for (code, discipline, section), rows in groups.items()
        if len(rows) > 1
    ]


@router.post("/resolve", status_code=200)
def resolve_conflict(
    body: ResolveRequest, db: Db, now: Now, user: Resolver
) -> dict[str, list[int]]:
    kept = db.get(SectionResult, body.keep_result_id)
    if kept is None:
        raise not_found("Result not found")
    if not _may_touch(user, kept.discipline):
        raise forbidden()
    rows = _live_rows(db, kept.participant_id, kept.discipline, kept.section)
    if len(rows) < 2 or kept.id not in {r.id for r in rows}:
        raise ProblemError(
            409, "no_conflict", "No conflict", "This result has no duplicate to resolve"
        )
    voided = [r for r in rows if r.id != kept.id]
    for row in voided:
        row.voided_at = now
        row.voided_by = user.id
        row.void_reason = body.reason
    write_audit(
        db,
        action="result.resolve",
        object_type="section_result",
        object_id=kept.id,
        user_id=user.id,
        after={"kept": kept.id, "voided": [r.id for r in voided]},
        reason=body.reason,
    )
    try:
        db.commit()
    except (OperationalError, IntegrityError) as exc:
        db.rollback()
        raise conflict("Result changed concurrently, try again") from exc
    return {"voided": [r.id for r in voided]}
