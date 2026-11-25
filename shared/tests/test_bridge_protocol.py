import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

SHARED = Path(__file__).parent.parent
SCHEMA = json.loads((SHARED / "bridge-protocol.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def doc_examples() -> list[dict[str, Any]]:
    lines = (SHARED / "bridge-protocol.md").read_text(encoding="utf-8").splitlines()
    return [json.loads(line[2:]) for line in lines if line.startswith(("← ", "→ "))]


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_doc_has_examples() -> None:
    assert len(doc_examples()) >= 5


@pytest.mark.parametrize("message", doc_examples())
def test_doc_examples_match_schema(message: dict[str, Any]) -> None:
    VALIDATOR.validate(message)


EEG_HELLO = {"name": "eeg", "state": "connected"}
EMG_HELLO = {"name": "emg", "state": "emulated"}
TENSE = {"phase": "tense", "s": 5}
RELAX = {"phase": "relax", "s": 5}


@pytest.mark.parametrize(
    "message",
    [
        # старые сообщения остаются валидными
        {"type": "hello", "protocol": 1, "signals": [EEG_HELLO]},
        {"type": "calibrate", "signal": "emg", "step": "rest"},
        {"type": "calibrate", "signal": "emg", "step": "contract"},
        {"type": "calibrate", "signal": "eeg", "step": "baseline"},
        # новое
        {"type": "hello", "protocol": 1, "signals": [EMG_HELLO], "features": []},
        {
            "type": "hello",
            "protocol": 1,
            "signals": [EEG_HELLO, EMG_HELLO],
            "features": ["burst", "emg_cycle", "baseline_duration"],
            "eeg_method": "alpha",
        },
        {"type": "hello", "protocol": 1, "signals": [EEG_HELLO], "eeg_method": "emotions"},
        {"type": "calibrate", "signal": "emg", "step": "cycle"},
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [TENSE, RELAX]},
        {
            "type": "calibrate",
            "signal": "emg_left",
            "step": "cycle",
            "segments": [{"phase": "tense", "s": 2}, {"phase": "relax", "s": 2}] * 4,
        },
        {"type": "calibrate", "signal": "eeg", "step": "baseline", "duration_s": 5},
        {"type": "calibrate", "signal": "eeg", "step": "baseline", "duration_s": 30},
        {
            "type": "calibration",
            "signal": "emg",
            "step": "cycle",
            "status": "running",
            "progress": 0.5,
            "segment": 3,
            "phase": "tense",
            "phase_left_s": 2.5,
        },
        {"type": "burst", "signal": "emg", "t_ms": 10, "seq": 1},
        {"type": "burst", "signal": "emg_right", "t_ms": 10, "seq": 7, "rise": 1},
        {"type": "burst", "signal": "emg_left", "t_ms": 0, "seq": 0, "rise": 0},
    ],
)
def test_valid_messages_accepted(message: dict[str, Any]) -> None:
    VALIDATOR.validate(message)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "hello", "protocol": 1, "signals": [EEG_HELLO], "features": ["telepathy"]},
        {"type": "hello", "protocol": 1, "signals": [EEG_HELLO, EMG_HELLO], "eeg_method": "fft"},
        # eeg_method только если в профиле есть eeg
        {"type": "hello", "protocol": 1, "signals": [EMG_HELLO], "eeg_method": "alpha"},
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [TENSE]},
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [TENSE, RELAX] * 5},
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [TENSE, TENSE]},
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [RELAX, RELAX]},
        {
            "type": "calibrate",
            "signal": "emg",
            "step": "cycle",
            "segments": [{"phase": "tense", "s": 1.9}, RELAX],
        },
        {
            "type": "calibrate",
            "signal": "emg",
            "step": "cycle",
            "segments": [{"phase": "tense", "s": 15.1}, RELAX],
        },
        {
            "type": "calibrate",
            "signal": "emg",
            "step": "cycle",
            "segments": [{"phase": "hold", "s": 5}, RELAX],
        },
        {"type": "calibrate", "signal": "emg", "step": "cycle", "segments": [{"s": 5}, RELAX]},
        {"type": "calibrate", "signal": "eeg", "step": "baseline", "duration_s": 4.9},
        {"type": "calibrate", "signal": "eeg", "step": "baseline", "duration_s": 30.1},
        {
            "type": "calibration",
            "signal": "emg",
            "step": "cycle",
            "status": "running",
            "phase": "x",
        },
        {
            "type": "calibration",
            "signal": "emg",
            "step": "cycle",
            "status": "running",
            "segment": 0,
        },
        {"type": "burst", "signal": "emg", "t_ms": 10},
        {"type": "burst", "signal": "emg", "seq": 1},
        {"type": "burst", "signal": "emg", "t_ms": 10, "seq": 1, "rise": 1.01},
        {"type": "burst", "signal": "emg", "t_ms": 10, "seq": 1, "rise": -0.1},
        {"type": "burst", "signal": "eeg", "t_ms": 10, "seq": 1},
        {"type": "burst", "signal": "emg", "t_ms": 10, "seq": 1.5},
    ],
)
def test_new_fields_out_of_bounds_rejected(message: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VALIDATOR.validate(message)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "hello", "protocol": 2, "signals": [{"name": "eeg", "state": "connected"}]},
        {"type": "sample", "t_ms": 1, "signals": {"eeg": {"value": 1.2, "valid": True}}},
        {"type": "sample", "t_ms": 1, "signals": {"eeg": {"value": 0.5, "valid": False}}},
        {"type": "sample", "t_ms": 1, "signals": {"alpha": {"value": 0.5, "valid": True}}},
        {"type": "sample", "t_ms": 1, "signals": {}},
        {"type": "calibration", "signal": "emg", "step": "rest", "status": "failed"},
        {"type": "calibrate", "signal": "eeg", "step": "squeeze"},
        {"type": "unknown"},
    ],
)
def test_invalid_messages_rejected(message: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VALIDATOR.validate(message)
