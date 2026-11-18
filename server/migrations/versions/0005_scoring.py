"""Scoring: voided results and configurable points per pong win.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

from neurotlon_server.models import UtcDateTime

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("section_result") as batch:
        batch.add_column(sa.Column("voided_at", UtcDateTime(), nullable=True))
        batch.add_column(sa.Column("voided_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("void_reason", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_section_result_voided_by_user", "user", ["voided_by"], ["id"])
    with op.batch_alter_table("discipline") as batch:
        batch.add_column(sa.Column("win_points", sa.Integer(), nullable=False, server_default="10"))
        batch.create_check_constraint("win_points", "win_points BETWEEN 0 AND 1000")


def downgrade() -> None:
    with op.batch_alter_table("discipline") as batch:
        batch.drop_constraint("win_points", type_="check")
        batch.drop_column("win_points")
    with op.batch_alter_table("section_result") as batch:
        batch.drop_constraint("fk_section_result_voided_by_user", type_="foreignkey")
        batch.drop_column("void_reason")
        batch.drop_column("voided_by")
        batch.drop_column("voided_at")
