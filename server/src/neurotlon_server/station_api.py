from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.auth import Db, Now
from neurotlon_server.caller import Anyone, StationOnly
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError, unauthorized
from neurotlon_server.models import (
    Discipline,
    GameSession,
    Participant,
    ParticipantPhoto,
    Station,
    Team,
)
from neurotlon_server.participants import photo_response, photo_version
from neurotlon_server.photo_access import PhotoAccess
from neurotlon_server.results import (
    DisciplineName,
    IssueCode,
    ParticipantCode,
    ResultReceipt,
    ResultSubmission,
    SectionName,
    add_session_participants,
    are_opponents,
    find_participants,
    is_busy,
    not_opponents,
    participant_issues,
    session_conflict,
    session_participant_codes,
    submit_result,
)

router = APIRouter(prefix="/api/v1", tags=["station"])


class ConfigOut(BaseModel):
    discipline: DisciplineName
    section: SectionName
    duration_s: int
    max_points: int | None


class TeamOut(BaseModel):
    number: int
    name: str
    color: str


class EligibilityOut(BaseModel):
    code: str
    display_name: str | None
    team: TeamOut | None
    issues: list[IssueCode]
    has_photo: bool
    photo_version: int | None


class SessionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    discipline: DisciplineName
    participant_codes: list[ParticipantCode] = Field(min_length=1, max_length=2)

    @field_validator("participant_codes")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("participant codes must be unique")
        return value


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["idle", "confirming", "calibrating", "playing", "sending"]
    session_id: UUID | None = None
    queue_length: int = Field(ge=0, le=100000)
    sensors: dict[
        Literal["eeg", "emg", "emg_left", "emg_right"],
        Literal["connected", "connecting", "disconnected", "emulated"],
    ] = Field(max_length=4)


def _find_participant(db: Session, raw_code: str) -> Participant | None:
    normalized = normalize_code(raw_code)
    if not normalized:
        return None
    return db.scalar(select(Participant).where(Participant.code == normalized))


def _known_participant(db: Session, raw_code: str) -> Participant:
    participant = _find_participant(db, raw_code)
    if participant is None:
        raise ProblemError(
            404, "unknown_participant", "Unknown participant", "No participant with this ID"
        )
    return participant


@router.get("/me/config")
def get_config(db: Db, caller: Anyone) -> ConfigOut:
    discipline = db.get(Discipline, caller.discipline)
    assert discipline is not None
    duration = (
        discipline.game_duration_s if caller.kind == "station" else discipline.physical_duration_s
    )
    return ConfigOut.model_validate(
        {
            "discipline": caller.discipline,
            "section": caller.section,
            "duration_s": duration,
            "max_points": None if caller.discipline == "pong" else discipline.max_section_points,
        }
    )


@router.get("/participants/{code}/eligibility")
def get_eligibility(
    code: str,
    discipline: Annotated[DisciplineName, Query()],
    section: Annotated[SectionName, Query()],
    db: Db,
    now: Now,
    caller: Anyone,
    request: Request,
    opponent: Annotated[str | None, Query(alias="with", max_length=32)] = None,
) -> EligibilityOut:
    caller.check(discipline, section)
    participant = _known_participant(db, code)
    issues = participant_issues(db, participant, discipline, section, now, caller.station_id)
    if discipline == "pong" and opponent is not None:
        other = _find_participant(db, opponent)
        # Unknown second code or a player outside the grid: no pair, so not an opponent.
        if other is None or not are_opponents(db, participant, other):
            issues.append("not_opponents")
    if caller.station_id is not None:  # the station may fetch this photo for a short while
        access: PhotoAccess = request.app.state.photo_access
        access.grant(caller.station_id, participant.code, now)
    photo_updated_at = db.scalar(
        select(ParticipantPhoto.updated_at).where(ParticipantPhoto.participant_id == participant.id)
    )
    team = db.get(Team, participant.team_id) if participant.team_id is not None else None
    return EligibilityOut(
        code=participant.code,
        display_name=participant.display_name,
        team=TeamOut(number=team.number, name=team.name, color=team.color) if team else None,
        issues=issues,
        has_photo=photo_updated_at is not None,
        photo_version=None if photo_updated_at is None else photo_version(photo_updated_at),
    )


