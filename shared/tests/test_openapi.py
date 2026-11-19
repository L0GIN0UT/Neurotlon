from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError
from openapi_spec_validator import validate

SPEC_PATH = Path(__file__).parent.parent / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return data


def schema_validator(spec: dict[str, Any], name: str) -> Draft202012Validator:
    schema = {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
    return Draft202012Validator(schema)


def test_spec_is_valid_openapi(spec: dict[str, Any]) -> None:
    validate(spec)


def test_result_examples_match_schema(spec: dict[str, Any]) -> None:
    validator = schema_validator(spec, "ResultSubmission")
    examples = spec["paths"]["/results"]["post"]["requestBody"]["content"]["application/json"][
        "examples"
    ]
    for example in examples.values():
        validator.validate(example["value"])


@pytest.mark.parametrize(
    "entry",
    [
        {"participant_code": "NT01", "outcome": "completed"},
        {"participant_code": "NT01", "outcome": "completed", "points": 5, "reason": "health"},
        {"participant_code": "NT01", "outcome": "not_completed"},
        {"participant_code": "NT01", "outcome": "not_completed", "reason": "health", "points": 1},
        {"participant_code": "nt01", "outcome": "completed", "points": 5},
        {"participant_code": "NT01", "outcome": "completed", "points": -1},
        {"participant_code": "NT01", "outcome": "completed", "points": 4.5},
        {"participant_code": "NT01", "outcome": "completed", "points": 5, "category": "x"},
    ],
)
def test_invalid_entries_rejected(spec: dict[str, Any], entry: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        schema_validator(spec, "ResultEntry").validate(entry)


def test_category_is_never_exposed(spec: dict[str, Any]) -> None:
    assert "category" not in SPEC_PATH.read_text(encoding="utf-8")


def test_schema_examples_match_schema(spec: dict[str, Any]) -> None:
    for name, schema in spec["components"]["schemas"].items():
        for example in schema.get("examples", []):
            schema_validator(spec, name).validate(example)
