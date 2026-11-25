"""Интерфейсы доступа к датчикам. SDK за ними: в тестах вместо него подделки."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

DeviceKind = Literal["brainbit", "callibri"]


class DeviceError(Exception):
    """Датчики недоступны: сообщение предназначено оператору (по-русски)."""


class SdkUnavailableError(DeviceError):
    """Не загрузился NeuroSDK или его нативные библиотеки."""


class BluetoothUnavailableError(DeviceError):
    """Нет Bluetooth-адаптера или он выключен."""


class DeviceNotFoundError(DeviceError):
    """Датчик с нужным серийным номером не найден поиском."""


@dataclass(frozen=True)
class DeviceInfo:
    kind: DeviceKind
    name: str
    serial: str  # может быть пустым: SDK иногда отдаёт номер только после подключения
    address: str
    rssi: int | None = None  # дБм; None — неизвестен


@dataclass(frozen=True)
class SensorHandlers:
    """Обратные вызовы SDK. Только буферизуют данные и никогда не бросают исключений."""

    on_samples: Callable[[Sequence[Sequence[float]]], None]
    """Строки отсчётов в вольтах: BrainBit (O1, O2, T3, T4), Callibri (значение,)."""
    on_state: Callable[[bool], None]
    """Датчик на связи (True) или вне зоны (False)."""
    on_battery: Callable[[int], None]
    on_electrode: Callable[[bool], None]
    """Контакт электродов Callibri: True — норма."""


class RawSensor(Protocol):
    """Подключённый и настроенный датчик."""

    @property
    def sampling_hz(self) -> int: ...

    def start_signal(self) -> None: ...

    def stop_signal(self) -> None: ...

    def battery(self) -> int | None: ...

    def serial_number(self) -> str:
        """Серийный номер, который SDK отдаёт после подключения (пустой, если не знает)."""

    def close(self) -> None:
        """Освободить датчик и нативные ресурсы SDK."""


class DeviceBackend(Protocol):
    def check(self) -> None:
        """Проверить, что SDK загружен и Bluetooth-адаптер есть; иначе `DeviceError`."""

    def scan(self, seconds: float) -> list[DeviceInfo]: ...

    def open_sensor(
        self, serial: str, kind: DeviceKind, handlers: SensorHandlers, address: str = ""
    ) -> RawSensor:
        """Найти датчик, подключить и настроить (блокирует на секунды).

        Сначала ищется адрес (если задан), затем серийный номер: адрес может смениться.
        """

    def close(self) -> None: ...


class ScannerPort(Protocol):
    """Фоновый поиск датчиков: список опрашивают, пока поиск включён."""

    def start(self) -> None:
        """Включить поиск; нет Bluetooth — `DeviceError`."""

    def stop(self) -> None: ...

    def sensors(self) -> list[DeviceInfo]:
        """Устройства, которые видны сейчас."""

    def connect(self, address: str, kind: DeviceKind, handlers: SensorHandlers) -> RawSensor:
        """Подключить и настроить найденное устройство; нет такого — `DeviceNotFoundError`."""

    def close(self) -> None:
        """Освободить сканер и нативные ресурсы."""
