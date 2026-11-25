"""Сообщения поиска датчиков «мост <-> лаунчер» из `shared/sensor-discovery.md`.

Единственное место, где проверяются строки обмена: мост и лаунчер импортируют эти функции.
Нарушение возвращается текстом (по-русски), `None` — всё в порядке.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from .contract import SchemaUnavailableError, shared_dir

DISCOVERY_MARK = "NEUROTLON_DISCOVERY="  # SDK пишет свой мусор в тот же stdout
DISCOVERY_VERSION = 1
SCHEMA_FILE = "sensor-discovery.schema.json"
SCHEMA_MISSING = f"не найдена схема поиска датчиков (shared/{SCHEMA_FILE})"
MESSAGES = "BridgeMessage"  # мост -> лаунчер
COMMANDS = "LauncherCommand"  # лаунчер -> мост
ITEM = "Item"  # пункт списка `devices`


@cache
def _defs() -> dict[str, Any]:
    try:
        text = (shared_dir() / SCHEMA_FILE).read_text(encoding="utf-8")
        defs: dict[str, Any] = json.loads(text)["$defs"]
    except (OSError, KeyError, ValueError) as exc:
        raise SchemaUnavailableError(SCHEMA_MISSING) from exc
    return defs


@cache
def discovery_validator(name: str) -> Draft202012Validator:
    """Валидатор определения (`BridgeMessage`, `LauncherCommand`, ...)."""
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": _defs()})


def discovery_problem(name: str, data: object) -> str | None:
    try:
        discovery_validator(name).validate(data)
    except ValidationError as exc:
        return exc.message
    return None


def encode_message(message: dict[str, Any]) -> str:
    """Строка вывода моста: метка и JSON."""
    return DISCOVERY_MARK + json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def decode_bridge_line(line: str) -> dict[str, Any] | None:
    """Сообщение моста из строки вывода; `None` — мусор SDK, не JSON или не по схеме."""
    # метка может оказаться не в начале строки: нативный поток SDK мог дописать своё до неё
    start = line.find(DISCOVERY_MARK)
    if start < 0:
        return None
    return _decode(line[start + len(DISCOVERY_MARK) :].strip(), MESSAGES)


def decode_command(line: str) -> dict[str, Any] | None:
    """Команда лаунчера из строки stdin моста; `None` — не JSON или не по схеме."""
    return _decode(line.strip(), COMMANDS)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"недопустимое число: {name}")  # NaN, Infinity, -Infinity


def _decode(text: str, name: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    if name == MESSAGES:
        data = _drop_bad_items(data)
    if discovery_problem(name, data) is not None:
        return None
    checked: dict[str, Any] = data
    return checked


def _drop_bad_items(data: dict[str, Any]) -> dict[str, Any]:
    """В `devices` один неверный пункт не губит всё сообщение: отбрасывается только он."""
    items = data.get("type") == "devices" and data.get("items")
    if not isinstance(items, list):
        return data
    good = [item for item in items if discovery_problem(ITEM, item) is None]
    return {**data, "items": good} if len(good) != len(items) else data