@router.get("/station/participants/{code}/photo")
def get_station_photo(
    code: str, db: Db, now: Now, caller: StationOnly, request: Request
) -> Response:
    """Photo of a participant the station has just checked; by code only, no listing.

    A stolen station token cannot enumerate photos: without a fresh eligibility request of
    this station for this code the answer is the same 404 as for a missing photo.
    """
    access: PhotoAccess = request.app.state.photo_access
    assert caller.station_id is not None
    if not access.try_request(caller.station_id, now):
        raise ProblemError(
            429, "too_many_requests", "Too many requests", "Too many photo requests, wait a minute"
        )
    participant = _find_participant(db, code)
    if participant is None or not access.allowed(caller.station_id, participant.code, now):
        raise ProblemError(404, "no_photo", "The participant has no photo")
    return photo_response(db, participant)


@router.post("/sessions", status_code=201)
def start_session(body: SessionStart, db: Db, now: Now, caller: StationOnly) -> Response:
    caller.check(body.discipline)
    session_id = str(body.session_id)
    people = find_participants(db, body.participant_codes)
    if db.get(GameSession, session_id) is not None:
        return _replay_start(db, caller.station_id, body, set(people))
    if body.discipline == "pong":
        if len(people) != 2:
            raise ProblemError(
                422, "invalid_request", "Invalid request", "Pong needs exactly two participants"
            )
        first, second = people.values()
        if not are_opponents(db, first, second):
            raise not_opponents()
    if any(is_busy(db, p, now, caller.station_id) for p in people.values()):
        raise ProblemError(
            409, "busy_on_other_station", "Busy", "Participant is playing on another station"
        )
    db.add(
        GameSession(
            session_id=session_id,
            station_id=caller.station_id,
            discipline=body.discipline,
            started_at=now,
        )
    )
    try:
        db.flush()
        # The write lock is held now: an archive committed since authentication is visible.
        archived = db.scalar(select(Station.archived_at).where(Station.id == caller.station_id))
        if archived is not None:
            db.rollback()
            raise unauthorized()
        add_session_participants(db, session_id, people)
        db.commit()
    except IntegrityError:  # parallel retry of the same session_id
        db.rollback()
        if db.get(GameSession, session_id) is None:
            raise
        return _replay_start(db, caller.station_id, body, set(people))
    return Response(status_code=201)


def _replay_start(
    db: Session, station_id: int | None, body: SessionStart, codes: set[str]
) -> Response:
    session_id = str(body.session_id)
    existing = db.get(GameSession, session_id)
    if (
        existing is None
        or existing.discipline != body.discipline
        or existing.station_id != station_id
        or session_participant_codes(db, session_id) != codes
    ):
        raise session_conflict()
    return Response(status_code=200)


@router.post("/results", status_code=201)
def post_result(
    body: ResultSubmission, db: Db, now: Now, caller: Anyone, response: Response
) -> ResultReceipt:
    try:
        receipt, created = submit_result(db, caller, body, now)
        db.commit()
    except IntegrityError:  # parallel duplicate of the same session_id: replay it
        db.rollback()
        if db.get(GameSession, str(body.session_id)) is None:
            raise  # not a duplicate: do not mask a real failure
        receipt, created = submit_result(db, caller, body, now)
        db.commit()
    if not created:
        response.status_code = 200
    return receipt


@router.post("/stations/me/heartbeat", status_code=204)
def post_heartbeat(body: Heartbeat, db: Db, now: Now, caller: StationOnly) -> Response:
    station = db.get(Station, caller.station_id)
    assert station is not None
    station.last_heartbeat_at = now
    station.last_state = body.state
    station.queue_length = body.queue_length
    db.commit()
    return Response(status_code=204)
