import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from neurotlon_bridge.calibration_store import (
    FILE_NAME,
    CalibrationRecord,
    CalibrationStore,
    FileCalibrationStore,
    MemoryStore,
)
from neurotlon_bridge.config import BridgeConfig, CalibrationConfig, ConfigError
from neurotlon_bridge.devices.fakes import FakeBackend, FakeClock, FakeRawSensor
from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.hardware_source import HardwareSource, make_engine_factory
from neurotlon_bridge.processing.alpha import AlphaEngine
from neurotlon_bridge.processing.eeg import EegResult
from neurotlon_bridge.processing.emg import EmgConfig
from neurotlon_bridge.server import BridgeServer
from neurotlon_bridge.source import EegMethod, Segment

FAST_EMG = EmgConfig(
    settle_s=0.0,
    calib_rest_s=1.0,
    calib_contractions=1,
    calib_contraction_s=1.0,
    calib_pause_s=0.5,
)
REST = 3.0
BURST = 100.0


class FakeEngine:
    def __init__(self) -> None:
        self.started = False
        self.percent = 0
        self.fail: str | None = None
        self.duration_s: float | None = None
        self.closed = False
        self.res = EegResult(0.6, True, False)

    @property
    def calibrated(self) -> bool:
        return self.started and self.percent >= 100

    @property
    def progress(self) -> float:
        return self.percent / 100.0

    @property
    def failure(self) -> str | None:
        return self.fail

    def start_calibration(self, duration_s: float) -> None:
        self.started = True
        self.duration_s = duration_s

    def push(self, volts: np.ndarray) -> None:
        self.percent = min(100, self.percent + 50)  # два пакета — и калибровка готова

    def result(self) -> EegResult:
        return self.res

    def close(self) -> None:
        self.closed = True


class Rig:
    engine_cls: type[FakeEngine] = FakeEngine

    def __init__(
        self,
        profile: str,
        serials: dict[str, str],
        *,
        store: CalibrationStore | None = None,
        wall_clock: Callable[[], float] = time.time,
        eeg_method: EegMethod = "alpha",
        calibration: CalibrationConfig | None = None,
    ) -> None:
        kinds = {"eeg": "brainbit"}
        self.raws = {
            sig: FakeRawSensor(kinds.get(sig, "callibri"), sn)  # type: ignore[arg-type]
            for sig, sn in serials.items()
        }
        self.backend = FakeBackend(list(self.raws.values()))
        self.clock = FakeClock(10.0)
        self.engines: list[FakeEngine] = []
        config = BridgeConfig(
            devices=serials, emg=FAST_EMG, calibration=calibration or CalibrationConfig()
        )
        self.src = HardwareSource(
            profile,
            config,
            self.backend,
            self.clock,
            threaded=False,
            engine_factory=self._engine,
            eeg_method=eeg_method,
            store=store,
            wall_clock=wall_clock,
        )
        self.rng = np.random.default_rng(7)
        self.src.start()
        deadline = time.monotonic() + 3
        while (
            any(self.src.state(s) != "connected" for s in serials) and time.monotonic() < deadline
        ):
            time.sleep(0.01)

    def _engine(self) -> FakeEngine:
        self.engines.append(self.engine_cls())
        return self.engines[-1]

    def run(self, seconds: float, sigmas: dict[str, float]) -> None:
        """Каждый указанный датчик шлёт шум своей амплитуды (мкВ), остальные молчат."""
        for _ in range(round(seconds / 0.02)):
            for sig, sigma in sigmas.items():
                raw = self.raws[sig]
                if raw.kind == "brainbit":
                    raw.emit_samples(self.rng.normal(0, 1e-5, (6, 4)).tolist())
                else:
                    raw.emit_samples((self.rng.normal(0, sigma, (20, 1)) * 1e-6).tolist())
            self.clock.advance(0.02)
            self.src.step()

    def calibrate_emg(self, signal: str) -> None:
        self.src.start_calibration(signal, "rest")
        self.run(1.2, {signal: REST})
        self.src.start_calibration(signal, "contract")
        self.run(1.6, {signal: BURST})
        self.run(0.2, {signal: REST})


PONG = {"emg_left": "CAL-L", "emg_right": "CAL-R"}
DARTS = {"eeg": "BB-1", "emg": "CAL-1"}


def test_darts_maps_serials_to_signals() -> None:
    rig = Rig("darts", DARTS)
    assert rig.backend.open_calls == ["BB-1", "CAL-1"] or rig.backend.open_calls == [
        "CAL-1",
        "BB-1",
    ]
    assert rig.src.signals() == ("eeg", "emg")
    assert rig.src.state("eeg") == "connected"
    assert rig.src.battery("emg") == 80
    assert rig.src.serial("eeg") == "BB-1"
    rig.src.close()


def test_pong_maps_two_callibri() -> None:
    rig = Rig("pong", PONG)
    assert sorted(rig.backend.open_calls) == ["CAL-L", "CAL-R"]
    assert rig.src.signals() == ("emg_left", "emg_right")
    rig.src.close()


