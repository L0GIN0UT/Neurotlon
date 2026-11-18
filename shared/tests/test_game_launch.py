import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

SHARED = Path(__file__).parent.parent
SCHEMA = json.loads((SHARED / "game-launch.schema.json").read_text(encoding="utf-8"))
OPENAPI = yaml.safe_load((SHARED / "openapi.yaml").read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


def doc_examples() -> list[dict[str, Any]]:
    text = (SHARED / "game-launch.md").read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]


def test_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_doc_examples_match_schema() -> None:
    launch, result = doc_examples()
    validator("Launch").validate(launch)
    validator("Result").validate(result)


def test_result_entries_follow_station_api() -> None:
    entry_schema = {
        "$ref": "#/components/schemas/ResultEntry",
        "components": OPENAPI["components"],
    }
    for entry in doc_examples()[1]["entries"]:
        Draft202012Validator(entry_schema).validate(entry)


def test_participant_code_pattern_matches_api() -> None:
    api_pattern = OPENAPI["components"]["schemas"]["ParticipantCode"]["pattern"]
    assert SCHEMA["$defs"]["ParticipantCode"]["pattern"] == api_pattern


@pytest.mark.parametrize(
    "result",
    [
        {
            "protocol": 1,
            "session_id": "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5",
            "status": "finished",
            "entries": [],
        },
        {
            "protocol": 1,
            "session_id": "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5",
            "status": "aborted",
            "entries": [],
        },
        {
            "protocol": 1,
            "session_id": "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5",
            "status": "aborted",
            "reason": "sensor lost",
            "entries": [{"participant_code": "NT01", "outcome": "completed", "points": 1}],
        },
        {
            "protocol": 2,
            "session_id": "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5",
            "status": "aborted",
            "reason": "x",
            "entries": [],
        },
    ],
)
def test_invalid_results_rejected(result: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validator("Result").validate(result)


def test_aborted_result_accepted() -> None:
    validator("Result").validate(
        {
            "protocol": 1,
            "session_id": "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5",
            "status": "aborted",
            "reason": "оператор прервал игру",
            "entries": [],
        }
    )
