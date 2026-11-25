"""Цикл `neurotlon-bridge --discover`: JSONL со стороны лаунчера (`shared/sensor-discovery.md`).

Читает команды, отдаёт их `DiscoveryService`, пишет сообщения с меткой. Подключение блокирует
на секунды, поэтому идёт в рабочем потоке по одному; пишет в вывод только главный поток.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import TextIO

from neurotlon_contracts.discovery import (
    DISCOVERY_VERSION,
    decode_command,
    encode_message,
)

from .devices.base import DeviceKind
from .devices.discovery import DiscoveryService

log = logging.getLogger(__name__)

TICK_S = 0.1  # как часто главный цикл опрашивает сервис и пишет сообщения
JOIN_S = 3.0  # сколько ждём рабочий поток при выходе (подключение может висеть в SDK)

Inbox = queue.Queue[str | None]


class DiscoverySession:
    def __init__(self, service: DiscoveryService, write: Callable[[str], None]) -> None:
        self._service = service
        self._write = write
        self._jobs: queue.Queue[tuple[str, DeviceKind] | None] = queue.Queue()
        self._queued: set[str] = set()  # подключения, ещё не начавшиеся
        self._queued_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._broken = False  # запись в stdout не удалась

    # --- команды ---
    def handle_line(self, line: str) -> bool:
        """Выполнить команду из строки stdin; `False` — выходим."""
        command = decode_command(line)
        if command is None:
            log.info("команда отброшена: %.200s", line.strip())
            return True
        match command["cmd"]:
            case "scan":
                self._service.set_scan(bool(command["on"]))
            case "connect":
                self._enqueue(str(command["id"]), command["kind"])
            case "release":
                with self._queued_lock:
                    self._queued.discard(str(command["id"]))
                self._service.release(str(command["id"]))
            case "quit":
                return False
        return True

    def _enqueue(self, device_id: str, kind: DeviceKind) -> None:
        with self._queued_lock:
            self._queued.add(device_id)
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="discover-connect", daemon=True)
            self._worker.start()
        self._jobs.put((device_id, kind))

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                device_id, kind = job
                with self._queued_lock:
                    if device_id not in self._queued:
                        continue  # отпустили, пока стояло в очереди
                    self._queued.discard(device_id)
                try:
                    self._service.connect(device_id, kind)
                except Exception:
                    log.exception("подключение %s", device_id)
            finally:
                self._jobs.task_done()

    def wait_idle(self) -> None:
        """Дождаться, пока все поставленные подключения закончатся (для тестов)."""
        self._jobs.join()

    # --- вывод ---
    def pump(self) -> None:
        """Один шаг: опросить сканер и записать накопившиеся сообщения."""
        self._service.poll()
        self.flush()

    def flush(self) -> None:
        for message in self._service.drain():
            try:
                self._write(encode_message(message))
            except (OSError, ValueError):  # лаунчер закрыл вывод: дальше писать некому
                self._broken = True
                return

    def hello(self) -> None:
        try:
            self._write(encode_message({"type": "hello", "v": DISCOVERY_VERSION}))
        except (OSError, ValueError):
            self._broken = True

    def run(self, inbox: Inbox, tick_s: float = TICK_S) -> None:
        """Главный цикл до `quit` или конца ввода (`None` в очереди)."""
        try:
            self.hello()
            while not self._broken:
                try:
                    line = inbox.get(timeout=tick_s)
                except queue.Empty:
                    self.pump()
                    continue
                if line is None or not self.handle_line(line):
                    break
                self.pump()
        finally:
            self.close()  # датчики и сканер отпускаются при любом выходе

    def close(self) -> None:
        """Отпустить датчики и сканер, дописать оставшиеся сообщения."""
        with self._queued_lock:
            self._queued.clear()  # ожидающие подключения не начинать
        self._jobs.put(None)
        if self._worker is not None:
            self._worker.join(JOIN_S)
        self._service.close()
        self.flush()


def pump_lines(stream: TextIO, inbox: Inbox) -> None:
    """Читать строки в очередь; конец ввода — `None`."""
    try:
        for line in stream:
            inbox.put(line)
    except (OSError, ValueError):
        log.info("ввод закрыт")
    finally:
        inbox.put(None)


def start_reader(stream: TextIO, inbox: Inbox) -> threading.Thread:
    thread = threading.Thread(target=pump_lines, args=(stream, inbox), name="discover-stdin")
    thread.daemon = True
    thread.start()
    return thread
