"""Связь лаунчера с мостом датчиков (`shared/bridge-protocol.md`) на экране «Калибровка».

Только стандартная библиотека: лаунчер не зависит от пакета моста, формат сообщений общий через
`shared/` (согласованность имён проверяет тест по схеме). Мост пускает одного клиента, поэтому
лаунчер подключается при входе на экран калибровки и закрывает связь до запуска игры.

`BridgeLink` — интерфейс для машины и оркестратора; `SocketBridgeLink` — настоящая реализация
(поток чтения с переподключением по образцу клиента моста), в тестах подставляется подделка.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import socket
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

LinkState = Literal["connecting", "live", "lost"]

RECONNECT_S = 0.5
CONNECT_TIMEOUT_S = 1.0
RING_SECONDS = 15.0  # сколько секунд значений хранить для потока `/api/signals`
SAMPLE_RATE_HZ = 50
BURST_RING = 64
MAX_LINE_BYTES = 64 * 1024
CLOSE_TIMEOUT_S = 3.0
FEATURE_CALIBRATION_STATE = "calibration_state"
# Шаги, после которых у сигнала готова шкала (`rest` без `contract` её не даёт).
FINAL_STEPS = frozenset({"cycle", "contract", "baseline"})


@dataclass(frozen=True)
class Hello:
    signals: tuple[tuple[str, str], ...]
    features: tuple[str, ...] = ()
    eeg_method: str | None = None
    calibrated: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepProgress:
    """Последнее сообщение `calibration` по сигналу."""

    step: str
    status: str  # running | done | failed
    progress: float = 0.0
    reason: str | None = None
    segment: int | None = None
    phase: str | None = None
    phase_left_s: float | None = None


@dataclass(frozen=True)
class Reading:
    v: float
    ok: bool
    reason: str | None = None


@dataclass(frozen=True)
class SampleRecord:
    seq: int  # номер в этой связи: растёт без разрывов, в отличие от `t_ms` моста
    t_ms: int
    signals: Mapping[str, Reading]


@dataclass(frozen=True)
class BurstRecord:
    n: int
    signal: str
    t_ms: int
    rise: float | None


@dataclass(frozen=True)
class LinkView:
    """Неизменяемый снимок состояния связи для одного шага машины."""

    link: LinkState
    hello: Hello | None = None
    states: Mapping[str, str] = field(default_factory=dict)
    batteries: Mapping[str, int | None] = field(default_factory=dict)
    calibrated: frozenset[str] = frozenset()
    progress: Mapping[str, StepProgress] = field(default_factory=dict)
    generation: int = 0  # растёт с каждым новым `hello` (мост перезапускался или переподключились)

    @property
    def emulated(self) -> bool:
        """Все датчики эмулятора: калибровка не нужна."""
        return bool(self.states) and all(s == "emulated" for s in self.states.values())


@dataclass(frozen=True)
class SignalBatch:
    cursor: int
    samples: tuple[SampleRecord, ...]
    bursts: tuple[BurstRecord, ...]
    generation: int


class BridgeLink(Protocol):
    def view(self) -> LinkView: ...

    def calibrate(self, signal: str, step: str, duration_s: float | None = None) -> bool:
        """Запустить шаг; сигнал сразу перестаёт считаться откалиброванным."""
        ...

    def reset(self) -> bool:
        """Новый участник: калибровка всех сигналов стирается."""
        ...

    def recent(self, after_seq: int, after_burst: int, limit: int) -> SignalBatch:
        """Не более `limit` последних значений новее `after_seq` и события новее `after_burst`."""
        ...

    def close(self) -> None:
        """Закрыть связь и дождаться закрытия сокета: слот моста освобождается."""
        ...


BridgeLinkFactory = Callable[[], BridgeLink]


def _number(value: object) -> float | None:
    """Конечное число или `None`: `NaN`, бесконечность и не числа отбрасываются."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:  # целое из сотен цифр
        return None
    return number if math.isfinite(number) else None


def parse_hello(data: dict[str, Any]) -> Hello:
    signals: list[tuple[str, str]] = []
    for item in data.get("signals") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            signals.append((item["name"], str(item.get("state", ""))))
    features = tuple(f for f in data.get("features") or [] if isinstance(f, str))
    method = data.get("eeg_method")
    calibrated = tuple(s for s in data.get("calibrated") or [] if isinstance(s, str))
    return Hello(tuple(signals), features, method if isinstance(method, str) else None, calibrated)


def parse_progress(data: dict[str, Any]) -> tuple[str, StepProgress] | None:
    signal, step, status = data.get("signal"), data.get("step"), data.get("status")
    if not (isinstance(signal, str) and isinstance(step, str) and isinstance(status, str)):
        return None
    progress = _number(data.get("progress"))
    if progress is None:
        progress = 1.0 if status == "done" else 0.0
    reason = data.get("reason")
    segment = _number(data.get("segment"))
    phase = data.get("phase")
    return signal, StepProgress(
        step,
        status,
        min(1.0, max(0.0, progress)),
        reason if isinstance(reason, str) else None,
        None if segment is None else int(segment),
        phase if isinstance(phase, str) else None,
        _number(data.get("phase_left_s")),
    )


