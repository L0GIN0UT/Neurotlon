"""Judge and admin tools for stored results: search, correction, lock (decision 9, section 8)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, require_role
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError, conflict, forbidden, not_found
from neurotlon_server.models import Participant, SectionResult, User
from neurotlon_server.results import DisciplineName, Reason, SectionName

router = APIRouter(prefix="/api/v1/results", tags=["results"])

Judge = Annotated[User, Depends(require_role("judge", "admin", "superuser"))]

_AUDITED = ("points", "wins", "outcome", "reason", "comment")


class ResultOut(BaseModel):
    id: int
    session_id: str
    participant_code: str
    discipline: str
    section: str
    outcome: str
    points: float | None
    wins: int | None
    reason: str | None
    comment: str | None
    status: str
    source: str
    finished_at: datetime
    version: int
    voided: bool


class ResultPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    wins: int | None = Field(default=None, ge=0, le=1)
    outcome: Literal["completed", "not_completed"] | None = None
    reason: Reason | None = None
    comment: str | None = Field(default=None, max_length=200)
    change_reason: str = Field(min_length=1, max_length=200)


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


def _apply(row: SectionResult, patch: ResultPatch) -> dict[str, Any]:
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
    return new


def _check_pong_wins(db: Db, row: SectionResult, new: dict[str, Any]) -> None:
    """Match-level rules. The winner is flipped in two edits, so only "at most one" is enforced."""
    if row.discipline != "pong":
        return
    others = list(
        db.scalars(
            select(SectionResult).where(
                SectionResult.session_id == row.session_id,
                SectionResult.id != row.id,
                SectionResult.voided_at.is_(None),
            )
        )
    )
    both_done = new["outcome"] == "completed" and all(o.outcome == "completed" for o in others)
    if both_done and others and new["wins"] is None:
        raise _invalid("both players completed: wins are required")
    if (new["wins"] or 0) + sum(o.wins or 0 for o in others) > 1:
        raise _invalid("a pong match has at most one winner")


@router.get("")
def list_results(
    db: Db,
    user: Judge,
    participant: Annotated[str | None, Query()] = None,
    discipline: Annotated[DisciplineName | None, Query()] = None,
    section: Annotated[SectionName | None, Query()] = None,
    session_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[ResultOut]:
    query = (
        select(SectionResult, Participant.code)
        .join(Participant, Participant.id == SectionResult.participant_id)
        .order_by(Participant.code, SectionResult.discipline, SectionResult.section)
        .order_by(SectionResult.id)
    )
    if participant:
        code = normalize_code(participant)
        if code is None:
            return []
        query = query.where(Participant.code == code)
    if discipline:
        query = query.where(SectionResult.discipline == discipline)
    if section:
        query = query.where(SectionResult.section == section)
    if session_id:
        query = query.where(SectionResult.session_id == session_id)
    return [_out(row, code) for row, code in db.execute(query)]


@router.post("/lock")
def lock_results(db: Db, user: Judge) -> dict[str, int]:
    done = db.execute(
        update(SectionResult)
        .where(SectionResult.status == "confirmed", SectionResult.voided_at.is_(None))
        .values(status="locked")
    )
    assert isinstance(done, CursorResult)
    locked = done.rowcount
    write_audit(
        db,
        action="result.lock",
        object_type="section_result",
        object_id="bulk",
        user_id=user.id,
        after={"locked": locked},
    )
    db.commit()
    return {"locked": locked}


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
    new = _apply(row, body)
    _check_pong_wins(db, row, new)
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
