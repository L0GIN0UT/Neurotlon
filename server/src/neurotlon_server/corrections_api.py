"""Volunteer undo (30 s) and correction requests to the admin afterwards."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.errors import conflict, forbidden, not_found
from neurotlon_server.models import CorrectionRequest, GameSession, Participant, SectionResult, User

UNDO_WINDOW = timedelta(seconds=30)

router = APIRouter(prefix="/api/v1", tags=["corrections"])

Volunteer = Annotated[User, Depends(require_role("volunteer"))]
Resolver = Annotated[User, Depends(require_role("admin", "superuser"))]
AnyStaff = Annotated[User, Depends(require_role("volunteer", "admin", "superuser"))]


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    comment: str = Field(min_length=1, max_length=200)


class CorrectionOut(BaseModel):
    id: int
    session_id: str
    participant_codes: list[str]
    comment: str
    created_at: datetime
    status: Literal["open", "done"]
    resolved_at: datetime | None


def _own_session(db: Db, user: User, session_id: str) -> GameSession:
    session = db.get(GameSession, session_id)
    if session is None:
        raise not_found("Session not found")
    if session.user_id != user.id:
        raise forbidden()
    return session


def _out(db: Db, row: CorrectionRequest) -> CorrectionOut:
    codes = db.scalars(
        select(Participant.code)
        .join(SectionResult, SectionResult.participant_id == Participant.id)
        .where(SectionResult.session_id == row.session_id)
    )
    return CorrectionOut(
        id=row.id,
        session_id=row.session_id,
        participant_codes=sorted(set(codes)),
        comment=row.comment,
        created_at=row.created_at,
        status="done" if row.status == "done" else "open",
        resolved_at=row.resolved_at,
    )


@router.post("/results/{session_id}/undo", status_code=204)
def undo_result(session_id: str, db: Db, now: Now, user: Volunteer) -> Response:
    session = _own_session(db, user, session_id)
    if session.closed_at is None:
        raise not_found("Result not found")
    if now - session.started_at > UNDO_WINDOW:
        raise conflict("Undo window of 30 seconds has passed")
    rows = list(
        db.scalars(
            select(SectionResult).where(
                SectionResult.session_id == session_id, SectionResult.voided_at.is_(None)
            )
        )
    )
    if not rows:
        raise conflict("Result is already undone")
    if any(r.status == "locked" for r in rows):
        raise conflict("Result is locked")
    before = [
        {
            "id": r.id,
            "status": r.status,
            "outcome": r.outcome,
            "points": r.points,
            "wins": r.wins,
        }
        for r in rows
    ]
    # Guarded update: of two parallel undos only one voids the rows.
    updated = db.execute(
        update(SectionResult)
        .where(
            SectionResult.id.in_([r.id for r in rows]),
            SectionResult.voided_at.is_(None),
            SectionResult.status != "locked",
        )
        .values(voided_at=now, voided_by=user.id, void_reason="undo")
    )
    assert isinstance(updated, CursorResult)
    if updated.rowcount != len(rows):
        db.rollback()
        raise conflict("Result changed concurrently")
    write_audit(
        db,
        action="result.undo",
        object_type="game_session",
        object_id=session_id,
        user_id=user.id,
        before={"rows": before},
        after={"voided": [r.id for r in rows]},
        reason="undo",
    )
    db.commit()
    return Response(status_code=204)


@router.post("/corrections", status_code=201)
def create_correction(body: CorrectionIn, db: Db, now: Now, user: Volunteer) -> CorrectionOut:
    _own_session(db, user, body.session_id)
    rows = list(
        db.scalars(
            select(SectionResult.voided_at).where(SectionResult.session_id == body.session_id)
        )
    )
    if not rows or all(v is not None for v in rows):
        raise conflict("Result is voided or missing")
    if db.scalars(
        select(CorrectionRequest.id).where(
            CorrectionRequest.session_id == body.session_id, CorrectionRequest.status == "open"
        )
    ).first():
        raise conflict("An open correction request already exists")
    row = CorrectionRequest(
        session_id=body.session_id, user_id=user.id, comment=body.comment, created_at=now
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        action="correction.create",
        object_type="correction_request",
        object_id=row.id,
        user_id=user.id,
        after={"session_id": body.session_id, "comment": body.comment},
    )
    db.commit()
    return _out(db, row)


@router.get("/corrections")
def list_corrections(
    db: Db, user: AnyStaff, status: Annotated[Literal["open", "done"], Query()] = "open"
) -> list[CorrectionOut]:
    query = (
        select(CorrectionRequest)
        .where(CorrectionRequest.status == status)
        .order_by(CorrectionRequest.id)
    )
    if user.role == "volunteer":
        query = query.where(CorrectionRequest.user_id == user.id)
    return [_out(db, row) for row in db.scalars(query)]


@router.post("/corrections/{correction_id}/done")
def resolve_correction(correction_id: int, db: Db, now: Now, user: Resolver) -> CorrectionOut:
    row = db.get(CorrectionRequest, correction_id)
    if row is None:
        raise not_found("Correction request not found")
    if row.status == "done":
        raise conflict("Correction request is already done")
    row.status = "done"
    row.resolved_by = user.id
    row.resolved_at = now
    write_audit(
        db,
        action="correction.done",
        object_type="correction_request",
        object_id=row.id,
        user_id=user.id,
        before={"status": "open"},
        after={"status": "done"},
    )
    db.commit()
    return _out(db, row)
