"""Reference normalizer for shared/participant-code.md, checked against the shared cases."""

import json
import re
from pathlib import Path

import pytest
import yaml

SHARED = Path(__file__).parent.parent
CASES = json.loads((SHARED / "participant-code.cases.json").read_text(encoding="utf-8"))
CODE_RE = re.compile(r"^NT(0[1-9]|[1-9][0-9])$")
INPUT_RE = re.compile(r"^(?:NT)?([0-9]{1,2})$")
CYRILLIC_PREFIX = str.maketrans({"Н": "N", "Т": "T"})  # noqa: RUF001 (Cyrillic on purpose)


def normalize(raw: str) -> str | None:
    text = re.sub(r"[\s\-_]", "", raw).upper().translate(CYRILLIC_PREFIX)
    match = INPUT_RE.match(text)
    if not match:
        return None
    code = f"NT{int(match.group(1)):02d}"
    return code if CODE_RE.match(code) else None


@pytest.mark.parametrize(("raw", "expected"), CASES["valid"].items())
def test_valid(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", CASES["invalid"])
def test_invalid(raw: str) -> None:
    assert normalize(raw) is None


def test_openapi_uses_same_pattern() -> None:
    spec = yaml.safe_load((SHARED / "openapi.yaml").read_text(encoding="utf-8"))
    assert spec["components"]["schemas"]["ParticipantCode"]["pattern"] == CODE_RE.pattern
