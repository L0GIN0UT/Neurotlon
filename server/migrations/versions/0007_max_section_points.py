"""Per-discipline limit of section points.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("discipline") as batch:
        batch.add_column(
            sa.Column("max_section_points", sa.Integer(), nullable=False, server_default="10")
        )
        batch.create_check_constraint("max_section_points", "max_section_points BETWEEN 1 AND 1000")


def downgrade() -> None:
    with op.batch_alter_table("discipline") as batch:
        batch.drop_constraint("max_section_points", type_="check")
        batch.drop_column("max_section_points")
