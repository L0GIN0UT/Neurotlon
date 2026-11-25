"""Адаптер NeuroSDK проверяется на подмене модулей `neurosdk`: железа и самого SDK не нужно."""

import enum
import subprocess
import sys
import threading
import time
import types
from typing import Any, ClassVar

import pytest

from neurotlon_bridge.devices.base import (
    BluetoothUnavailableError,
    DeviceError,
    DeviceNotFoundError,
    SdkUnavailableError,
    SensorHandlers,
)
from neurotlon_bridge.devices.neurosdk_backend import NeuroSdkBackend
from neurotlon_bridge.devices.sdk_sensor import SdkSensor as Wrapper


def _enum(name: str, *members: str) -> Any:
    return enum.Enum(name, {m: i for i, m in enumerate(members)})


Family = _enum("SensorFamily", "LEBrainBit", "LECallibri", "LEKolibri", "LEOther")
State = _enum("SensorState", "StateInRange", "StateOutOfRange")
Command = _enum("SensorCommand", "StartSignal", "StopSignal")
SignalType = _enum("CallibriSignalType", "EMG", "ECG")
AdcInput = _enum("SensorADCInput", "Electrodes", "Test")
SwitchInput = _enum("SensorExternalSwitchInput", "Electrodes", "Short")
Parameter = _enum("SensorParameter", "ADCInputState", "ExternalSwitchState")
Freq = _enum("SensorSamplingFrequency", "FrequencyHz500", "FrequencyHz1000")


class SdkInfo:
    def __init__(self, family: Any, name: str, serial: str, address: str, rssi: int = 0) -> None:
        self.SensFamily = family
        self.Name = name
        self.SerialNumber = serial
        self.Address = address
        self.RSSI = rssi


class Packet:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class SdkSensor:
    log: list[str]
    fail_starts: int

    def __init__(self, serial: str, in_range: bool = True) -> None:
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "serial_number", serial)
        object.__setattr__(self, "state", State.StateInRange if in_range else State.StateOutOfRange)
        object.__setattr__(self, "batt_power", 71)
        object.__setattr__(self, "sampling_frequency", Freq.FrequencyHz500)
        object.__setattr__(self, "released", False)

    def __setattr__(self, name: str, value: Any) -> None:
        self.log.append(name)
        if name == "sampling_frequency" and self.__dict__.get("stuck_500"):
            return
        object.__setattr__(self, name, value)

    def is_supported_parameter(self, _p: Any) -> bool:
        return True

    def exec_command(self, command: Any) -> None:
        if command.name == "StartSignal" and self.__dict__.get("fail_starts", 0) > 0:
            object.__setattr__(self, "fail_starts", self.fail_starts - 1)
            raise RuntimeError("StartSignal не прошёл")
        self.log.append(command.name)

    def disconnect(self) -> None:
        self.log.append("disconnect")

    def __del__(self) -> None:
        if "log" in self.__dict__:
            self.log.append("__del__")


class SdkScanner:
    infos: ClassVar[list[SdkInfo]] = []
    sensors_by_address: ClassVar[dict[str, SdkSensor]] = {}
    start_error: Exception | None = None
    start_calls: ClassVar[int] = 0
    stop_calls: ClassVar[int] = 0

    def __init__(self, families: list[Any]) -> None:
        self.families = families

    def start(self) -> None:
        SdkScanner.start_calls += 1
        if self.start_error is not None:
            raise self.start_error

    def stop(self) -> None:
        SdkScanner.stop_calls += 1

    def sensors(self) -> list[SdkInfo]:
        return self.infos

    def create_sensor(self, info: SdkInfo) -> SdkSensor:
        return self.sensors_by_address[info.Address]


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> type[SdkScanner]:
    SdkScanner.infos = []
    SdkScanner.sensors_by_address = {}
    SdkScanner.start_error = None
    SdkScanner.start_calls = 0
    SdkScanner.stop_calls = 0
    pkg = types.ModuleType("neurosdk")
    types_mod = types.ModuleType("neurosdk.cmn_types")
    for enum_cls in (Family, State, Command, SignalType, AdcInput, SwitchInput, Parameter, Freq):
        setattr(types_mod, enum_cls.__name__, enum_cls)
    scanner_mod = types.ModuleType("neurosdk.scanner")
    scanner_mod.Scanner = SdkScanner  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "neurosdk", pkg)
    monkeypatch.setitem(sys.modules, "neurosdk.cmn_types", types_mod)
    monkeypatch.setitem(sys.modules, "neurosdk.scanner", scanner_mod)
    return SdkScanner


