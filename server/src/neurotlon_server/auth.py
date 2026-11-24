import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.errors import ProblemError, forbidden, unauthorized
from neurotlon_server.models import Station, User, WebSession
from neurotlon_server.security import hash_password, hash_token, new_token, verify_password
from neurotlon_server.users import normalize_login

COOKIE_NAME = "neurotlon_session"
MAX_FAILED_ATTEMPTS = 5
THROTTLE_WINDOW = timedelta(minutes=5)

# Verified when the login is unknown, so response time does not reveal it.
_DUMMY_HASH = hash_password("not-a-real-password")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginThrottle:
    """Fixed window per login, held in memory (single-process server).

    The attempt is counted before the password is checked, under a lock, so parallel
    requests cannot get more than MAX_FAILED_ATTEMPTS guesses per window.
    """

    MAX_ENTRIES = 1024

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, tuple[datetime, int]] = {}

    def try_attempt(self, login: str) -> bool:
        """Count an attempt; False means the login is locked."""
        with self._lock:
            now = self._clock()
            self._state = {
                key: entry for key, entry in self._state.items() if now - entry[0] < THROTTLE_WINDOW
            }
            entry = self._state.get(login)
            if entry is not None and entry[1] >= MAX_FAILED_ATTEMPTS:
                return False
            self._state[login] = (now, 1) if entry is None else (entry[0], entry[1] + 1)
            while len(self._state) > self.MAX_ENTRIES:
                del self._state[next(iter(self._state))]  # dicts keep insertion order
            return True

    def reset(self, login: str) -> None:
        with self._lock:
            self._state.pop(login, None)


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


Db = Annotated[Session, Depends(get_db)]


def get_now(request: Request) -> datetime:
    now: datetime = request.app.state.clock()
    return now


Now = Annotated[datetime, Depends(get_now)]


def current_web_session(
    db: Db, now: Now, token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None
) -> WebSession:
    if not token:
        raise unauthorized()
    web_session = db.scalar(select(WebSession).where(WebSession.token_hash == hash_token(token)))
    if web_session is None or web_session.revoked_at is not None or web_session.expires_at <= now:
        raise unauthorized()
    return web_session


def current_user(db: Db, web_session: Annotated[WebSession, Depends(current_web_session)]) -> User:
    user = db.get(User, web_session.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return dependency


def current_station(db: Db, authorization: Annotated[str | None, Header()] = None) -> Station:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized()
    station = db.scalar(select(Station).where(Station.token_hash == hash_token(token)))
    if station is None or station.archived_at is not None:
        raise unauthorized()
    return station


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("login")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_login(value)


class MeResponse(BaseModel):
    login: str
    role: str
    discipline: str | None


@router.post("/login", status_code=204)
def login(body: LoginRequest, request: Request, db: Db, now: Now) -> Response:
    throttle: LoginThrottle = request.app.state.throttle
    if not throttle.try_attempt(body.login):
        raise ProblemError(
            429, "too_many_attempts", "Too many attempts", "Try again in a few minutes"
        )
    user = db.scalar(select(User).where(User.login == body.login))
    password_ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not user.is_active or not password_ok:
        raise unauthorized()
    throttle.reset(body.login)
    ttl: int = request.app.state.settings.session_ttl_seconds
    token = new_token()
    db.add(
        WebSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    db.commit()
    out = Response(status_code=204, headers={"Cache-Control": "no-store"})
    out.set_cookie(
        COOKIE_NAME, token, max_age=ttl, path="/", httponly=True, secure=True, samesite="strict"
    )
    return out


@router.post("/logout", status_code=204)
def logout(
    db: Db, now: Now, web_session: Annotated[WebSession, Depends(current_web_session)]
) -> Response:
    web_session.revoked_at = now
    db.commit()
    out = Response(status_code=204)
    out.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")
    return out


@router.get("/me")
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(login=user.login, role=user.role, discipline=user.discipline)