@pytest.mark.parametrize(
    ("profile", "devices", "missing"),
    [
        ("darts", {"eeg": "BB-1"}, "emg"),
        ("football", {"emg": "C"}, "eeg"),
        ("pong", {"emg_left": "L"}, "emg_right"),
    ],
)
def test_missing_serial_is_config_error(
    profile: str, devices: dict[str, str], missing: str
) -> None:
    backend = FakeBackend()
    with pytest.raises(ConfigError, match=missing):
        HardwareSource(profile, BridgeConfig(devices=devices), backend, threaded=False)
    assert backend.open_calls == []


def test_same_serial_twice_is_config_error() -> None:
    config = BridgeConfig(devices={"emg_left": "X", "emg_right": "x"})
    with pytest.raises(ConfigError, match="один и тот же"):
        HardwareSource("pong", config, FakeBackend(), threaded=False)


def test_unknown_profile() -> None:
    with pytest.raises(ValueError):
        HardwareSource("chess", BridgeConfig(), FakeBackend(), threaded=False)


def test_unknown_signal_and_wrong_step() -> None:
    rig = Rig("darts", DARTS)
    with pytest.raises(ValueError):
        rig.src.state("emg_left")
    with pytest.raises(ValueError):
        rig.src.start_calibration("emg", "baseline")
    with pytest.raises(ValueError):
        rig.src.start_calibration("eeg", "rest")
    rig.src.close()


def test_device_not_found_keeps_other_channel_alive() -> None:
    rig = Rig("pong", PONG)
    rig.src.close()
    backend = FakeBackend([FakeRawSensor("callibri", "CAL-L")])
    config = BridgeConfig(devices=PONG, emg=FAST_EMG)
    src = HardwareSource("pong", config, backend, FakeClock(), threaded=False)
    src.start()
    deadline = time.monotonic() + 3
    while src.state("emg_left") != "connected" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert src.state("emg_left") == "connected"
    assert src.state("emg_right") == "disconnected"
    readings = src.read(0)
    assert (readings["emg_right"].valid, readings["emg_right"].reason) == (False, "disconnected")
    src.close()


def test_two_callibri_never_share_state() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    # правый не калибровался: свой процессор, свой not_calibrated
    rig.run(0.5, {"emg_left": REST, "emg_right": REST})
    readings = rig.src.read(0)
    assert readings["emg_left"].valid
    assert (readings["emg_right"].valid, readings["emg_right"].reason) == (False, "not_calibrated")
    assert rig.src.calibration_status("emg_right") is None
    left_status = rig.src.calibration_status("emg_left")
    assert left_status is not None
    assert left_status.status == "done"
    rig.src.close()


def test_burst_on_left_does_not_move_right() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.calibrate_emg("emg_right")
    rig.run(1.0, {"emg_left": REST, "emg_right": REST})
    quiet = rig.src.read(0)
    assert quiet["emg_left"].value < 0.15
    assert quiet["emg_right"].value < 0.15

    rig.run(1.0, {"emg_left": BURST, "emg_right": REST})
    left_burst = rig.src.read(0)
    assert left_burst["emg_left"].value > 0.6
    assert left_burst["emg_right"].value < 0.15

    rig.run(1.0, {"emg_left": REST, "emg_right": BURST})
    right_burst = rig.src.read(0)
    assert right_burst["emg_left"].value < 0.15
    assert right_burst["emg_right"].value > 0.6
    rig.src.close()


def test_calibrating_one_channel_does_not_start_other() -> None:
    rig = Rig("pong", PONG)
    rig.src.start_calibration("emg_left", "rest")
    rig.run(0.5, {"emg_left": REST, "emg_right": REST})
    assert rig.src.calibration_status("emg_left").status == "running"  # type: ignore[union-attr]
    assert rig.src.calibration_status("emg_right") is None
    rig.src.close()


def test_reset_clears_every_channel() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.calibrate_emg("emg_right")
    rig.src.reset()
    rig.run(0.3, {"emg_left": REST, "emg_right": REST})
    for name in PONG:
        assert rig.src.calibration_status(name) is None
        assert rig.src.read(0)[name].reason == "not_calibrated"
    rig.src.close()


def test_stale_when_data_stops() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(0.2, {"emg_left": REST})
    assert rig.src.read(0)["emg_left"].valid
    rig.clock.advance(0.6)
    reading = rig.src.read(0)["emg_left"]
    assert (reading.valid, reading.reason) == (False, "stale")


def test_electrode_detached_means_no_contact() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(0.2, {"emg_left": REST})
    rig.raws["emg_left"].emit_electrode(False)
    assert rig.src.read(0)["emg_left"].reason == "no_contact"
    assert rig.src.read(0)["emg_right"].reason != "no_contact"
    rig.raws["emg_left"].emit_electrode(True)
    rig.run(0.1, {"emg_left": REST})
    assert rig.src.read(0)["emg_left"].valid
    rig.src.close()


