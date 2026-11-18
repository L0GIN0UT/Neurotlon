from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from neurotlon_server.app import create_app
from neurotlon_server.config import Settings
from neurotlon_server.users import create_user

SERVER_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2027, 1, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def app(tmp_path: Path, clock: FakeClock) -> FastAPI:
    url = f"sqlite:///{tmp_path / 'app.db'}"
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_app(Settings(database_url=url), clock=clock)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # https so the Secure session cookie is sent back
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    with app.state.session_factory() as session:
        yield session


def make_user(db: Session, login: str, role: str = "admin", discipline: str | None = None) -> int:
    return create_user(
        db, login=login, password=PASSWORD, role=role, discipline=discipline, actor_id=None
    ).id


def login_as(app: FastAPI, login: str) -> TestClient:
    """A fresh client with a logged-in session for the given login."""
    test_client = TestClient(app, base_url="https://testserver")
    response = test_client.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
    assert response.status_code == 204
    return test_client
