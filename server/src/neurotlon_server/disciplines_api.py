"""Discipline settings changed during the event (decision 16)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, require_role
from neurotlon_server.errors import ProblemError, not_found
from neurotlon_server.models import Discipline, User

router = APIRouter(prefix="/api/v1/disciplines", tags=["disciplines"])

Editor = Annotated[User, Depends(require_role("superuser", "admin", "judge"))]


class DisciplinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_duration_s: int | None = Field(default=None, ge=10, le=3600)
    physical_duration_s: int | None = Field(default=None, ge=10, le=3600)
    win_points: int | None = Field(default=None, ge=0, le=1000)


class DisciplineOut(BaseModel):
    code: str
    game_duration_s: int
    physical_duration_s: int
    win_points: int


def _out(d: Discipline) -> DisciplineOut:
    return DisciplineOut(
        code=d.code,
        game_duration_s=d.game_duration_s,
        physical_duration_s=d.physical_duration_s,
        win_points=d.win_points,
    )


@router.patch("/{code}")
def patch_discipline(code: str, body: DisciplinePatch, db: Db, user: Editor) -> DisciplineOut:
    discipline = db.get(Discipline, code)
    if discipline is None:
        raise not_found("Discipline not found")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ProblemError(422, "invalid_request", "Invalid request", "Nothing to change")
    before = {key: getattr(discipline, key) for key in changes}
    for key, value in changes.items():
        setattr(discipline, key, value)
    write_audit(
        db,
        action="discipline.update",
        object_type="discipline",
        object_id=code,
        user_id=user.id,
        before=before,
        after=changes,
    )
    db.commit()
    return _out(discipline)