def test_disconnect_and_reconnect_resets_filters_keeps_calibration() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(0.2, {"emg_left": REST})
    raw = rig.raws["emg_left"]
    raw.emit_state(False)
    rig.src.step()
    assert rig.src.state("emg_left") == "disconnected"
    assert rig.src.read(0)["emg_left"].reason == "disconnected"
    raw.emit_state(True)
    rig.src.step()
    assert rig.src.state("emg_left") == "connected"
    assert rig.src.read(0)["emg_left"].reason == "stale"  # фильтры с нуля, данных ещё нет
    rig.run(0.5, {"emg_left": REST})
    after = rig.src.read(0)["emg_left"]
    assert after.valid
    assert after.value < 0.15


def test_disconnect_during_calibration_fails_it() -> None:
    rig = Rig("pong", PONG)
    rig.src.start_calibration("emg_left", "rest")
    rig.run(0.3, {"emg_left": REST})
    rig.raws["emg_left"].emit_state(False)
    rig.src.step()
    status = rig.src.calibration_status("emg_left")
    assert status is not None
    assert (status.status, status.reason) == ("failed", "датчик отключён")
    rig.src.close()


def test_darts_eeg_calibration_and_calm() -> None:
    rig = Rig("darts", DARTS)
    assert rig.src.read(0)["eeg"].reason == "stale"
    rig.run(0.1, {"eeg": 0})
    assert rig.src.read(0)["eeg"].reason == "not_calibrated"
    rig.src.start_calibration("eeg", "baseline")
    rig.run(0.1, {"eeg": 0})
    status = rig.src.calibration_status("eeg")
    assert status is not None
    assert (status.step, status.status) == ("baseline", "done")
    rig.run(0.1, {"eeg": 0})
    reading = rig.src.read(0)["eeg"]
    assert reading.valid
    assert reading.value == pytest.approx(0.6)
    rig.engines[0].res = EegResult(0.6, True, True)
    rig.run(0.1, {"eeg": 0})
    assert rig.src.read(0)["eeg"].reason == "artifact"
    rig.src.reset()
    assert rig.engines[0].closed
    assert rig.src.read(0)["eeg"].reason == "not_calibrated"
    rig.src.close()


def test_darts_eeg_and_emg_independent() -> None:
    rig = Rig("darts", DARTS)
    rig.calibrate_emg("emg")
    rig.run(0.3, {"emg": BURST})
    readings = rig.src.read(0)
    assert readings["emg"].valid
    assert readings["eeg"].reason in {"stale", "not_calibrated"}
    rig.src.close()


def test_close_releases_sensors_and_backend() -> None:
    rig = Rig("darts", DARTS)
    rig.src.close()
    assert all(raw.closed for raw in rig.raws.values())
    assert rig.backend.closed
    assert rig.engines == []


def test_threaded_source_produces_readings() -> None:
    raw = FakeRawSensor("callibri", "T-1")
    config = BridgeConfig(devices={"emg": "T-1", "eeg": "B-1"}, emg=FAST_EMG)
    bb = FakeRawSensor("brainbit", "B-1")
    src = HardwareSource("darts", config, FakeBackend([raw, bb]), engine_factory=FakeEngine)
    src.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            raw.emit_samples([[1e-6]] * 20) if raw.handlers else None
            if src.state("emg") == "connected" and src.read(0)["emg"].reason == "not_calibrated":
                break
            time.sleep(0.02)
        assert src.read(0)["emg"].reason == "not_calibrated"
    finally:
        src.close()


async def _read_lines(port: int, count: int) -> list[dict[str, object]]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        return [json.loads(await asyncio.wait_for(reader.readline(), 3)) for _ in range(count)]
    finally:
        writer.close()


def test_bridge_server_serves_hardware_source_unchanged() -> None:
    rig = Rig("pong", PONG)

    async def scenario() -> list[dict[str, object]]:
        server = BridgeServer(rig.src, port=0)
        await server.start()
        try:
            return await _read_lines(server.port, 3)
        finally:
            await server.stop()

    messages = asyncio.run(scenario())
    rig.src.close()
    assert messages[0]["type"] == "hello"
    assert messages[0]["signals"] == [
        {"name": "emg_left", "state": "connected"},
        {"name": "emg_right", "state": "connected"},
    ]
    sample = next(m for m in messages if m["type"] == "sample")
    signals = sample["signals"]
    assert isinstance(signals, dict)
    assert set(signals) == {"emg_left", "emg_right"}


def test_close_is_parallel_and_bounded() -> None:
    rig = Rig("pong", PONG)
    for raw in rig.raws.values():
        raw.close_delay_s = 0.4
    started = time.monotonic()
    rig.src.close()
    elapsed = time.monotonic() - started
    assert all(raw.closed for raw in rig.raws.values())
    assert elapsed < 0.7  # последовательно вышло бы 0,8 с


def test_close_announces_before_releasing() -> None:
    rig = Rig("pong", PONG)
    order: list[str] = []
    for name, raw in rig.raws.items():
        original = raw.close

        def close(name: str = name, original: Any = original) -> None:
            # к моменту освобождения первого датчика остальные уже знают о закрытии
            flags = [c.sensor._closing for c in rig.src._channels.values()]
            order.append(f"{name}:{flags}")
            original()

        raw.close = close  # type: ignore[method-assign]
    rig.src.close()
    assert order
    assert all(entry.endswith("[True, True]") for entry in order)


