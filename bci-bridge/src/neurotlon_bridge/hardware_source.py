"""Источник сигналов от настоящих датчиков (BrainBit, Callibri) для `BridgeServer`.

Сигнал привязан к датчику по серийному номеру из `bridge.toml`. На каждый датчик свой
`SdkSensor`, свой обработчик и свой рабочий поток; состояние между каналами не делится
(в понге два Callibri работают одновременно).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from .config import BridgeConfig, required_devices
from .devices.base import DeviceBackend, DeviceKind
from .devices.sdk_sensor import SdkSensor
from .processing.eeg import EEG_STEPS, EegProcessor, EmotionsEngine
from .processing.emg import EMG_STEPS, EmgProcessor
from .source import (
    PROFILES,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    Reading,
    SensorState,
)

log = logging.getLogger(__name__)

STALE_S = 0.5
VOLTS_TO_MICROVOLTS = 1e6
EMG_PERIOD_S = 0.02
EEG_PERIOD_S = 0.04
CLOSE_TIMEOUT_S = 30.0


class _Channel:
    """Датчик + обработчик + рабочий поток одного сигнала."""

    kind: DeviceKind
    period_s: float

    def __init__(self, name: str, sensor: SdkSensor, clock: Clock) -> None:
        self.name = name
        self.sensor = sensor
        self._clock = clock
        self._lock = threading.Lock()
        self._updated: float | None = None
        self._seen_reconnects = 0
        self._thread: threading.Thread | None = None
        self._running = False

    # --- потоки ---
    def start(self, threaded: bool) -> None:
        self.sensor.connect_async()
        if threaded:
            self._running = True
            self._thread = threading.Thread(target=self._loop, name=f"hw-{self.name}", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while self._running:
            time.sleep(self.period_s)
            try:
                self.step()
            except Exception:
                log.exception("ошибка обработки сигнала %s", self.name)

    def begin_close(self) -> None:
        self._running = False
        self.sensor.begin_close()

    def close(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.sensor.close()
        self._close_processor()

    def _close_processor(self) -> None:
        """Освободить ресурсы обработчика."""

    # --- шаг обработки ---
    def step(self) -> None:
        self.sensor.poll()
        batches = self.sensor.drain()
        now = self._clock()
        with self._lock:
            if self.sensor.reconnects != self._seen_reconnects:
                self._seen_reconnects = self.sensor.reconnects
                self._on_reconnect()
            if self.sensor.state != "connected":
                self._abort("датчик отключён")
            self._before_batches()
            for t, data in batches:
                self._push(data, t)
            self._tick(now)
            if batches:
                self._updated = batches[-1][0]

    def _on_reconnect(self) -> None:
        raise NotImplementedError

    def _abort(self, reason: str) -> None:
        raise NotImplementedError

    def _before_batches(self) -> None:
        """Подготовка перед пачками (например, частота дискретизации)."""

    def _push(self, data: np.ndarray, now: float) -> None:
        raise NotImplementedError

    def _tick(self, now: float) -> None:
        """Продвинуть время без данных."""

    # --- чтение ---
    def reading(self) -> Reading:
        if self.sensor.state != "connected":
            return Reading(0.0, False, "disconnected")
        if self.sensor.electrode_ok is False:
            return Reading(0.0, False, "no_contact")
        with self._lock:
            updated = self._updated
            if updated is None or self._clock() - updated > STALE_S:
                return Reading(0.0, False, "stale")
            return self._reading()

    def _reading(self) -> Reading:
        raise NotImplementedError

    def start_calibration(self, step: CalibrationStep) -> None:
        raise NotImplementedError

    def calibration_status(self) -> CalibrationProgress | None:
        raise NotImplementedError

    def drain_bursts(self) -> list[BurstEvent]:
        return []

    def reset(self) -> None:
        raise NotImplementedError


class _EmgChannel(_Channel):
    kind: DeviceKind = "callibri"
    period_s = EMG_PERIOD_S

    def __init__(self, name: str, sensor: SdkSensor, clock: Clock, processor: EmgProcessor) -> None:
        super().__init__(name, sensor, clock)
        self._proc = processor

    def _on_reconnect(self) -> None:
        self._proc.reset_stream()
        self._updated = None

    def _abort(self, reason: str) -> None:
        self._proc.abort_calibration(reason)

    def _before_batches(self) -> None:
        hz = self.sensor.sampling_hz
        if hz:
            self._proc.set_fs(hz)
        contact = self.sensor.state == "connected" and self.sensor.electrode_ok is not False
        self._proc.set_contact(contact)

    def _push(self, data: np.ndarray, now: float) -> None:
        self._proc.push(data[:, 0] * VOLTS_TO_MICROVOLTS, now)

    def _tick(self, now: float) -> None:
        self._proc.update(now)

    def _reading(self) -> Reading:
        return self._proc.reading()

    def start_calibration(self, step: CalibrationStep) -> None:
        if step not in EMG_STEPS:
            raise ValueError(f"шаг {step} не подходит для {self.name}")
        with self._lock:
            self._proc.start_calibration(step, self._clock())

    def calibration_status(self) -> CalibrationProgress | None:
        with self._lock:
            return self._proc.calibration_status()

    def drain_bursts(self) -> list[BurstEvent]:
        with self._lock:
            return self._proc.drain_bursts()

    def reset(self) -> None:
        with self._lock:
            self._proc.reset()


class _EegChannel(_Channel):
    kind: DeviceKind = "brainbit"
    period_s = EEG_PERIOD_S

    def __init__(self, name: str, sensor: SdkSensor, clock: Clock, processor: EegProcessor) -> None:
        super().__init__(name, sensor, clock)
        self._proc = processor

    def _on_reconnect(self) -> None:
        self._proc.abort_calibration("связь с датчиком прервалась")
        self._updated = None

    def _abort(self, reason: str) -> None:
        self._proc.abort_calibration(reason)

    def _push(self, data: np.ndarray, now: float) -> None:
        if data.shape[1] == 4:
            self._proc.push(data)

    def _reading(self) -> Reading:
        return self._proc.reading()

    def _close_processor(self) -> None:
        with self._lock:
            self._proc.close()

    def start_calibration(self, step: CalibrationStep) -> None:
        if step not in EEG_STEPS:
            raise ValueError(f"шаг {step} не подходит для {self.name}")
        with self._lock:
            self._proc.start_calibration(step)

    def calibration_status(self) -> CalibrationProgress | None:
        with self._lock:
            return self._proc.calibration_status()

    def reset(self) -> None:
        with self._lock:
            self._proc.reset()


EngineFactory = Callable[[], EmotionsEngine]


def _default_engine_factory(config: BridgeConfig) -> EngineFactory:
    def make() -> EmotionsEngine:
        from .processing.emotions import Pyem

        return Pyem(config.eeg)

    return make


class HardwareSource:
    """Реализация `SignalSource` на настоящих датчиках.

    `start()` запускает подключение и рабочие потоки; `threaded=False` (тесты) — потоков нет,
    шаги обработки вызываются вручную через `step()`.
    """

    def __init__(
        self,
        profile: str,
        config: BridgeConfig,
        backend: DeviceBackend,
        clock: Clock = time.monotonic,
        *,
        threaded: bool = True,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile: {profile}")
        plan = required_devices(profile, config)  # ConfigError до любых подключений
        self._profile = profile
        self._backend = backend
        self._threaded = threaded
        self._channels: dict[str, _Channel] = {}
        factory = engine_factory or _default_engine_factory(config)
        for signal, serial in plan.items():
            if signal == "eeg":
                sensor = SdkSensor(serial, "brainbit", backend, clock)
                self._channels[signal] = _EegChannel(signal, sensor, clock, EegProcessor(factory))
            else:
                sensor = SdkSensor(serial, "callibri", backend, clock)
                processor = EmgProcessor(config.emg, burst=config.burst)
                self._channels[signal] = _EmgChannel(signal, sensor, clock, processor)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for channel in self._channels.values():
            channel.start(self._threaded)

    def step(self) -> None:
        """Один проход обработки по всем каналам (для тестов без потоков)."""
        for channel in self._channels.values():
            channel.step()

    def close(self) -> None:
        # Сначала всем сообщаем о закрытии, затем освобождаем параллельно:
        # остановка не должна быть суммой времён отдельных датчиков.
        for channel in self._channels.values():
            channel.begin_close()
        threads = [
            threading.Thread(target=channel.close, name=f"close-{name}", daemon=True)
            for name, channel in self._channels.items()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=CLOSE_TIMEOUT_S)
        self._backend.close()

    # --- SignalSource ---
    def signals(self) -> tuple[str, ...]:
        return PROFILES[self._profile]

    def read(self, now_ms: int) -> dict[str, Reading]:
        return {name: ch.reading() for name, ch in self._channels.items()}

    def state(self, signal: str) -> SensorState:
        state = self._channel(signal).sensor.state
        if state == "connected":
            return "connected"
        return "connecting" if state == "connecting" else "disconnected"

    def start_calibration(self, signal: str, step: CalibrationStep) -> None:
        self._channel(signal).start_calibration(step)

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        return self._channel(signal).calibration_status()

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        return self._channel(signal).drain_bursts()

    def reset(self) -> None:
        for channel in self._channels.values():
            channel.reset()

    # --- для окна ---
    def battery(self, signal: str) -> int | None:
        return self._channel(signal).sensor.battery

    def serial(self, signal: str) -> str:
        return self._channel(signal).sensor.serial

    def _channel(self, signal: str) -> _Channel:
        try:
            return self._channels[signal]
        except KeyError:
            raise ValueError(f"unknown signal: {signal}") from None
