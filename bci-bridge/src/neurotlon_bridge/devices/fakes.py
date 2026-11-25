"""Подделки SDK: датчики без железа. Рабочий мост их не использует, только `--discover --fake`."""

from __future__ import annotations

import dataclasses
import math
import random
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .base import DeviceError, DeviceInfo, DeviceKind, DeviceNotFoundError, SensorHandlers


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRawSensor:
    """Датчик, которым управляет тест: `emit_*` вызывает колбэки так, как это делает SDK."""

    def __init__(self, kind: DeviceKind, serial: str, sampling_hz: int | None = None) -> None:
        self.kind: DeviceKind = kind
        self.serial = serial
        self._hz = sampling_hz or (1000 if kind == "callibri" else 250)
        self.handlers: SensorHandlers | None = None
        self.start_calls = 0
        self.stop_calls = 0
        self.closed = False
        self.battery_value: int | None = 80
        self.fail_start = False
        self.close_delay_s = 0.0
        self.on_start: Callable[[], None] | None = None  # тест «шлёт отсчёты» после StartSignal

    @property
    def sampling_hz(self) -> int:
        return self._hz

    def start_signal(self) -> None:
        if self.fail_start:
            raise DeviceError("StartSignal не прошёл")
        self.start_calls += 1
        if self.on_start is not None:
            self.on_start()

    def stop_signal(self) -> None:
        self.stop_calls += 1

    def battery(self) -> int | None:
        return self.battery_value

    def serial_number(self) -> str:
        return self.serial

    def close(self) -> None:
        if self.close_delay_s:
            time.sleep(self.close_delay_s)
        self.closed = True

    # --- со стороны «SDK» ---
    def emit_samples(self, rows: Sequence[Sequence[float]]) -> None:
        assert self.handlers is not None
        self.handlers.on_samples(rows)

    def emit_state(self, in_range: bool) -> None:
        assert self.handlers is not None
        self.handlers.on_state(in_range)

    def emit_battery(self, value: int) -> None:
        assert self.handlers is not None
        self.handlers.on_battery(value)

    def emit_electrode(self, ok: bool) -> None:
        assert self.handlers is not None
        self.handlers.on_electrode(ok)


class FakeBackend:
    def __init__(self, sensors: Sequence[FakeRawSensor] = ()) -> None:
        self.sensors = {s.serial: s for s in sensors}
        self.check_error: DeviceError | None = None
        self.open_calls: list[str] = []
        self.closed = False
        self.scan_seconds: float | None = None

    def check(self) -> None:
        if self.check_error is not None:
            raise self.check_error

    def scan(self, seconds: float) -> list[DeviceInfo]:
        self.scan_seconds = seconds
        return [
            DeviceInfo(s.kind, s.kind.capitalize(), s.serial, f"AA:{i:02d}")
            for i, s in enumerate(self.sensors.values())
        ]

    def open_sensor(
        self, serial: str, kind: DeviceKind, handlers: SensorHandlers, address: str = ""
    ) -> FakeRawSensor:
        self.open_calls.append(serial)
        sensor = self.sensors.get(serial)
        if sensor is None or sensor.kind != kind:
            raise DeviceNotFoundError(f"{kind} {serial} не найден")
        sensor.handlers = handlers
        sensor.closed = False
        return sensor

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class FakeDevice:
    """Устройство в эфире подделки: когда появляется, пропадает и как подключается."""

    info: DeviceInfo
    appear_s: float = 0.0
    vanish_s: float | None = None
    connect_error: str | None = None  # текст `DeviceError` при подключении
    serial_after_connect: str = ""  # номер, который SDK отдаёт только после подключения


