"""Сквозной тест: машина + настоящий HTTP-клиент + настоящий сервер + буфер + игра-заглушка."""

from __future__ import annotations

import copy
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from neurotlon_launcher.api import HttpStationApi, Offline
from neurotlon_launcher.game import SubprocessGameRunner
from neurotlon_launcher.heartbeat import HeartbeatLoop
from neurotlon_launcher.machine import Confirm, Done, StationMachine
from neurotlon_launcher.outbox import Outbox
from neurotlon_launcher.sender import Sender
from neurotlon_server.app import create_app
from neurotlon_server.config import Settings
from neurotlon_server.models import GameSession, Participant, SectionResult, Station
from neurotlon_server.security import hash_token, new_token

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
NOW = datetime(2027, 1, 1, 9, 0, tzinfo=UTC)
STUB = (sys.executable, "-m", "neurotlon_games.stub", "--seconds", "0")


class Link:
    """Канал отправки результатов, который можно «оборвать»."""

    def __init__(self, api: HttpStationApi) -> None:
        self.api = api
        self.up = True

    def submit_result(self, payload: dict[str, Any]) -> None:
        if not self.up:
            raise Offline("cable unplugged")
        self.api.submit_result(payload)


class Rig:
    def __init__(self, tmp_path: Path, app: FastAPI, client: TestClient, discipline: str) -> None:
        self.app = app
        token = new_token()
        with app.state.session_factory() as db:
            station = Station(name=discipline, discipline=discipline, token_hash=hash_token(token))
            db.add(station)
            db.add_all(
                Participant(code=f"NT0{i}", category="general", checked_in_at=NOW)
                for i in range(1, 5)
            )
            db.commit()
            self.station_id = station.id
        data_dir = tmp_path / "data"
        self.api = HttpStationApi(
            "http://testserver", token, client=client, cache_path=data_dir / "config-cache.json"
        )
        self.link = Link(self.api)
        self.outbox = Outbox(data_dir / "outbox.db")
        self.sender = Sender(self.outbox, self.link)
        self.machine = StationMachine(
            discipline,
            self.api,
            self.outbox,
            SubprocessGameRunner(STUB, None, data_dir, "127.0.0.1", 8765),
            clock=lambda: NOW,
            on_enqueue=self.sender.kick,
        )

    def play(self, *codes: str) -> dict[str, Any]:
        """Ввод кодов, «Это я», игра до конца; возвращает поставленный в буфер результат."""
        for code in codes:
            self.machine.enter_code(code)
            self._tick_until(Confirm)
            self.machine.confirm()
        self._tick_until(Done)
        return self.outbox.pending()[-1].payload

    def _tick_until(self, kind: type) -> None:
        end = time.monotonic() + 30
        while not isinstance(self.machine.state, kind):
            assert time.monotonic() < end, f"stuck in {self.machine.state}"
            self.machine.tick()
            time.sleep(0.01)

    def count(self, model: type) -> int:
        with self.app.state.session_factory() as db:
            return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    url = f"sqlite:///{tmp_path / 'server.db'}"
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_app(Settings(database_url=url), clock=lambda: NOW)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


def test_darts_result_reaches_server_and_replay_is_idempotent(
    tmp_path: Path, app: FastAPI, client: TestClient
) -> None:
    rig = Rig(tmp_path, app, client, "darts")
    payload = rig.play("nt-02")
    assert rig.count(GameSession) == 1  # startSession отработал
    assert rig.sender.send_pending() is True
    assert rig.outbox.pending_count() == 0
    with app.state.session_factory() as db:
        result = db.scalars(select(SectionResult)).one()
        assert (result.discipline, result.section, result.source) == ("darts", "bci", "station")
        assert result.station_id == rig.station_id
        assert result.status == "confirmed"
        assert result.points == payload["entries"][0]["points"]
        assert db.scalars(select(GameSession)).one().closed_at is not None

    rig.api.submit_result(payload)  # повтор того же тела
    assert rig.count(SectionResult) == 1
    assert rig.count(GameSession) == 1


def test_pong_pair_waits_in_outbox_while_offline_then_resends(
    tmp_path: Path, app: FastAPI, client: TestClient
) -> None:
    rig = Rig(tmp_path, app, client, "pong")
    payload = rig.play("3", "4")

    rig.link.up = False
    assert rig.sender.send_pending() is False
    assert rig.outbox.pending_count() == 1
    assert rig.count(SectionResult) == 0

    rig.link.up = True
    assert rig.sender.send_pending() is True
    assert rig.outbox.pending_count() == 0
    with app.state.session_factory() as db:
        rows = db.execute(
            select(Participant.code, SectionResult.wins)
            .join(Participant, Participant.id == SectionResult.participant_id)
            .order_by(Participant.code)
        ).all()
    assert [code for code, _ in rows] == ["NT03", "NT04"]
    assert sorted(wins for _, wins in rows) == [0, 1]

    rig.api.submit_result(payload)
    assert rig.count(SectionResult) == 2


def test_conflicting_resend_is_rejected_and_kept(
    tmp_path: Path, app: FastAPI, client: TestClient
) -> None:
    rig = Rig(tmp_path, app, client, "darts")
    payload = rig.play("1")
    assert rig.sender.send_pending() is True
    other = copy.deepcopy(payload)
    other["entries"][0]["points"] = payload["entries"][0]["points"] + 1
    second_box = Outbox(tmp_path / "second" / "outbox.db")
    second_box.add(other)  # тот же session_id, другие данные
    sender = Sender(second_box, rig.link)
    assert sender.send_pending() is True
    assert second_box.rejected_count() == 1
    assert "session_conflict" in (second_box.rejected()[0].last_error or "")
    assert rig.count(SectionResult) == 1


def test_heartbeat_reaches_server(tmp_path: Path, app: FastAPI, client: TestClient) -> None:
    rig = Rig(tmp_path, app, client, "darts")
    loop = HeartbeatLoop(rig.api, rig.machine.heartbeat_view, rig.outbox.pending_count)
    assert loop.beat() is True
    with app.state.session_factory() as db:
        station = db.get(Station, rig.station_id)
        assert station is not None
        assert station.last_state == "idle"
        assert station.last_heartbeat_at is not None


def test_config_and_eligibility_from_real_server(
    tmp_path: Path, app: FastAPI, client: TestClient
) -> None:
    rig = Rig(tmp_path, app, client, "darts")
    config = rig.api.get_config()
    assert (config.discipline, config.section) == ("darts", "bci")
    eligibility = rig.api.eligibility("NT01", "darts", "bci")
    assert eligibility.code == "NT01"
    assert eligibility.team is None
    assert "no_pair_assigned" in eligibility.issues
