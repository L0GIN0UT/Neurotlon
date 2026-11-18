import json
from pathlib import Path

import pytest

from neurotlon_launcher.codes import normalize_code

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "participant-code.cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(("raw", "expected"), CASES["valid"].items())
def test_valid_cases(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", CASES["invalid"])
def test_invalid_cases(raw: str) -> None:
    assert normalize_code(raw) is None