class FakeScanner:
    """`ScannerPort` с расписанием: устройства появляются и пропадают по часам.

    `events` хранит порядок вызовов (`start`, `stop`, `connect:<адрес>`), по нему тесты проверяют,
    что поиск ставится на паузу на время подключения. Подключённые датчики — `FakeRawSensor`.
    """

    def __init__(
        self,
        devices: Sequence[FakeDevice],
        clock: Callable[[], float],
        *,
        stream_samples: bool = False,
        rssi_wobble_db: float = 0.0,
    ) -> None:
        self.devices = list(devices)
        self._clock = clock
        self._stream = stream_samples
        self._wobble = rssi_wobble_db
        self.start_error: Exception | None = None
        self.sensors_error: Exception | None = None
        self.connect_error: Exception | None = None  # для любого устройства
        self.on_connected: Callable[[FakeRawSensor], None] | None = None
        self.events: list[str] = []
        self.sensors_calls = 0
        self.scanning = False
        self.closed = False
        self.rssi_override: dict[str, int | None] = {}
        self.connect_gate: threading.Event | None = None  # держит подключение, пока не открыт
        self.raws: dict[str, FakeRawSensor] = {}
        self._seen: set[str] = set()

    # --- ScannerPort ---
    def start(self) -> None:
        self.events.append("start")
        if self.start_error is not None:
            raise self.start_error
        self.scanning = True

    def stop(self) -> None:
        self.events.append("stop")
        self.scanning = False

    def sensors(self) -> list[DeviceInfo]:
        self.sensors_calls += 1
        if self.sensors_error is not None:
            raise self.sensors_error
        now = self._clock()
        visible: list[DeviceInfo] = []
        for index, device in enumerate(self.devices):
            if now < device.appear_s or (device.vanish_s is not None and now >= device.vanish_s):
                continue
            info = device.info
            self._seen.add(info.address)
            rssi = self.rssi_override.get(info.address, info.rssi)
            if rssi is not None and self._wobble:
                rssi = round(rssi + self._wobble * math.sin(now / 5.0 + index))
            visible.append(dataclasses.replace(info, rssi=rssi))
        return visible

    def connect(self, address: str, kind: DeviceKind, handlers: SensorHandlers) -> FakeRawSensor:
        self.events.append(f"connect:{address}")
        device = next((d for d in self.devices if d.info.address == address), None)
        if device is None or address not in self._seen or device.info.kind != kind:
            raise DeviceNotFoundError("Устройство не найдено")
        if self.connect_gate is not None:
            self.connect_gate.wait(10)
        if self.connect_error is not None:
            raise self.connect_error
        if device.connect_error is not None:
            raise DeviceError(device.connect_error)
        serial = device.serial_after_connect or device.info.serial
        raw: FakeRawSensor = (
            _StreamingRawSensor(kind, serial, self._clock)
            if self._stream
            else FakeRawSensor(kind, serial)
        )
        raw.handlers = handlers
        self.raws[address] = raw
        if self.on_connected is not None:
            self.on_connected(raw)
        return raw

    def close(self) -> None:
        self.events.append("close")
        self.closed = True


class _StreamingRawSensor(FakeRawSensor):
    """Для `--discover --fake`: после `start_signal` сам шлёт отсчёты, ЭМГ «дышит» волнами."""

    PERIOD_S = 6.0
    TICK_S = 0.1

    def __init__(self, kind: DeviceKind, serial: str, clock: Callable[[], float]) -> None:
        super().__init__(kind, serial)
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rng = random.Random(serial)

    def start_signal(self) -> None:
        super().start_signal()
        if self._thread is not None:
            return
        if self.handlers is not None and self.kind == "callibri":
            self.handlers.on_electrode(True)
        self._thread = threading.Thread(target=self._run, name="fake-stream", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        super().close()

    def _run(self) -> None:
        rows_per_tick = max(1, int(self._hz * self.TICK_S))
        while not self._stop.wait(self.TICK_S):
            if self.handlers is None:
                continue
            wave = max(0.0, math.sin(2 * math.pi * self._clock() / self.PERIOD_S)) ** 2
            amplitude = 15e-6 + 350e-6 * wave
            rows: list[tuple[float, ...]]
            if self.kind == "callibri":
                rows = [(self._rng.gauss(0.0, amplitude),) for _ in range(rows_per_tick)]
            else:
                rows = [
                    tuple(self._rng.gauss(0.0, 20e-6) for _ in range(4))
                    for _ in range(rows_per_tick)
                ]
            self.handlers.on_samples(rows)


def demo_devices() -> list[FakeDevice]:
    """Сценарий `--discover --fake`: устройства появляются по одному, одно не подключается."""
    return [
        FakeDevice(DeviceInfo("brainbit", "BrainBit", "BB-DEMO-01", "DE:MO:00:00:00:01", -52), 1.0),
        FakeDevice(
            DeviceInfo("callibri", "Callibri_Red", "", "DE:MO:00:00:00:02", -63),
            2.5,
            serial_after_connect="CA-DEMO-02",
        ),
        FakeDevice(
            DeviceInfo("callibri", "Callibri_Red", "", "DE:MO:00:00:00:03", -71),
            4.0,
            serial_after_connect="CA-DEMO-03",
        ),
        FakeDevice(
            DeviceInfo("callibri", "Callibri_Blue", "", "DE:MO:00:00:00:04", -80),
            6.0,
            connect_error="Не удалось подключиться: устройство занято или вне зоны",
        ),
        FakeDevice(
            DeviceInfo("brainbit", "BrainBit", "BB-DEMO-05", "DE:MO:00:00:00:05", -90), 8.0, 20.0
        ),
    ]
