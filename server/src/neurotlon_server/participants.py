from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.badges import build_badges_pdf
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError
from neurotlon_server.models import Participant, ParticipantPhoto, Team, User

router = APIRouter(prefix="/api/v1/participants", tags=["participants"])

Manager = Annotated[User, Depends(require_role("superuser", "admin"))]
Viewer = Annotated[User, Depends(require_role("superuser", "admin"))]

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


def _photo_version(updated_at: datetime) -> int:
    """Cache-busting stamp: milliseconds, so a quick replacement still changes it."""
    return int(updated_at.timestamp() * 1000)


def _out(
    participant: Participant,
    team: Team | None,
    with_category: bool,
    photo_updated_at: datetime | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": participant.code,
        "display_name": participant.display_name,
        "checked_in": participant.checked_in_at is not None,
        "checked_in_at": participant.checked_in_at,
        "team": None
        if team is None
        else {"number": team.number, "name": team.name, "color": team.color},
        "has_photo": photo_updated_at is not None,
        "photo_version": None if photo_updated_at is None else _photo_version(photo_updated_at),
    }
    if with_category:
        out["category"] = participant.category
    return out


def _out_one(db: Session, participant: Participant) -> dict[str, Any]:
    team = None if participant.team_id is None else db.get(Team, participant.team_id)
    photo_updated_at = db.scalar(
        select(ParticipantPhoto.updated_at).where(ParticipantPhoto.participant_id == participant.id)
    )
    return _out(participant, team, with_category=True, photo_updated_at=photo_updated_at)


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
    # One query for all photo stamps; the BLOB column is never loaded here.
    stamps = {
        pid: updated_at
        for pid, updated_at in db.execute(
            select(ParticipantPhoto.participant_id, ParticipantPhoto.updated_at)
        )
    }
    return [_out(p, t, with_category, stamps.get(p.id)) for p, t in rows]


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


MAX_PHOTO_BYTES = 400 * 1024
JPEG_START = b"\xff\xd8\xff"
JPEG_END = b"\xff\xd9"


def _photo_too_large() -> ProblemError:
    return ProblemError(413, "photo_too_large", "Photo is larger than 400 KB")


async def _read_photo(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_PHOTO_BYTES:
        raise _photo_too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_PHOTO_BYTES:
            raise _photo_too_large()
    return bytes(body)


PhotoBody = Annotated[bytes, Depends(_read_photo)]


def _photo_headers() -> dict[str, str]:
    return {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.put("/{code}/photo", status_code=204)
def set_photo(code: str, db: Db, now: Now, actor: Manager, content: PhotoBody) -> Response:
    if not (content.startswith(JPEG_START) and content.endswith(JPEG_END)):
        raise ProblemError(422, "invalid_photo", "The photo must be a complete JPEG")
    participant = _get_participant(db, code)
    photo = db.get(ParticipantPhoto, participant.id)
    if photo is None:
        db.add(ParticipantPhoto(participant_id=participant.id, content=content, updated_at=now))
    else:
        photo.content = content
        photo.updated_at = now
    # Only the size is audited, never the picture.
    write_audit(
        db,
        action="participant.photo_set",
        object_type="participant",
        object_id=participant.id,
        user_id=actor.id,
        after={"code": participant.code, "size": len(content)},
    )
    db.commit()
    return Response(status_code=204, headers=_photo_headers())


@router.delete("/{code}/photo", status_code=204)
def clear_photo(code: str, db: Db, actor: Manager) -> Response:
    participant = _get_participant(db, code)
    photo = db.get(ParticipantPhoto, participant.id)
    if photo is None:
        raise ProblemError(404, "no_photo", "The participant has no photo")
    db.delete(photo)
    write_audit(
        db,
        action="participant.photo_clear",
        object_type="participant",
        object_id=participant.id,
        user_id=actor.id,
        after={"code": participant.code},
    )
    db.commit()
    return Response(status_code=204, headers=_photo_headers())


@router.get("/{code}/photo")
def get_photo(code: str, db: Db, actor: Manager) -> Response:
    participant = _get_participant(db, code)
    photo = db.get(ParticipantPhoto, participant.id)
    if photo is None:
        raise ProblemError(404, "no_photo", "The participant has no photo")
    return Response(photo.content, media_type="image/jpeg", headers=_photo_headers())
