"""Remove the judge role: judges become admins (decision 33).

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _rebuild_user_table(roles: str) -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("role", type_="check")
        batch.create_check_constraint("role", f"role IN ({roles})")


def _rebuild_with_references_unchecked(roles: str, *statements: str) -> None:
    """Rebuild "user" (SQLite cannot alter a CHECK), which other tables reference.

    The pragma only takes effect outside a transaction, so it must come before any write.
    """
    op.execute("PRAGMA foreign_keys=OFF")
    for statement in statements:
        op.execute(statement)
    _rebuild_user_table(roles)
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("foreign key violations after rebuilding the user table")


def upgrade() -> None:
    _rebuild_with_references_unchecked(
        "'superuser', 'admin', 'volunteer'",
        "UPDATE \"user\" SET role = 'admin' WHERE role = 'judge'",
    )


def downgrade() -> None:
    _rebuild_with_references_unchecked("'superuser', 'admin', 'judge', 'volunteer'")
