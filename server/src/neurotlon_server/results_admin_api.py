"""Judge and admin tools for stored results: search, correction, lock (decision 9, section 8)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, require_role
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError, conflict, forbidden, not_found
from neurotlon_server.models import (
    CorrectionRequest,
    Discipline,
    Participant,
    SectionResult,
    User,
)
from neurotlon_server.results import DisciplineName, Reason, SectionName, points_over_limit
from neurotlon_server.scoring import COUNTED_STATUSES

router = APIRouter(prefix="/api/v1/results", tags=["results"])

Judge = Annotated[User, Depends(require_role("judge", "admin", "superuser"))]

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
_AUDITED = ("points", "wins", "outcome", "reason", "comment")


class ResultOut(BaseModel):
    id: int
    session_id: str
    participant_code: str
    discipline: str
    section: str
    outcome: str
    points: int | None
    wins: int | None
    reason: str | None
    comment: str | None
    status: str
    source: str
    finished_at: datetime
    version: int
    voided: bool


class ResultPage(BaseModel):
    total: int
    items: list[ResultOut]


class ResultPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: int | None = Field(default=None, ge=0, le=1000)
    wins: int | None = Field(default=None, ge=0, le=1)
    outcome: Literal["completed", "not_completed"] | None = None
    reason: Reason | None = None
    comment: str | None = Field(default=None, max_length=200)
    change_reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


def _out(row: SectionResult, code: str) -> ResultOut:
    return ResultOut(
        id=row.id,
        session_id=row.session_id,
        participant_code=code,
        discipline=row.discipline,
        section=row.section,
        outcome=row.outcome,
        points=row.points,
        wins=row.wins,
        reason=row.reason,
        comment=row.comment,
        status=row.status,
        source=row.source,
        finished_at=row.finished_at,
        version=row.version,
        voided=row.voided_at is not None,
    )


def _snapshot(row: SectionResult) -> dict[str, Any]:
    return {key: getattr(row, key) for key in _AUDITED}


def _invalid(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_entries", "Invalid entries", detail)


def _apply(db: Db, row: SectionResult, patch: ResultPatch) -> dict[str, Any]:
    """New field values for the row, validated by the same rules as a submission."""
    changes = patch.model_dump(exclude_unset=True, exclude={"change_reason"})
    if not changes:
        raise ProblemError(422, "invalid_request", "Invalid request", "Nothing to change")
    new = _snapshot(row)
    outcome = changes.get("outcome", row.outcome)
    if outcome is None:
        raise _invalid("outcome must not be null")
    if outcome != row.outcome:
        # Switching the outcome resets the fields that belong to the other one.
        if outcome == "not_completed":
            new["points"] = new["wins"] = None
        else:
            new["reason"] = None
    new.update(changes)
    new["outcome"] = outcome
    if new["comment"] == "":
        new["comment"] = None
    if outcome == "completed":
        if new["points"] is None or new["reason"] is not None:
            raise _invalid("completed needs points and no reason")
    elif new["reason"] is None or new["points"] is not None or new["wins"] is not None:
        raise _invalid("not_completed needs reason and no points or wins")
    if row.discipline != "pong" and new["wins"] is not None:
        raise _invalid("wins are only for pong")
    if "points" in changes:  # fixing other fields must not trip over a lowered limit
        discipline = db.get(Discipline, row.discipline)
        assert discipline is not None
        message = points_over_limit(row.discipline, new["points"], discipline.max_section_points)
        if message:
            raise _invalid(message)
    return new


def _pong_siblings(
    db: Db, row: SectionResult, new: dict[str, Any], user: User
) -> list[SectionResult]:
    """Match-level rules; returns the other rows that must get wins=0 in the same edit."""
    if row.discipline != "pong":
        return []
    others = list(
        db.scalars(
            select(SectionResult).where(
                SectionResult.session_id == row.session_id,
                SectionResult.id != row.id,
                SectionResult.voided_at.is_(None),
            )
        )
    )
    completed = new["outcome"] == "completed"
    if completed and row.wins == 1 and new["wins"] != 1:
        raise _invalid("the winner cannot be removed: set wins=1 on the other player")
    promoted = new["wins"] == 1 and row.wins != 1
    changed = [o for o in others if promoted and o.outcome == "completed" and o.wins != 0]
    if completed and others and all(o.outcome == "completed" for o in others):
        wins = (new["wins"] or 0) + sum(0 if o in changed else (o.wins or 0) for o in others)
        if wins != 1 or new["wins"] is None:
            raise _invalid("both players completed: exactly one must have wins=1")
    for other in changed:
        if other.status == "locked" and user.role == "judge":
            raise forbidden()
        if other.status not in ("confirmed", "locked"):
            raise conflict("The other player's result is not confirmed")
    return changed


@router.get("")
def list_results(
    db: Db,
    user: Judge,
    participant: Annotated[str | None, Query()] = None,
    discipline: Annotated[DisciplineName | None, Query()] = None,
    section: Annotated[SectionName | None, Query()] = None,
    session_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResultPage:
    query = (
        select(SectionResult, Participant.code)
        .join(Participant, Participant.id == SectionResult.participant_id)
        .order_by(Participant.code, SectionResult.discipline, SectionResult.section)
        .order_by(SectionResult.id)
    )
    if participant:
        code = normalize_code(participant)
        if code is None:
            return ResultPage(total=0, items=[])
        query = query.where(Participant.code == code)
    if discipline:
        query = query.where(SectionResult.discipline == discipline)
    if section:
        query = query.where(SectionResult.section == section)
    if session_id:
        query = query.where(SectionResult.session_id == session_id)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.execute(query.limit(limit).offset(offset))
    return ResultPage(total=total, items=[_out(row, code) for row, code in rows])


class LockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


def _blockers(db: Db) -> dict[str, int]:
    """Unresolved duplicates and open correction requests that should stop the lock."""
    live = db.execute(
        select(
            SectionResult.participant_id,
            SectionResult.discipline,
            SectionResult.section,
            func.count(),
        )
        .where(SectionResult.voided_at.is_(None), SectionResult.status.in_(COUNTED_STATUSES))
        .group_by(SectionResult.participant_id, SectionResult.discipline, SectionResult.section)
    )
    conflicts = sum(1 for *_, n in live if n > 1)
    open_requests = db.scalar(
        select(func.count())
        .select_from(CorrectionRequest)
        .where(CorrectionRequest.status == "open")
    )
    return {"conflicts": conflicts, "open_corrections": open_requests or 0}


@router.post("/lock")
def lock_results(
    db: Db, user: Judge, body: Annotated[LockRequest | None, Body()] = None
) -> dict[str, int]:
    force = body is not None and body.force
    if force and user.role == "judge":
        raise forbidden()
    blockers = _blockers(db)
    blocked = any(blockers.values())
    if blocked and not force:
        raise ProblemError(
            409,
            "conflict",
            "Conflict",
            f"Unresolved conflicts: {blockers['conflicts']}, "
            f"open correction requests: {blockers['open_corrections']}",
            extra=blockers,
        )
    ids = list(
        db.scalars(
            select(SectionResult.id)
            .where(SectionResult.status == "confirmed", SectionResult.voided_at.is_(None))
            .order_by(SectionResult.id)
        )
    )
    done = db.execute(
        update(SectionResult)
        .where(
            SectionResult.id.in_(ids),
            SectionResult.status == "confirmed",
            SectionResult.voided_at.is_(None),
        )
        .values(status="locked")
    )
    assert isinstance(done, CursorResult)
    locked = done.rowcount
    after: dict[str, Any] = {"locked": locked, "ids": ids}
    if force:
        after |= {"force": True, **blockers}
    write_audit(
        db,
        action="result.lock",
        object_type="section_result",
        object_id="bulk",
        user_id=user.id,
        after=after,
    )
    db.commit()
    return {"locked": locked}


def _demote_sibling(db: Db, other: SectionResult, user: User, change_reason: str) -> None:
    """The other pong player becomes the loser (wins=0) in the same transaction."""
    version = other.version
    before = _snapshot(other) | {"version": version}
    done = db.execute(
        update(SectionResult)
        .where(
            SectionResult.id == other.id,
            SectionResult.version == version,
            SectionResult.status == other.status,
            SectionResult.voided_at.is_(None),
        )
        .values(wins=0, version=version + 1)
    )
    assert isinstance(done, CursorResult)
    if done.rowcount != 1:
        db.rollback()
        raise conflict("Result changed concurrently, reload and try again")
    code = db.scalar(select(Participant.code).where(Participant.id == other.participant_id))
    write_audit(
        db,
        action="result.correct",
        object_type="section_result",
        object_id=other.id,
        user_id=user.id,
        before=before,
        after=_snapshot(other) | {"wins": 0, "version": version + 1, "participant_code": code},
        reason=change_reason,
    )


@router.patch("/{result_id}")
def patch_result(result_id: int, body: ResultPatch, db: Db, user: Judge) -> ResultOut:
    row = db.get(SectionResult, result_id)
    if row is None:
        raise not_found("Result not found")
    if row.voided_at is not None:
        raise conflict("Result is voided")
    if row.status == "locked" and user.role == "judge":
        raise forbidden()
    if row.status not in ("confirmed", "locked"):
        raise conflict("Only confirmed or locked results can be corrected")
    new = _apply(db, row, body)
    siblings = _pong_siblings(db, row, new, user)
    before = _snapshot(row) | {"version": row.version}
    version, status = row.version, row.status
    # Guarded update: of two parallel corrections (or a lock in between) only one wins.
    done = db.execute(
        update(SectionResult)
        .where(
            SectionResult.id == row.id,
            SectionResult.version == version,
            SectionResult.status == status,
            SectionResult.voided_at.is_(None),
        )
        .values(**new, version=version + 1)
    )
    assert isinstance(done, CursorResult)
    if done.rowcount != 1:
        db.rollback()
        raise conflict("Result changed concurrently, reload and try again")
    code = db.scalar(select(Participant.code).where(Participant.id == row.participant_id))
    assert code is not None
    for other in siblings:
        _demote_sibling(db, other, user, body.change_reason)
    write_audit(
        db,
        action="result.correct",
        object_type="section_result",
        object_id=row.id,
        user_id=user.id,
        before=before,
        after=new | {"version": version + 1, "participant_code": code},
        reason=body.change_reason,
    )
    db.commit()
    db.refresh(row)
    return _out(row, code)
