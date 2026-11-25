"""Фоновый поиск датчиков для экрана настройки: состояние списка и подключений.

`DiscoveryService` не читает stdin и не пишет в stdout: команды приходят вызовами методов,
сообщения для лаунчера (`shared/sensor-discovery.md`) забирает `drain()`. Сканер (`ScannerPort`),
часы и ожидание внедряются, поэтому всё проверяется без железа и без потоков.

Потоки: `poll()` и `drain()` зовёт главный цикл, `connect()` блокирует на секунды и идёт в
рабочем потоке; колбэки SDK приходят из нативных потоков и только складывают данные.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from neurotlon_contracts.sensor_devices import MAX_ADDRESS, MAX_NAME, clean_text

from ..source import Clock
from .base import (
    DeviceError,
    DeviceInfo,
    DeviceKind,
    RawSensor,
    ScannerPort,
    SensorHandlers,
)

log = logging.getLogger(__name__)

POLL_S = 0.5  # как часто спрашиваем у сканера список
STALE_S = 15.0  # не виден дольше: «нет в эфире»
DROP_S = 60.0  # не виден дольше и без соединения: убрать из списка
CANCEL_STEP_S = 0.2  # как часто ожидание подключения смотрит на отмену
MAX_ITEMS = 64  # больше схема не пускает
MAX_AGE_MS = 3_600_000
MIN_DEVICES_EMIT_S = 0.5  # `devices` не чаще двух раз в секунду
MIN_LINK_EMIT_S = 0.2  # `link` при сдвиге уровня не чаще пяти раз в секунду
RSSI_STEP_DB = 5  # сдвиг RSSI, который считается изменением
LEVEL_STEP = 0.03  # сдвиг уровня, который считается изменением
PROBE_WAIT_S = 2.0  # ждём первых отсчётов после подключения
SIGNAL_FRESH_S = 2.0  # отсчёты не старше: `signal` истинно
CONNECT_TIMEOUT_S = 20.0
LEVEL_FULL_V = 3e-4  # RMS, которой соответствует уровень 1 (300 мкВ): грубая шкала без калибровки
LEVEL_WINDOW_S = 0.25
SAMPLE_BUFFER = 4000
PROBE_STEP_S = 0.05

NOT_SEEN = "Устройство не найдено: подождите, пока оно появится в списке"
WRONG_KIND = "Устройство другого вида"
CANCELLED_TEXT = "Подключение отменено"
CONNECT_FAILED = "Не удалось подключиться"
TIMEOUT_TEXT = "Подключение не завершилось за {seconds:g} с: выключите и включите датчик"
SCAN_FAILED = "Ошибка поиска датчиков"

Message = dict[str, Any]


@dataclass
class _Seen:
    info: DeviceInfo
    first_seen: float
    last_seen: float


class _Link:
    """Подключение к одному датчику; поля читает и пишет разные потоки, поэтому под замком."""

    def __init__(self, address: str, kind: DeviceKind, clock: Clock) -> None:
        self.address = address
        self.kind: DeviceKind = kind
        self._clock = clock
        self._lock = threading.Lock()
        self._samples: deque[float] = deque(maxlen=SAMPLE_BUFFER)
        self._last_data: float | None = None
        self._state = "connecting"
        self._serial = ""
        self._battery: int | None = None
        self._contact: bool | None = None
        self._error = ""
        self._hz = 1000
        self.raw: RawSensor | None = None
        self.cancelled = False
        self.abandoned = False

    # --- колбэки SDK: не бросают исключений ---
    def handlers(self) -> SensorHandlers:
        return SensorHandlers(self._on_samples, self._on_state, self._on_battery, self._on_contact)

    def _on_samples(self, rows: Sequence[Sequence[float]]) -> None:
        try:
            values = [float(row[0]) for row in rows]
            with self._lock:
                self._samples.extend(values)
                self._last_data = self._clock()
        except Exception:
            log.debug("битый пакет отсчётов", exc_info=True)

    def _on_state(self, in_range: bool) -> None:
        with self._lock:
            if self._state in ("connected", "lost"):
                self._state = "connected" if in_range else "lost"

    def _on_battery(self, value: int) -> None:
        with self._lock:
            self._battery = int(value)

    def _on_contact(self, ok: bool) -> None:
        with self._lock:
            self._contact = bool(ok)

    # --- управление ---
    def attach(self, raw: RawSensor) -> None:
        hz = raw.sampling_hz  # вызовы SDK: не под замком, который берут колбэки
        serial = clean_text(raw.serial_number(), MAX_NAME)
        battery = raw.battery()
        with self._lock:
            self.raw = raw
            self._hz = hz
            self._serial = serial
            if battery is not None and self._battery is None:
                self._battery = battery
            self._state = "connected"

    def has_data(self) -> bool:
        with self._lock:
            return self._last_data is not None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def serial(self) -> str:
        with self._lock:
            return self._serial

    def view(self) -> Message:
        """Сообщение `link` по текущему состоянию."""
        now = self._clock()
        with self._lock:
            signal = self._last_data is not None and now - self._last_data <= SIGNAL_FRESH_S
            level = self._level() if signal and self.kind == "callibri" else None
            message: Message = {
                "type": "link",
                "id": self.address,
                "state": self._state,
                "serial": self._serial,
                "battery": self._battery,
                "contact": self._contact if self.kind == "callibri" else None,
                "signal": signal,
                "level": level,
            }
            if self._error:
                message["error"] = self._error
            return message

    def _level(self) -> float | None:
        """Грубая RMS последних 0,25 с без постоянной составляющей, 0…1."""
        count = max(8, int(self._hz * LEVEL_WINDOW_S))
        if len(self._samples) < 8:
            return None
        window = np.fromiter(list(self._samples)[-count:], dtype=float)
        rms = float(np.sqrt(np.mean((window - window.mean()) ** 2)))
        return round(min(1.0, rms / LEVEL_FULL_V), 2)

    def fail(self, error: str) -> Message:
        with self._lock:
            self._state = "failed"
            self._error = clean_text(error, 300)
        return self.view()

    def close(self) -> None:
        """Освободить датчик; ошибки SDK не мешают закрыть остальное."""
        with self._lock:
            raw, self.raw = self.raw, None
        if raw is None:
            return
        try:
            raw.stop_signal()
        except Exception as exc:
            log.warning("StopSignal: %s", exc)
        try:
            raw.close()
        except Exception as exc:
            log.warning("освобождение датчика: %s", exc)


@dataclass
class _Sent:
    """Что уходило лаунчеру в последний раз: по этому решаем, есть ли что слать."""

    devices_key: tuple[Any, ...] | None = None
    devices_rssi: dict[str, int | None] = field(default_factory=dict)
    devices_at: float | None = None
    links: dict[str, tuple[tuple[Any, ...], float | None, float]] = field(default_factory=dict)


class DiscoveryService:
    def __init__(
        self,
        scanner: ScannerPort,
        clock: Clock = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        *,
        connect_timeout_s: float = CONNECT_TIMEOUT_S,
        probe_wait_s: float = PROBE_WAIT_S,
    ) -> None:
        self._scanner = scanner
        self._clock = clock
        self._sleep = sleep
        self._connect_timeout_s = connect_timeout_s
        self._probe_wait_s = probe_wait_s
        self._lock = threading.Lock()  # состояние; держится недолго
        self._io = threading.Lock()  # вызовы сканера start/stop/sensors; не во время connect
        self._seen: dict[str, _Seen] = {}
        self._serials: dict[str, str] = {}  # адрес -> серийный номер, узнанный после подключения
        self._links: dict[str, _Link] = {}
        self._outbox: list[Message] = []
        self._scanning = False  # поиск включён лаунчером (может быть на паузе)
        self._paused = 0  # сколько подключений идут сейчас
        self._last_poll: float | None = None
        self._sent = _Sent()
        # Время «старения» стоит, пока поиск выключен или на паузе: список замирает, а не
        # превращается в «нет в эфире» только потому, что никто не смотрит.
        self._frozen_at: float | None = clock()
        self._frozen_total = 0.0

    # --- команды лаунчера ---
    @property
    def scanning(self) -> bool:
        return self._scanning

    def set_scan(self, on: bool) -> None:
        with self._lock:
            if self._scanning == on:
                return
            self._scanning = on
            paused = self._paused > 0
            if on:
                self._last_poll = None
            self._refresh_aging()
        if paused:
            return  # после подключения поиск возобновится сам
        with self._io:
            try:
                if on:
                    self._scanner.start()
                else:
                    self._scanner.stop()
            except Exception as exc:
                self._scan_failed(exc)

    def poll(self) -> None:
        """Спросить у сканера список, если поиск включён и пора."""
        now = self._clock()
        with self._lock:
            if not self._scanning or self._paused:
                return
            if self._last_poll is not None and now - self._last_poll < POLL_S:
                return
            self._last_poll = now
        with self._io:
            with self._lock:
                if self._paused or not self._scanning:
                    return  # подключение началось: SDK не опрашиваем
            try:
                found = self._scanner.sensors()
            except Exception as exc:
                self._scan_failed(exc)
                return
        with self._lock:
            self._remember(found, self._aged(now))

    def connect(self, device_id: str, kind: DeviceKind) -> None:
        """Подключиться и держать соединение (блокирует до 20 с). Результат — сообщения `link`."""
        with self._lock:
            if device_id in self._links:
                return  # уже подключаемся или подключены
            seen = self._seen.get(device_id)
            problem = NOT_SEEN if seen is None else WRONG_KIND if seen.info.kind != kind else None
            if problem is not None:
                self._outbox.append(_failed(device_id, problem))
                return
            link = _Link(device_id, kind, self._clock)
            self._links[device_id] = link
            self._paused += 1
            self._refresh_aging()
            first = self._link_message(link, self._clock(), force=True)
            assert first is not None
            self._outbox.append(first)
        try:
            self._pause_scanning()
            self._open(link)
        except Exception as exc:
            self._drop_link(link)
            link.close()
            if not link.cancelled:
                with self._lock:
                    self._outbox.append(link.fail(_reason(exc)))
        finally:
            with self._lock:
                self._paused -= 1
                self._refresh_aging()
                resume = self._paused == 0 and self._scanning
            if resume:
                self._resume_scanning()
        if link.cancelled:
            link.close()

    def release(self, device_id: str) -> None:
        with self._lock:
            link = self._links.pop(device_id, None)
            self._sent.links.pop(device_id, None)
        if link is None:
            return
        link.cancelled = True  # подключение в разгаре: отпустит само по окончании
        link.close()

    def close(self) -> None:
        """Отпустить все датчики и сканер."""
        with self._lock:
            links = list(self._links.values())
            self._links.clear()
            self._scanning = False
            self._refresh_aging()
        for link in links:
            link.cancelled = True
            link.close()
        with self._io:
            try:
                self._scanner.stop()
            except Exception as exc:
                log.warning("остановка поиска: %s", exc)
            try:
                self._scanner.close()
            except Exception as exc:
                log.warning("освобождение сканера: %s", exc)

    # --- сообщения для лаунчера ---
    def drain(self) -> list[Message]:
        """Что нужно отправить сейчас: ошибки, список (если изменился), подключения."""
        now = self._clock()
        with self._lock:
            out, self._outbox = self._outbox, []
            aged = self._aged(now)
            self._expire(aged)
            devices = self._devices_message(now, aged)
            if devices is not None:
                out.append(devices)
            for link in list(self._links.values()):
                message = self._link_message(link, now)
                if message is not None:
                    out.append(message)
        return out

    # --- подключение ---
    def _pause_scanning(self) -> None:
        """Поиск ставится на паузу: на Windows поиск вместе с подключением ненадёжен."""
        with self._io:  # дожидаемся sensors(), который мог начаться до паузы
            if self._scanning:
                self._scanner.stop()

    def _resume_scanning(self) -> None:
        with self._io:
            try:
                self._scanner.start()
            except Exception as exc:
                self._scan_failed(exc)

    def _open(self, link: _Link) -> None:
        raw = self._connect_with_timeout(link)
        if link.cancelled:  # отпустили, пока подключались
            raw.close()
            return
        try:
            raw.start_signal()
        except Exception:
            raw.close()
            raise
        link.attach(raw)
        with self._lock:
            serial = link.serial
            if serial:
                self._serials[link.address] = serial
        deadline = self._clock() + self._probe_wait_s
        while not link.has_data() and self._clock() < deadline and not link.cancelled:
            self._sleep(PROBE_STEP_S)

    def _connect_with_timeout(self, link: _Link) -> RawSensor:
        """`scanner.connect` в отдельном потоке: SDK может зависнуть, а мы ждём не дольше срока."""
        outcome: list[RawSensor | BaseException] = []
        guard = threading.Lock()
        done = threading.Event()

        def work() -> None:
            try:
                result: RawSensor | BaseException = self._scanner.connect(
                    link.address, link.kind, link.handlers()
                )
            except BaseException as exc:
                result = exc
            with guard:
                if link.abandoned and not isinstance(result, BaseException):
                    result.close()  # опоздал: никому не нужен
                else:
                    outcome.append(result)
            done.set()

        threading.Thread(target=work, name=f"connect-{link.address}", daemon=True).start()
        deadline = time.monotonic() + self._connect_timeout_s
        while not done.wait(min(CANCEL_STEP_S, max(0.0, deadline - time.monotonic()))):
            expired = time.monotonic() >= deadline
            if expired or link.cancelled:  # «Отключить» во время подключения не держит поток
                with guard:
                    if not outcome:
                        link.abandoned = True
                        raise DeviceError(
                            TIMEOUT_TEXT.format(seconds=self._connect_timeout_s)
                            if expired
                            else CANCELLED_TEXT
                        )
                break
        result = outcome[0]
        if isinstance(result, BaseException):
            raise result
        return result

    def _drop_link(self, link: _Link) -> None:
        with self._lock:
            if self._links.get(link.address) is link:
                del self._links[link.address]
            self._sent.links.pop(link.address, None)

    # --- список ---
    def _refresh_aging(self) -> None:
        """Вызывать под `_lock` после смены `_scanning` или `_paused`."""
        now = self._clock()
        running = self._scanning and self._paused == 0
        if running and self._frozen_at is not None:
            self._frozen_total += now - self._frozen_at
            self._frozen_at = None
        elif not running and self._frozen_at is None:
            self._frozen_at = now

    def _aged(self, now: float) -> float:
        """Время по часам старения: стоит, пока поиск не идёт."""
        return (now if self._frozen_at is None else self._frozen_at) - self._frozen_total

    def _remember(self, found: Sequence[DeviceInfo], now: float) -> None:
        for info in found:
            seen = self._seen.get(info.address)
            if seen is None:
                self._seen[info.address] = _Seen(info, now, now)
            else:
                seen.info, seen.last_seen = info, now

    def _expire(self, now: float) -> None:
        for address, seen in list(self._seen.items()):
            if now - seen.last_seen > DROP_S and address not in self._links:
                del self._seen[address]
                self._serials.pop(address, None)

    def _scan_failed(self, exc: Exception) -> None:
        text = str(exc) if isinstance(exc, DeviceError) else f"{SCAN_FAILED}: {exc}"
        text = clean_text(text, 300) or SCAN_FAILED  # схема: от 1 до 300 знаков
        if not isinstance(exc, DeviceError):
            log.warning("поиск датчиков: %s", exc, exc_info=True)
        with self._lock:
            self._scanning = False
            self._refresh_aging()
            self._outbox.append({"type": "error", "message": text})

    def _items(self, now: float) -> list[Message]:
        items: list[Message] = []
        for address, seen in self._visible():
            link = self._links.get(address)
            held = link is not None and link.state == "connected"
            age_ms = 0 if held else min(MAX_AGE_MS, max(0, int((now - seen.last_seen) * 1000)))
            info = seen.info
            items.append(
                {
                    "id": address,
                    "kind": info.kind,
                    "name": clean_text(info.name, MAX_NAME) or info.kind,
                    "serial": clean_text(info.serial or self._serials.get(address, ""), MAX_NAME),
                    "address": address,
                    "rssi": info.rssi,
                    "age_ms": age_ms,
                }
            )
        return items

    def _visible(self) -> list[tuple[str, _Seen]]:
        """Не больше `MAX_ITEMS` устройств: лишние (самые слабые по RSSI) не показываются.

        Порядок среди оставшихся прежний, по времени первого обнаружения.
        """
        entries = [(a, s) for a, s in self._seen.items() if 0 < len(a) <= MAX_ADDRESS]
        if len(entries) <= MAX_ITEMS:
            return entries

        def strength(index: int) -> int:
            address, seen = entries[index]
            rssi = seen.info.rssi if seen.info.rssi is not None else -999
            return rssi + (1000 if address in self._links else 0)  # подключённые остаются всегда

        strongest = sorted(range(len(entries)), key=strength, reverse=True)[:MAX_ITEMS]
        return [entries[i] for i in sorted(strongest)]

    def _devices_message(self, now: float, aged: float) -> Message | None:
        items = self._items(aged)
        key = (
            self._scanning,
            tuple(
                (i["id"], i["kind"], i["name"], i["serial"], i["age_ms"] < STALE_S * 1000)
                for i in items
            ),
        )
        sent = self._sent
        changed = key != sent.devices_key or any(
            _rssi_moved(sent.devices_rssi.get(i["id"]), i["rssi"], i["id"] in sent.devices_rssi)
            for i in items
        )
        if not changed:
            return None
        if sent.devices_at is not None and now - sent.devices_at < MIN_DEVICES_EMIT_S:
            return None
        sent.devices_key, sent.devices_at = key, now
        sent.devices_rssi = {i["id"]: i["rssi"] for i in items}
        return {"type": "devices", "scanning": self._scanning, "items": items}

    def _link_message(self, link: _Link, now: float, *, force: bool = False) -> Message | None:
        message = link.view()
        key = tuple(
            message.get(name)
            for name in ("state", "serial", "battery", "contact", "signal", "error")
        )
        level = message["level"]
        previous = None if force else self._sent.links.get(link.address)
        if previous is not None:
            last_key, last_level, last_at = previous
            if key == last_key and not _level_moved(last_level, level):
                return None
            if key == last_key and now - last_at < MIN_LINK_EMIT_S:
                return None
        self._sent.links[link.address] = (key, level, now)
        return message


def _failed(device_id: str, error: str) -> Message:
    return {
        "type": "link",
        "id": device_id,
        "state": "failed",
        "serial": "",
        "battery": None,
        "contact": None,
        "signal": False,
        "level": None,
        "error": clean_text(error, 300),
    }


def _reason(exc: BaseException) -> str:
    text = str(exc).strip()
    if isinstance(exc, DeviceError) and text:
        return text[:300]
    return f"{CONNECT_FAILED}: {text}"[:300] if text else CONNECT_FAILED


def _rssi_moved(last: int | None, now: int | None, known: bool) -> bool:
    if not known:
        return True
    if last is None or now is None:
        return last != now
    return abs(now - last) >= RSSI_STEP_DB


def _level_moved(last: float | None, now: float | None) -> bool:
    if last is None or now is None:
        return last != now
    return abs(now - last) >= LEVEL_STEP
