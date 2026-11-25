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

from .calibration_store import (
    CalibrationRecord,
    CalibrationStore,
    EegScale,
    EmgScale,
    Scale,
    Stamped,
    record_problem,
    same_scale,
)
from .config import BridgeConfig, required_devices
from .devices.base import DeviceBackend, DeviceKind
from .devices.sdk_sensor import SdkSensor
from .processing.alpha import AlphaEngine
from .processing.eeg import EegEngine, EegProcessor
from .processing.emg import EmgProcessor
from .source import (
    EEG_STEPS,
    EMG_STEPS,
    PROFILES,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    EegMethod,
    Reading,
    Segment,
    SensorState,
)

log = logging.getLogger(__name__)

STALE_S = 0.5
VOLTS_TO_MICROVOLTS = 1e6
EMG_PERIOD_S = 0.02
EEG_PERIOD_S = 0.04
CLOSE_TIMEOUT_S = 30.0


def _nothing() -> None:
    """Без действия."""


class _Channel:
    """Датчик + обработчик + рабочий поток одного сигнала."""

    kind: DeviceKind
    period_s: float

    def __init__(self, name: str, sensor: SdkSensor, clock: Clock) -> None:
        self.name = name
        self.sensor = sensor
        self._clock = clock
        self.on_change: Callable[[], None] = _nothing  # шаг мог изменить калибровку
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
        self.on_change()  # вне замка: источник сам берёт замки каналов

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

    def start_calibration(
        self,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None,
        duration_s: float | None,
    ) -> None:
        raise NotImplementedError

    def calibration_status(self) -> CalibrationProgress | None:
        raise NotImplementedError

    def drain_bursts(self) -> list[BurstEvent]:
        return []

    def reset(self) -> None:
        raise NotImplementedError

    def is_calibrated(self) -> bool:
        raise NotImplementedError

    def export_scale(self) -> Scale | None:
        """Шкала для сохранения на диск; нет готовой или метод не умеет - None."""
        raise NotImplementedError

    def restore_scale(self, scale: Scale) -> bool:
        """Применить шкалу с диска; False, если канал её не принял."""
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

    def start_calibration(
        self,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None,
        duration_s: float | None,
    ) -> None:
        if step not in EMG_STEPS:
            raise ValueError(f"шаг {step} не подходит для {self.name}")
        with self._lock:
            self._proc.start_calibration(step, self._clock(), segments)

    def calibration_status(self) -> CalibrationProgress | None:
        with self._lock:
            return self._proc.calibration_status()

    def drain_bursts(self) -> list[BurstEvent]:
        with self._lock:
            return self._proc.drain_bursts()

    def reset(self) -> None:
        with self._lock:
            self._proc.reset()

    def is_calibrated(self) -> bool:
        with self._lock:
            return self._proc.calibrated

    def export_scale(self) -> Scale | None:
        with self._lock:
            bounds = self._proc.export_calibration()
            return None if bounds is None else EmgScale(bounds[0], bounds[1], self._proc.fs)

    def restore_scale(self, scale: Scale) -> bool:
        if not isinstance(scale, EmgScale):
            return False
        with self._lock:
            self._proc.restore_calibration(scale.rest, scale.peak)
        return True


class _EegChannel(_Channel):
    kind: DeviceKind = "brainbit"
    period_s = EEG_PERIOD_S

    def __init__(
        self,
        name: str,
        sensor: SdkSensor,
        clock: Clock,
        processor: EegProcessor,
        sampling_hz: float,
    ) -> None:
        super().__init__(name, sensor, clock)
        self._proc = processor
        self._sampling_hz = sampling_hz

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

    def start_calibration(
        self,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None,
        duration_s: float | None,
    ) -> None:
        if step not in EEG_STEPS:
            raise ValueError(f"шаг {step} не подходит для {self.name}")
        with self._lock:
            self._proc.start_calibration(step, duration_s)

    def calibration_status(self) -> CalibrationProgress | None:
        with self._lock:
            return self._proc.calibration_status()

    def reset(self) -> None:
        with self._lock:
            self._proc.reset()

    def is_calibrated(self) -> bool:
        with self._lock:
            return self._proc.calibrated

    def export_scale(self) -> Scale | None:
        with self._lock:
            bounds = self._proc.export_calibration()
        return None if bounds is None else EegScale(bounds[0], bounds[1], self._sampling_hz)

    def restore_scale(self, scale: Scale) -> bool:
        if not isinstance(scale, EegScale):
            return False
        with self._lock:
            return self._proc.restore_calibration(scale.low, scale.high)


EngineFactory = Callable[[], EegEngine]


def _make_alpha(config: BridgeConfig, clock: Clock) -> EegEngine:
    return AlphaEngine(config.alpha, config.eeg.sampling_rate, clock)