def test_sharp_contraction_gives_burst_only_on_that_channel() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.calibrate_emg("emg_right")
    rig.run(1.5, {"emg_left": REST, "emg_right": REST})
    rig.src.drain_bursts("emg_left")
    rig.src.drain_bursts("emg_right")
    onset = rig.clock()
    rig.run(1.0, {"emg_left": BURST, "emg_right": REST})
    left = rig.src.drain_bursts("emg_left")
    assert len(left) == 1
    assert 0.0 < left[0].t_s - onset < 0.4
    assert rig.src.drain_bursts("emg_right") == []
    assert rig.src.drain_bursts("emg_left") == []
    rig.src.close()


def test_darts_eeg_has_no_bursts_and_unknown_signal_is_an_error() -> None:
    rig = Rig("darts", DARTS)
    assert rig.src.drain_bursts("eeg") == []
    with pytest.raises(ValueError):
        rig.src.drain_bursts("emg_left")
    rig.src.close()


def test_no_burst_without_electrode_contact() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(1.5, {"emg_left": REST})
    rig.raws["emg_left"].emit_electrode(False)
    rig.run(1.0, {"emg_left": BURST})
    assert rig.src.drain_bursts("emg_left") == []
    rig.src.close()


def test_contact_loss_without_data_drops_the_arm() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(1.5, {"emg_left": REST})  # взведено
    rig.raws["emg_left"].emit_electrode(False)
    rig.src.step()  # потока данных нет, но взвод уже сброшен
    rig.raws["emg_left"].emit_electrode(True)
    rig.run(0.5, {"emg_left": BURST})  # сразу высокий уровень: старый спокойный уровень не в счёт
    assert rig.src.drain_bursts("emg_left") == []
    rig.src.close()


def test_no_burst_right_after_reconnect() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(1.5, {"emg_left": REST})
    raw = rig.raws["emg_left"]
    raw.emit_state(False)
    rig.src.step()
    raw.emit_state(True)
    rig.src.step()
    rig.run(1.0, {"emg_left": BURST})  # высокий уровень сразу после переподключения
    assert rig.src.drain_bursts("emg_left") == []
    rig.src.close()


def test_reset_drops_pending_bursts() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.run(1.5, {"emg_left": REST})
    rig.run(0.5, {"emg_left": BURST})
    rig.src.reset()
    assert rig.src.drain_bursts("emg_left") == []
    rig.src.close()


def test_cycle_calibrates_emg_and_reports_phases() -> None:
    rig = Rig("pong", PONG)
    rhythm = (Segment("tense", 2.0), Segment("relax", 2.0), Segment("tense", 2.0))
    rig.src.start_calibration("emg_left", "cycle", segments=rhythm)
    rig.run(1.0, {"emg_left": BURST})
    mid = rig.src.calibration_status("emg_left")
    assert mid is not None
    assert (mid.status, mid.segment, mid.phase) == ("running", 1, "tense")
    assert mid.phase_left_s == pytest.approx(1.0, abs=0.1)
    rig.run(1.0, {"emg_left": BURST})
    rig.run(1.0, {"emg_left": REST})
    second = rig.src.calibration_status("emg_left")
    assert second is not None and (second.segment, second.phase) == (2, "relax")
    rig.run(1.0, {"emg_left": REST})
    rig.run(2.1, {"emg_left": BURST})
    done = rig.src.calibration_status("emg_left")
    assert done is not None and done.status == "done"
    rig.run(1.0, {"emg_left": REST})
    assert rig.src.read(0)["emg_left"].value < 0.15
    rig.run(1.0, {"emg_left": BURST})
    assert rig.src.read(0)["emg_left"].value > 0.6
    assert rig.src.calibration_status("emg_right") is None
    rig.src.close()


def test_cycle_uses_default_rhythm_when_not_given() -> None:
    rig = Rig("pong", PONG)
    rig.src.start_calibration("emg_left", "cycle")
    rig.run(0.5, {"emg_left": BURST})
    status = rig.src.calibration_status("emg_left")
    assert status is not None
    assert (status.segment, status.phase) == (1, "tense")
    assert status.phase_left_s == pytest.approx(FAST_EMG.cycle_tense_s - 0.5, abs=0.1)
    rig.src.close()


def test_cycle_is_not_for_eeg() -> None:
    rig = Rig("darts", DARTS)
    with pytest.raises(ValueError):
        rig.src.start_calibration("eeg", "cycle")
    rig.src.close()


def test_baseline_duration_goes_to_the_engine() -> None:
    rig = Rig("darts", DARTS)
    rig.src.start_calibration("eeg", "baseline", duration_s=20.0)
    assert rig.engines[-1].duration_s == 20.0
    rig.src.start_calibration("eeg", "baseline")
    assert rig.engines[-1].duration_s == 12.0  # без запроса: из настроек, по умолчанию 12 с
    rig.src.close()


