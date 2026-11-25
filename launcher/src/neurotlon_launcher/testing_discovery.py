"""Подделка процесса `neurotlon-bridge --discover` для тестов: без процесса и Bluetooth."""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from neurotlon_contracts.discovery import encode_message
from neurotlon_launcher.discovery import DiscoveryClient, DiscoveryListener

Responder = Callable[[dict[str, Any]], Sequence[dict[str, Any]]]


def item(
    address: str,
    kind: str = "callibri",
    name: str = "Callibri_Red",
    serial: str = "",
    rssi: int | None = -60,
    age_ms: int = 100,
) -> dict[str, Any]:
    return {
        "id": address,
        "kind": kind,
        "name": name,
        "serial": serial,
        "address": address,
        "rssi": rssi,
        "age_ms": age_ms,
    }


def devices(*items: dict[str, Any], scanning: bool = True) -> dict[str, Any]:
    return {"type": "devices", "scanning": scanning, "items": list(items)}


def link(address: str, state: str = "connected", **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "link",
        "id": address,
        "state": state,
        "serial": "",
        "battery": None,
        "contact": None,
        "signal": False,
        "level": None,
    }
    return {**base, **fields}


class FakeProcess:
    """Процесс поиска: команды из stdin видны в `commands`, ответы подаёт `responder` или тест."""

    def __init__(self, responder: Responder | None = None) -> None:
        self._out: queue.Queue[str | None] = queue.Queue()
        self._err: queue.Queue[str | None] = queue.Queue()
        self._responder = responder
        self._code: int | None = None
        self._lock = threading.Lock()
        self.commands: list[dict[str, Any]] = []
        self.killed = False
        self.input_closed = False

    # --- со стороны теста ---
    def feed(self, *messages: dict[str, Any]) -> None:
        for message in messages:
            self._out.put(encode_message(message) + "\n")

    def feed_raw(self, line: str) -> None:
        self._out.put(line + "\n")

    def exit(self, code: int = 1, stderr: str | None = None) -> None:
        with self._lock:
            if self._code is not None:
                return
            self._code = code
        if stderr:
            self._err.put(stderr + "\n")
        self._err.put(None)
        self._out.put(None)

    def sent(self, cmd: str) -> list[dict[str, Any]]:
        return [c for c in self.commands if c["cmd"] == cmd]

    # --- DiscoveryProcess ---
    def write(self, line: str) -> None:
        with self._lock:
            if self.input_closed or self._code is not None:
                raise OSError("процесс закрыт")
        command = json.loads(line)
        self.commands.append(command)
        if command["cmd"] == "quit":
            self.exit(0)
            return
        if self._responder is not None:
            self.feed(*self._responder(command))

    def close_input(self) -> None:
        self.input_closed = True
        self.exit(0)

    def stdout_lines(self) -> Iterator[str]:
        while (line := self._out.get()) is not None:
            yield line

    def stderr_lines(self) -> Iterator[str]:
        while (line := self._err.get()) is not None:
            yield line

    def returncode(self) -> int | None:
        return self._code

    def wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self._code is None and time.monotonic() < deadline:
            time.sleep(0.005)
        return self._code is not None

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)


class Spawner:
    """Фабрика клиентов для `SensorSession`: хранит все созданные процессы."""

    def __init__(self, responder: Responder | None = None) -> None:
        self.responder = responder
        self.processes: list[FakeProcess] = []

    def __call__(self, listener: DiscoveryListener) -> DiscoveryClient:
        process = FakeProcess(self.responder)
        self.processes.append(process)
        return DiscoveryClient(process, listener)

    @property
    def last(self) -> FakeProcess:
        return self.processes[-1]


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition(), "условие не выполнилось вовремя"


class Clock:
    """Виртуальные часы для автоматической остановки и возраста «нет в эфире»."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
