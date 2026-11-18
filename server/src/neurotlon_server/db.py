from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from neurotlon_server.config import Settings

_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
)


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    for pragma in _PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


def create_engine_from_settings(settings: Settings) -> Engine:
    engine = create_engine(settings.database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
