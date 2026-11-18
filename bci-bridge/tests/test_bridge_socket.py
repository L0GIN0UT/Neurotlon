"""Интеграция: сервер и клиент по настоящему localhost-сокету."""

import asyncio
import contextlib
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from neurotlon_bridge import protocol
from neurotlon_bridge.client import BridgeClient
from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.server import BridgeServer, BridgeThread

TIMEOUT_S = 5.0  # запас для медленного CI; быстрые тесты от него не зависят


def wait_for(cond: Callable[[], bool], timeout_s: float = TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class RawConn:
    """Сырое соединение: сообщения по порядку, чтение всегда ограничено таймаутом."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT_S)
        self.sock.settimeout(0.2)
        self.buf = b""

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def next_message(self, timeout_s: float = TIMEOUT_S) -> protocol.Message | None:
        """Следующее известное сообщение; None - соединение закрыто или время вышло."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if b"\n" in self.buf:
                line, _, self.buf = self.buf.partition(b"\n")
                msg = protocol.decode(line)
                if msg is not None:
                    return msg
                continue
            try:
                chunk = self.sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            self.buf += chunk
        return None

    def wait_closed(self, timeout_s: float = TIMEOUT_S) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if not self.sock.recv(65536):
                    return True
            except TimeoutError:
                continue
            except OSError:
                return True
        return False

    def close(self) -> None:
        self.sock.close()


class Env:
    def __init__(self, rate_hz: float = 200, speed: float = 8.0) -> None:
        self.source = EmulatedSource("darts", time.monotonic, speed=speed)
        self.server = BridgeServer(
            self.source, port=0, rate_hz=rate_hz, calibration_interval_s=0.02
        )
        self.thread = BridgeThread(self.server)
        self.thread.start()

    def client(self, **kwargs: Any) -> BridgeClient:
        kwargs.setdefault("reconnect_s", 0.05)
        return BridgeClient("127.0.0.1", self.server.port, **kwargs)

    def raw(self) -> RawConn:
        return RawConn(self.server.port)


@pytest.fixture
def env() -> Iterator[Env]:
    e = Env()
    yield e
    e.thread.stop()


def test_hello_and_samples(env: Env) -> None:
    client = env.client()
    try:
        assert wait_for(lambda: client.latest("emg") is not None)
        assert client.sensor_state("eeg") == "emulated"
        assert client.sensor_state("emg") == "emulated"
        reading = client.latest("eeg")
        assert reading is not None and reading.valid and reading.value == 0.5
    finally:
        client.close()


def test_t_ms_is_monotonic(env: Env) -> None:
    conn = env.raw()
    try:
        assert isinstance(conn.next_message(), protocol.Hello)
        times: list[int] = []
        while len(times) < 20:
            msg = conn.next_message()
            assert msg is not None
            if isinstance(msg, protocol.Sample):
                times.append(msg.t_ms)
        assert times == sorted(times)
        assert times[-1] > times[0]
    finally:
        conn.close()


def test_value_follows_keys(env: Env) -> None:
    client = env.client()
    try:
        env.source.set_keys({"emg", "eeg_artifact"})
        env.source.tick(2.0)

        def high() -> bool:
            r = client.latest("emg")
            return r is not None and r.value > 0.99

        assert wait_for(high)
        eeg = client.latest("eeg")
        assert eeg is not None and not eeg.valid and eeg.reason == "artifact"
    finally:
        client.close()


def test_calibration_messages_in_order(env: Env) -> None:
    conn = env.raw()
    try:
        assert isinstance(conn.next_message(), protocol.Hello)
        conn.send(protocol.encode(protocol.Calibrate("emg", "rest")))
        statuses: list[str] = []
        progresses: list[float] = []
        while not statuses or statuses[-1] != "done":
            msg = conn.next_message()
            assert msg is not None, f"соединение прервано, получено: {statuses}"
            if isinstance(msg, protocol.Calibration):
                assert (msg.signal, msg.step) == ("emg", "rest")
                statuses.append(msg.status)
                if msg.status == "running":
                    assert msg.progress is not None
                    progresses.append(msg.progress)
        assert statuses[0] == "running"
        assert set(statuses[:-1]) == {"running"}
        assert progresses == sorted(progresses)
    finally:
        conn.close()


def test_client_calibrate_and_reset(env: Env) -> None:
    client = env.client()
    try:
        assert wait_for(lambda: client.connected)
        assert wait_for(lambda: client.calibrate("emg", "rest"))

        def done() -> bool:
            status = client.calibration("emg")
            return status is not None and status.status == "done"

        assert wait_for(done)
        status = client.calibration("emg")
        assert status is not None and status.progress == 1.0
        client.reset()
        assert client.calibration("emg") is None
        assert wait_for(lambda: env.source.calibration_status("emg") is None)
    finally:
        client.close()


def test_second_connection_rejected_until_first_closes(env: Env) -> None:
    first = env.client()
    try:
        assert wait_for(lambda: first.latest("emg") is not None)
        intruder = env.raw()
        try:
            assert intruder.next_message(timeout_s=TIMEOUT_S) is None  # закрыт без hello
        finally:
            intruder.close()
        assert first.connected or wait_for(lambda: first.connected)
        first.close()
        second = env.client()
        try:
            assert wait_for(lambda: second.latest("emg") is not None)
        finally:
            second.close()
    finally:
        first.close()


def test_malformed_lines_do_not_kill_server(env: Env) -> None:
    conn = env.raw()
    try:
        assert isinstance(conn.next_message(), protocol.Hello)
        conn.send(b'garbage\n{"type":"calibrate","signal":"zzz","step":"rest"}\n')
        conn.send(b'{"type":"unknown"}\n\xff\xfe\n{"type":"x","v":NaN}\n')
        samples = 0
        while samples < 3:
            msg = conn.next_message()
            assert msg is not None
            samples += isinstance(msg, protocol.Sample)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "line",
    [
        b'{"type":"calibrate","signal":"emg","step":"rest","x":NaN}\n',
        b'{"type":"calibrate","signal":"emg","step":"rest","x":Infinity}\n',
        b'{"type":"calibrate","signal":"emg","step":"rest","x":-Infinity}\n',
    ],
)
def test_nan_infinity_lines_ignored(env: Env, line: bytes) -> None:
    conn = env.raw()
    try:
        assert isinstance(conn.next_message(), protocol.Hello)
        conn.send(line)
        for _ in range(5):
            assert isinstance(conn.next_message(), protocol.Sample)
        assert env.source.calibration_status("emg") is None
    finally:
        conn.close()


