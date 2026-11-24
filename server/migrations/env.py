from alembic import context
from sqlalchemy import Connection

from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings
from neurotlon_server.models import Base

# Tests (and one-off runs) may override the URL via `-x`-style config option.
_url = context.config.get_main_option("sqlalchemy.url")
_engine = create_engine_from_settings(Settings(database_url=_url) if _url else Settings())

_REPORTED_VIOLATIONS = 5


def _restore_foreign_keys(connection: Connection) -> None:
    """A migration may switch foreign keys off to rebuild a table: restore and verify."""
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        shown = "; ".join(
            f"table={table} rowid={rowid} parent={parent}"
            for table, rowid, parent, _fk in violations[:_REPORTED_VIOLATIONS]
        )
        raise RuntimeError(
            f"foreign key violations after migration ({len(violations)}), first: {shown}"
        )


with _engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
    if connection.dialect.name == "sqlite":
        _restore_foreign_keys(connection)
_engine.dispose()