def parse_sample(data: dict[str, Any], seq: int) -> SampleRecord | None:
    t_ms, raw = _number(data.get("t_ms")), data.get("signals")
    if t_ms is None or not isinstance(raw, dict):
        return None
    readings: dict[str, Reading] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        value = _number(item.get("value"))
        if value is None or not isinstance(item.get("valid"), bool):
            continue
        reason = item.get("reason")
        readings[str(name)] = Reading(
            min(1.0, max(0.0, value)),
            item["valid"],
            None if item["valid"] else (reason if isinstance(reason, str) else "disconnected"),
        )
    return SampleRecord(seq, int(t_ms), readings)


class SocketBridgeLink:
    """TCP-клиент моста в отдельном потоке: читает, переподключается, отвечает на команды."""

    def __init__(self, host: str, port: int, *, reconnect_s: float = RECONNECT_S) -> None:
        self._host = host
        self._port = port
        self._reconnect_s = reconnect_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._link: LinkState = "connecting"
        self._hello: Hello | None = None
        self._states: dict[str, str] = {}
        self._batteries: dict[str, int | None] = {}
        self._calibrated: set[str] = set()
        self._progress: dict[str, StepProgress] = {}
        self._generation = 0
        self._seq = 0
        self._burst_n = 0
        self._samples: deque[SampleRecord] = deque(maxlen=int(RING_SECONDS * SAMPLE_RATE_HZ))
        self._bursts: deque[BurstRecord] = deque(maxlen=BURST_RING)
        self._thread = threading.Thread(target=self._run, name="bridge-link", daemon=True)
        self._thread.start()

    # --- чтение состояния ---

    def view(self) -> LinkView:
        with self._lock:
            return LinkView(
                self._link,
                self._hello,
                dict(self._states),
                dict(self._batteries),
                frozenset(self._calibrated),
                dict(self._progress),
                self._generation,
            )

    def recent(self, after_seq: int, after_burst: int, limit: int) -> SignalBatch:
        with self._lock:
            fresh = [s for s in self._samples if s.seq > after_seq][-limit:]
            bursts = tuple(b for b in self._bursts if b.n > after_burst)
            cursor = fresh[-1].seq if fresh else after_seq
            return SignalBatch(cursor, tuple(fresh), bursts, self._generation)

    # --- команды ---

    def calibrate(self, signal: str, step: str, duration_s: float | None = None) -> bool:
        with self._lock:
            self._calibrated.discard(signal)  # мост стирает прежнюю шкалу при старте шага
            self._progress.pop(signal, None)
        message: dict[str, Any] = {"type": "calibrate", "signal": signal, "step": step}
        if duration_s is not None:
            message["duration_s"] = duration_s
        return self._send(message)

    def reset(self) -> bool:
        with self._lock:
            self._calibrated.clear()
            self._progress.clear()
        return self._send({"type": "reset"})

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            sock = self._sock
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        self._thread.join(timeout=CLOSE_TIMEOUT_S)
        if self._thread.is_alive():
            log.warning("bridge link thread did not stop in %.0f s", CLOSE_TIMEOUT_S)

    # --- внутреннее ---

    def _send(self, message: dict[str, Any]) -> bool:
        with self._lock:
            sock = self._sock
        if sock is None:
            return False
        try:
            sock.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        except OSError:
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self._host, self._port), timeout=CONNECT_TIMEOUT_S)
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
                log.exception("bridge link read failed")
            finally:
                with self._lock:
                    self._sock = None
                    if self._hello is not None:
                        self._link = "lost"
                with contextlib.suppress(OSError):
                    sock.close()
            self._stop.wait(self._reconnect_s)

    def _read_loop(self, sock: socket.socket) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                return
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            if len(buffer) > MAX_LINE_BYTES:
                log.warning("bridge line longer than %d bytes, link closed", MAX_LINE_BYTES)
                return
            for line in lines:
                if line.strip():
                    self._on_line(line)

    def _on_line(self, line: bytes) -> None:
        try:
            data = json.loads(line)
        except ValueError:
            log.warning("broken bridge message ignored")
            return
        if isinstance(data, dict):
            with self._lock:
                self._apply(data)

    def _apply(self, data: dict[str, Any]) -> None:
        match data.get("type"):
            case "hello":
                hello = parse_hello(data)
                self._hello = hello
                self._link = "live"
                self._generation += 1
                self._states = dict(hello.signals)
                self._batteries = {}
                self._calibrated = set(hello.calibrated)
                self._progress = {}
                self._bursts.clear()
            case "sample":
                record = parse_sample(data, self._seq + 1)
                if record is not None:
                    self._seq = record.seq
                    self._samples.append(record)
            case "sensor":
                signal = data.get("signal")
                if isinstance(signal, str):
                    self._states[signal] = str(data.get("state", ""))
                    battery = _number(data.get("battery"))
                    self._batteries[signal] = None if battery is None else int(battery)
            case "calibration":
                parsed = parse_progress(data)
                if parsed is not None:
                    self._apply_progress(*parsed)
            case "burst":
                signal, t_ms = data.get("signal"), _number(data.get("t_ms"))
                if isinstance(signal, str) and t_ms is not None:
                    self._burst_n += 1
                    rise = _number(data.get("rise"))
                    self._bursts.append(BurstRecord(self._burst_n, signal, int(t_ms), rise))
            case _:
                pass

    def _apply_progress(self, signal: str, progress: StepProgress) -> None:
        self._progress[signal] = progress
        if progress.status == "done" and progress.step in FINAL_STEPS:
            self._calibrated.add(signal)
        else:
            self._calibrated.discard(signal)