def _make_emotions(config: BridgeConfig, clock: Clock) -> EegEngine:
    from .processing.emotions import Pyem  # библиотека нужна только этому методу

    return Pyem(config.eeg)


_ENGINE_BUILDERS: dict[EegMethod, Callable[[BridgeConfig, Clock], EegEngine]] = {
    "alpha": _make_alpha,
    "emotions": _make_emotions,
}


def make_engine_factory(method: EegMethod, config: BridgeConfig, clock: Clock) -> EngineFactory:
    """Фабрика движка ЭЭГ выбранного метода; новый объект на каждую калибровку."""
    build = _ENGINE_BUILDERS[method]
    return lambda: build(config, clock)


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
        eeg_method: EegMethod = "alpha",
        store: CalibrationStore | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown profile: {profile}")
        plan = required_devices(profile, config)  # ConfigError до любых подключений
        self._profile = profile
        self._backend = backend
        self._threaded = threaded
        self._channels: dict[str, _Channel] = {}
        factory = engine_factory or make_engine_factory(eeg_method, config, clock)
        for signal, serial in plan.items():
            if signal == "eeg":
                sensor = SdkSensor(serial, "brainbit", backend, clock)
                self._channels[signal] = _EegChannel(
                    signal,
                    sensor,
                    clock,
                    EegProcessor(factory, config.eeg.calibration_s),
                    config.eeg.sampling_rate,
                )
            else:
                sensor = SdkSensor(serial, "callibri", backend, clock)
                processor = EmgProcessor(config.emg, burst=config.burst)
                self._channels[signal] = _EmgChannel(signal, sensor, clock, processor)
        self._started = False
        self._eeg_method: EegMethod | None = eeg_method if "eeg" in self._channels else None
        self._eeg_fs = float(config.eeg.sampling_rate)
        self._emg_fs = float(config.emg.fs_nominal)
        self._ttl_s = config.calibration.ttl_s
        self._store = store
        self._wall_clock = wall_clock
        self._store_lock = threading.Lock()
        self._saved: dict[str, Stamped] = {}  # что сейчас лежит в хранилище
        try:
            self._restore()
        except Exception:  # битый файл не должен мешать запуску моста
            log.warning("восстановление калибровки не удалось, начинаем с нуля", exc_info=True)
            self._saved = {}
        for channel in self._channels.values():
            channel.on_change = self._sync_store

    # --- сохранение калибровки ---
    def _restore(self) -> None:
        """Применить сохранённую калибровку, если ей можно верить; иначе стереть файл."""
        if self._store is None:
            return
        try:
            record = self._store.load()
        except OSError:
            log.warning("калибровку не прочитать с диска, начинаем с нуля", exc_info=True)
            return
        if record is None:
            return
        problem = record_problem(
            record,
            now=self._wall_clock(),
            ttl_s=self._ttl_s,
            signals=self._channels.keys(),
            eeg_method=self._eeg_method,
            eeg_fs=self._eeg_fs,
            emg_fs=self._emg_fs,
        )
        if problem is not None:
            log.info("сохранённая калибровка не подходит (%s), стёрта", problem)
            self._saved = {}
            self._write_store()
            return
        for name, stamped in record.signals.items():
            if self._channels[name].restore_scale(stamped.scale):
                self._saved[name] = stamped
                log.info("калибровка %s восстановлена с диска", name)
        if self._saved != record.signals:  # часть не восстановилась (метод emotions)
            self._write_store()

    def _sync_store(self) -> None:
        """Привести файл в соответствие с калибровкой каналов (пишет только при изменении)."""
        if self._store is None:
            return
        with self._store_lock:
            now = self._wall_clock()
            current: dict[str, Stamped] = {}
            for name, channel in self._channels.items():
                scale = channel.export_scale()
                if scale is None:
                    continue
                prev = self._saved.get(name)
                # метка времени обновляется только при смене самой шкалы, не частоты
                same = prev is not None and same_scale(prev.scale, scale)
                current[name] = Stamped(scale, prev.at if same and prev is not None else now)
            if current != self._saved:
                self._saved = current
                self._write_store()

    def _write_store(self) -> None:
        """Записать `self._saved` (пусто - стереть). Сбой диска не должен ронять мост."""
        assert self._store is not None
        try:
            if self._saved:
                self._store.save(CalibrationRecord(self._eeg_method, dict(self._saved)))
            else:
                self._store.clear()
        except OSError:
            log.warning("калибровку не записать на диск", exc_info=True)

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

    def start_calibration(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self._channel(signal).start_calibration(step, segments, duration_s)
        self._sync_store()  # новый шаг делает прежнюю шкалу сигнала недействительной

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        return self._channel(signal).calibration_status()

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        return self._channel(signal).drain_bursts()

    def reset(self) -> None:
        for channel in self._channels.values():
            channel.reset()
        self._sync_store()

    def is_calibrated(self, signal: str) -> bool:
        return self._channel(signal).is_calibrated()

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
