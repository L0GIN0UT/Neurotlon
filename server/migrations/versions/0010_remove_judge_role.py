"""Remove the judge role: judges become admins (decision 35).

Revision ID: 0010
Revises: 0009
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _rebuild_user_table(roles: str) -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("role", type_="check")
        batch.create_check_constraint("role", f"role IN ({roles})")


def _rebuild_with_references_unchecked(roles: str, *statements: sa.TextClause) -> None:
    """Rebuild "user" (SQLite cannot alter a CHECK), which other tables reference.

    The pragma only takes effect outside a transaction, so it must come before any write.
    env.py turns foreign keys back on and checks them after the whole run.
    """
    bind = op.get_bind()
    op.execute("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
        raise RuntimeError(
            "could not turn foreign keys off: the migration runs inside a transaction, "
            "but rebuilding the user table needs them off"
        )
    for statement in statements:
        op.execute(statement)
    _rebuild_user_table(roles)


def upgrade() -> None:
    at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    audit = sa.text(
        "INSERT INTO audit_log (at, user_id, action, object_type, object_id, before, after) "
        "SELECT :at, NULL, 'user.role_migrated', 'user', CAST(id AS TEXT), "
        """'{"role": "judge"}', '{"role": "admin"}' FROM "user" WHERE role = 'judge'"""
    ).bindparams(at=at)
    promote = sa.text("""UPDATE "user" SET role = 'admin' WHERE role = 'judge'""")
    _rebuild_with_references_unchecked("'superuser', 'admin', 'volunteer'", audit, promote)


def downgrade() -> None:
    _rebuild_with_references_unchecked("'superuser', 'admin', 'judge', 'volunteer'")
