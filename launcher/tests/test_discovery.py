"""`DiscoveryClient`: разбор потока моста и запись команд, без настоящего процесса."""

import logging
import sys
import threading
from typing import Any

import pytest

from neurotlon_contracts.discovery import DISCOVERY_MARK, encode_message
from neurotlon_launcher.discovery import DiscoveryClient, PopenDiscoveryProcess
from neurotlon_launcher.testing_discovery import FakeProcess, devices, item, link, wait_until


class Listener:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.exits: list[str | None] = []

    def on_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def on_exit(self, error: str | None) -> None:
        self.exits.append(error)


def started(process: FakeProcess) -> tuple[DiscoveryClient, Listener]:
    listener = Listener()
    client = DiscoveryClient(process, listener)
    client.start()
    return client, listener


def test_messages_with_the_mark_are_parsed_and_sdk_noise_is_skipped() -> None:
    process = FakeProcess()
    client, listener = started(process)
    good = devices(item("AA:01", serial="BB-1"))
    process.feed_raw("[2026-11-23 16:23:49.183] [sdk_log] [warning] Failed start BLE scanner")
    process.feed(good)
    process.feed_raw(DISCOVERY_MARK + "{плохо")  # не JSON
    process.feed_raw(DISCOVERY_MARK + '{"type":"unknown"}')  # не по схеме
    process.feed_raw(DISCOVERY_MARK + '{"type":"link","id":"A","state":"connected","serial":"",')
    process.feed(link("AA:01", level=0.4, signal=True))
    process.feed_raw("sdk wrote without newline " + encode_message({"type": "hello", "v": 1}))
    wait_until(lambda: len(listener.messages) == 3)
    assert [m["type"] for m in listener.messages] == ["devices", "link", "hello"]
    assert listener.messages[0] == good
    process.exit(0)
    client.close()


def test_level_outside_zero_one_is_dropped_by_the_schema() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.feed(link("AA:01", level=1.7))
    process.feed(link("AA:01", level=0.5))
    wait_until(lambda: len(listener.messages) == 1)
    assert listener.messages[0]["level"] == 0.5
    client.close()


def test_commands_are_checked_against_the_schema_before_writing() -> None:
    process = FakeProcess()
    client, _ = started(process)
    assert client.send({"cmd": "scan", "on": True})
    assert client.send({"cmd": "connect", "id": "AA:01", "kind": "callibri"})
    assert client.send({"cmd": "release", "id": "AA:01"})
    assert not client.send({"cmd": "scan", "on": "да"})
    assert not client.send({"cmd": "connect", "id": "AA:01", "kind": "kolibri"})
    assert not client.send({"cmd": "connect", "id": "x" * 100, "kind": "callibri"})
    assert not client.send({"cmd": "format_disk"})
    assert [c["cmd"] for c in process.commands] == ["scan", "connect", "release"]
    client.close()


def test_send_fails_when_the_process_is_gone() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.exit(3, "Ошибка: нет адаптера")
    wait_until(lambda: bool(listener.exits))
    assert not client.alive
    assert not client.send({"cmd": "scan", "on": True})


def test_exit_reports_the_last_stderr_line() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.exit(3, "Ошибка: Bluetooth-адаптер не найден")
    wait_until(lambda: bool(listener.exits))
    assert listener.exits == ["Ошибка: Bluetooth-адаптер не найден"]
    client.close()


def test_exit_without_stderr_reports_the_code() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.exit(5)
    wait_until(lambda: bool(listener.exits))
    assert listener.exits == ["Поиск датчиков завершился (код 5)"]
    client.close()


def test_close_sends_quit_closes_stdin_and_does_not_report_an_exit() -> None:
    process = FakeProcess()
    client, listener = started(process)
    client.close()
    assert process.sent("quit") and process.input_closed and process.killed
    assert listener.exits == []  # свой выход не считается падением
    client.close()  # повторно безопасно
    assert len(process.sent("quit")) == 1


def test_close_does_not_wait_forever_for_a_process_that_ignores_quit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Stubborn(FakeProcess):
        def write(self, line: str) -> None:
            self.commands.append({"cmd": line})  # не выходит ни по quit, ни по закрытию stdin

        def close_input(self) -> None:
            self.input_closed = True

        def wait(self, timeout: float) -> bool:
            return self.returncode() is not None

    process = Stubborn()
    client, _ = started(process)
    with caplog.at_level(logging.WARNING):
        client.close()
    assert process.killed
    assert "принудительно" in caplog.text


