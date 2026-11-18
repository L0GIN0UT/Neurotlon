from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Aware datetimes in, aware UTC datetimes out (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed, use an aware one")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UtcDateTime()}


class Discipline(Base):
    __tablename__ = "discipline"
    __table_args__ = (
        CheckConstraint("code IN ('darts', 'football', 'pong')", name="code"),
        CheckConstraint("game_duration_s BETWEEN 10 AND 3600", name="game_duration"),
        CheckConstraint("physical_duration_s BETWEEN 10 AND 3600", name="physical_duration"),
        CheckConstraint("win_points BETWEEN 0 AND 1000", name="win_points"),
        CheckConstraint("max_section_points BETWEEN 1 AND 1000", name="max_section_points"),
    )

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    modalities: Mapped[list[str]] = mapped_column(JSON)
    game_duration_s: Mapped[int] = mapped_column(Integer)
    physical_duration_s: Mapped[int] = mapped_column(Integer)
    win_points: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    # Upper bound of `points` for darts and football; pong scores by wins instead.
    max_section_points: Mapped[int] = mapped_column(Integer, default=10, server_default="10")


class Team(Base):
    __tablename__ = "team"
    __table_args__ = (
        CheckConstraint("number >= 1", name="number"),
        CheckConstraint(
            "color GLOB '#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'",
            name="color",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String)
    color: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column(Integer)


class Participant(Base):
    __tablename__ = "participant"
    __table_args__ = (
        CheckConstraint("code GLOB 'NT[0-9][0-9]' AND code <> 'NT00'", name="code"),
        CheckConstraint("category IN ('general', 'ovz')", name="category"),
        UniqueConstraint("team_id", "number_in_team", name="uq_participant_team_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    checked_in_at: Mapped[datetime | None]
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    number_in_team: Mapped[int | None]


class Duel(Base):
    __tablename__ = "duel"
    __table_args__ = (CheckConstraint("team_a_id <> team_b_id", name="distinct_teams"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    team_b_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    order: Mapped[int] = mapped_column(Integer, unique=True)


class Pair(Base):
    __tablename__ = "pair"
    __table_args__ = (
        CheckConstraint("participant_a_id <> participant_b_id", name="distinct_participants"),
        UniqueConstraint("duel_id", "k", name="uq_pair_duel_k"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    duel_id: Mapped[int] = mapped_column(ForeignKey("duel.id"))
    k: Mapped[int]
    participant_a_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    participant_b_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    zone_statuses: Mapped[dict[str, Any]] = mapped_column(JSON)


class Station(Base):
    __tablename__ = "station"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    discipline: Mapped[str] = mapped_column(ForeignKey("discipline.code"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    last_heartbeat_at: Mapped[datetime | None]
    last_state: Mapped[str | None] = mapped_column(Text)
    queue_length: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class GameSession(Base):
    __tablename__ = "game_session"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    discipline: Mapped[str] = mapped_column(ForeignKey("discipline.code"))
    started_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    payload_hash: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[dict[str, str]] | None] = mapped_column(JSON(none_as_null=True))


session_participant = Table(
    "session_participant",
    Base.metadata,
    Column("session_id", ForeignKey("game_session.session_id"), primary_key=True),
    Column("participant_id", ForeignKey("participant.id"), primary_key=True),
)


class SectionResult(Base):
    __tablename__ = "section_result"
    __table_args__ = (
        CheckConstraint("section IN ('bci', 'physical')", name="section"),
        CheckConstraint("outcome IN ('completed', 'not_completed')", name="outcome"),
        CheckConstraint("points >= 0", name="points"),
        CheckConstraint("wins >= 0", name="wins"),
        CheckConstraint(
            "reason IN ('participant_refused', 'health', 'equipment', 'no_show', 'other')",
            name="reason",
        ),
        CheckConstraint("status IN ('entered', 'confirmed', 'locked')", name="status"),
        CheckConstraint("source IN ('station', 'volunteer', 'judge', 'admin')", name="source"),
        CheckConstraint(
            "outcome <> 'completed' OR (points IS NOT NULL AND reason IS NULL)",
            name="completed_fields",
        ),
        CheckConstraint(
            "outcome <> 'not_completed' "
            "OR (reason IS NOT NULL AND points IS NULL AND wins IS NULL)",
            name="not_completed_fields",
        ),
        # A session is exactly one section (station = bci, volunteer = physical),
        # so there is one row per participant per session.
        UniqueConstraint(
            "session_id", "participant_id", name="uq_section_result_session_participant"
        ),
        Index(
            "ix_section_result_participant_discipline_section",
            "participant_id",
            "discipline",
            "section",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participant.id"))
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pair.id"))
    discipline: Mapped[str] = mapped_column(ForeignKey("discipline.code"))
    section: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    points: Mapped[float | None] = mapped_column(Float)
    wins: Mapped[int | None]
    reason: Mapped[str | None] = mapped_column(String)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="entered", server_default="entered")
    source: Mapped[str] = mapped_column(String)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    finished_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    voided_at: Mapped[datetime | None]
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)


class CorrectionRequest(Base):
    """A volunteer asks the judge to fix a submitted result after the undo window."""

    __tablename__ = "correction_request"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="status"),
        CheckConstraint("length(comment) <= 200", name="comment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("game_session.session_id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    comment: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String, default="open", server_default="open")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    resolved_at: Mapped[datetime | None]


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint("role IN ('superuser', 'admin', 'judge', 'volunteer')", name="role"),
        CheckConstraint(
            "(role = 'volunteer') = (discipline IS NOT NULL)", name="volunteer_discipline"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    discipline: Mapped[str | None] = mapped_column(ForeignKey("discipline.code"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"))
    action: Mapped[str] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[str] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    reason: Mapped[str | None] = mapped_column(Text)


for _action in ("UPDATE", "DELETE"):
    event.listen(
        AuditLog.__table__,
        "after_create",
        DDL(  # type: ignore[no-untyped-call]
            f"CREATE TRIGGER IF NOT EXISTS audit_log_no_{_action.lower()} "
            f"BEFORE {_action} ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
        ).execute_if(dialect="sqlite"),
    )


class WebSession(Base):
    __tablename__ = "web_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class Draw(Base):
    __tablename__ = "draw"

    id: Mapped[int] = mapped_column(primary_key=True)
    seed: Mapped[int] = mapped_column(BigInteger)
    m: Mapped[int] = mapped_column(Integer)
    team_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    protocol: Mapped[dict[str, Any]] = mapped_column(JSON)
