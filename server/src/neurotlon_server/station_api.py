from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from neurotlon_server.auth import Db, Now
from neurotlon_server.caller import Anyone, StationOnly
from neurotlon_server.codes import normalize_code
from neurotlon_server.errors import ProblemError
from neurotlon_server.models import Discipline, GameSession, Participant, Station, Team
from neurotlon_server.results import (
    DisciplineName,
    IssueCode,
    ParticipantCode,
    ResultReceipt,
    ResultSubmission,
    SectionName,
    add_session_participants,
    find_participants,
    is_busy,
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


class TeamOut(BaseModel):
    number: int
    name: str
    color: str


class EligibilityOut(BaseModel):
    code: str
    display_name: str | None
    team: TeamOut | None
    issues: list[IssueCode]


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


@router.get("/me/config")
def get_config(db: Db, caller: Anyone) -> ConfigOut:
    discipline = db.get(Discipline, caller.discipline)
    assert discipline is not None
    duration = (
        discipline.game_duration_s if caller.kind == "station" else discipline.physical_duration_s
    )
    return ConfigOut.model_validate(
        {"discipline": caller.discipline, "section": caller.section, "duration_s": duration}
    )


@router.get("/participants/{code}/eligibility")
def get_eligibility(
    code: str,
    discipline: Annotated[DisciplineName, Query()],
    section: Annotated[SectionName, Query()],
    db: Db,
    now: Now,
    caller: Anyone,
) -> EligibilityOut:
    caller.check(discipline, section)
    normalized = normalize_code(code)
    participant = (
        db.scalar(select(Participant).where(Participant.code == normalized)) if normalized else None
    )
    if participant is None:
        raise ProblemError(
            404, "unknown_participant", "Unknown participant", "No participant with this ID"
        )
    team = db.get(Team, participant.team_id) if participant.team_id is not None else None
    return EligibilityOut(
        code=participant.code,
        display_name=participant.display_name,
        team=TeamOut(number=team.number, name=team.name, color=team.color) if team else None,
        issues=participant_issues(db, participant, discipline, section, now, caller.station_id),
    )


@router.post("/sessions", status_code=201)
def start_session(body: SessionStart, db: Db, now: Now, caller: StationOnly) -> Response:
    caller.check(body.discipline)
    session_id = str(body.session_id)
    people = find_participants(db, body.participant_codes)
    if db.get(GameSession, session_id) is not None:
        return _replay_start(db, caller.station_id, body, set(people))
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
