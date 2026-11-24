"""Stations are archived, not deleted: the audit log references them.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("station", sa.Column("archived_at", UtcDateTime(), nullable=True))


def downgrade() -> None:
    # Native DROP COLUMN: a batch rebuild drops `station`, which audit_log and
    # game_session reference.
    op.execute("ALTER TABLE station DROP COLUMN archived_at")
