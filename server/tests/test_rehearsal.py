import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config

from neurotlon_server.app import create_app
from neurotlon_server.cli import main as server_main
from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings, create_session_factory
from neurotlon_server.rehearsal import Http, Rehearsal, Report, main, reset_database
from neurotlon_server.users import create_user

from .conftest import SERVER_DIR

PASSWORD = "rehearsal-root-pw"


def migrate(db: Path) -> str:
    url = f"sqlite:///{db}"
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def make_superuser(url: str) -> None:
    engine = create_engine_from_settings(Settings(database_url=url))
    with create_session_factory(engine)() as db:
        create_user(
            db, login="root", password=PASSWORD, role="superuser", discipline=None, actor_id=None
        )
    engine.dispose()


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """The real app behind a real HTTP server on a free local port."""
    db = tmp_path / "live.db"
    url = migrate(db)
    make_superuser(url)
    app = create_app(Settings(database_url=url), scoreboard_interval=0.3)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{sock.getsockname()[1]}", db
    server.should_exit = True
    thread.join(timeout=10)


def test_full_rehearsal_passes_through_the_cli(
    live_server: tuple[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base, _ = live_server
    monkeypatch.setenv("NEUROTLON_REHEARSAL_PASSWORD", PASSWORD)
    xlsx = tmp_path / "out.xlsx"
    code = main(["--base-url", base, "--xlsx-out", str(xlsx)])
    output = capsys.readouterr().out
    assert code == 0, output
    assert "FAIL" not in output
    assert "RESULT: PASS" in output
    assert output.count("PASS  ") >= 30
    assert "scoreboard stream delivered the change" in output
    assert xlsx.read_bytes()[:2] == b"PK"
    assert main(["--base-url", base]) == 1  # second run: the database is no longer fresh


def test_rehearsal_refuses_a_database_with_participants(live_server: tuple[str, Path]) -> None:
    base, db = live_server
    engine = create_engine_from_settings(Settings(database_url=f"sqlite:///{db}"))
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO participant (code) VALUES ('NT01')")
    engine.dispose()
    report = Report(out=lambda _: None)
    Rehearsal(lambda: Http(base), "root", PASSWORD, report).run()
    assert not report.passed
    assert "fresh database" in report.checks[-1].detail
    # nothing was created on the real data
    assert Http(base).get("/api/v1/scoreboard").json() == {"teams": []}


def test_rehearsal_fails_on_wrong_password(live_server: tuple[str, Path]) -> None:
    base, _ = live_server
    report = Report(out=lambda _: None)
    Rehearsal(lambda: Http(base), "root", "wrong-password", report).run()
    assert not report.passed
    assert report.summary().startswith("RESULT: FAIL")


def test_rehearsal_reports_unreachable_server() -> None:
    report = Report(out=lambda _: None)
    Rehearsal(lambda: Http("http://127.0.0.1:1"), "root", PASSWORD, report).run()
    assert not report.passed


def test_reset_refuses_while_server_runs(live_server: tuple[str, Path]) -> None:
    _, db = live_server
    assert main(["--reset", "--db", str(db)]) == 1
    assert db.exists()


def test_reset_after_server_stopped(tmp_path: Path) -> None:
    db = tmp_path / "r.db"
    url = migrate(db)
    make_superuser(url)
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO participant (code, display_name) VALUES ('NT01', 'Rehearsal 1')"
        )
    engine.dispose()
    reset_database(db)
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM participant").scalar() == 0
        assert conn.exec_driver_sql("SELECT count(*) FROM user").scalar() == 0
    engine.dispose()


def test_reset_refuses_real_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "real.db"
    url = migrate(db)
    engine = create_engine_from_settings(Settings(database_url=url))
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO participant (code, display_name) VALUES ('NT01', 'Anna')")
    engine.dispose()
    assert main(["--reset", "--db", str(db)]) == 1
    assert "non-rehearsal" in capsys.readouterr().err
    assert db.exists()


def test_reset_refuses_real_staff(tmp_path: Path) -> None:
    db = tmp_path / "staff.db"
    url = migrate(db)
    engine = create_engine_from_settings(Settings(database_url=url))
    session = create_session_factory(engine)()
    create_user(
        session,
        login="boss",
        password="long-enough-pw",
        role="admin",
        discipline=None,
        actor_id=None,
    )
    session.close()
    engine.dispose()
    assert main(["--reset", "--db", str(db)]) == 1


def test_server_cli_still_parses(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        server_main(["backup"])  # --db and --to are required
    assert "--db" in capsys.readouterr().err