def test_overlong_line_drops_connection_and_frees_slot(env: Env) -> None:
    conn = env.raw()
    try:
        assert isinstance(conn.next_message(), protocol.Hello)
        with contextlib.suppress(OSError):  # сервер мог уже закрыть соединение
            conn.send(b"x" * (300 * 1024))  # без перевода строки
        assert conn.wait_closed()
    finally:
        conn.close()
    client = env.client()
    try:
        assert wait_for(lambda: client.latest("emg") is not None)
    finally:
        client.close()


def test_stalled_writer_is_dropped() -> None:
    """Клиент, который не читает: drain не завершается, сервер сбрасывает соединение."""

    class Transport:
        aborted = False

        def abort(self) -> None:
            self.aborted = True

    class StuckWriter:
        def __init__(self) -> None:
            self.transport = Transport()

        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            await asyncio.sleep(30)

    server = BridgeServer(EmulatedSource("darts", time.monotonic), port=0, write_timeout_s=0.05)
    writer = StuckWriter()

    async def run() -> None:
        await server._write(writer, b"x")  # type: ignore[arg-type]

    with pytest.raises(ConnectionError):
        asyncio.run(run())
    assert writer.transport.aborted


def test_client_marks_stale_with_fake_clock() -> None:
    env = Env()
    clock = FakeClock()
    client = env.client(clock=clock)
    try:
        assert wait_for(lambda: client.latest("emg") is not None)
        env.thread.stop()
        assert wait_for(lambda: not client.connected)
        assert client.sensor_state("emg") is None  # состояния сброшены при разрыве
        last = client.latest("emg")
        assert last is not None and last.valid
        clock.now += 0.4
        fresh = client.latest("emg")
        assert fresh is not None and fresh.valid
        clock.now += 0.2
        stale = client.latest("emg")
        assert stale is not None and (stale.valid, stale.reason, stale.value) == (False, "stale", 0)
    finally:
        client.close()


def test_client_returns_none_before_any_data() -> None:
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    client = BridgeClient("127.0.0.1", silent.getsockname()[1], reconnect_s=0.05)
    try:
        assert wait_for(lambda: client.connected)
        assert client.latest("emg") is None
        assert client.sensor_state("emg") is None
    finally:
        client.close()
        silent.close()


def _fake_bridge(payload: bytes) -> tuple[socket.socket, int]:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    return srv, srv.getsockname()[1]


def test_client_drops_overlong_line_and_survives_garbage() -> None:
    srv, port = _fake_bridge(b"")
    client = BridgeClient("127.0.0.1", port, reconnect_s=0.05)
    try:
        srv.settimeout(TIMEOUT_S)
        conn, _ = srv.accept()
        conn.sendall(
            b'garbage\n{"type":"sample","t_ms":1,"signals":{"emg":{"value":NaN,"valid":true}}}\n'
        )
        conn.sendall(b'{"type":"sample","t_ms":2,"signals":{"emg":{"value":0.3,"valid":true}}}\n')
        assert wait_for(lambda: client.latest("emg") is not None)
        with contextlib.suppress(OSError):
            conn.sendall(b"y" * (200 * 1024))
        conn.settimeout(0.2)
        closed = False
        deadline = time.monotonic() + TIMEOUT_S
        while not closed and time.monotonic() < deadline:
            try:
                closed = not conn.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                closed = True
        assert closed
        conn.close()
        # поток клиента жив: переподключается
        conn2, _ = srv.accept()
        conn2.sendall(b'{"type":"sample","t_ms":3,"signals":{"emg":{"value":0.9,"valid":true}}}\n')
        assert wait_for(lambda: (r := client.latest("emg")) is not None and r.value == 0.9)
        conn2.close()
    finally:
        client.close()
        srv.close()


def test_thread_stop_without_start_is_safe() -> None:
    server = BridgeServer(EmulatedSource("darts", time.monotonic), port=0)
    BridgeThread(server).stop()


def test_client_does_not_import_pygame() -> None:
    code = "import sys, neurotlon_bridge.client; sys.exit('pygame' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
