from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.auth import Db, Now, require_role
from neurotlon_server.errors import conflict, not_found
from neurotlon_server.models import GameSession, Station, User, WebSession
from neurotlon_server.results import HEARTBEAT_WINDOW
from neurotlon_server.security import hash_password, hash_token, new_token
from neurotlon_server.users import LoginTakenError, create_user, normalize_login

router = APIRouter(prefix="/api/v1", tags=["admin"])

Discipline = Literal["darts", "football", "pong"]
Superuser = Annotated[User, Depends(require_role("superuser"))]
StationManager = Annotated[User, Depends(require_role("superuser", "admin"))]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["admin", "judge", "volunteer"]
    discipline: Discipline | None = None

    @field_validator("login")
    @classmethod
    def _normalize(cls, value: str) -> str:
        value = normalize_login(value)
        if not value:
            raise ValueError("login must not be blank")
        return value

    @model_validator(mode="after")
    def _discipline_iff_volunteer(self) -> Self:
        if (self.role == "volunteer") != (self.discipline is not None):
            raise ValueError("discipline is required for volunteer and forbidden otherwise")
        return self


class UserOut(BaseModel):
    id: int
    login: str
    role: str
    discipline: str | None


class UserListItem(UserOut):
    is_active: bool


class StationListItem(BaseModel):
    id: int
    name: str
    discipline: str
    online: bool
    last_heartbeat_at: datetime | None
    last_state: str | None
    queue_length: int


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class StationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    discipline: Discipline


class StationOut(BaseModel):
    id: int
    name: str
    discipline: str
    token: str


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("user")
    return user


def _station_name_taken(db: Session, name: str) -> bool:
    return db.scalar(select(Station.id).where(Station.name == name)) is not None


def _get_active_station(db: Session, station_id: int) -> Station:
    station = db.get(Station, station_id)
    if station is None or station.archived_at is not None:
        raise not_found("station")
    return station


def _revoke_sessions(db: Session, user_id: int, now: Now) -> int:
    result = db.execute(
        update(WebSession)
        .where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


@router.get("/users")
def list_users(db: Db, actor: Superuser) -> list[UserListItem]:
    return [
        UserListItem(
            id=u.id, login=u.login, role=u.role, discipline=u.discipline, is_active=u.is_active
        )
        for u in db.scalars(select(User).order_by(User.id))
    ]


@router.post("/users", status_code=201)
def post_user(body: UserCreate, db: Db, actor: Superuser) -> UserOut:
    try:
        user = create_user(
            db,
            login=body.login,
            password=body.password,
            role=body.role,
            discipline=body.discipline,
            actor_id=actor.id,
        )
    except LoginTakenError:
        raise conflict("login already exists") from None
    return UserOut(id=user.id, login=user.login, role=user.role, discipline=user.discipline)


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: int, db: Db, now: Now, actor: Superuser) -> Response:
    user = _get_user(db, user_id)
    revoked = _revoke_sessions(db, user.id, now)
    write_audit(
        db,
        action="user.revoke_sessions",
        object_type="user",
        object_id=user.id,
        user_id=actor.id,
        after={"revoked": revoked},
    )
    db.commit()
    return Response(status_code=204)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, db: Db, now: Now, actor: Superuser) -> UserOut:
    user = _get_user(db, user_id)
    if body.is_active is False and user.id == actor.id:
        raise conflict("superuser cannot deactivate themselves")
    after: dict[str, bool | int] = {}
    if body.is_active is not None:
        user.is_active = body.is_active
        after["is_active"] = body.is_active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        after["password_changed"] = True
    # Deactivation and password change both end existing sessions.
    if body.is_active is False or body.password is not None:
        after["revoked"] = _revoke_sessions(db, user.id, now)
    write_audit(
        db,
        action="user.update",
        object_type="user",
        object_id=user.id,
        user_id=actor.id,
        after=after,
    )
    db.commit()
    return UserOut(id=user.id, login=user.login, role=user.role, discipline=user.discipline)


def _station_out(station: Station, token: str) -> StationOut:
    return StationOut(id=station.id, name=station.name, discipline=station.discipline, token=token)


def _is_online(station: Station, now: datetime) -> bool:
    beat = station.last_heartbeat_at
    return beat is not None and now - beat <= HEARTBEAT_WINDOW


@router.get("/stations")
def list_stations(db: Db, now: Now, actor: StationManager) -> list[StationListItem]:
    return [
        StationListItem(
            id=s.id,
            name=s.name,
            discipline=s.discipline,
            online=_is_online(s, now),
            last_heartbeat_at=s.last_heartbeat_at,
            last_state=s.last_state,
            queue_length=s.queue_length,
        )
        for s in db.scalars(
            select(Station).where(Station.archived_at.is_(None)).order_by(Station.id)
        )
    ]


@router.post("/stations", status_code=201)
def post_station(
    body: StationCreate, db: Db, actor: StationManager, response: Response
) -> StationOut:
    response.headers["Cache-Control"] = "no-store"
    if _station_name_taken(db, body.name):
        raise conflict("station name already exists")
    token = new_token()
    station = Station(name=body.name, discipline=body.discipline, token_hash=hash_token(token))
    db.add(station)
    try:
        db.flush()
    except IntegrityError:  # lost a race against a concurrent create
        db.rollback()
        raise conflict("station name already exists") from None
    write_audit(
        db,
        action="station.create",
        object_type="station",
        object_id=station.id,
        user_id=actor.id,
        after={"name": station.name, "discipline": station.discipline},
    )
    db.commit()
    return _station_out(station, token)


@router.post("/stations/{station_id}/rotate-token")
def rotate_token(station_id: int, db: Db, actor: StationManager, response: Response) -> StationOut:
    response.headers["Cache-Control"] = "no-store"
    station = _get_active_station(db, station_id)
    token = new_token()
    station.token_hash = hash_token(token)
    write_audit(
        db,
        action="station.rotate_token",
        object_type="station",
        object_id=station.id,
        user_id=actor.id,
    )
    db.commit()
    return _station_out(station, token)


@router.delete("/stations/{station_id}", status_code=204)
def archive_station(station_id: int, db: Db, now: Now, actor: StationManager) -> Response:
    """The audit log references stations, so a station is archived, never deleted.

    The unique name is freed by renaming and the token is replaced by an unknown one.
    """
    station = _get_active_station(db, station_id)
    open_session = db.scalar(
        select(GameSession.session_id)
        .where(GameSession.station_id == station.id, GameSession.closed_at.is_(None))
        .limit(1)
    )
    if open_session is not None:
        raise conflict("station has an unfinished session")
    after = {"name": station.name, "discipline": station.discipline}
    station.archived_at = now
    station.name = f"{station.name} [удалена {station.id}]"
    station.token_hash = hash_token(new_token())
    write_audit(
        db,
        action="station.archive",
        object_type="station",
        object_id=station.id,
        user_id=actor.id,
        after=after,
    )
    db.commit()
    return Response(status_code=204)
