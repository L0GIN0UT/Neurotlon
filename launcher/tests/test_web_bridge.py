import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from neurotlon_launcher.api import Eligibility, Team
from neurotlon_launcher.machine import Candidate, Confirm, Done, Idle, StationMachine
from neurotlon_launcher.snapshot import snapshot
from neurotlon_launcher.status import StationStatus
from neurotlon_launcher.testing import (
    FakeApi,
    FakeQueue,
    FakeRunner,
    Ids,
    SyncExecutor,
    Time,
)
from neurotlon_launcher.web_bridge import BridgeServer, Station

TOKEN = "t" * 32


def make_machine(discipline: str = "darts") -> tuple[StationMachine, Time]:
    clock = Time()
    machine = StationMachine(
        discipline,
        FakeApi(),
        FakeQueue(),
        FakeRunner(),
        clock=clock.clock,
        monotonic=clock.monotonic,
        new_session_id=Ids(),
        executor=SyncExecutor(),
    )
    return machine, clock


@pytest.fixture
def bridge() -> Iterator[tuple[BridgeServer, StationMachine]]:
    machine, _ = make_machine()
    station = Station(machine, lambda: StationStatus(2, 1, True))
    server = BridgeServer(station, TOKEN)
    station.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, machine
    server.close()


def call(
    server: BridgeServer,
    path: str,
    *,
    method: str = "GET",
    body: Any = None,
    token: str | None = TOKEN,
    host: str | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}", data=data, method=method
    )
    if token is not None:
        request.add_header("X-Station-Token", token)
    if host is not None:
        request.add_header("Host", host)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_state_requires_token(bridge: tuple[BridgeServer, StationMachine]) -> None:
    server, _ = bridge
    assert call(server, "/api/state", token=None)[0] == 403
    assert call(server, "/api/state", token="wrong")[0] == 403
    status, body = call(server, "/api/state")
    assert status == 200
    data = json.loads(body)
    assert data["discipline"] == "darts"
    assert data["state"] == {"kind": "idle", "input": "", "notice": None, "taken": []}
    assert data["status"] == {"pending": 2, "rejected": 1, "online": True}


def test_foreign_host_is_rejected_against_dns_rebinding(
    bridge: tuple[BridgeServer, StationMachine],
) -> None:
    server, _ = bridge
    assert call(server, "/api/state", host="evil.example")[0] == 403


def test_commands_drive_the_machine(bridge: tuple[BridgeServer, StationMachine]) -> None:
    server, machine = bridge
    for char in "07":
        assert (
            call(
                server, "/api/command", method="POST", body={"action": "type_char", "value": char}
            )[0]
            == 204
        )
    assert machine.state == Idle("07")
    assert call(server, "/api/command", method="POST", body={"action": "backspace"})[0] == 204
    assert machine.state == Idle("0")
    state = json.loads(call(server, "/api/state")[1])["state"]
    assert state["input"] == "0"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "close"},
        {"action": "__init__"},
        {"action": "type_char"},
        {"action": "type_char", "value": 7},
        {"action": 5},
        {},
        [],
    ],
)
def test_unknown_or_malformed_commands_are_rejected(
    bridge: tuple[BridgeServer, StationMachine], body: Any
) -> None:
    server, machine = bridge
    assert call(server, "/api/command", method="POST", body=body)[0] == 400
    assert machine.state == Idle()


def test_command_requires_token_and_known_route(
    bridge: tuple[BridgeServer, StationMachine],
) -> None:
    server, _ = bridge
    body = {"action": "backspace"}
    assert call(server, "/api/command", method="POST", body=body, token=None)[0] == 403
    assert call(server, "/api/other", method="POST", body=body)[0] == 404
    assert call(server, "/api/nothing")[0] == 404


def test_events_stream_sends_snapshot_then_changes(
    bridge: tuple[BridgeServer, StationMachine],
) -> None:
    server, _ = bridge
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/api/events?token={TOKEN}")
    with urllib.request.urlopen(request, timeout=5) as stream:
        first = stream.readline()
        assert first.startswith(b"data: ")
        assert json.loads(first[6:])["state"]["input"] == ""
        stream.readline()  # пустая строка-разделитель
        call(server, "/api/command", method="POST", body={"action": "type_char", "value": "7"})
        line = stream.readline()
        assert json.loads(line[6:])["state"]["input"] == "7"


def test_events_without_token_are_forbidden(
    bridge: tuple[BridgeServer, StationMachine],
) -> None:
    server, _ = bridge
    assert call(server, "/api/events", token=None)[0] == 403


def test_snapshot_describes_confirm_with_team_and_last_flag() -> None:
    machine, _ = make_machine("pong")
    team = Team(1, "Красные", "#e5484d")
    candidate = Candidate("NT03", Eligibility("NT03", "Анна", team, ("no_pair_assigned",)))
    machine.state = Confirm(candidate)
    view = snapshot(machine, StationStatus())["state"]
    assert view["kind"] == "confirm"
    assert view["is_last"] is False  # понг: нужен ещё второй игрок
    assert view["candidate"] == {
        "code": "NT03",
        "display_name": "Анна",
        "team": {"number": 1, "name": "Красные", "color": "#e5484d"},
        "issues": ["no_pair_assigned"],
        "offline": False,
        "warned": True,
    }


def test_snapshot_done_counts_down_and_has_no_secrets() -> None:
    machine, clock = make_machine()
    machine.state = Done(("NT07: 8 очк.",), clock.monotonic() + 5)
    assert snapshot(machine, StationStatus())["state"]["seconds_left"] == 5.0
    clock.mono += 2
    assert snapshot(machine, StationStatus())["state"]["seconds_left"] == 3.0
    text = json.dumps(snapshot(machine, StationStatus()), ensure_ascii=False)
    assert "ОВЗ" not in text and "token" not in text.lower()  # noqa: RUF001
