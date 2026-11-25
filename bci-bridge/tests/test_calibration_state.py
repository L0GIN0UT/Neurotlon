"""Состояние калибровки: поле `hello.calibrated`, клиент, настройки, процессоры, `--state-dir`."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from neurotlon_bridge import hardware_source, protocol
from neurotlon_bridge.__main__ import main
from neurotlon_bridge.calibration_store import FILE_NAME, FileCalibrationStore
from neurotlon_bridge.client import BridgeClient
from neurotlon_bridge.config import (
    CONFIG_NAME,
    BridgeConfig,
    CalibrationConfig,
    ConfigError,
    load_config,
    parse_config,
)
from neurotlon_bridge.devices.fakes import FakeBackend, FakeRawSensor
from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.processing.alpha import AlphaConfig, AlphaEngine
from neurotlon_bridge.processing.eeg import EegProcessor, EegResult, PersistentEngine
from neurotlon_bridge.processing.emg import EmgConfig, EmgProcessor
from neurotlon_bridge.server import FEATURES, BridgeServer, BridgeThread

EXAMPLE = Path(__file__).resolve().parents[1] / "bridge.example.toml"
TIMEOUT_S = 5.0


def wait_for(cond: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# --- протокол ---


def test_hello_calibrated_roundtrip() -> None:
    hello = protocol.Hello(
        (("eeg", "connected"), ("emg", "connected")),
        features=("calibration_state",),
        eeg_method="alpha",
        calibrated=("emg",),
    )
    assert protocol.decode(protocol.encode(hello)) == hello
    assert protocol.to_dict(hello)["calibrated"] == ["emg"]


def test_hello_without_calibrated_has_no_field() -> None:
    hello = protocol.Hello((("emg", "connected"),))
    assert "calibrated" not in protocol.to_dict(hello)
    assert protocol.decode(protocol.encode(hello)) == hello


def test_empty_calibrated_is_kept() -> None:
    hello = protocol.Hello((("emg", "connected"),), calibrated=())
    assert protocol.to_dict(hello)["calibrated"] == []
    decoded = protocol.decode(protocol.encode(hello))
    assert isinstance(decoded, protocol.Hello) and decoded.calibrated == ()


def test_decode_skips_unknown_names_in_calibrated() -> None:
    line = (
        '{"type":"hello","protocol":1,"signals":[{"name":"emg","state":"connected"}],'
        '"calibrated":["gsr","emg",7]}'
    )
    decoded = protocol.decode(line)
    assert isinstance(decoded, protocol.Hello) and decoded.calibrated == ("emg",)


def test_decode_ignores_calibrated_of_wrong_type() -> None:
    line = (
        '{"type":"hello","protocol":1,"signals":[{"name":"emg","state":"connected"}],'
        '"calibrated":"emg"}'
    )
    decoded = protocol.decode(line)
    assert isinstance(decoded, protocol.Hello) and decoded.calibrated is None


def test_server_announces_calibration_state() -> None:
    assert "calibration_state" in FEATURES


# --- мост с эмулятором: калибровка не нужна ---


def test_emulator_hello_has_empty_calibrated_and_emulated_states() -> None:
    server = BridgeServer(EmulatedSource("darts", time.monotonic), port=0, eeg_method="alpha")
    thread = BridgeThread(server)
    thread.start()
    try:
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=TIMEOUT_S)
        with sock:
            line = sock.makefile("rb").readline()
        hello = json.loads(line)
        assert hello["calibrated"] == []
        assert {s["state"] for s in hello["signals"]} == {"emulated"}
    finally:
        thread.stop()


# --- клиент ---


class OneShotServer:
    def __init__(self) -> None:
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._conn: socket.socket | None = None
        self.received = b""
        threading.Thread(target=self._accept, daemon=True).start()

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
    (("eeg", "connected"), ("emg", "connected")),
    features=("calibration_state",),
    eeg_method="alpha",
    calibrated=("emg",),
)


def test_client_reads_calibrated_from_hello(server: OneShotServer, client: BridgeClient) -> None:
    assert not client.calibrated("emg")
    server.send(HELLO)
    assert wait_for(lambda: client.calibrated("emg"))
    assert not client.calibrated("eeg")


def test_client_of_old_bridge_never_sees_calibrated(
    server: OneShotServer, client: BridgeClient
) -> None:
    server.send(protocol.Hello((("emg", "connected"),)))
    assert wait_for(lambda: client.sensor_state("emg") == "connected")
    assert not client.calibrated("emg")


def test_client_forgets_calibrated_on_reset_and_on_disconnect(
    server: OneShotServer, client: BridgeClient
) -> None:
    server.send(HELLO)
    assert wait_for(lambda: client.calibrated("emg"))
    assert client.reset()
    assert not client.calibrated("emg")
    server.send(HELLO)
    assert wait_for(lambda: client.calibrated("emg"))
    server.drop()
    assert wait_for(lambda: not client.calibrated("emg"))


# --- настройки ---


def test_ttl_default_and_example_file() -> None:
    assert BridgeConfig().calibration == CalibrationConfig(ttl_h=4.0)
    assert load_config(EXAMPLE).calibration == BridgeConfig().calibration
    assert BridgeConfig().calibration.ttl_s == 4 * 3600


def test_ttl_override_accepts_integers() -> None:
    assert parse_config({"calibration": {"ttl_h": 2}}).calibration.ttl_h == 2.0
    assert parse_config({"calibration": {"ttl_h": 0.5}}).calibration.ttl_s == 1800


@pytest.mark.parametrize(
    "section",
    [{"ttl_h": 0}, {"ttl_h": -1}, {"ttl_h": 24 * 30}, {"ttl_h": "4"}, {"ttl_h": True}, {"x": 1}],
)
def test_bad_ttl_is_a_config_error(section: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"calibration": section})


# --- процессоры ---


def test_emg_processor_exports_and_restores_scale() -> None:
    proc = EmgProcessor(EmgConfig(settle_s=0.0))
    assert proc.export_calibration() is None
    proc.restore_calibration(3.0, 40.0)
    assert proc.calibrated
    assert proc.export_calibration() == (3.0, 40.0)
    proc.reset()
    assert proc.export_calibration() is None


@pytest.mark.parametrize(
    ("rest", "peak"),
    [(5.0, 5.0), (9.0, 1.0), (-1.0, 2.0), (float("nan"), 2.0), (1.0, float("inf"))],
)
def test_emg_processor_refuses_bad_scale(rest: float, peak: float) -> None:
    proc = EmgProcessor(EmgConfig(settle_s=0.0))
    with pytest.raises(ValueError):
        proc.restore_calibration(rest, peak)
    assert not proc.calibrated


def test_emg_restored_scale_gives_levels() -> None:
    proc = EmgProcessor(EmgConfig(settle_s=0.0))
    proc.restore_calibration(5.0, 25.0)
    proc._last_rms = 15.0
    reading = proc.reading()
    assert reading.valid and reading.value == pytest.approx(0.5)


class _Engine:
    """Движок с выгрузкой границ (как `AlphaEngine`)."""

    def __init__(self) -> None:
        self.bounds: tuple[float, float] | None = None
        self.closed = False

    @property
    def calibrated(self) -> bool:
        return self.bounds is not None

    @property
    def progress(self) -> float:
        return 1.0 if self.bounds else 0.0

    @property
    def failure(self) -> str | None:
        return None

    def start_calibration(self, duration_s: float) -> None:
        self.bounds = (0.2, 0.6)

    def push(self, volts: np.ndarray) -> None:
        pass

    def result(self) -> EegResult:
        return EegResult(0.5, True, False)

    def close(self) -> None:
        self.closed = True

    def export_bounds(self) -> tuple[float, float] | None:
        return self.bounds

    def restore_bounds(self, low: float, high: float) -> None:
        self.bounds = (low, high)


class _PlainEngine(_Engine):
    """Без выгрузки (как `Pyem`)."""

    export_bounds = None  # type: ignore[assignment]
    restore_bounds = None  # type: ignore[assignment]


def test_eeg_processor_exports_after_calibration_only() -> None:
    proc = EegProcessor(_Engine)
    assert proc.export_calibration() is None
    assert not proc.calibrated
    proc.start_calibration("baseline")
    assert proc.calibrated
    assert proc.export_calibration() == (0.2, 0.6)
    proc.reset()
    assert proc.export_calibration() is None


def test_eeg_processor_restores_into_a_fresh_engine() -> None:
    engines: list[_Engine] = []

    def factory() -> _Engine:
        engines.append(_Engine())
        return engines[-1]

    proc = EegProcessor(factory)
    assert proc.restore_calibration(0.1, 0.5)
    assert proc.calibrated
    assert proc.export_calibration() == (0.1, 0.5)
    assert proc.calibration_status() is None
    assert proc.reading().reason == "stale"  # данных ещё нет, но шкала есть
    assert proc.restore_calibration(0.3, 0.9)
    assert engines[0].closed  # прежний движок освобождён


def test_eeg_processor_refuses_when_engine_cannot_restore() -> None:
    engines: list[_PlainEngine] = []

    def factory() -> _PlainEngine:
        engines.append(_PlainEngine())
        return engines[-1]

    proc = EegProcessor(factory)
    assert not proc.restore_calibration(0.1, 0.5)
    assert not proc.calibrated
    assert engines[0].closed
    proc.start_calibration("baseline")
    assert proc.calibrated
    assert proc.export_calibration() is None  # метод без выгрузки не сохраняется


def test_eeg_processor_refuses_bad_bounds_from_the_engine() -> None:
    cfg = AlphaConfig()
    proc = EegProcessor(lambda: AlphaEngine(cfg, 250, time.monotonic))
    assert not proc.restore_calibration(0.5, 0.5)
    assert not proc.calibrated


def test_alpha_engine_is_persistent_and_restores_bounds() -> None:
    engine = AlphaEngine(AlphaConfig(), 250, time.monotonic)
    assert isinstance(engine, PersistentEngine)
    assert engine.export_bounds() is None
    engine.restore_bounds(0.1, 0.4)
    assert engine.calibrated
    assert engine.progress == 1.0
    assert engine.export_bounds() == (0.1, 0.4)
    with pytest.raises(ValueError):
        engine.restore_bounds(0.4, 0.1)
    with pytest.raises(ValueError):
        engine.restore_bounds(float("nan"), 0.1)


# --- --state-dir ---


def _write_config(folder: Path) -> Path:
    path = folder / CONFIG_NAME
    path.write_text('[devices]\neeg = "BB1"\nemg = "C1"\n', encoding="utf-8")
    return path


def _run_hardware(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> Path:
    class _Server:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def serve_forever(self) -> None:
            return None

    monkeypatch.setattr("neurotlon_bridge.__main__.BridgeServer", _Server)
    paths: list[Path] = []
    real = hardware_source.HardwareSource

    class Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, *a: object, **kwargs: object) -> None:
            store = kwargs.get("store")
            assert isinstance(store, FileCalibrationStore)
            paths.append(store.path)
            super().__init__(*a, **kwargs)

    monkeypatch.setattr(hardware_source, "HardwareSource", Recording)
    backend = FakeBackend([FakeRawSensor("brainbit", "BB1"), FakeRawSensor("callibri", "C1")])
    assert main([*args, "--headless"], backend_factory=lambda _scan_s: backend) == 0
    return paths[0]


def test_state_dir_defaults_to_the_config_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _write_config(tmp_path)
    assert _run_hardware(monkeypatch, ["--config", str(config)]) == tmp_path / FILE_NAME


def test_state_dir_can_be_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    data = tmp_path / "data"
    path = _run_hardware(monkeypatch, ["--config", str(config), "--state-dir", str(data)])
    assert path == data / FILE_NAME
