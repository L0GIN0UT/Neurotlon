"""Initial schema, audit_log append-only triggers, discipline seed.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_DT = UtcDateTime()
_HEX = "[0-9A-Fa-f]"
_COLOR_PATTERN = "#" + _HEX * 6


def upgrade() -> None:
    op.create_table(
        "discipline",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("modalities", sa.JSON(), nullable=False),
        sa.Column("game_duration_s", sa.Integer(), nullable=False),
        sa.Column("physical_duration_s", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint("code IN ('darts', 'football', 'pong')", name="code"),
        sa.CheckConstraint("game_duration_s BETWEEN 10 AND 3600", name="game_duration"),
        sa.CheckConstraint("physical_duration_s BETWEEN 10 AND 3600", name="physical_duration"),
    )
    op.create_table(
        "team",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.CheckConstraint("number >= 1", name="number"),
        sa.CheckConstraint(f"color GLOB '{_COLOR_PATTERN}'", name="color"),
    )
    op.create_table(
        "participant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("checked_in_at", _DT, nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("number_in_team", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("team_id", "number_in_team", name="uq_participant_team_number"),
        sa.CheckConstraint("code GLOB 'NT[0-9][0-9]' AND code <> 'NT00'", name="code"),
        sa.CheckConstraint("category IN ('general', 'ovz')", name="category"),
    )
    op.create_table(
        "duel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_a_id", sa.Integer(), nullable=False),
        sa.Column("team_b_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["team_a_id"], ["team.id"]),
        sa.ForeignKeyConstraint(["team_b_id"], ["team.id"]),
        sa.UniqueConstraint("order"),
        sa.CheckConstraint("team_a_id <> team_b_id", name="distinct_teams"),
    )
    op.create_table(
        "pair",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("duel_id", sa.Integer(), nullable=False),
        sa.Column("k", sa.Integer(), nullable=False),
        sa.Column("participant_a_id", sa.Integer(), nullable=False),
        sa.Column("participant_b_id", sa.Integer(), nullable=False),
        sa.Column("zone_statuses", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["duel_id"], ["duel.id"]),
        sa.ForeignKeyConstraint(["participant_a_id"], ["participant.id"]),
        sa.ForeignKeyConstraint(["participant_b_id"], ["participant.id"]),
        sa.UniqueConstraint("duel_id", "k", name="uq_pair_duel_k"),
        sa.CheckConstraint("participant_a_id <> participant_b_id", name="distinct_participants"),
    )
    op.create_table(
        "station",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("discipline", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("last_heartbeat_at", _DT, nullable=True),
        sa.Column("last_state", sa.Text(), nullable=True),
        sa.Column("queue_length", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["discipline"], ["discipline.code"]),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "game_session",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("discipline", sa.String(), nullable=False),
        sa.Column("started_at", _DT, nullable=False),
        sa.Column("closed_at", _DT, nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.ForeignKeyConstraint(["station_id"], ["station.id"]),
        sa.ForeignKeyConstraint(["discipline"], ["discipline.code"]),
    )
    op.create_table(
        "session_participant",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "participant_id"),
        sa.ForeignKeyConstraint(["session_id"], ["game_session.session_id"]),
        sa.ForeignKeyConstraint(["participant_id"], ["participant.id"]),
    )
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("discipline", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["discipline"], ["discipline.code"]),
        sa.UniqueConstraint("login"),
        sa.CheckConstraint("role IN ('superuser', 'admin', 'judge', 'volunteer')", name="role"),
        sa.CheckConstraint(
            "(role = 'volunteer') = (discipline IS NOT NULL)", name="volunteer_discipline"
        ),
    )
    op.create_table(
        "section_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("participant_id", sa.Integer(), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=True),
        sa.Column("discipline", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("points", sa.Float(), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="entered", nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("finished_at", _DT, nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["participant_id"], ["participant.id"]),
        sa.ForeignKeyConstraint(["pair_id"], ["pair.id"]),
        sa.ForeignKeyConstraint(["discipline"], ["discipline.code"]),
        sa.ForeignKeyConstraint(["station_id"], ["station.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint(
            "session_id", "participant_id", name="uq_section_result_session_participant"
        ),
        sa.CheckConstraint("section IN ('bci', 'physical')", name="section"),
        sa.CheckConstraint("outcome IN ('completed', 'not_completed')", name="outcome"),
        sa.CheckConstraint("points >= 0", name="points"),
        sa.CheckConstraint("wins >= 0", name="wins"),
        sa.CheckConstraint(
            "reason IN ('participant_refused', 'health', 'equipment', 'no_show', 'other')",
            name="reason",
        ),
        sa.CheckConstraint("status IN ('entered', 'confirmed', 'locked')", name="status"),
        sa.CheckConstraint("source IN ('station', 'volunteer', 'judge', 'admin')", name="source"),
        sa.CheckConstraint(
            "outcome <> 'completed' OR (points IS NOT NULL AND reason IS NULL)",
            name="completed_fields",
        ),
        sa.CheckConstraint(
            "outcome <> 'not_completed' "
            "OR (reason IS NOT NULL AND points IS NULL AND wins IS NULL)",
            name="not_completed_fields",
        ),
    )
    op.create_index(
        "ix_section_result_participant_discipline_section",
        "section_result",
        ["participant_id", "discipline", "section"],
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", _DT, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("before", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["station_id"], ["station.id"]),
    )
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS audit_log_no_{event.lower()} "
            f"BEFORE {event} ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
        )

    discipline = sa.table(
        "discipline",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("modalities", sa.JSON),
        sa.column("game_duration_s", sa.Integer),
        sa.column("physical_duration_s", sa.Integer),
    )
    op.bulk_insert(
        discipline,
        [
            {
                "code": code,
                "name": name,
                "modalities": modalities,
                "game_duration_s": 120,
                "physical_duration_s": 300,
            }
            for code, name, modalities in (
                ("darts", "Дартс", ["eeg", "emg"]),
                ("football", "Футбол", ["eeg", "emg"]),
                ("pong", "Понг", ["emg"]),
            )
        ],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_update")
    op.execute("DROP TRIGGER audit_log_no_delete")
    op.drop_table("audit_log")
    op.drop_index("ix_section_result_participant_discipline_section", "section_result")
    for table in (
        "section_result",
        "user",
        "session_participant",
        "game_session",
        "station",
        "pair",
        "duel",
        "participant",
        "team",
        "discipline",
    ):
        op.drop_table(table)
