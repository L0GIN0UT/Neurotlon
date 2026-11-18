import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.caller import Caller
from neurotlon_server.errors import ProblemError
from neurotlon_server.models import (
    Discipline,
    GameSession,
    Pair,
    Participant,
    SectionResult,
    Station,
    session_participant,
)

HEARTBEAT_WINDOW = timedelta(seconds=30)
# A session this much longer than the game is abandoned: a station that lost the game
# process keeps sending heartbeats, and must not hold participants forever.
SESSION_SLACK = timedelta(seconds=300)
FINISHED_AT_TOLERANCE = timedelta(days=2)

ParticipantCode = Annotated[str, StringConstraints(pattern=r"^NT(0[1-9]|[1-9][0-9])$")]
DisciplineName = Literal["darts", "football", "pong"]
SectionName = Literal["bci", "physical"]
IssueCode = Literal[
    "not_checked_in", "already_completed", "busy_on_other_station", "no_pair_assigned"
]
Reason = Literal["participant_refused", "health", "equipment", "no_show", "other"]


class ResultEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_code: ParticipantCode
    outcome: Literal["completed", "not_completed"]
    points: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    wins: int | None = Field(default=None, ge=0, le=1)
    reason: Reason | None = None
    comment: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _fields_match_outcome(self) -> Self:
        if self.outcome == "completed":
            if self.points is None or self.reason is not None:
                raise ValueError("completed needs points and no reason")
        elif self.reason is None or self.points is not None or self.wins is not None:
            raise ValueError("not_completed needs reason and no points or wins")
        return self


class ResultSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    discipline: DisciplineName
    section: SectionName
    finished_at: AwareDatetime
    entries: list[ResultEntry] = Field(min_length=1, max_length=2)


class ReceiptResult(BaseModel):
    id: int
    participant_code: str
    status: str


class ReceiptWarning(BaseModel):
    participant_code: str
    code: IssueCode


class ResultReceipt(BaseModel):
    session_id: str
    results: list[ReceiptResult]
    warnings: list[ReceiptWarning]


def session_conflict() -> ProblemError:
    return ProblemError(
        409, "session_conflict", "Session conflict", "This session_id was used with other data"
    )


def payload_hash(body: ResultSubmission) -> str:
    data = body.model_dump(mode="json", exclude={"finished_at"})
    data["finished_at"] = body.finished_at.astimezone(UTC).isoformat()
    data["entries"] = sorted(data["entries"], key=lambda e: e["participant_code"])
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def find_participants(db: Session, codes: list[str]) -> dict[str, Participant]:
    found = {p.code: p for p in db.scalars(select(Participant).where(Participant.code.in_(codes)))}
    if len(found) != len(set(codes)):
        raise ProblemError(
            422, "unknown_participant", "Unknown participant", "No participant with this ID"
        )
    return {code: found[code] for code in codes}


def session_participant_codes(db: Session, session_id: str) -> set[str]:
    return set(
        db.scalars(
            select(Participant.code)
            .join(session_participant, session_participant.c.participant_id == Participant.id)
            .where(session_participant.c.session_id == session_id)
        )
    )


def add_session_participants(db: Session, session_id: str, people: dict[str, Participant]) -> None:
    for person in people.values():
        db.execute(
            session_participant.insert().values(session_id=session_id, participant_id=person.id)
        )


def pair_of(db: Session, participant: Participant) -> Pair | None:
    # By design a participant belongs to at most one pair (the pair stays together for the
    # whole route, a decision from the concept), so the first match is the only one.
    return db.scalars(
        select(Pair)
        .where(
            or_(Pair.participant_a_id == participant.id, Pair.participant_b_id == participant.id)
        )
        .order_by(Pair.id)
    ).first()


def is_busy(
    db: Session,
    participant: Participant,
    now: datetime,
    own_station_id: int | None,
    exclude_session: str | None = None,
) -> bool:
    """Open session on another station that still sends heartbeats."""
    query = (
        select(GameSession.started_at, Discipline.game_duration_s)
        .join(session_participant, session_participant.c.session_id == GameSession.session_id)
        .join(Station, Station.id == GameSession.station_id)
        .join(Discipline, Discipline.code == GameSession.discipline)
        .where(
            session_participant.c.participant_id == participant.id,
            GameSession.closed_at.is_(None),
            Station.last_heartbeat_at >= now - HEARTBEAT_WINDOW,
        )
    )
    if own_station_id is not None:
        query = query.where(GameSession.station_id != own_station_id)
    if exclude_session is not None:
        query = query.where(GameSession.session_id != exclude_session)
    return any(
        now - started_at <= timedelta(seconds=duration_s) + SESSION_SLACK
        for started_at, duration_s in db.execute(query)
    )


def participant_issues(
    db: Session,
    participant: Participant,
    discipline: str,
    section: str,
    now: datetime,
    own_station_id: int | None,
    exclude_session: str | None = None,
) -> list[IssueCode]:
    issues: list[IssueCode] = []
    if participant.checked_in_at is None:
        issues.append("not_checked_in")
    done = db.scalars(
        select(SectionResult.id).where(
            SectionResult.participant_id == participant.id,
            SectionResult.discipline == discipline,
            SectionResult.section == section,
            SectionResult.voided_at.is_(None),
        )
    ).first()
    if done is not None:
        issues.append("already_completed")
    if is_busy(db, participant, now, own_station_id, exclude_session):
        issues.append("busy_on_other_station")
    if pair_of(db, participant) is None:
        issues.append("no_pair_assigned")
    return issues


