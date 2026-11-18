from alembic import context

from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings
from neurotlon_server.models import Base

# Tests (and one-off runs) may override the URL via `-x`-style config option.
_url = context.config.get_main_option("sqlalchemy.url")
_engine = create_engine_from_settings(Settings(database_url=_url) if _url else Settings())

with _engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
_engine.dispose()
