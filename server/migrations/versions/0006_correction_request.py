"""Correction requests from volunteers to the judge.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "correction_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", UtcDateTime(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'done')", name=op.f("ck_correction_request_status")),
        sa.CheckConstraint("length(comment) <= 200", name=op.f("ck_correction_request_comment")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_session.session_id"],
            name=op.f("fk_correction_request_session_id_game_session"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_correction_request_user_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["user.id"], name=op.f("fk_correction_request_resolved_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction_request")),
    )
    op.create_index(op.f("ix_correction_request_session_id"), "correction_request", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_correction_request_session_id"), table_name="correction_request")
    op.drop_table("correction_request")
