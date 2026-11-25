import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neurotlon_bridge import protocol
from neurotlon_bridge.source import Reading, Segment

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "bridge-protocol.schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

MESSAGES: list[protocol.Message] = [
    protocol.Hello((("eeg", "connected"), ("emg", "emulated"))),
    protocol.Sample(120450, {"eeg": Reading(0.41), "emg": Reading(0.7)}),
    protocol.Sample(1, {"eeg": Reading(0.0, False, "artifact")}),
    protocol.Sample(2, {"emg": Reading(1.7)}),  # обрезается до 1
    protocol.Sensor("emg", "disconnected"),
    protocol.Sensor("eeg", "connected", battery=80),
    protocol.Calibration("emg", "rest", "running", progress=0.4),
    protocol.Calibration("emg", "rest", "done"),
    protocol.Calibration("eeg", "baseline", "failed", reason="нет контакта"),
    protocol.Calibrate("emg", "contract"),
    protocol.Reset(),
    protocol.Hello((("eeg", "connected"), ("emg", "emulated")), features=()),
    protocol.Hello(
        (("eeg", "connected"), ("emg", "emulated")),
        features=("burst", "emg_cycle", "baseline_duration"),
        eeg_method="alpha",
    ),
    protocol.Calibration(
        "emg", "cycle", "running", 0.3, segment=2, phase="relax", phase_left_s=3.5
    ),
    protocol.Calibration("emg", "cycle", "failed", reason="слабое сжатие"),
    protocol.Burst("emg", 120490, 1),
    protocol.Burst("emg_left", 5, 12, rise=0.8),
    protocol.Calibrate("emg", "cycle"),
    protocol.Calibrate("emg", "cycle", segments=(Segment("tense", 4), Segment("relax", 2.5))),
    protocol.Calibrate("eeg", "baseline", duration_s=15),
]


@pytest.mark.parametrize("msg", MESSAGES)
def test_encoded_message_matches_schema(msg: protocol.Message) -> None:
    raw = protocol.encode(msg)
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1
    VALIDATOR.validate(json.loads(raw))


@pytest.mark.parametrize("msg", [m for m in MESSAGES if not isinstance(m, protocol.Sample)])
def test_roundtrip(msg: protocol.Message) -> None:
    assert protocol.decode(protocol.encode(msg)) == msg


def test_sample_roundtrip_clamps_value() -> None:
    decoded = protocol.decode(protocol.encode(protocol.Sample(2, {"emg": Reading(1.7)})))
    assert decoded == protocol.Sample(2, {"emg": Reading(1.0)})


def test_encode_is_compact_utf8() -> None:
    raw = protocol.encode(protocol.Calibration("eeg", "baseline", "failed", reason="ошибка"))
    assert b" " not in raw
    assert "ошибка".encode() in raw


def test_invalid_reading_without_reason_gets_one() -> None:
    raw = protocol.encode(protocol.Sample(0, {"eeg": Reading(0.2, False)}))
    VALIDATOR.validate(json.loads(raw))


def test_unknown_type_returns_none() -> None:
    assert protocol.decode('{"type":"future","x":1}') is None


def test_unknown_fields_ignored() -> None:
    msg = protocol.decode('{"type":"calibrate","signal":"emg","step":"rest","extra":[1]}')
    assert msg == protocol.Calibrate("emg", "rest")


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "[1,2]",
        '{"type":"calibrate","signal":"nope","step":"rest"}',
        '{"type":"calibrate","signal":"emg"}',
        '{"type":"sample","t_ms":"x","signals":{}}',
        '{"type":"sample","t_ms":1,"signals":{"emg":{"value":0.1,"valid":false}}}',
        b"\xff\xfe",
    ],
)
def test_malformed_raises_value_error(line: str | bytes) -> None:
    with pytest.raises(ValueError):
        protocol.decode(line)
