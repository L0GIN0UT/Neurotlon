"""Подделки SDK для тестов: датчики без железа. Мостом при работе не используются."""

from __future__ import annotations

import time
from collections.abc import Sequence

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

    @property
    def sampling_hz(self) -> int:
        return self._hz

    def start_signal(self) -> None:
        if self.fail_start:
            raise DeviceError("StartSignal не прошёл")
        self.start_calls += 1

    def stop_signal(self) -> None:
        self.stop_calls += 1

    def battery(self) -> int | None:
        return self.battery_value

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

    def open_sensor(self, serial: str, kind: DeviceKind, handlers: SensorHandlers) -> FakeRawSensor:
        self.open_calls.append(serial)
        sensor = self.sensors.get(serial)
        if sensor is None or sensor.kind != kind:
            raise DeviceNotFoundError(f"{kind} {serial} не найден")
        sensor.handlers = handlers
        sensor.closed = False
        return sensor

    def close(self) -> None:
        self.closed = True
