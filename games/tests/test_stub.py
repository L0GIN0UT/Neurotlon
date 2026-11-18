import json
import random
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from neurotlon_games import stub

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "game-launch.schema.json").read_text(
        encoding="utf-8"
    )
)
SESSION = "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5"


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": SCHEMA["$defs"]})


def _write_launch(tmp_path: Path, discipline: str, codes: list[str]) -> Path:
    participants: list[dict[str, Any]] = [
        {"code": c, "display_name": None, **({"side": s} if discipline == "pong" else {})}
        for c, s in zip(codes, ["left", "right"], strict=False)
    ]
    launch = {
        "protocol": 1,
        "session_id": SESSION,
        "discipline": discipline,
        "duration_s": 10,
        "participants": participants,
        "bridge": {"host": "127.0.0.1", "port": 8765},
        "result_path": str(tmp_path / "result.json"),
        "language": "ru",
    }
    _validator("Launch").validate(launch)
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(launch), encoding="utf-8")
    return path


def _read_result(tmp_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    _validator("Result").validate(result)
    return result


def test_darts_result_matches_schema(tmp_path: Path) -> None:
    path = _write_launch(tmp_path, "darts", ["NT07"])
    assert stub.main(["--launch", str(path), "--seconds", "0"]) == 0
    result = _read_result(tmp_path)
    assert result["status"] == "finished"
    assert [e["participant_code"] for e in result["entries"]] == ["NT07"]
    assert not list(tmp_path.glob("*.tmp"))


def test_pong_has_exactly_one_winner(tmp_path: Path) -> None:
    path = _write_launch(tmp_path, "pong", ["NT03", "NT14"])
    assert stub.main(["--launch", str(path), "--seconds", "0", "--seed", "1"]) == 0
    assert sorted(e["wins"] for e in _read_result(tmp_path)["entries"]) == [0, 1]


def test_abort_writes_aborted_result(tmp_path: Path) -> None:
    path = _write_launch(tmp_path, "football", ["NT01"])
    assert stub.main(["--launch", str(path), "--seconds", "0", "--abort"]) == 0
    result = _read_result(tmp_path)
    assert result["status"] == "aborted"
    assert result["entries"] == []


def test_crash_exits_nonzero_without_result(tmp_path: Path) -> None:
    path = _write_launch(tmp_path, "darts", ["NT01"])
    assert stub.main(["--launch", str(path), "--seconds", "0", "--crash"]) == 1
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("seed", range(5))
def test_build_result_is_valid_for_any_seed(seed: int) -> None:
    launch = {
        "session_id": SESSION,
        "discipline": "pong",
        "participants": [{"code": "NT01"}, {"code": "NT02"}],
    }
    _validator("Result").validate(stub.build_result(launch, random.Random(seed), abort=False))
