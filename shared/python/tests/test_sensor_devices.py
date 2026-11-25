import tomllib
from typing import Any

import pytest

from neurotlon_contracts.sensor_devices import (
    DEVICE_ROLES,
    ROLE_KIND,
    DeviceRef,
    DevicesFormatError,
    clean_text,
    parse_devices,
    render_devices,
    toml_string,
)


def test_old_form_is_serial_only() -> None:
    assert parse_devices({"eeg": "BB-1", "emg": 123456, "scan_s": 5}) == {
        "eeg": DeviceRef(serial="BB-1"),
        "emg": DeviceRef(serial="123456"),
    }


def test_new_form_reads_all_keys() -> None:
    raw = {
        "emg_left": {"address": " AA:01 ", "serial": "CA-1", "name": "Callibri", "kind": "callibri"}
    }
    assert parse_devices(raw) == {"emg_left": DeviceRef("AA:01", "CA-1", "Callibri", "callibri")}


def test_forms_can_be_mixed_and_empty_entries_are_skipped() -> None:
    raw = {"eeg": "  ", "emg": {"address": "A1"}, "emg_right": {"serial": ""}, "emg_left": "CA"}
    assert parse_devices(raw) == {
        "emg": DeviceRef(address="A1"),
        "emg_left": DeviceRef(serial="CA"),
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"emg_middle": "x"},
        {"eeg": True},
        {"eeg": ["x"]},
        {"eeg": {"address": 5}},
        {"eeg": {"address": "x" * 200}},
        {"eeg": {"address": "A1", "colour": "red"}},
        {"eeg": {"address": "A1", "kind": "callibri"}},
        {"emg": {"address": "A1", "kind": "brainbit"}},
    ],
)
def test_bad_records_are_rejected_in_russian(raw: dict[str, Any]) -> None:
    with pytest.raises(DevicesFormatError, match="devices"):
        parse_devices(raw)


def test_same_device_by_address_or_serial_ignoring_case() -> None:
    assert DeviceRef(address="aa:01").same_device(DeviceRef(address="AA:01", serial="X"))
    assert DeviceRef(serial="ca-1").same_device(DeviceRef(address="B", serial="CA-1"))
    assert not DeviceRef(address="A").same_device(DeviceRef(address="B"))
    assert not DeviceRef().same_device(DeviceRef())  # пустые не совпадают


def test_render_is_readable_back_and_writes_only_the_new_form() -> None:
    devices = {
        "emg_right": DeviceRef("A2", "CA-2", "Callibri", "callibri"),
        "eeg": DeviceRef(address="B1", name='BrainBit "демо"'),
        "emg": DeviceRef(serial="CA-3"),  # старая запись: вид берётся по роли
        "emg_left": DeviceRef(),  # пустая роль не пишется
    }
    text = render_devices(devices)
    assert "[devices.eeg]" in text
    assert "[devices.emg_left]" not in text
    assert text.index("[devices.eeg]") < text.index("[devices.emg]")
    assert text.index("[devices.emg]") < text.index("[devices.emg_right]")
    data = tomllib.loads(text)
    assert parse_devices(data["devices"]) == {
        "eeg": DeviceRef(address="B1", name='BrainBit "демо"', kind="brainbit"),
        "emg": DeviceRef(serial="CA-3", kind="callibri"),
        "emg_right": DeviceRef("A2", "CA-2", "Callibri", "callibri"),
    }


def test_render_nothing() -> None:
    assert render_devices({}) == ""


def test_every_role_has_a_kind() -> None:
    assert set(ROLE_KIND) == set(DEVICE_ROLES)
    assert set(ROLE_KIND.values()) == {"brainbit", "callibri"}


NASTY = [
    "",
    "обычное имя",
    'кавычки " и \\ слеши',
    "DEL\x7f внутри",
    "\x00\x01\x1f управляющие",
    "табы\tи\nпереводы\r\nстрок",
    '"\n[evil]\nkey = "x',
    '[devices.emg]\naddress = "подмена"',
    "эмодзи \U0001f9e0 вне BMP \U00010348",
    "bidi \u202e развёрнуто \u2066",
    "\u2028 \u2029 разделители",
    "'одинарные' и ''' тройные",
    "#решётка = 1",
    "x" * 128,
]


@pytest.mark.parametrize("text", NASTY)
@pytest.mark.parametrize("field", ["address", "serial", "name"])
def test_render_then_toml_then_parse_gives_the_same_strings(text: str, field: str) -> None:
    fields = {"address": "A1", "serial": "S1", "name": "N", field: text}
    ref = DeviceRef(kind="callibri", **fields)
    if not (ref.address or ref.serial):
        return  # пустая запись не пишется
    data = tomllib.loads(render_devices({"emg": ref}))
    assert list(data) == ["devices"] and list(data["devices"]) == ["emg"]  # ничего не вылезло
    back = parse_devices(data["devices"])["emg"]
    assert (back.address, back.serial, back.name) == (
        ref.address.strip(),
        ref.serial.strip(),
        ref.name.strip(),
    )


@pytest.mark.parametrize("text", ["\ud800", "до \udc00 после", "\udfff"])
def test_lone_surrogates_are_refused(text: str) -> None:
    with pytest.raises(DevicesFormatError):
        toml_string(text)
    with pytest.raises(DevicesFormatError):
        render_devices({"emg": DeviceRef(address="A1", name=text)})


def test_control_characters_are_escaped_not_written_raw() -> None:
    out = toml_string("a\x7fb\x00c\nd")
    assert out == '"a\\u007Fb\\u0000c\\nd"'
    assert all(ord(ch) >= 0x20 and ord(ch) != 0x7F for ch in out)


def test_clean_text_removes_cc_cs_cf_and_truncates() -> None:
    assert clean_text("Call\x7fibri\u202e\x00 \u200b", 128) == "Callibri"
    assert clean_text("\ud800ab", 128) == "ab"
    assert clean_text("x" * 500, 128) == "x" * 128
    assert clean_text("  имя  ", 128) == "имя"
    assert clean_text("\U0001f9e0 ok", 128) == "\U0001f9e0 ok"
