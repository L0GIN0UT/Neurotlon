from dataclasses import dataclass
from pathlib import Path

import pytest

from neurotlon_contracts import contract

SESSION = "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5"


@dataclass(frozen=True)
class E:
    participant_code: str
    outcome: str = "completed"
    wins: int | None = None


def result(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "protocol": 1,
        "session_id": SESSION,
        "status": "finished",
        "entries": [{"participant_code": "NT01", "outcome": "completed", "points": 5}],
    }
    return {**base, **fields}


def problem(
    data: object, discipline: str = "darts", codes: tuple[str, ...] = ("NT01",)
) -> str | None:
    return contract.result_problem(data, session_id=SESSION, discipline=discipline, codes=codes)


def test_valid_result() -> None:
    assert problem(result()) is None


def test_aborted_needs_reason_and_no_entries() -> None:
    assert problem(result(status="aborted", entries=[], reason="датчик")) is None
    assert "схем" in (problem(result(status="aborted", entries=[])) or "")


def test_other_session_is_rejected() -> None:
    assert "session_id" in (problem(result(session_id=SESSION.replace("7b", "7c"))) or "")


def test_wrong_participant_is_rejected() -> None:
    bad = result(entries=[{"participant_code": "NT02", "outcome": "completed", "points": 1}])
    assert "не соответствуют" in (problem(bad) or "")


def test_completed_without_points() -> None:
    bad = result(entries=[{"participant_code": "NT01", "outcome": "completed"}])
    assert "points" in (problem(bad) or "")


def test_not_completed_with_points() -> None:
    bad = result(entries=[{"participant_code": "NT01", "outcome": "not_completed", "points": 1}])
    assert "not_completed" in (problem(bad) or "")


def test_not_a_dict() -> None:
    assert "схем" in (problem([1]) or "")


@pytest.mark.parametrize(
    ("wins", "ok"),
    [((1, 0), True), ((0, 1), True), ((1, 1), False), ((0, 0), False), ((None, 1), False)],
)
def test_pong_winner_rule(wins: tuple[int | None, int | None], ok: bool) -> None:
    entries = [E("NT01", wins=wins[0]), E("NT02", wins=wins[1])]
    assert (contract.entries_problem("pong", entries) is None) is ok


def test_pong_not_completed_needs_no_winner() -> None:
    entries = [E("NT01", wins=1), E("NT02", outcome="not_completed")]
    assert contract.entries_problem("pong", entries) is None


def test_wins_forbidden_outside_pong() -> None:
    assert contract.entries_problem("darts", [E("NT01", wins=1)]) is not None


def test_entry_count_per_discipline() -> None:
    assert contract.entries_problem("pong", [E("NT01", wins=1)]) is not None
    assert contract.entries_problem("football", [E("NT01"), E("NT02")]) is not None


def limited(points: float, discipline: str = "darts", max_points: int | None = 10) -> str | None:
    entries = [{"participant_code": "NT01", "outcome": "completed", "points": points}]
    return contract.result_problem(
        result(entries=entries),
        session_id=SESSION,
        discipline=discipline,
        codes=("NT01",),
        max_points=max_points,
    )


def test_points_above_section_limit_are_rejected() -> None:
    assert limited(10) is None
    assert "лимита" in (limited(11) or "")
    assert "лимита" in (limited(11, "football") or "")


def test_no_limit_means_no_check() -> None:
    assert limited(999, max_points=None) is None


def test_pong_points_are_not_limited() -> None:
    codes = ("NT03", "NT04")
    entries = [
        {"participant_code": "NT03", "outcome": "completed", "points": 50, "wins": 1},
        {"participant_code": "NT04", "outcome": "completed", "points": 7, "wins": 0},
    ]
    assert (
        contract.result_problem(
            result(entries=entries),
            session_id=SESSION,
            discipline="pong",
            codes=codes,
            max_points=10,
        )
        is None
    )


def test_fractional_points_are_rejected_by_schema() -> None:
    assert "схему" in (limited(4.5) or "")
    assert "схему" in (limited(4.5, discipline="pong", max_points=None) or "")


def test_whole_float_points_are_accepted() -> None:
    assert limited(7.0) is None


@pytest.mark.parametrize(
    "body", [None, "{broken", '{"$defs": {}}', '{"$defs": {"EegMethod": {"enum": []}}}']
)
def test_eeg_methods_report_a_missing_or_broken_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str | None
) -> None:
    if body is not None:
        (tmp_path / "bridge-protocol.schema.json").write_text(body, encoding="utf-8")
    monkeypatch.setenv(contract.SHARED_ENV, str(tmp_path))
    contract.eeg_methods.cache_clear()
    try:
        with pytest.raises(contract.SchemaUnavailableError, match=r"bridge-protocol.schema.json"):
            contract.eeg_methods()
    finally:
        contract.eeg_methods.cache_clear()


def test_eeg_methods_come_from_the_bridge_schema() -> None:
    assert contract.eeg_methods() == ("emotions", "alpha")
