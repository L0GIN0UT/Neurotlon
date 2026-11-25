import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

SHARED = Path(__file__).parent.parent
SCHEMA = json.loads((SHARED / "sensor-discovery.schema.json").read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


MESSAGES = validator("BridgeMessage")
COMMANDS = validator("LauncherCommand")


def doc_lines(prefix: str) -> list[dict[str, Any]]:
    lines = (SHARED / "sensor-discovery.md").read_text(encoding="utf-8").splitlines()
    return [json.loads(line[2:]) for line in lines if line.startswith(prefix)]


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_doc_has_examples_both_ways() -> None:
    assert len(doc_lines("← ")) >= 6
    assert len(doc_lines("→ ")) >= 4


@pytest.mark.parametrize("message", doc_lines("← "))
def test_doc_bridge_messages_match_schema(message: dict[str, Any]) -> None:
    MESSAGES.validate(message)
    assert not COMMANDS.is_valid(message)


@pytest.mark.parametrize("command", doc_lines("→ "))
def test_doc_commands_match_schema(command: dict[str, Any]) -> None:
    COMMANDS.validate(command)
    assert not MESSAGES.is_valid(command)


def link(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "link",
        "id": "A1",
        "state": "connected",
        "serial": "",
        "battery": None,
        "contact": None,
        "signal": False,
        "level": None,
    }
    return {**base, **fields}


ITEM: dict[str, object] = {
    "id": "A1",
    "kind": "callibri",
    "name": "Callibri",
    "serial": "",
    "address": "A1",
    "rssi": None,
    "age_ms": 0,
}


@pytest.mark.parametrize(
    "message",
    [
        {"type": "hello", "v": 1},
        {"type": "devices", "scanning": False, "items": []},
        {"type": "devices", "scanning": True, "items": [ITEM]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "rssi": -60}]},
        link(level=0),
        link(level=1, battery=100, contact=False),
        link(state="failed", error="Не удалось"),
        {"type": "error", "message": "Bluetooth выключен"},
    ],
)
def test_valid_bridge_messages(message: dict[str, Any]) -> None:
    MESSAGES.validate(message)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "hello", "v": 2},
        {"type": "hello"},
        {"type": "unknown"},
        {"type": "devices", "scanning": "yes", "items": []},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "kind": "kolibri"}]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "rssi": 10}]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "age_ms": -1}]},
        {
            "type": "devices",
            "scanning": True,
            "items": [{k: v for k, v in ITEM.items() if k != "id"}],
        },
        link(level=1.5),
        {**link(), "extra": "лишнее"},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "extra": 1}]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "age_ms": 3600001}]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "name": "x" * 129}]},
        {"type": "devices", "scanning": True, "items": [{**ITEM, "id": "x" * 65}]},
        link(level=-0.1),
        link(battery=101),
        link(state="ready"),
        link(signal="yes"),
        {"type": "error", "message": ""},
        {"type": "error"},
        [],
    ],
)
def test_invalid_bridge_messages(message: object) -> None:
    assert not MESSAGES.is_valid(message)


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "scan", "on": True},
        {"cmd": "scan", "on": False},
        {"cmd": "connect", "id": "A1", "kind": "brainbit"},
        {"cmd": "release", "id": "A1"},
        {"cmd": "quit"},
    ],
)
def test_valid_commands(command: dict[str, Any]) -> None:
    COMMANDS.validate(command)


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "scan"},
        {"cmd": "scan", "on": 1},
        {"cmd": "connect", "id": "A1"},
        {"cmd": "connect", "id": "", "kind": "callibri"},
        {"cmd": "connect", "id": "x" * 65, "kind": "callibri"},
        {"cmd": "connect", "id": "A1", "kind": "kolibri"},
        {"cmd": "release"},
        {"cmd": "quit", "force": True},
        {"cmd": "scan", "on": True, "extra": 1},
        {"cmd": "release", "id": "A1", "extra": 1},
        {"cmd": "format_disk"},
        {"type": "quit"},
    ],
)
def test_invalid_commands(command: dict[str, Any]) -> None:
    assert not COMMANDS.is_valid(command)
