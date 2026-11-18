import getpass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from neurotlon_server.app import create_app
from neurotlon_server.cli import main
from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings, create_session_factory
from neurotlon_server.models import AuditLog, User

from .conftest import SERVER_DIR


@pytest.fixture
def url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    monkeypatch.setenv("NEUROTLON_DATABASE_URL", url)
    return url


def _passwords(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    queue = list(answers)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": queue.pop(0))


def test_create_superuser(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _passwords(monkeypatch, "s3cret-pass", "s3cret-pass")
    assert main(["create-superuser", "--login", "root"]) == 0
    engine = create_engine_from_settings(Settings(database_url=url))
    with create_session_factory(engine)() as db:
        user = db.scalars(select(User)).one()
        assert (user.login, user.role, user.discipline, user.is_active) == (
            "root",
            "superuser",
            None,
            True,
        )
        assert "s3cret-pass" not in user.password_hash
        audit = db.scalars(select(AuditLog)).one()
        assert (audit.action, audit.user_id) == ("user.create", None)
    engine.dispose()
    client = TestClient(create_app(Settings(database_url=url)), base_url="https://testserver")
    response = client.post("/api/v1/auth/login", json={"login": "root", "password": "s3cret-pass"})
    assert response.status_code == 204


def test_create_superuser_rejects_mismatch_short_and_duplicate(
    url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _passwords(monkeypatch, "s3cret-pass", "different-pass")
    assert main(["create-superuser", "--login", "root"]) == 1
    _passwords(monkeypatch, "short")
    assert main(["create-superuser", "--login", "root"]) == 1
    _passwords(monkeypatch, "s3cret-pass", "s3cret-pass")
    assert main(["create-superuser", "--login", "root"]) == 0
    _passwords(monkeypatch, "s3cret-pass", "s3cret-pass")
    assert main(["create-superuser", "--login", "root"]) == 1
    assert "already exists" in capsys.readouterr().err


def test_login_argument_is_required() -> None:
    with pytest.raises(SystemExit):
        main(["create-superuser"])
