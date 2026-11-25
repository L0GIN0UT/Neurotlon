"""Клиент моста для игр. Без pygame и SDK датчиков."""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from collections import deque

from . import protocol
from .source import (
    MAX_PENDING_BURSTS,
    CalibrationProgress,
    CalibrationStep,
    Clock,
    EegMethod,
    Feature,
    Reading,
    Segment,
    SensorState,
)

log = logging.getLogger(__name__)

STALE_AFTER_S = 0.5
RECONNECT_S = 1.0
MAX_LINE_BYTES = 64 * 1024


class BridgeClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        clock: Clock = time.monotonic,
        reconnect_s: float = RECONNECT_S,
    ) -> None:
        self._host = host
        self._port = port
        self._clock = clock
        self._reconnect_s = reconnect_s
        self._lock = threading.Lock()
        self._samples: dict[str, tuple[Reading, float]] = {}
        self._states: dict[str, SensorState] = {}
        self._calibrations: dict[str, CalibrationProgress] = {}
        self._features: tuple[Feature, ...] = ()
        self._eeg_method: EegMethod | None = None
        self._calibrated: frozenset[str] = frozenset()
        self._bursts: deque[protocol.Burst] = deque(maxlen=MAX_PENDING_BURSTS)
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bridge-client", daemon=True)
        self._thread.start()

    # --- чтение состояния (из потока игры) ---

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._sock is not None

    def latest(self, signal: str) -> Reading | None:
        with self._lock:
            entry = self._samples.get(signal)
        if entry is None:
            return None
        reading, received = entry
        if self._clock() - received > STALE_AFTER_S:
            return Reading(0.0, False, "stale")
        return reading

    def sensor_state(self, signal: str) -> SensorState | None:
        with self._lock:
            return self._states.get(signal)

    def calibration(self, signal: str) -> CalibrationProgress | None:
        with self._lock:
            return self._calibrations.get(signal)

    @property
    def features(self) -> tuple[Feature, ...]:
        """Что умеет мост (`hello.features`); у старого моста пусто."""
        with self._lock:
            return self._features

    @property
    def eeg_method(self) -> EegMethod | None:
        """Метод ЭЭГ из `hello`; None, если мост не сообщил."""
        with self._lock:
            return self._eeg_method

    def calibrated(self, signal: str) -> bool:
        """Шкала сигнала готова по `hello.calibrated`; у старого моста всегда False.

        Список обновляется только новым `hello`: ход самой калибровки виден в `calibration`.
        """
        with self._lock:
            return signal in self._calibrated

    def bursts(self) -> list[protocol.Burst]:
        """События резких сокращений с прошлого вызова, в порядке прихода."""
        with self._lock:
            out = list(self._bursts)
            self._bursts.clear()
        return out

    # --- команды ---

    def calibrate(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> bool:
        return self._send(protocol.Calibrate(signal, step, segments, duration_s))

    def reset(self) -> bool:
        with self._lock:
            self._calibrations.clear()
            self._calibrated = frozenset()
        return self._send(protocol.Reset())

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            sock = self._sock
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        self._thread.join(timeout=3)

    # --- внутреннее ---

    def _send(self, msg: protocol.Message) -> bool:
        with self._lock:
            sock = self._sock
        if sock is None:
            return False
        try:
            sock.sendall(protocol.encode(msg))
        except OSError:
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self._host, self._port), timeout=1.0)
            except OSError:
                self._stop.wait(self._reconnect_s)
                continue
            sock.settimeout(0.2)
            with self._lock:
                self._sock = sock
            try:
                self._read_loop(sock)
            except OSError:
                pass
            except Exception:
                log.exception("сбой чтения из моста")
            finally:
                with self._lock:
                    self._sock = None
                    self._states.clear()
                    self._calibrations.clear()
                    self._features = ()
                    self._eeg_method = None
                    self._calibrated = frozenset()
                    self._bursts.clear()
                sock.close()
            self._stop.wait(self._reconnect_s)

    def _read_loop(self, sock: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                return
            buf += chunk
            *lines, buf = buf.split(b"\n")
            if len(buf) > MAX_LINE_BYTES:
                log.warning("строка моста длиннее %d байт, соединение закрыто", MAX_LINE_BYTES)
                return
            for line in lines:
                if line.strip():
                    self._on_line(line)

    def _on_line(self, line: bytes) -> None:
        try:
            self._apply(protocol.decode(line))
        except ValueError as exc:
            log.warning("битое сообщение моста: %s", exc)
        except Exception:
            log.exception("не удалось обработать сообщение моста")

    def _apply(self, msg: protocol.Message | None) -> None:
        now = self._clock()
        with self._lock:
            match msg:
                case protocol.Hello():
                    self._states = dict(msg.signals)
                    self._features = msg.features or ()
                    self._eeg_method = msg.eeg_method
                    self._calibrated = frozenset(msg.calibrated or ())
                    self._bursts.clear()
                case protocol.Sample():
                    for name, reading in msg.signals.items():
                        self._samples[name] = (reading, now)
                case protocol.Sensor():
                    self._states[msg.signal] = msg.state
                case protocol.Calibration():
                    progress = msg.progress
                    if progress is None:
                        progress = 1.0 if msg.status == "done" else 0.0
                    self._calibrations[msg.signal] = CalibrationProgress(
                        msg.step,
                        msg.status,
                        progress,
                        msg.reason,
                        msg.segment,
                        msg.phase,
                        msg.phase_left_s,
                    )
                case protocol.Burst():
                    self._bursts.append(msg)
                case _:
                    pass