class Collector:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.states: list[bool] = []
        self.electrodes: list[bool] = []
        self.battery: list[int] = []

    def handlers(self) -> SensorHandlers:
        return SensorHandlers(
            self.on_samples, self.states.append, self.battery.append, self.electrodes.append
        )

    def on_samples(self, rows: Any) -> None:
        self.rows.append(rows)


def make_backend() -> NeuroSdkBackend:
    return NeuroSdkBackend(0.0, sleep=lambda _s: None)


def test_scan_maps_families_and_dedupes(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1"),
        SdkInfo(Family.LECallibri, "Callibri_Red", "CA1", "A2"),
        SdkInfo(Family.LEKolibri, "Kolibri", "KO1", "A3"),
        SdkInfo(Family.LEOther, "Other", "OT", "A4"),
        SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1"),
    ]
    found = make_backend().scan(0.0)
    assert sorted((d.kind, d.serial) for d in found) == [
        ("brainbit", "BB1"),
        ("callibri", "CA1"),
        ("callibri", "KO1"),
    ]


def test_callibri_is_configured_emg_first_then_frequency(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sensor = SdkSensor("CA1")
    sdk.sensors_by_address = {"A2": sensor}
    col = Collector()
    raw = make_backend().open_sensor("ca1", "callibri", col.handlers())
    log = sensor.log
    order = [
        n for n in log if n in {"signal_type", "sampling_frequency", "adc_input", "ext_sw_input"}
    ]
    assert order == ["signal_type", "sampling_frequency", "adc_input", "ext_sw_input"]
    assert raw.battery() == 71
    assert raw.sampling_hz == 1000


def test_callibri_actual_frequency_is_reported(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sensor = SdkSensor("CA1")
    object.__setattr__(sensor, "stuck_500", True)  # устройство не переключилось на 1000 Гц
    sdk.sensors_by_address = {"A2": sensor}
    raw = make_backend().open_sensor("CA1", "callibri", Collector().handlers())
    assert raw.sampling_hz == 500


def test_callibri_callbacks_convert_and_swallow_errors(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sensor = SdkSensor("CA1")
    sdk.sensors_by_address = {"A2": sensor}
    col = Collector()
    raw = make_backend().open_sensor("CA1", "callibri", col.handlers())
    raw.start_signal()
    assert "StartSignal" in sensor.log
    sensor.signalDataReceived(sensor, [Packet(Samples=[1e-6, 2e-6]), Packet(Samples=[3e-6])])  # type: ignore[attr-defined]
    assert col.rows == [[(1e-6,), (2e-6,), (3e-6,)]]
    sensor.signalDataReceived(sensor, [object()])  # type: ignore[attr-defined]  # битый пакет не бросает
    sensor.sensorStateChanged(sensor, State.StateOutOfRange)  # type: ignore[attr-defined]
    sensor.electrodeStateChanged(sensor, types.SimpleNamespace(name="Detached"))  # type: ignore[attr-defined]
    assert col.states == [False]
    assert col.electrodes == [False]
    raw.stop_signal()
    raw.close()
    assert "disconnect" in sensor.log
    assert "__del__" in sensor.log


def test_brainbit_rows_have_four_channels(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1")]
    sensor = SdkSensor("BB1")
    sdk.sensors_by_address = {"A1": sensor}
    col = Collector()
    raw = make_backend().open_sensor("BB1", "brainbit", col.handlers())
    assert raw.sampling_hz == 250
    raw.start_signal()
    sensor.signalDataReceived(sensor, [Packet(O1=1.0, O2=2.0, T3=3.0, T4=4.0)])  # type: ignore[attr-defined]
    assert col.rows == [[(1.0, 2.0, 3.0, 4.0)]]
    assert "signal_type" not in sensor.log


def test_unknown_serial_not_found(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1")]
    with pytest.raises(DeviceNotFoundError):
        make_backend().open_sensor("NOPE", "brainbit", Collector().handlers())


def test_wrong_kind_not_matched(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LEBrainBit, "BrainBit", "X1", "A1")]
    with pytest.raises(DeviceNotFoundError):
        make_backend().open_sensor("X1", "callibri", Collector().handlers())


def test_empty_serial_found_by_probing(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LECallibri, "Callibri", "", "A1"),
        SdkInfo(Family.LECallibri, "Callibri", "", "A2"),
    ]
    first, second = SdkSensor("CA-1"), SdkSensor("CA-2")
    sdk.sensors_by_address = {"A1": first, "A2": second}
    backend = make_backend()
    right = backend.open_sensor("CA-2", "callibri", Collector().handlers())
    assert right is not None
    assert "disconnect" in first.log  # чужой освобождён
    assert "disconnect" not in second.log
    # второй Callibri не подключается повторно к уже занятому
    left = backend.open_sensor("CA-1", "callibri", Collector().handlers())
    assert left is not None


def test_out_of_range_sensor_is_error(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1")]
    sensor = SdkSensor("BB1", in_range=False)
    sdk.sensors_by_address = {"A1": sensor}
    with pytest.raises(Exception, match="не на связи"):
        make_backend().open_sensor("BB1", "brainbit", Collector().handlers())
    assert "disconnect" in sensor.log


def test_missing_adapter_becomes_bluetooth_error(sdk: type[SdkScanner]) -> None:
    sdk.start_error = RuntimeError("Bluetooth adapter not found")
    with pytest.raises(BluetoothUnavailableError):
        make_backend().check()
    with pytest.raises(BluetoothUnavailableError):
        make_backend().scan(0.0)


def test_sdk_import_failure_is_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "neurosdk", None)
    monkeypatch.setitem(sys.modules, "neurosdk.cmn_types", None)
    with pytest.raises(SdkUnavailableError, match="NeuroSDK"):
        NeuroSdkBackend()


def test_importing_bridge_modules_does_not_load_sdk() -> None:
    code = (
        "import sys\n"
        "import neurotlon_bridge.__main__, neurotlon_bridge.hardware_source\n"
        "import neurotlon_bridge.devices.neurosdk_backend, neurotlon_bridge.processing.emotions\n"
        "assert 'neurosdk' not in sys.modules and 'em_st_artifacts' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_close_releases_device_for_reopen(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sdk.sensors_by_address = {"A2": SdkSensor("CA1")}
    backend = make_backend()
    first = backend.open_sensor("CA1", "callibri", Collector().handlers())
    with pytest.raises(DeviceNotFoundError):  # пока занят, второй раз не отдаётся
        backend.open_sensor("CA1", "callibri", Collector().handlers())
    first.close()
    first.close()  # повторное закрытие безопасно
    assert backend.open_sensor("CA1", "callibri", Collector().handlers()) is not None


def test_failed_start_signal_releases_claim_for_retry(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sensor = SdkSensor("CA1")
    object.__setattr__(sensor, "fail_starts", 1)
    sdk.sensors_by_address = {"A2": sensor}
    wrapper = Wrapper("CA1", "callibri", make_backend(), lambda: 0.0)
    wrapper.connect()
    assert wrapper.state == "disconnected"
    wrapper.connect()  # вторая попытка находит тот же датчик
    assert wrapper.state == "connected"


def test_known_serial_is_not_rescanned(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sdk.sensors_by_address = {"A2": SdkSensor("CA1")}
    backend = make_backend()
    backend.open_sensor("CA1", "callibri", Collector().handlers()).close()
    scans = sdk.start_calls
    backend.open_sensor("CA1", "callibri", Collector().handlers())
    assert sdk.start_calls == scans
    # занятый, но известный серийный номер тоже не вызывает нового поиска
    with pytest.raises(DeviceNotFoundError):
        backend.open_sensor("CA1", "callibri", Collector().handlers())
    assert sdk.start_calls == scans


def test_missing_device_search_does_not_block_other_connect(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA1", "A2")]
    sdk.sensors_by_address = {"A2": SdkSensor("CA1")}
    gate = threading.Event()

    def slow_sleep(_seconds: float) -> None:
        gate.wait(5)

    backend = NeuroSdkBackend(1.0, sleep=slow_sleep)
    backend.scan(0.0)  # CA1 уже известен
    errors: list[Exception] = []

    def search_missing() -> None:
        try:
            backend.open_sensor("MISSING", "callibri", Collector().handlers())
        except DeviceNotFoundError as exc:
            errors.append(exc)

    thread = threading.Thread(target=search_missing)
    thread.start()
    deadline = time.monotonic() + 3
    while sdk.start_calls < 2 and time.monotonic() < deadline:  # поиск идёт
        time.sleep(0.005)
    started = time.monotonic()
    raw = backend.open_sensor("CA1", "callibri", Collector().handlers())
    assert raw is not None
    assert time.monotonic() - started < 1.0
    assert thread.is_alive()  # поиск ещё не закончился
    gate.set()
    thread.join(5)
    assert len(errors) == 1


# --- фоновый поиск (ScannerPort) ---


def test_sensors_returns_what_is_visible_now_with_rssi(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1", rssi=-55),
        SdkInfo(Family.LECallibri, "Callibri", "", "A2"),  # RSSI 0: неизвестен
        SdkInfo(Family.LEOther, "Other", "OT", "A3"),
        SdkInfo(Family.LECallibri, "Callibri", "", "A2"),  # повтор
    ]
    backend = make_backend()
    found = backend.sensors()
    assert [(d.address, d.rssi) for d in found] == [("A1", -55), ("A2", None)]
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "", "A2", rssi=-70)]
    assert [(d.address, d.rssi) for d in backend.sensors()] == [("A2", -70)]


def test_start_and_stop_are_idempotent_and_do_not_scan_by_themselves(
    sdk: type[SdkScanner],
) -> None:
    backend = make_backend()
    backend.stop()  # ещё не запускали
    assert sdk.stop_calls == 0
    backend.start()
    backend.start()
    assert sdk.start_calls == 1
    backend.stop()
    backend.stop()
    assert sdk.stop_calls == 1
    backend.start()  # после паузы поиск включается снова
    assert sdk.start_calls == 2


def test_start_without_adapter_is_a_bluetooth_error(sdk: type[SdkScanner]) -> None:
    sdk.start_error = RuntimeError("Bluetooth adapter not found")
    with pytest.raises(BluetoothUnavailableError):
        make_backend().start()


def test_connect_by_address_does_not_touch_other_unnamed_devices(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LECallibri, "Callibri", "", "A1"),
        SdkInfo(Family.LECallibri, "Callibri", "", "A2"),
    ]
    first, second = SdkSensor("CA-1"), SdkSensor("CA-2")
    sdk.sensors_by_address = {"A1": first, "A2": second}
    backend = make_backend()
    backend.sensors()
    raw = backend.connect("A2", "callibri", Collector().handlers())
    assert raw.serial_number() == "CA-2"  # номер, который SDK отдаёт после подключения
    assert first.log == []  # к первому Callibri даже не подключались
    assert "signal_type" in second.log  # Callibri настроен в режим ЭМГ


def test_connect_rejects_unknown_wrong_kind_and_busy_devices(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "", "A1")]
    sdk.sensors_by_address = {"A1": SdkSensor("CA-1")}
    backend = make_backend()
    backend.sensors()
    handlers = Collector().handlers()
    with pytest.raises(DeviceNotFoundError, match="не найдено"):
        backend.connect("ZZ", "callibri", handlers)
    with pytest.raises(DeviceNotFoundError):
        backend.connect("A1", "brainbit", handlers)
    first = backend.connect("A1", "callibri", handlers)
    with pytest.raises(DeviceError, match="уже подключён"):
        backend.connect("A1", "callibri", handlers)
    first.close()
    assert backend.connect("A1", "callibri", handlers) is not None


def test_open_sensor_prefers_the_address_and_skips_probing(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LECallibri, "Callibri", "", "A1"),
        SdkInfo(Family.LECallibri, "Callibri", "", "A2"),
    ]
    first, second = SdkSensor("CA-1"), SdkSensor("CA-2")
    sdk.sensors_by_address = {"A1": first, "A2": second}
    backend = make_backend()
    backend.scan(0.0)
    raw = backend.open_sensor("CA-1", "callibri", Collector().handlers(), address="A2")
    assert raw.serial_number() == "CA-2"  # адрес важнее серийного номера
    assert first.log == []


def test_open_sensor_by_address_alone_without_serial(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "", "A1")]
    sdk.sensors_by_address = {"A1": SdkSensor("CA-1")}
    raw = make_backend().open_sensor("", "callibri", Collector().handlers(), address="A1")
    assert raw.serial_number() == "CA-1"


def test_changed_address_falls_back_to_the_serial_number(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "CA-1", "NEW")]
    sdk.sensors_by_address = {"NEW": SdkSensor("CA-1")}
    raw = make_backend().open_sensor("CA-1", "callibri", Collector().handlers(), address="OLD")
    assert raw.serial_number() == "CA-1"