def points_over_limit(discipline: str, points: float | None, limit: int) -> str | None:
    """Message when darts/football points exceed the discipline limit; pong is not limited."""
    if discipline == "pong" or points is None or points <= limit:
        return None
    return f"points must not exceed {limit} for {discipline}"


def _validate_entries(db: Session, body: ResultSubmission) -> None:
    expected = 2 if body.discipline == "pong" else 1
    distinct = {e.participant_code for e in body.entries}
    if len(body.entries) != expected or len(distinct) != expected:
        raise ProblemError(
            422,
            "invalid_entries",
            "Invalid entries",
            f"{body.discipline} needs exactly {expected} distinct participant(s)",
        )
    wins = [e.wins for e in body.entries]
    if body.discipline != "pong":
        valid = all(w is None for w in wins)
    elif all(e.outcome == "completed" for e in body.entries):
        valid = None not in wins and sum(w or 0 for w in wins) == 1
    else:
        valid = True
    if not valid:
        raise ProblemError(
            422, "invalid_entries", "Invalid entries", "Wins do not match the discipline rules"
        )
    discipline = db.get(Discipline, body.discipline)
    assert discipline is not None
    for entry in body.entries:
        message = points_over_limit(body.discipline, entry.points, discipline.max_section_points)
        if message:
            raise ProblemError(422, "invalid_entries", "Invalid entries", message)


def _check_finished_at(body: ResultSubmission, now: datetime) -> datetime:
    try:
        finished = body.finished_at.astimezone(UTC)
    except (OverflowError, ValueError):
        finished = None
    if finished is None or abs(finished - now) > FINISHED_AT_TOLERANCE:
        raise ProblemError(
            422, "invalid_request", "Invalid request", "finished_at is too far from server time"
        )
    return finished


def _receipt(db: Session, session: GameSession) -> ResultReceipt:
    rows = db.execute(
        select(SectionResult.id, Participant.code, SectionResult.status)
        .join(Participant, Participant.id == SectionResult.participant_id)
        .where(SectionResult.session_id == session.session_id)
        .order_by(SectionResult.id)
    )
    return ResultReceipt(
        session_id=session.session_id,
        results=[ReceiptResult(id=i, participant_code=c, status=s) for i, c, s in rows],
        warnings=[ReceiptWarning.model_validate(w) for w in session.warnings or []],
    )


def _audit_after(body: ResultSubmission, warnings: list[dict[str, str]]) -> dict[str, object]:
    return {
        "discipline": body.discipline,
        "section": body.section,
        "entries": [
            {
                "participant_code": e.participant_code,
                "outcome": e.outcome,
                "points": e.points,
                "wins": e.wins,
                "reason": e.reason,
            }
            for e in body.entries
        ],
        "warnings": warnings,
    }


def submit_result(
    db: Session, caller: Caller, body: ResultSubmission, now: datetime
) -> tuple[ResultReceipt, bool]:
    """Store a result; returns the receipt and whether anything was newly written."""
    caller.check(body.discipline, body.section)
    _validate_entries(db, body)
    _check_finished_at(body, now)
    session_id = str(body.session_id)
    digest = payload_hash(body)
    people = find_participants(db, [e.participant_code for e in body.entries])

    session = db.get(GameSession, session_id)
    if session is None:
        session = GameSession(
            session_id=session_id,
            station_id=caller.station_id,
            user_id=caller.user_id,
            discipline=body.discipline,
            started_at=now,
        )
        db.add(session)
        db.flush()
        add_session_participants(db, session_id, people)
    elif session.payload_hash is not None:
        if session.payload_hash != digest:
            raise session_conflict()
        if session.station_id != caller.station_id or session.user_id != caller.user_id:
            raise session_conflict()
        voided = db.scalars(
            select(SectionResult.voided_at).where(SectionResult.session_id == session_id)
        ).all()
        if voided and all(v is not None for v in voided):
            raise ProblemError(
                409, "result_voided", "Result voided", "This session was undone, enter it again"
            )
        return _receipt(db, session), False
    elif (
        session.discipline != body.discipline
        or session.station_id != caller.station_id
        or session_participant_codes(db, session_id) != set(people)
    ):
        raise session_conflict()

    warnings = [
        {"participant_code": code, "code": issue}
        for code, person in people.items()
        for issue in participant_issues(
            db, person, body.discipline, body.section, now, caller.station_id, session_id
        )
    ]
    # Station results: the game counts points and the participant confirmed «Это я».
    # Volunteer results: pressing «Записать» is the confirmation (decisions 9, 19).
    status = "confirmed"
    for entry in body.entries:
        person = people[entry.participant_code]
        pair = pair_of(db, person)
        db.add(
            SectionResult(
                session_id=session_id,
                participant_id=person.id,
                pair_id=pair.id if pair else None,
                discipline=body.discipline,
                section=body.section,
                outcome=entry.outcome,
                points=entry.points,
                wins=entry.wins,
                reason=entry.reason,
                comment=entry.comment,
                status=status,
                source=caller.kind,
                station_id=caller.station_id,
                user_id=caller.user_id,
                finished_at=body.finished_at,
            )
        )
    session.closed_at = now
    session.payload_hash = digest
    session.warnings = warnings
    write_audit(
        db,
        action="result.submit",
        object_type="game_session",
        object_id=session_id,
        user_id=caller.user_id,
        station_id=caller.station_id,
        after=_audit_after(body, warnings),
    )
    db.flush()
    return _receipt(db, session), True
