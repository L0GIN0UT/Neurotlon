"""Staff web sessions (cookie token hashes).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_DT = UtcDateTime()


def upgrade() -> None:
    op.create_table(
        "web_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", _DT, nullable=False),
        sa.Column("expires_at", _DT, nullable=False),
        sa.Column("revoked_at", _DT, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_web_session_user_id_user"),
        sa.PrimaryKeyConstraint("id", name="pk_web_session"),
        sa.UniqueConstraint("token_hash", name="uq_web_session_token_hash"),
    )
    op.create_index("ix_web_session_user_id", "web_session", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_web_session_user_id", table_name="web_session")
    op.drop_table("web_session")