def test_changed_address_falls_back_to_probing_when_advertised_serial_is_empty(
    sdk: type[SdkScanner],
) -> None:
    sdk.infos = [
        SdkInfo(Family.LECallibri, "Callibri", "", "N1"),
        SdkInfo(Family.LECallibri, "Callibri", "", "N2"),
    ]
    first, second = SdkSensor("CA-1"), SdkSensor("CA-2")
    sdk.sensors_by_address = {"N1": first, "N2": second}
    raw = make_backend().open_sensor("CA-2", "callibri", Collector().handlers(), address="OLD")
    assert raw.serial_number() == "CA-2"
    assert "disconnect" in first.log  # пробный чужой освобождён


def test_address_only_not_found_says_so(sdk: type[SdkScanner]) -> None:
    with pytest.raises(DeviceNotFoundError, match="адресом OLD"):
        make_backend().open_sensor("", "callibri", Collector().handlers(), address="OLD")


def test_search_ends_early_when_the_device_appears(sdk: type[SdkScanner]) -> None:
    info = SdkInfo(Family.LECallibri, "Callibri", "", "A1")
    sdk.sensors_by_address = {"A1": SdkSensor("CA-1")}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # устройство появилось в эфире на третьем опросе
            sdk.infos = [info]

    backend = NeuroSdkBackend(30.0, sleep=sleep)  # по часам до конца поиска 30 с
    started = time.monotonic()
    raw = backend.open_sensor("", "callibri", Collector().handlers(), address="A1")
    assert raw.serial_number() == "CA-1"
    assert len(sleeps) == 2  # не ждали все 30 с
    assert time.monotonic() - started < 5
    assert sdk.stop_calls == 1  # поиск остановлен


