import asyncio
import json
import time
from typing import Any

import numpy as np
import pytest

from neurotlon_bridge.config import BridgeConfig, ConfigError
from neurotlon_bridge.devices.fakes import FakeBackend, FakeClock, FakeRawSensor
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
    def __init__(self, profile: str, serials: dict[str, str]) -> None:
        kinds = {"eeg": "brainbit"}
        self.raws = {
            sig: FakeRawSensor(kinds.get(sig, "callibri"), sn)  # type: ignore[arg-type]
            for sig, sn in serials.items()
        }
        self.backend = FakeBackend(list(self.raws.values()))
        self.clock = FakeClock(10.0)
        self.engines: list[FakeEngine] = []
        config = BridgeConfig(devices=serials, emg=FAST_EMG)
        self.src = HardwareSource(
            profile, config, self.backend, self.clock, threaded=False, engine_factory=self._engine
        )
        self.rng = np.random.default_rng(7)
        self.src.start()
        deadline = time.monotonic() + 3
        while (
            any(self.src.state(s) != "connected" for s in serials) and time.monotonic() < deadline
        ):
            time.sleep(0.01)

    def _engine(self) -> FakeEngine:
        self.engines.append(FakeEngine())
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