def test_segments_and_duration_do_not_leak_into_other_channel_kinds() -> None:
    rig = Rig("darts", DARTS)
    rig.src.start_calibration("emg", "rest", segments=(Segment("tense", 2.0),), duration_s=7.0)
    status = rig.src.calibration_status("emg")
    assert status is not None and status.step == "rest"
    rig.src.close()


def test_factory_builds_alpha_engine() -> None:
    engine = make_engine_factory("alpha", BridgeConfig(), time.monotonic)()
    assert isinstance(engine, AlphaEngine)


def test_factory_builds_emotions_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[object] = []

    class FakePyem(FakeEngine):
        def __init__(self, cfg: object) -> None:
            super().__init__()
            built.append(cfg)

    monkeypatch.setattr("neurotlon_bridge.processing.emotions.Pyem", FakePyem)
    config = BridgeConfig()
    engine = make_engine_factory("emotions", config, time.monotonic)()
    assert isinstance(engine, FakePyem)
    assert built == [config.eeg]


@pytest.mark.parametrize("method", ["alpha", "emotions"])
def test_source_uses_selected_method(monkeypatch: pytest.MonkeyPatch, method: EegMethod) -> None:
    monkeypatch.setattr("neurotlon_bridge.processing.emotions.Pyem", lambda cfg: FakeEngine())
    raw = FakeRawSensor("brainbit", "B-1")
    config = BridgeConfig(devices={"eeg": "B-1", "emg": "C-1"}, emg=FAST_EMG)
    backend = FakeBackend([raw, FakeRawSensor("callibri", "C-1")])
    src = HardwareSource(
        "darts", config, backend, FakeClock(10.0), threaded=False, eeg_method=method
    )
    src.start()
    deadline = time.monotonic() + 3
    while src.state("eeg") != "connected" and time.monotonic() < deadline:
        time.sleep(0.01)
    src.start_calibration("eeg", "baseline")
    raw.emit_samples(np.zeros((25, 4)).tolist())
    src.step()
    status = src.calibration_status("eeg")
    assert status is not None and status.status == "running"
    # FakeEngine набирает 50% с каждой пачки; AlphaEngine считает отсчёты (25 из 12 с * 250 Гц)
    expected = 0.5 if method == "emotions" else 25 / (12 * 250)
    assert status.progress == pytest.approx(expected, abs=0.01)
    # длительность из calibrate: у альфы это число отсчётов, у Emotions - секунды в библиотеку
    src.start_calibration("eeg", "baseline", duration_s=5.0)
    raw.emit_samples(np.zeros((25, 4)).tolist())
    src.step()
    status = src.calibration_status("eeg")
    assert status is not None
    expected = 0.5 if method == "emotions" else 25 / (5 * 250)
    assert status.progress == pytest.approx(expected, abs=0.01)
    src.close()


# --- калибровка: hello.calibrated и сохранение на диск ---


class PersistentFakeEngine(FakeEngine):
    """Движок, умеющий выгружать и принимать границы (как `AlphaEngine`)."""

    LOW, HIGH = 0.1, 0.4

    def __init__(self) -> None:
        super().__init__()
        self.bounds: tuple[float, float] | None = None

    @property
    def calibrated(self) -> bool:
        return self.bounds is not None or super().calibrated

    def export_bounds(self) -> tuple[float, float] | None:
        if self.bounds is None and super().calibrated:
            self.bounds = (self.LOW, self.HIGH)
        return self.bounds

    def restore_bounds(self, low: float, high: float) -> None:
        if not low < high:
            raise ValueError("границы")
        self.bounds = (low, high)


class PersistentRig(Rig):
    engine_cls = PersistentFakeEngine


class WallClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def calibrate_eeg(rig: Rig) -> None:
    rig.src.start_calibration("eeg", "baseline")
    rig.run(0.1, {"eeg": 0})


