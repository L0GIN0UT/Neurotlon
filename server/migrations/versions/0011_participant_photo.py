"""Participant photo for the badge (decision 36).

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "participant_photo",
        sa.Column(
            "participant_id", sa.Integer(), sa.ForeignKey("participant.id"), primary_key=True
        ),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("participant_photo")
