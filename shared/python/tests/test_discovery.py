import json
from pathlib import Path

import pytest

from neurotlon_contracts import discovery
from neurotlon_contracts.contract import SHARED_ENV, SchemaUnavailableError


def test_encode_then_decode_roundtrip() -> None:
    message = {"type": "error", "message": "Bluetooth выключен"}
    line = discovery.encode_message(message)
    assert line.startswith(discovery.DISCOVERY_MARK)
    assert "\n" not in line
    assert "Bluetooth выключен" in line  # не \u-экранирование
    assert discovery.decode_bridge_line(line + "\n") == message


@pytest.mark.parametrize(
    "line",
    [
        "",
        "NeuroSDK: scanner started",
        discovery.DISCOVERY_MARK + "{плохо",
        discovery.DISCOVERY_MARK + json.dumps({"type": "unknown"}),
        discovery.DISCOVERY_MARK + json.dumps({"type": "hello", "v": 9}),
        discovery.DISCOVERY_MARK + json.dumps([1, 2]),
        json.dumps({"type": "hello", "v": 1}),  # без метки
    ],
)
def test_decode_bridge_line_drops_garbage(line: str) -> None:
    assert discovery.decode_bridge_line(line) is None


def test_mark_may_follow_sdk_text_on_the_same_line() -> None:
    line = "sdk: device found " + discovery.encode_message({"type": "hello", "v": 1})
    assert discovery.decode_bridge_line(line) == {"type": "hello", "v": 1}


def test_decode_command_checks_schema() -> None:
    assert discovery.decode_command('{"cmd":"scan","on":true}\n') == {"cmd": "scan", "on": True}
    assert discovery.decode_command('{"cmd":"scan","on":"да"}') is None
    assert discovery.decode_command("не json") is None
    assert discovery.decode_command('{"cmd":"rm"}') is None
    assert discovery.decode_command("[]") is None


def test_missing_schema_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SHARED_ENV, str(tmp_path))
    discovery._defs.cache_clear()
    discovery.discovery_validator.cache_clear()
    try:
        with pytest.raises(SchemaUnavailableError):
            discovery.decode_command('{"cmd":"quit"}')
    finally:
        monkeypatch.undo()
        discovery._defs.cache_clear()
        discovery.discovery_validator.cache_clear()


def test_nan_and_infinity_are_rejected() -> None:
    for constant in ("NaN", "Infinity", "-Infinity"):
        line = discovery.DISCOVERY_MARK + (
            '{"type":"link","id":"A","state":"connected","serial":"","battery":null,'
            f'"contact":null,"signal":false,"level":{constant}}}'
        )
        assert discovery.decode_bridge_line(line) is None
    assert discovery.decode_command('{"cmd":"scan","on":NaN}') is None


def test_very_deep_json_does_not_raise() -> None:
    deep = "[" * 5000 + "]" * 5000
    assert discovery.decode_bridge_line(discovery.DISCOVERY_MARK + deep) is None
    assert discovery.decode_command(deep) is None


def _item(address: str, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": address,
        "kind": "callibri",
        "name": "Callibri",
        "serial": "",
        "address": address,
        "rssi": None,
        "age_ms": 0,
    }
    return {**base, **fields}


def test_one_bad_item_drops_only_that_item() -> None:
    items = [
        _item("A1"),
        _item("A2", name="x" * 129),
        _item("A3", kind="kolibri"),
        _item("A4", rssi=5),
        _item("A5", extra="лишнее"),
        "не пункт",
        _item("A6", age_ms=-1),
        _item("A7"),
    ]
    line = discovery.encode_message({"type": "devices", "scanning": True, "items": items})
    message = discovery.decode_bridge_line(line)
    assert message is not None
    assert [i["id"] for i in message["items"]] == ["A1", "A7"]


def test_a_bad_envelope_still_drops_the_whole_message() -> None:
    line = discovery.encode_message({"type": "devices", "scanning": "yes", "items": [_item("A1")]})
    assert discovery.decode_bridge_line(line) is None
    line = discovery.encode_message({"type": "devices", "scanning": True, "items": "no"})
    assert discovery.decode_bridge_line(line) is None
