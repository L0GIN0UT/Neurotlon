"""Draw protocol (seed, parameters, rosters).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "draw",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("m", sa.Integer(), nullable=False),
        sa.Column("team_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_draw_user_id_user"),
        sa.PrimaryKeyConstraint("id", name="pk_draw"),
    )


def downgrade() -> None:
    op.drop_table("draw")
