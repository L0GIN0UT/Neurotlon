"""Result idempotency: payload hash, warnings and author of a session.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("game_session") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("payload_hash", sa.Text(), nullable=True))
        batch.add_column(sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True))
        batch.create_foreign_key("fk_game_session_user_id_user", "user", ["user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("game_session") as batch:
        batch.drop_constraint("fk_game_session_user_id_user", type_="foreignkey")
        batch.drop_column("warnings")
        batch.drop_column("payload_hash")
        batch.drop_column("user_id")