def stored(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((tmp_path / FILE_NAME).read_text(encoding="utf-8"))
    return data


def wait_until(cond: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_emulator_needs_no_calibration() -> None:
    source = EmulatedSource("darts", time.monotonic)
    assert [source.is_calibrated(s) for s in source.signals()] == [False, False]
    assert [source.state(s) for s in source.signals()] == ["emulated", "emulated"]
    with pytest.raises(ValueError):
        source.is_calibrated("gsr")


def test_unknown_signal_is_an_error() -> None:
    rig = Rig("pong", PONG)
    with pytest.raises(ValueError):
        rig.src.is_calibrated("eeg")
    rig.src.close()


def test_is_calibrated_follows_steps() -> None:
    rig = Rig("darts", DARTS)
    assert not rig.src.is_calibrated("emg")
    assert not rig.src.is_calibrated("eeg")
    rig.src.start_calibration("emg", "rest")
    rig.run(1.2, {"emg": REST})
    assert not rig.src.is_calibrated("emg")  # покой есть, максимума нет
    rig.src.start_calibration("emg", "contract")
    rig.run(1.6, {"emg": BURST})
    rig.run(0.2, {"emg": REST})
    assert rig.src.is_calibrated("emg")
    assert not rig.src.is_calibrated("eeg")
    rig.src.start_calibration("eeg", "baseline")
    assert not rig.src.is_calibrated("eeg")  # идёт
    rig.run(0.1, {"eeg": 0})
    assert rig.src.is_calibrated("eeg")
    rig.src.reset()
    assert not rig.src.is_calibrated("emg")
    assert not rig.src.is_calibrated("eeg")
    rig.src.close()


def test_calibration_survives_sensor_reconnect() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.raws["emg_left"].emit_state(False)
    rig.src.step()
    rig.raws["emg_left"].emit_state(True)
    rig.src.step()
    assert rig.src.is_calibrated("emg_left")
    assert not rig.src.is_calibrated("emg_right")
    rig.src.close()


def test_restarting_one_signal_keeps_the_other_calibrated() -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    rig.calibrate_emg("emg_right")
    rig.src.start_calibration("emg_left", "rest")
    assert not rig.src.is_calibrated("emg_left")
    assert rig.src.is_calibrated("emg_right")
    rig.src.close()


def test_no_store_means_nothing_is_written(tmp_path: Path) -> None:
    rig = Rig("pong", PONG)
    rig.calibrate_emg("emg_left")
    assert list(tmp_path.iterdir()) == []
    rig.src.close()


def test_successful_steps_are_saved(tmp_path: Path) -> None:
    clock = WallClock()
    rig = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    assert not (tmp_path / FILE_NAME).exists()
    rig.calibrate_emg("emg")
    data = stored(tmp_path)
    assert set(data["signals"]) == {"emg"}
    emg = data["signals"]["emg"]
    assert 0 <= emg["rest"] < emg["peak"]
    assert emg["calibrated_at"] == clock.now
    assert data["eeg_method"] == "alpha"
    calibrate_eeg(rig)
    eeg = stored(tmp_path)["signals"]["eeg"]
    assert (eeg["low"], eeg["high"]) == (0.1, 0.4)
    assert eeg["fs"] == 250.0
    rig.src.close()


def test_file_is_not_rewritten_without_changes() -> None:
    class CountingStore(MemoryStore):
        saves = 0

        def save(self, record: CalibrationRecord) -> None:
            self.saves += 1
            super().save(record)

    store = CountingStore()
    rig = Rig("pong", PONG, store=store)
    rig.calibrate_emg("emg_left")
    assert store.saves == 1
    rig.run(1.0, {"emg_left": REST})
    assert store.saves == 1
    rig.src.close()


def test_new_step_failed_step_and_reset_erase(tmp_path: Path) -> None:
    rig = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path))
    rig.calibrate_emg("emg")
    calibrate_eeg(rig)
    assert set(stored(tmp_path)["signals"]) == {"emg", "eeg"}
    # новый шаг ЭМГ делает прежнюю шкалу недействительной, ЭЭГ остаётся
    rig.src.start_calibration("emg", "cycle", (Segment("relax", 2.0), Segment("tense", 2.0)))
    assert set(stored(tmp_path)["signals"]) == {"eeg"}
    rig.run(4.4, {"emg": REST})  # сокращения нет: шаг проваливается
    status = rig.src.calibration_status("emg")
    assert status is not None and status.status == "failed"
    assert set(stored(tmp_path)["signals"]) == {"eeg"}
    rig.src.reset()
    assert not (tmp_path / FILE_NAME).exists()
    rig.src.close()


def test_failed_contract_erases_the_signal(tmp_path: Path) -> None:
    rig = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    rig.calibrate_emg("emg_left")
    assert (tmp_path / FILE_NAME).exists()
    rig.src.start_calibration("emg_left", "contract")  # покой остался, максимум сброшен
    assert not (tmp_path / FILE_NAME).exists()
    rig.run(1.8, {"emg_left": REST})  # сокращения нет
    status = rig.src.calibration_status("emg_left")
    assert status is not None and status.status == "failed"
    assert not (tmp_path / FILE_NAME).exists()
    rig.src.close()


def test_calibration_survives_process_restart(tmp_path: Path) -> None:
    clock = WallClock()
    first = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    first.calibrate_emg("emg")
    calibrate_eeg(first)
    first.src.close()
    saved_at = clock.now
    clock.now += 600  # мост перезапускался десять минут
    second = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    assert second.src.is_calibrated("emg")
    assert second.src.is_calibrated("eeg")
    # шкала применяется: покой даёт около нуля, сокращение около единицы
    second.run(1.0, {"emg": REST, "eeg": 0})
    rest = second.src.read(0)["emg"]
    assert rest.valid and rest.value < 0.15
    second.run(1.0, {"emg": BURST, "eeg": 0})
    assert second.src.read(0)["emg"].value > 0.5
    engine = second.engines[0]
    assert isinstance(engine, PersistentFakeEngine)
    assert engine.bounds == (0.1, 0.4)
    # восстановленная калибровка остаётся в файле, время калибровки прежнее
    assert stored(tmp_path)["signals"]["emg"]["calibrated_at"] == saved_at
    second.src.close()


