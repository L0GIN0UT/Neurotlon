"""Клиент моста: features, eeg_method, очередь burst, поля хода калибровки."""

import socket
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from neurotlon_bridge import protocol
from neurotlon_bridge.client import BridgeClient
from neurotlon_bridge.source import MAX_PENDING_BURSTS, Reading, Segment

TIMEOUT_S = 5.0


def wait_for(cond: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class OneShotServer:
    """Принимает одно подключение; отдаёт заданные сообщения и запоминает принятое."""

    def __init__(self) -> None:
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._conn: socket.socket | None = None
        self.received = b""
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        conn, _ = self._listener.accept()
        conn.settimeout(0.1)
        self._conn = conn
        while True:
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            self.received += chunk

    def send(self, *messages: protocol.Message) -> None:
        assert wait_for(lambda: self._conn is not None)
        assert self._conn is not None
        self._conn.sendall(b"".join(protocol.encode(m) for m in messages))

    def drop(self) -> None:
        assert self._conn is not None
        self._conn.close()

    def close(self) -> None:
        self._listener.close()
        if self._conn is not None:
            self._conn.close()


@pytest.fixture
def server() -> Iterator[OneShotServer]:
    srv = OneShotServer()
    yield srv
    srv.close()


@pytest.fixture
def client(server: OneShotServer) -> Iterator[BridgeClient]:
    c = BridgeClient(port=server.port, reconnect_s=0.05)
    yield c
    c.close()


HELLO = protocol.Hello(
    (("eeg", "connected"), ("emg", "emulated")),
    features=("burst", "emg_cycle"),
    eeg_method="alpha",
)


def test_features_and_eeg_method_come_from_hello(
    server: OneShotServer, client: BridgeClient
) -> None:
    assert not client.features
    assert client.eeg_method is None
    server.send(HELLO)
    assert wait_for(lambda: client.eeg_method == "alpha")
    assert client.features == ("burst", "emg_cycle")


def test_old_bridge_hello_leaves_features_empty(
    server: OneShotServer, client: BridgeClient
) -> None:
    server.send(protocol.Hello((("emg", "emulated"),)))
    assert wait_for(lambda: client.sensor_state("emg") == "emulated")
    assert client.features == ()
    assert client.eeg_method is None


def test_bursts_are_accumulated_in_order_and_drained(
    server: OneShotServer, client: BridgeClient
) -> None:
    server.send(
        HELLO,
        protocol.Burst("emg", 100, 1, 0.8),
        protocol.Burst("emg_left", 110, 1),
        protocol.Burst("emg", 500, 2),
    )
    got: list[protocol.Burst] = []

    def collect() -> bool:
        got.extend(client.bursts())
        return len(got) >= 3

    assert wait_for(collect)
    assert got == [
        protocol.Burst("emg", 100, 1, 0.8),
        protocol.Burst("emg_left", 110, 1),
        protocol.Burst("emg", 500, 2),
    ]
    assert client.bursts() == []


def test_burst_queue_is_bounded_and_keeps_newest(
    server: OneShotServer, client: BridgeClient
) -> None:
    total = MAX_PENDING_BURSTS + 10
    marker = protocol.Sample(1, {"emg": Reading(0.5)})
    server.send(HELLO, *(protocol.Burst("emg", i, i) for i in range(total)), marker)
    assert wait_for(lambda: client.latest("emg") is not None)  # marker идёт после всех burst
    queued = client.bursts()
    assert [b.seq for b in queued] == list(range(total - MAX_PENDING_BURSTS, total))


def test_calibration_progress_carries_cycle_fields(
    server: OneShotServer, client: BridgeClient
) -> None:
    server.send(
        HELLO,
        protocol.Calibration(
            "emg", "cycle", "running", 0.3, segment=2, phase="relax", phase_left_s=3.5
        ),
    )
    assert wait_for(lambda: client.calibration("emg") is not None)
    progress = client.calibration("emg")
    assert progress is not None
    assert (progress.segment, progress.phase, progress.phase_left_s) == (2, "relax", 3.5)


def test_new_connection_does_not_see_old_bursts(server: OneShotServer) -> None:
    c = BridgeClient(port=server.port, reconnect_s=0.05)
    try:
        server.send(HELLO, protocol.Burst("emg", 1, 1))
        assert wait_for(lambda: len(c.features) > 0)
        server.drop()
        assert wait_for(lambda: not c.connected)
        assert c.features == ()
        assert c.eeg_method is None
        assert c.bursts() == []
    finally:
        c.close()


def test_calibrate_sends_segments_and_duration(server: OneShotServer, client: BridgeClient) -> None:
    server.send(HELLO)
    assert wait_for(lambda: client.connected)
    segments = (Segment("tense", 4), Segment("relax", 3))
    assert client.calibrate("emg", "cycle", segments=segments)
    assert client.calibrate("eeg", "baseline", duration_s=15)
    assert wait_for(lambda: server.received.count(b"\n") >= 2)
    first, second = (protocol.decode(line) for line in server.received.splitlines())
    assert first == protocol.Calibrate("emg", "cycle", segments=segments)
    assert second == protocol.Calibrate("eeg", "baseline", duration_s=15)
