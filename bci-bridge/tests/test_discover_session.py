"""Цикл `--discover`: строки команд внутрь, строки с меткой наружу."""

import io
import json
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from neurotlon_bridge.__main__ import main
from neurotlon_bridge.devices.base import DeviceInfo, SdkUnavailableError
from neurotlon_bridge.devices.discovery import DiscoveryService
from neurotlon_bridge.devices.fakes import FakeClock, FakeDevice, FakeScanner
from neurotlon_bridge.discover_session import DiscoverySession, Inbox, pump_lines
from neurotlon_contracts.discovery import DISCOVERY_MARK, decode_bridge_line

CA1 = "AA:01"
CA2 = "AA:02"


def devices() -> list[FakeDevice]:
    return [
        FakeDevice(
            DeviceInfo("callibri", "Callibri", "", CA1, -60), 0.0, serial_after_connect="S1"
        ),
        FakeDevice(
            DeviceInfo("callibri", "Callibri", "", CA2, -61), 0.0, serial_after_connect="S2"
        ),
    ]


class Rig:
    """Сессия на виртуальных часах: команды вызываются напрямую, вывод копится в списке."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.scanner = FakeScanner(devices(), self.clock)
        service = DiscoveryService(self.scanner, self.clock, self.clock.advance)
        self.lines: list[str] = []
        self.session = DiscoverySession(service, self.lines.append)

    def send(self, **command: Any) -> bool:
        return self.session.handle_line(json.dumps(command))

    def messages(self) -> list[dict[str, Any]]:
        decoded = [decode_bridge_line(line) for line in self.lines]
        assert None not in decoded  # всё, что мост пишет, проходит схему
        return [m for m in decoded if m is not None]

    def step(self, seconds: float = 0.5) -> None:
        self.clock.advance(seconds)
        self.session.pump()


def test_every_output_line_carries_the_mark_and_hello_comes_first() -> None:
    rig = Rig()
    rig.session.hello()
    rig.send(cmd="scan", on=True)
    rig.step()
    assert all(line.startswith(DISCOVERY_MARK) for line in rig.lines)
    assert rig.messages()[0] == {"type": "hello", "v": 1}
    assert len(rig.messages()[-1]["items"]) == 2


def test_connect_runs_in_the_worker_and_reports_the_link() -> None:
    rig = Rig()
    rig.send(cmd="scan", on=True)
    rig.step()
    rig.send(cmd="connect", id=CA1, kind="callibri")
    rig.session.wait_idle()
    rig.session.pump()
    links = [m for m in rig.messages() if m["type"] == "link"]
    assert [m["state"] for m in links] == ["connecting", "connected"]
    assert links[-1]["serial"] == "S1"


def test_garbage_and_unknown_commands_are_ignored() -> None:
    rig = Rig()
    for line in [
        "",
        "мусор SDK",
        "{плохо",
        "[]",
        '{"cmd":"explode"}',
        '{"cmd":"scan","on":"yes"}',
        '{"cmd":"connect","id":"AA:01","kind":"kolibri"}',
        '{"cmd":"connect","id":"","kind":"callibri"}',
    ]:
        assert rig.session.handle_line(line) is True
    rig.session.wait_idle()
    assert rig.scanner.events == []


def test_quit_command_asks_to_stop() -> None:
    rig = Rig()
    assert rig.send(cmd="quit") is False


def test_release_removes_a_connect_that_is_still_queued() -> None:
    rig = Rig()
    rig.send(cmd="scan", on=True)
    rig.step()
    gate = threading.Event()
    rig.scanner.connect_gate = gate
    rig.send(cmd="connect", id=CA1, kind="callibri")
    deadline = time.monotonic() + 5
    while f"connect:{CA1}" not in rig.scanner.events and time.monotonic() < deadline:
        time.sleep(0.005)
    rig.send(cmd="connect", id=CA2, kind="callibri")  # встало в очередь за первым
    rig.send(cmd="release", id=CA2)
    gate.set()
    rig.session.wait_idle()
    assert f"connect:{CA2}" not in rig.scanner.events
    assert CA1 in rig.scanner.raws


def run_session(
    scanner: FakeScanner, probe_wait_s: float = 0.0
) -> tuple[Inbox, list[str], threading.Thread]:
    service = DiscoveryService(scanner, time.monotonic, time.sleep, probe_wait_s=probe_wait_s)
    lines: list[str] = []
    inbox: Inbox = queue.Queue()
    session = DiscoverySession(service, lines.append)
    thread = threading.Thread(target=session.run, args=(inbox, 0.01), daemon=True)
    thread.start()
    return inbox, lines, thread


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def test_main_loop_end_to_end_with_quit() -> None:
    scanner = FakeScanner(devices(), time.monotonic)
    inbox, lines, thread = run_session(scanner)
    inbox.put('{"cmd":"scan","on":true}\n')
    wait_for(lambda: any('"items":[{' in line for line in lines))
    inbox.put(json.dumps({"cmd": "connect", "id": CA1, "kind": "callibri"}))
    wait_for(lambda: any('"state":"connected"' in line for line in lines))
    inbox.put('{"cmd":"quit"}')
    thread.join(5)
    assert not thread.is_alive()
    assert scanner.raws[CA1].closed  # выход отпускает датчики
    assert scanner.events[-1] == "close"
    assert decode_bridge_line(lines[0]) == {"type": "hello", "v": 1}


def test_closing_stdin_also_releases_the_sensors() -> None:
    scanner = FakeScanner(devices(), time.monotonic)
    stdin = io.StringIO(
        '{"cmd":"scan","on":true}\n'
        + '{"cmd":"connect","id":"AA:01","kind":"callibri"}\n'  # устройство ещё не найдено
    )
    inbox: Inbox = queue.Queue()
    pump_lines(stdin, inbox)  # весь ввод и конец ввода (None) сразу в очереди
    service = DiscoveryService(scanner, time.monotonic, time.sleep, probe_wait_s=0.0)
    lines: list[str] = []
    DiscoverySession(service, lines.append).run(inbox, 0.01)
    assert scanner.events[-1] == "close"
    assert decode_bridge_line(lines[0]) == {"type": "hello", "v": 1}


def test_main_discover_fake_speaks_the_protocol_over_streams() -> None:
    stdin = io.StringIO("")  # сразу конец ввода: hello, список и выход
    stdout = io.StringIO()
    assert main(["--discover", "--fake"], stdin=stdin, stdout=stdout) == 0
    messages = [decode_bridge_line(line) for line in stdout.getvalue().splitlines()]
    assert messages[0] == {"type": "hello", "v": 1}
    assert all(m is not None for m in messages)


def test_main_discover_without_sdk_reports_the_error_and_exits_3() -> None:
    def broken() -> FakeScanner:
        raise SdkUnavailableError("Не удалось загрузить NeuroSDK")

    stdout = io.StringIO()
    assert main(["--discover"], scanner_factory=broken, stdin=io.StringIO(""), stdout=stdout) == 3
    assert decode_bridge_line(stdout.getvalue()) == {
        "type": "error",
        "message": "Не удалось загрузить NeuroSDK",
    }


def test_main_discover_uses_the_given_scanner_and_closes_it() -> None:
    scanner = FakeScanner(devices(), time.monotonic)
    stdin = io.StringIO('{"cmd":"scan","on":true}\n{"cmd":"quit"}\n')
    assert main(["--discover"], scanner_factory=lambda: scanner, stdin=stdin) == 0
    assert scanner.events[0] == "start" and scanner.events[-1] == "close"


def test_old_scan_json_keeps_its_shape_without_rssi(capsys: pytest.CaptureFixture[str]) -> None:
    from neurotlon_bridge.__main__ import SCAN_JSON_MARK
    from neurotlon_bridge.devices.fakes import FakeBackend, FakeRawSensor

    backend = FakeBackend([FakeRawSensor("callibri", "CA-1")])
    assert main(["--scan", "--json"], backend_factory=lambda _s: backend) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith(SCAN_JSON_MARK))
    item = json.loads(line[len(SCAN_JSON_MARK) :])[0]
    assert set(item) == {"kind", "name", "serial", "address"}


def test_broken_stdout_ends_the_loop_and_releases_the_sensors() -> None:
    scanner = FakeScanner(devices(), time.monotonic)
    service = DiscoveryService(scanner, time.monotonic, time.sleep, probe_wait_s=0.0)
    written: list[str] = []

    def write(line: str) -> None:
        if written:
            raise BrokenPipeError("лаунчер закрыл вывод")
        written.append(line)

    inbox: Inbox = queue.Queue()
    inbox.put('{"cmd":"scan","on":true}\n')
    thread = threading.Thread(target=DiscoverySession(service, write).run, args=(inbox, 0.01))
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert scanner.events[-1] == "close"


def test_exception_in_the_loop_still_closes_the_scanner() -> None:
    scanner = FakeScanner(devices(), time.monotonic)
    service = DiscoveryService(scanner, time.monotonic, time.sleep)
    session = DiscoverySession(service, lambda line: None)

    def boom(line: str) -> bool:
        raise RuntimeError("сбой")

    session.handle_line = boom  # type: ignore[method-assign]
    inbox: Inbox = queue.Queue()
    inbox.put('{"cmd":"quit"}\n')
    with pytest.raises(RuntimeError):
        session.run(inbox, 0.01)
    assert scanner.events[-1] == "close"