def test_restored_emg_scale_equals_the_saved_one(tmp_path: Path) -> None:
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    first.calibrate_emg("emg_left")
    saved = stored(tmp_path)["signals"]["emg_left"]
    first.src.close()
    second = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    assert second.src.is_calibrated("emg_left")
    assert not second.src.is_calibrated("emg_right")
    assert stored(tmp_path)["signals"]["emg_left"] == saved
    second.src.close()


def test_restored_calibration_gives_bursts(tmp_path: Path) -> None:
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    first.calibrate_emg("emg_left")
    first.src.close()
    second = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    second.run(1.0, {"emg_left": REST})
    second.src.drain_bursts("emg_left")
    second.run(0.6, {"emg_left": BURST})
    assert second.src.drain_bursts("emg_left")
    second.src.close()


def test_expired_file_is_ignored_and_erased(tmp_path: Path) -> None:
    clock = WallClock()
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    first.calibrate_emg("emg_left")
    first.src.close()
    clock.now += 4 * 3600 + 1
    second = Rig("pong", PONG, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    assert not second.src.is_calibrated("emg_left")
    assert not (tmp_path / FILE_NAME).exists()
    second.src.close()


def test_ttl_comes_from_config(tmp_path: Path) -> None:
    clock = WallClock()
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    first.calibrate_emg("emg_left")
    first.src.close()
    clock.now += 2 * 3600
    short = Rig(
        "pong",
        PONG,
        store=FileCalibrationStore(tmp_path),
        wall_clock=clock,
        calibration=CalibrationConfig(ttl_h=1.0),
    )
    assert not short.src.is_calibrated("emg_left")
    short.src.close()


def test_corrupt_file_is_ignored_and_erased(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_text("{оборвано", encoding="utf-8")
    rig = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    assert not rig.src.is_calibrated("emg_left")
    assert not (tmp_path / FILE_NAME).exists()
    rig.src.close()


def test_other_eeg_method_is_ignored_and_erased(tmp_path: Path) -> None:
    first = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path))
    first.calibrate_emg("emg")
    calibrate_eeg(first)
    first.src.close()
    second = PersistentRig(
        "darts", DARTS, store=FileCalibrationStore(tmp_path), eeg_method="emotions"
    )
    assert not second.src.is_calibrated("emg")
    assert not second.src.is_calibrated("eeg")
    assert not (tmp_path / FILE_NAME).exists()
    second.src.close()


def test_file_with_a_foreign_signal_is_ignored(tmp_path: Path) -> None:
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    first.calibrate_emg("emg_left")
    first.src.close()
    second = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path))
    assert not second.src.is_calibrated("emg")
    assert not (tmp_path / FILE_NAME).exists()
    second.src.close()


