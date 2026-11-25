"""Сигналы датчиков для игры: тонкая обёртка над клиентом моста."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

from neurotlon_bridge.client import BridgeClient
from neurotlon_bridge.source import Feature, Reading, SensorState

from .launch import LaunchInfo

# значение использовать нельзя и датчик «потерян» (а не просто артефакт или плохой контакт)
_LOST_REASONS = frozenset({"disconnected", "stale"})


class Bridge(Protocol):
    """То, что нужно от клиента моста; `BridgeClient` подходит, в тестах — подделка."""

    @property
    def connected(self) -> bool: ...

    def latest(self, signal: str) -> Reading | None: ...

    def sensor_state(self, signal: str) -> SensorState | None: ...

    @property
    def features(self) -> tuple[Feature, ...]: ...

    def calibrated(self, signal: str) -> bool: ...

    def close(self) -> None: ...


class Signals:
    def __init__(self, bridge: Bridge, names: Sequence[str]) -> None:
        self._bridge = bridge
        self._names = tuple(names)

    @classmethod
    def connect(cls, launch: LaunchInfo) -> Signals:
        """Подключиться к мосту из `launch.json`; переподключение клиент делает сам."""
        return cls(BridgeClient(launch.bridge_host, launch.bridge_port), launch.signals)

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    @property
    def connected(self) -> bool:
        return self._bridge.connected

    def value(self, signal: str) -> float | None:
        """Значение 0…1 или `None`: артефакт, нет контакта, данные старше 500 мс, нет связи."""
        reading = self._bridge.latest(signal)
        if reading is None or not reading.valid:
            return None
        return reading.value

    def reading(self, signal: str) -> Reading | None:
        return self._bridge.latest(signal)

    def sensor_state(self, signal: str) -> SensorState | None:
        return self._bridge.sensor_state(signal)

    def supports(self, feature: Feature) -> bool:
        """Объявил ли мост функцию в `hello.features`; у старого моста всегда `False`."""
        return feature in self._bridge.features

    def calibrated(self, signal: str) -> bool:
        """Шкала сигнала готова по `hello.calibrated`; у старого моста всегда `False`.

        Эмулируемый сигнал здесь не числится: его состояние датчика `emulated`.
        """
        return self._bridge.calibrated(signal)

    def uncalibrated(self) -> list[str]:
        """Сигналы игры без калибровки; пусто, если калибровка не требуется.

        Требуется, только если мост объявил `calibration_state`: у старого моста проверить
        нечего. Сигнал в порядке, если он в `hello.calibrated` или его датчик `emulated`.
        """
        if not self.supports("calibration_state"):
            return []
        return [
            n
            for n in self._names
            if not self._bridge.calibrated(n) and self._bridge.sensor_state(n) != "emulated"
        ]

    def calibration_lost(self) -> list[str]:
        """Сигналы, которые мост сейчас помечает `not_calibrated` (калибровку стёрли)."""
        lost: list[str] = []
        for name in self._names:
            reading = self._bridge.latest(name)
            if reading is not None and reading.reason == "not_calibrated":
                lost.append(name)
        return lost

    def lost_signals(self) -> list[str]:
        """Сигналы, которых нет: мост не отвечает, датчик отключён или данные устарели."""
        if not self._bridge.connected:
            return list(self._names)
        lost: list[str] = []
        for name in self._names:
            reading = self._bridge.latest(name)
            if self._bridge.sensor_state(name) == "disconnected" or (
                reading is not None and reading.reason in _LOST_REASONS
            ):
                lost.append(name)
        return lost

    def wait_connected(
        self,
        timeout_s: float = 10.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> bool:
        """Ждать связи с мостом и состояния всех нужных датчиков (сообщение `hello`)."""
        deadline = clock() + timeout_s
        while True:
            if self._bridge.connected and all(
                self._bridge.sensor_state(n) is not None for n in self._names
            ):
                return True
            if clock() >= deadline:
                return False
            sleep(0.02)

    def close(self) -> None:
        self._bridge.close()