def test_search_by_serial_also_ends_early(sdk: type[SdkScanner]) -> None:
    sdk.sensors_by_address = {"A1": SdkSensor("BB1")}
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        sdk.infos = [SdkInfo(Family.LEBrainBit, "BrainBit", "BB1", "A1")]

    backend = NeuroSdkBackend(30.0, sleep=sleep)
    assert backend.open_sensor("bb1", "brainbit", Collector().handlers()) is not None
    assert len(calls) == 1


def test_names_and_serials_from_the_air_are_cleaned_and_limited(sdk: type[SdkScanner]) -> None:
    sdk.infos = [
        SdkInfo(Family.LECallibri, "Call\x7fibri\u202e\ud800", "CA\x00-1", "A1"),
        SdkInfo(Family.LECallibri, "\x7f\x00", "", "A2"),  # после чистки имя пустое
        SdkInfo(Family.LECallibri, "n" * 500, "s" * 500, "A3"),
        SdkInfo(Family.LECallibri, "Callibri", "", "A" * 65),  # адрес длиннее схемы
        SdkInfo(Family.LECallibri, "Callibri", "", "B\x7f4"),  # в адресе управляющий знак
        SdkInfo(Family.LECallibri, "Callibri", "", ""),
    ]
    found = {d.address: d for d in make_backend().sensors()}
    assert set(found) == {"A1", "A2", "A3"}
    assert (found["A1"].name, found["A1"].serial) == ("Callibri", "CA-1")
    assert found["A2"].name == "callibri"  # пустое имя заменено видом
    assert len(found["A3"].name) == 128 and len(found["A3"].serial) == 128


def test_serial_after_connect_is_cleaned(sdk: type[SdkScanner]) -> None:
    sdk.infos = [SdkInfo(Family.LECallibri, "Callibri", "", "A1")]
    sdk.sensors_by_address = {"A1": SdkSensor("CA\x7f\u202e-1")}
    backend = make_backend()
    backend.sensors()
    assert backend.connect("A1", "callibri", Collector().handlers()).serial_number() == "CA-1"
