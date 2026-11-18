"""Обёртка датчика: подключение в фоне, буфер данных, повторы, учёт переподключений.

Колбэки SDK только кладут данные в буфер под замком и не бросают исключений.
Рабочий поток зовёт `poll()` (повторное подключение и повторный StartSignal)
и `drain()` (забрать накопленное).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from ..source import Clock
from .base import DeviceBackend, DeviceKind, DeviceNotFoundError, RawSensor, SensorHandlers

log = logging.getLogger(__name__)

Batch = tuple[float, NDArray[np.float64]]
"""Момент прихода и массив (n, столбцы) в вольтах."""

SILENCE_RESTART_S = 2.0
RESTART_INTERVAL_S = 3.0
RETRY_INTERVAL_S = 3.0
BACKOFF_FACTORS = (1, 2, 4, 10)  # 3, 6, 12, 30 с при базовых 3 с
JOIN_TIMEOUT_S = 20.0
BUFFER_BATCHES = 20000


class SdkSensor:
    def __init__(
        self,
        serial: str,
        kind: DeviceKind,
        backend: DeviceBackend,
        clock: Clock,
        *,
        silence_restart_s: float = SILENCE_RESTART_S,
        restart_interval_s: float = RESTART_INTERVAL_S,
        retry_interval_s: float = RETRY_INTERVAL_S,
    ) -> None:
        self.serial = serial
        self.kind: DeviceKind = kind
        self._backend = backend
        self._clock = clock
        self._silence_s = silence_restart_s
        self._restart_s = restart_interval_s
        self._retry_s = retry_interval_s
        self._buffer_lock = threading.Lock()
        self._life = threading.Lock()  # raw и команды устройству
        self._buf: deque[Batch] = deque(maxlen=BUFFER_BATCHES)
        self._raw: RawSensor | None = None
        self._state = "disconnected"
        self._accepting = False
        self._closing = False
        self._connect_thread: threading.Thread | None = None
        self._last_attempt: float | None = None
        self._last_restart = float("-inf")
        self._last_data: float | None = None
        self._signal_started: float | None = None
        self._battery: int | None = None
        self._electrode_ok: bool | None = None
        self._not_found_streak = 0
        self._battery_from_callback = False
        self.reconnects = 0
        self.callback_errors = 0
        self.restarts = 0
        self.error = ""

    # --- состояние ---
    @property
    def state(self) -> str:
        """`connecting`, `connected` или `disconnected`."""
        return self._state

    @property
    def battery(self) -> int | None:
        return self._battery

    @property
    def electrode_ok(self) -> bool | None:
        """None — датчик контакт не сообщает или ещё не сообщил."""
        return self._electrode_ok

    @property
    def sampling_hz(self) -> int | None:
        raw = self._raw
        return None if raw is None else raw.sampling_hz

    # --- подключение ---
    def connect_async(self) -> None:
        if self._closing or self._state != "disconnected" or self._connect_thread_alive():
            return
        self._state = "connecting"
        self._last_attempt = self._clock()
        self._connect_thread = threading.Thread(
            target=self.connect, name=f"connect-{self.serial}", daemon=True
        )
        self._connect_thread.start()

    def _connect_thread_alive(self) -> bool:
        thread = self._connect_thread
        return thread is not None and thread.is_alive() and thread is not threading.current_thread()

    def connect(self) -> None:
        """Блокирующее подключение (секунды); не вызывать из игрового цикла."""
        self._state = "connecting"
        self._last_attempt = self._clock()
        raw: RawSensor | None = None
        self._battery_from_callback = False
        self._electrode_ok = None  # контакт новой связи ещё неизвестен
        try:
            raw = self._backend.open_sensor(self.serial, self.kind, self._handlers())
            with self._life:
                if self._closing:
                    raw.close()
                    return
                self._raw = raw
                self._accepting = True
                raw.start_signal()
                now = self._clock()
                self._signal_started = now
                if not self._battery_from_callback:  # колбэк мог прийти раньше и он свежее
                    self._battery = raw.battery()
                self._state = "connected"
                self._not_found_streak = 0
        except Exception as exc:
            if isinstance(exc, DeviceNotFoundError):
                self._not_found_streak += 1
            else:
                self._not_found_streak = 0
            log.warning("датчик %s не подключился: %s", self.serial, exc)
            self.error = str(exc)
            with self._life:
                self._release_locked(raw)
                self._state = "disconnected"

    def _handlers(self) -> SensorHandlers:
        return SensorHandlers(
            self._on_samples, self._on_state, self._on_battery, self._on_electrode
        )

    # --- колбэки SDK ---
    def _on_samples(self, rows: Sequence[Sequence[float]]) -> None:
        try:
            if not self._accepting:
                return
            arr = np.asarray(rows, dtype=float)
            if arr.ndim != 2 or arr.size == 0:
                return
            now = self._clock()
            with self._buffer_lock:
                self._buf.append((now, arr))
                self._last_data = now
        except Exception:
            self.callback_errors += 1

    def _on_state(self, in_range: bool) -> None:
        try:
            if self._closing or self._raw is None:
                return
            if not in_range and self._state == "connected":
                self._state = "disconnected"
            elif in_range and self._state == "disconnected":
                self._state = "connected"
                self.reconnects += 1
                self._last_data = None
                self._signal_started = self._clock()
        except Exception:
            self.callback_errors += 1

    def _on_battery(self, value: int) -> None:
        try:
            self._battery = int(value)
            self._battery_from_callback = True
        except Exception:
            self.callback_errors += 1

    def _on_electrode(self, ok: bool) -> None:
        try:
            self._electrode_ok = bool(ok)
        except Exception:
            self.callback_errors += 1

    # --- рабочий поток ---
    def drain(self) -> list[Batch]:
        with self._buffer_lock:
            out = list(self._buf)
            self._buf.clear()
        return out

    def poll(self) -> bool:
        """Повторное подключение и повторный StartSignal. True, если StartSignal отправлен."""
        if self._closing:
            return False
        now = self._clock()
        if self._state == "disconnected" and self._raw is None:
            last = self._last_attempt
            if last is None or now - last >= self._retry_delay():
                self.connect_async()
            return False
        if self._state != "connected":
            return False
        baseline = self._last_data if self._last_data is not None else self._signal_started
        if baseline is None:
            return False
        if now - baseline > self._silence_s and now - self._last_restart > self._restart_s:
            self._last_restart = now
            return self._restart_signal()
        return False

    def _retry_delay(self) -> float:
        """Пауза до новой попытки: растёт, пока датчик не находится поиском."""
        streak = min(self._not_found_streak, len(BACKOFF_FACTORS))
        return self._retry_s * BACKOFF_FACTORS[max(0, streak - 1)]

    def _restart_signal(self) -> bool:
        with self._life:
            raw = self._raw
            if raw is None or self._closing:
                return False
            try:
                raw.start_signal()
            except Exception as exc:
                self.error = f"StartSignal: {exc}"
                return False
            self.restarts += 1
            return True

    # --- освобождение ---
    def begin_close(self) -> None:
        """Сообщить о закрытии, не ожидая: так несколько датчиков закрываются параллельно."""
        self._closing = True
        self._accepting = False

    def close(self) -> None:
        self.begin_close()
        thread = self._connect_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=JOIN_TIMEOUT_S)
        with self._life:
            self._release_locked(self._raw)
            self._state = "disconnected"

    def _release_locked(self, raw: RawSensor | None) -> None:
        self._accepting = False
        if raw is None:
            return
        try:
            raw.stop_signal()
        except Exception as exc:
            self.error = f"StopSignal: {exc}"
        try:
            raw.close()
        except Exception as exc:
            self.error = f"освобождение: {exc}"
        if raw is self._raw:
            self._raw = None
