"""Поиск датчиков для `neurotlon-bridge --scan`."""

from __future__ import annotations

from .base import DeviceBackend, DeviceInfo

UNKNOWN_SERIAL = "(неизвестен до подключения)"
KIND_TITLES = {"brainbit": "BrainBit", "callibri": "Callibri"}


def scan_devices(backend: DeviceBackend, seconds: float) -> list[DeviceInfo]:
    """Найденные устройства без повторов, по виду, имени и адресу."""
    unique = {(d.kind, d.address): d for d in backend.scan(seconds)}
    return sorted(unique.values(), key=lambda d: (d.kind, d.name, d.address))


def format_devices(devices: list[DeviceInfo]) -> str:
    if not devices:
        return "Датчики не найдены. Проверьте питание, Bluetooth-адаптер и расстояние."
    lines = [f"{'вид':<10}{'имя':<20}{'серийный номер':<32}адрес"]
    for d in devices:
        serial = d.serial or UNKNOWN_SERIAL
        lines.append(f"{KIND_TITLES[d.kind]:<10}{d.name:<20}{serial:<32}{d.address}")
    return "\n".join(lines)
