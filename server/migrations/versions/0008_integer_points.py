"""Section points are whole numbers (decision 28).

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE section_result SET points = CAST(ROUND(points) AS INTEGER) WHERE points IS NOT NULL"
    )
    with op.batch_alter_table("section_result") as batch:
        batch.alter_column("points", existing_type=sa.Float(), type_=sa.Integer())


def downgrade() -> None:
    with op.batch_alter_table("section_result") as batch:
        batch.alter_column("points", existing_type=sa.Integer(), type_=sa.Float())