@pytest.mark.parametrize(
    "scale",
    [
        {"kind": "emg", "rest": 9.0, "peak": 3.0, "fs": 1000.0, "calibrated_at": 999_999.0},
        {"kind": "emg", "rest": 3.0, "peak": 3.0, "fs": 1000.0, "calibrated_at": 999_999.0},
        {"kind": "emg", "rest": 1.0, "peak": 1e999, "fs": 1000.0, "calibrated_at": 999_999.0},
        {"kind": "eeg", "low": 0.1, "high": 0.4, "fs": 250.0, "calibrated_at": 999_999.0},
    ],
)
def test_file_with_wrong_values_is_ignored(tmp_path: Path, scale: dict[str, Any]) -> None:
    payload = {"schema_version": 1, "eeg_method": None, "signals": {"emg_left": scale}}
    (tmp_path / FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")
    rig = Rig("pong", PONG, store=FileCalibrationStore(tmp_path), wall_clock=WallClock())
    assert not rig.src.is_calibrated("emg_left")
    assert not (tmp_path / FILE_NAME).exists()
    rig.src.close()


def test_engine_without_export_is_not_saved_nor_declared(tmp_path: Path) -> None:
    """Движок без выгрузки параметров (как `Pyem`): ЭМГ сохраняется, ЭЭГ нет."""
    first = Rig("darts", DARTS, store=FileCalibrationStore(tmp_path), eeg_method="emotions")
    first.calibrate_emg("emg")
    calibrate_eeg(first)
    assert first.src.is_calibrated("eeg")
    assert set(stored(tmp_path)["signals"]) == {"emg"}
    first.src.close()
    second = Rig("darts", DARTS, store=FileCalibrationStore(tmp_path), eeg_method="emotions")
    assert second.src.is_calibrated("emg")
    assert not second.src.is_calibrated("eeg")
    second.src.close()


def test_broken_disk_does_not_stop_the_bridge() -> None:
    class Broken(MemoryStore):
        def load(self) -> CalibrationRecord | None:
            raise OSError("диск")

        def save(self, record: CalibrationRecord) -> None:
            raise OSError("диск")

        def clear(self) -> None:
            raise OSError("диск")

    rig = Rig("pong", PONG, store=Broken())
    rig.calibrate_emg("emg_left")
    assert rig.src.is_calibrated("emg_left")  # калибровка живёт в памяти, мост работает
    rig.src.reset()
    assert not rig.src.is_calibrated("emg_left")
    rig.src.close()


def test_threaded_steps_save_without_deadlock(tmp_path: Path) -> None:
    raw = FakeRawSensor("callibri", "T-1")
    bb = FakeRawSensor("brainbit", "B-1")
    config = BridgeConfig(devices={"emg": "T-1", "eeg": "B-1"}, emg=FAST_EMG)
    store = FileCalibrationStore(tmp_path)
    src = HardwareSource(
        "darts", config, FakeBackend([raw, bb]), engine_factory=PersistentFakeEngine, store=store
    )
    src.start()
    try:
        src.start_calibration("eeg", "baseline")
        deadline = time.monotonic() + 5
        while not src.is_calibrated("eeg") and time.monotonic() < deadline:
            bb.emit_samples([[1e-6] * 4] * 6)
            time.sleep(0.02)
        assert src.is_calibrated("eeg")
        assert wait_until(lambda: (tmp_path / FILE_NAME).exists())
    finally:
        src.close()


# --- hello.calibrated по сокету: калибровка не зависит от соединения ---


async def _hello(port: int) -> dict[str, Any]:
    """`hello` нового клиента; слот ещё занят прежним - пробуем снова."""
    deadline = time.monotonic() + 3
    while True:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        line = await asyncio.wait_for(reader.readline(), 3)
        writer.close()
        await writer.wait_closed()
        if line or time.monotonic() > deadline:
            hello: dict[str, Any] = json.loads(line)
            return hello
        await asyncio.sleep(0.02)


def test_hello_lists_calibrated_signals_for_each_new_client(tmp_path: Path) -> None:
    rig = PersistentRig("darts", DARTS, store=FileCalibrationStore(tmp_path))
    rig.calibrate_emg("emg")

    async def scenario() -> list[dict[str, Any]]:
        server = BridgeServer(rig.src, port=0, eeg_method="alpha")
        await server.start()
        try:
            first = await _hello(server.port)  # клиент отключился...
            calibrate_eeg(rig)  # ...калибровка продолжилась без него
            second = await _hello(server.port)  # ...новый клиент её видит
            return [first, second]
        finally:
            await server.stop()

    first, second = asyncio.run(scenario())
    rig.src.close()
    assert "calibration_state" in first["features"]
    assert first["calibrated"] == ["emg"]
    assert second["calibrated"] == ["eeg", "emg"]


def test_hello_after_bridge_restart_lists_restored_signals(tmp_path: Path) -> None:
    first = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    first.calibrate_emg("emg_left")
    first.src.close()
    second = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))

    async def scenario() -> dict[str, Any]:
        server = BridgeServer(second.src, port=0)
        await server.start()
        try:
            return await _hello(server.port)
        finally:
            await server.stop()

    hello = asyncio.run(scenario())
    second.src.close()
    assert hello["calibrated"] == ["emg_left"]


def test_reset_over_the_wire_clears_hello_and_file(tmp_path: Path) -> None:
    rig = Rig("pong", PONG, store=FileCalibrationStore(tmp_path))
    rig.calibrate_emg("emg_left")

    async def scenario() -> dict[str, Any]:
        server = BridgeServer(rig.src, port=0)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            await reader.readline()
            writer.write(b'{"type":"reset"}\n')
            await writer.drain()
            deadline = time.monotonic() + 3
            while rig.src.is_calibrated("emg_left") and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            writer.close()
            await writer.wait_closed()
            return await _hello(server.port)
        finally:
            await server.stop()

    hello = asyncio.run(scenario())
    rig.src.close()
    assert hello["calibrated"] == []
    assert not (tmp_path / FILE_NAME).exists()


def test_restore_never_raises_from_the_constructor() -> None:
    class Exploding(MemoryStore):
        def load(self) -> CalibrationRecord:
            raise RuntimeError("неожиданно")

    rig = Rig("pong", PONG, store=Exploding())
    assert not rig.src.is_calibrated("emg_left")
    rig.src.close()


def test_changed_sampling_rate_does_not_refresh_the_calibration_time(tmp_path: Path) -> None:
    from neurotlon_bridge.calibration_store import EmgScale

    clock = WallClock()
    rig = Rig("pong", PONG, store=FileCalibrationStore(tmp_path), wall_clock=clock)
    rig.calibrate_emg("emg_left")
    first = stored(tmp_path)["signals"]["emg_left"]
    clock.now += 3600
    channel = rig.src._channel("emg_left")
    original = channel.export_scale
    channel.export_scale = lambda: EmgScale(first["rest"], first["peak"], 500.0)  # type: ignore[method-assign]
    rig.src._sync_store()
    channel.export_scale = original  # type: ignore[method-assign]
    after = stored(tmp_path)["signals"]["emg_left"]
    assert after["fs"] == 500.0
    assert after["calibrated_at"] == first["calibrated_at"]  # TTL не «молодеет»
    rig.src.close()