def test_exceptions_in_the_listener_do_not_stop_reading() -> None:
    process = FakeProcess()

    class Bad(Listener):
        def on_message(self, message: dict[str, Any]) -> None:
            super().on_message(message)
            if message["type"] == "hello":
                raise RuntimeError("упало")

    listener = Bad()
    client = DiscoveryClient(process, listener)
    client.start()
    process.feed({"type": "hello", "v": 1}, {"type": "error", "message": "x"})
    wait_until(lambda: len(listener.messages) == 2)
    client.close()


def test_concurrent_senders_do_not_interleave_lines() -> None:
    process = FakeProcess()
    client, _ = started(process)

    def spam() -> None:
        for _ in range(50):
            client.send({"cmd": "scan", "on": True})

    threads = [threading.Thread(target=spam) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(process.sent("scan")) == 200
    client.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object только на Windows")
def test_real_process_roundtrip_through_pipes() -> None:
    code = (
        "import sys, json\n"
        "print('NEUROTLON_DISCOVERY=' + json.dumps({'type': 'hello', 'v': 1}), flush=True)\n"
        "for line in sys.stdin:\n"
        "    if json.loads(line)['cmd'] == 'quit':\n"
        "        break\n"
    )
    listener = Listener()
    process = PopenDiscoveryProcess([sys.executable, "-c", code])
    client = DiscoveryClient(process, listener)
    client.start()
    wait_until(lambda: bool(listener.messages), 15)
    assert listener.messages == [{"type": "hello", "v": 1}]
    client.close()
    assert process.returncode() is not None


def test_reader_survives_deep_nesting_huge_lines_and_garbage() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.feed_raw(DISCOVERY_MARK + "[" * 5000 + "]" * 5000)  # RecursionError в json
    process.feed_raw(DISCOVERY_MARK + "x" * (1024 * 1024))  # 1 МиБ без перевода строки
    process.feed_raw(DISCOVERY_MARK + '{"type":"error","message":"' + "я" * 70000 + '"}')
    process.feed_raw(DISCOVERY_MARK + '{"type":"link","level":NaN}')
    process.feed({"type": "hello", "v": 1})
    wait_until(lambda: len(listener.messages) == 1)
    assert listener.messages == [{"type": "hello", "v": 1}]  # поток чтения жив
    assert client.alive
    client.close()


def test_one_bad_item_does_not_cost_the_whole_list() -> None:
    process = FakeProcess()
    client, listener = started(process)
    bad = item("AA:02", name="x" * 200)
    process.feed(devices(item("AA:01"), bad, item("AA:03")))
    wait_until(lambda: bool(listener.messages))
    assert [i["id"] for i in listener.messages[0]["items"]] == ["AA:01", "AA:03"]
    client.close()


def test_long_stderr_is_cut_in_the_exit_message() -> None:
    process = FakeProcess()
    client, listener = started(process)
    process.exit(3, "Ошибка: " + "я" * 5000)
    wait_until(lambda: bool(listener.exits))
    assert listener.exits[0] is not None and len(listener.exits[0]) == 300
    client.close()


def test_bounded_lines_cuts_overlong_lines_and_keeps_the_rest() -> None:
    import io

    from neurotlon_launcher.discovery import bounded_lines

    stream = io.StringIO("короткая\n" + "я" * 100 + "\nещё одна\n" + "ю" * 50)
    assert list(bounded_lines(stream, 10)) == ["короткая\n", "", "ещё одна\n", ""]
    exact = io.StringIO("a" * 10 + "\nb\n")
    assert list(bounded_lines(exact, 10)) == ["a" * 10 + "\n", "b\n"]
    assert list(bounded_lines(io.StringIO(""), 10)) == []
    huge = io.StringIO("z" * 3_000_000 + "\nok\n")
    assert list(bounded_lines(huge)) == ["", "ok\n"]


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object только на Windows")
def test_real_process_streams_are_closed_after_close() -> None:
    code = "import sys\nfor line in sys.stdin:\n    pass\n"
    process = PopenDiscoveryProcess([sys.executable, "-c", code])
    client = DiscoveryClient(process, Listener())
    client.start()
    client.close()
    proc = process._proc
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed
