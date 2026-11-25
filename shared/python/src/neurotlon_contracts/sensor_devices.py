"""Назначение датчиков ролям в `bridge.toml` (`[devices]`): общий код моста и лаунчера.

Два вида записи, вид определяется типом значения:
- старый: `eeg = "BB-123456"` — только серийный номер;
- новый: `[devices.emg_left]` с `address` (главный ключ), `serial` (запасной), `name`, `kind`.

Читают оба вида, пишут только новый. Нарушение формата — `DevicesFormatError` (по-русски).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEVICE_ROLES = ("eeg", "emg", "emg_left", "emg_right")
ROLE_KIND = {"eeg": "brainbit", "emg": "callibri", "emg_left": "callibri", "emg_right": "callibri"}
SENSOR_KINDS = ("brainbit", "callibri")
NON_ROLE_KEYS = frozenset({"scan_s"})  # лежит в той же таблице, но не датчик
_FIELDS = ("address", "serial", "name", "kind")
_MAX_FIELD = 128
MAX_NAME = 128  # имя и серийный номер из эфира
MAX_ADDRESS = 64
_BAD_CATEGORIES = frozenset({"Cc", "Cs", "Cf"})  # управляющие, суррогаты, форматирующие (bidi)


def clean_text(value: str, limit: int) -> str:
    """Текст из эфира без управляющих, суррогатных и форматирующих знаков, не длиннее `limit`."""
    kept = "".join(ch for ch in value if unicodedata.category(ch) not in _BAD_CATEGORIES)
    return kept.strip()[:limit]


def toml_string(value: str) -> str:
    """Базовая строка TOML; суррогаты отклоняются (`DevicesFormatError`)."""
    out: list[str] = ['"']
    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise DevicesFormatError("в тексте недопустимый знак (одиночный суррогат)")
        if ch in '\\"':
            out.append("\\" + ch)
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


class DevicesFormatError(ValueError):
    """Неверная запись `[devices]`; сообщение по-русски."""


@dataclass(frozen=True)
class DeviceRef:
    """Датчик роли: адрес (главный ключ) и серийный номер (запасной); хотя бы один из них."""

    address: str = ""
    serial: str = ""
    name: str = ""
    kind: str = ""  # brainbit | callibri; пусто — по роли

    def same_device(self, other: DeviceRef) -> bool:
        """Один и тот же датчик: совпал адрес или серийный номер (без учёта регистра)."""
        if self.address and other.address and self.address.lower() == other.address.lower():
            return True
        return bool(self.serial and other.serial and self.serial.lower() == other.serial.lower())


def parse_devices(raw: Mapping[str, Any]) -> dict[str, DeviceRef]:
    """Роль -> датчик из таблицы `[devices]`; пустые записи пропускаются."""
    result: dict[str, DeviceRef] = {}
    for key, value in raw.items():
        if key in NON_ROLE_KEYS:
            continue
        if key not in DEVICE_ROLES:
            raise DevicesFormatError(f"[devices] неизвестный ключ: {key}")
        ref = _parse_entry(key, value)
        if ref is not None:
            result[key] = ref
    return result


def _parse_entry(role: str, value: Any) -> DeviceRef | None:
    if isinstance(value, bool):
        raise DevicesFormatError(f"[devices] {role}: нужна строка с серийным номером")
    if isinstance(value, str | int):
        serial = str(value).strip()
        return DeviceRef(serial=serial) if serial else None
    if not isinstance(value, Mapping):
        raise DevicesFormatError(f"[devices] {role}: нужна строка или таблица [devices.{role}]")
    unknown = set(value) - set(_FIELDS)
    if unknown:
        raise DevicesFormatError(
            f"[devices.{role}] неизвестные ключи: {', '.join(sorted(unknown))}"
        )
    fields: dict[str, str] = {}
    for name in _FIELDS:
        item = value.get(name, "")
        if not isinstance(item, str) or len(item) > _MAX_FIELD:
            raise DevicesFormatError(
                f"[devices.{role}] {name}: нужна строка до {_MAX_FIELD} знаков"
            )
        fields[name] = item.strip()
    if fields["kind"] and fields["kind"] != ROLE_KIND[role]:
        raise DevicesFormatError(
            f"[devices.{role}] kind: для этой роли нужен {ROLE_KIND[role]}, а не {fields['kind']}"
        )
    if not fields["address"] and not fields["serial"]:
        return None
    return DeviceRef(**fields)


def render_devices(devices: Mapping[str, DeviceRef]) -> str:
    """Таблицы `[devices.<роль>]` в новом виде; роли в порядке `DEVICE_ROLES`."""
    blocks: list[str] = []
    for role in DEVICE_ROLES:
        ref = devices.get(role)
        if ref is None or not (ref.address or ref.serial):
            continue
        lines = [f"[devices.{role}]"]
        for name in _FIELDS:
            value = getattr(ref, name) or (ROLE_KIND[role] if name == "kind" else "")
            if value:
                lines.append(f"{name} = {toml_string(value)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
