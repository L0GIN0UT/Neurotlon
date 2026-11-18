from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.badges import build_badges_pdf
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError
from neurotlon_server.models import Participant, Team, User

router = APIRouter(prefix="/api/v1/participants", tags=["participants"])

Manager = Annotated[User, Depends(require_role("superuser", "admin"))]
Viewer = Annotated[User, Depends(require_role("superuser", "admin", "judge"))]

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=24)]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=99)


class _NameModel(BaseModel):
    @field_validator("display_name", check_fields=False)
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value or None


class CheckInRequest(_NameModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["general", "ovz"]
    display_name: DisplayName | None = None


class PatchRequest(_NameModel):
    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None


def unknown_participant() -> ProblemError:
    return ProblemError(404, "unknown_participant", "Unknown participant")


def _get_participant(db: Session, raw_code: str) -> Participant:
    code = normalize_code(raw_code)
    participant = (
        None if code is None else db.scalar(select(Participant).where(Participant.code == code))
    )
    if participant is None:
        raise unknown_participant()
    return participant


def _out(participant: Participant, team: Team | None, with_category: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": participant.code,
        "display_name": participant.display_name,
        "checked_in": participant.checked_in_at is not None,
        "checked_in_at": participant.checked_in_at,
        "team": None
        if team is None
        else {"number": team.number, "name": team.name, "color": team.color},
    }
    if with_category:
        out["category"] = participant.category
    return out


def _out_one(db: Session, participant: Participant) -> dict[str, Any]:
    team = None if participant.team_id is None else db.get(Team, participant.team_id)
    return _out(participant, team, with_category=True)


@router.post("/generate")
def generate(body: GenerateRequest, db: Db, actor: Manager) -> dict[str, Any]:
    created: list[str] = []
    for n in range(1, body.count + 1):
        code = f"NT{n:02d}"
        # DO NOTHING: a concurrent generate cannot fail with a unique violation.
        result = db.execute(
            sqlite_insert(Participant)
            .values(code=code)
            .on_conflict_do_nothing(index_elements=["code"])
        )
        if result.rowcount:  # type: ignore[attr-defined]
            created.append(code)
    if created:
        write_audit(
            db,
            action="participant.generate",
            object_type="participant",
            object_id="bulk",
            user_id=actor.id,
            after={"created": created},
        )
    db.commit()
    total = db.scalar(select(func.count()).select_from(Participant)) or 0
    return {"created": created, "total": total}


@router.get("")
def list_participants(db: Db, user: Viewer) -> list[dict[str, Any]]:
    with_category = user.role in ("superuser", "admin")
    rows = db.execute(
        select(Participant, Team)
        .outerjoin(Team, Participant.team_id == Team.id)
        .order_by(Participant.code)
    )
    return [_out(p, t, with_category) for p, t in rows]


@router.get("/badges.pdf")
def badges_pdf(db: Db, actor: Manager, codes: Annotated[str | None, Query()] = None) -> Response:
    query = select(Participant.code).order_by(Participant.code)
    wanted: list[str] = []
    if codes is not None:
        for raw in codes.split(","):
            code = normalize_code(raw)
            if code is None:
                raise unknown_participant()
            if code not in wanted:
                wanted.append(code)
        query = query.where(Participant.code.in_(wanted))
    found = list(db.scalars(query))
    if not found or (codes is not None and len(found) != len(wanted)):
        raise unknown_participant()
    return Response(
        build_badges_pdf(found),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="badges.pdf"'},
    )


@router.post("/{code}/check-in")
def check_in(code: str, body: CheckInRequest, db: Db, now: Now, actor: Manager) -> dict[str, Any]:
    participant = _get_participant(db, code)
    participant.category = body.category
    participant.display_name = body.display_name
    participant.checked_in_at = now
    # The category is deliberately absent from the audit record.
    write_audit(
        db,
        action="participant.check_in",
        object_type="participant",
        object_id=participant.id,
        user_id=actor.id,
        after={"checked_in": True, "category_set": True, "display_name": body.display_name},
    )
    db.commit()
    return _out_one(db, participant)


@router.delete("/{code}/check-in")
def undo_check_in(code: str, db: Db, actor: Manager) -> dict[str, Any]:
    participant = _get_participant(db, code)
    participant.category = None
    participant.checked_in_at = None
    write_audit(
        db,
        action="participant.undo_check_in",
        object_type="participant",
        object_id=participant.id,
        user_id=actor.id,
        after={"checked_in": False, "category_set": False},
    )
    db.commit()
    return _out_one(db, participant)


@router.patch("/{code}")
def patch_participant(code: str, body: PatchRequest, db: Db, actor: Manager) -> dict[str, Any]:
    participant = _get_participant(db, code)
    participant.display_name = body.display_name
    write_audit(
        db,
        action="participant.update",
        object_type="participant",
        object_id=participant.id,
        user_id=actor.id,
        after={"display_name": body.display_name},
    )
    db.commit()
    return _out_one(db, participant)
