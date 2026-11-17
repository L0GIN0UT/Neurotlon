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
