"""Правила обмена «лаунчер <-> игра» из `shared/game-launch.md`.

Единственное место, где проверяется `launch.json` и `result.json`: лаунчер, SDK игр и
`neurotlon-game-check` импортируют эти функции, а не копируют правила.
Нарушение возвращается текстом (по-русски), `None` — всё в порядке.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, ValidationError

PROTOCOL = 1
SHARED_ENV = "NEUROTLON_SHARED"
RESULT_REASON_MAX = 200


class EntryLike(Protocol):
    """Запись результата участника (launcher.GameEntry, sdk.ResultEntry)."""

    @property
    def participant_code(self) -> str: ...

    @property
    def outcome(self) -> str: ...

    @property
    def wins(self) -> int | None: ...


def shared_dir() -> Path:
    """Папка `shared/`: переменная `NEUROTLON_SHARED` или корень монорепозитория."""
    env = os.environ.get(SHARED_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "shared"


@cache
def _launch_defs() -> dict[str, Any]:
    text = (shared_dir() / "game-launch.schema.json").read_text(encoding="utf-8")
    defs: dict[str, Any] = json.loads(text)["$defs"]
    return defs


def launch_validator(name: str) -> Draft202012Validator:
    """Валидатор определения (`Launch`, `Result`, ...) из game-launch.schema.json."""
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": _launch_defs()})


def schema_problem(name: str, data: object) -> str | None:
    try:
        launch_validator(name).validate(data)
    except ValidationError as exc:
        return exc.message
    return None


def entries_problem(discipline: str, entries: Sequence[EntryLike]) -> str | None:
    """Правила сервера (`_validate_entries`); нарушение там даёт 422."""
    expected = 2 if discipline == "pong" else 1
    if len(entries) != expected or len({e.participant_code for e in entries}) != expected:
        return f"{discipline}: нужно ровно {expected} участник(ов) в результате"
    if discipline != "pong":
        if any(e.wins is not None for e in entries):
            return f"wins допустимы только в понге, а не в {discipline}"
        return None
    return pong_winner_problem(entries)


def pong_winner_problem(entries: Sequence[EntryLike]) -> str | None:
    """Понг: если завершили оба, `wins` есть у обоих и ровно у одного равно 1."""
    wins = [e.wins for e in entries]
    if all(e.outcome == "completed" for e in entries) and (
        None in wins or sum(w or 0 for w in wins) != 1
    ):
        return "понг: при двух завершивших wins есть у обоих, ровно у одного 1"
    return None


def raw_entries_problem(raw_entries: Sequence[dict[str, Any]], codes: Sequence[str]) -> str | None:
    """Записи из JSON: те же участники, что в сессии; points и wins только где положено."""
    by_code = {e["participant_code"]: e for e in raw_entries}
    if len(by_code) != len(raw_entries) or set(by_code) != set(codes):
        return "записи result.json не соответствуют участникам сессии"
    for code in codes:
        raw = by_code[code]
        if raw["outcome"] == "completed":
            if "points" not in raw:
                return f"у {code} нет points при completed"
        elif "points" in raw or "wins" in raw:
            return f"у {code} есть points или wins при not_completed"
    return None


class RawEntry:
    """Запись из разобранного JSON в виде `EntryLike`."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.participant_code: str = raw["participant_code"]
        self.outcome: str = raw["outcome"]
        self.wins: int | None = raw.get("wins")


def result_problem(
    data: object, *, session_id: str, discipline: str, codes: Sequence[str]
) -> str | None:
    """Полная проверка разобранного result.json против запущенной сессии."""
    problem = schema_problem("Result", data)
    if problem:
        return f"result.json не проходит схему: {problem}"
    assert isinstance(data, dict)
    if data["session_id"] != session_id:
        return "session_id в result.json не совпадает с запущенной сессией"
    if data["status"] == "aborted":
        return None
    raw: list[dict[str, Any]] = data["entries"]
    problem = raw_entries_problem(raw, codes)
    if problem:
        return problem
    return entries_problem(discipline, [RawEntry(e) for e in raw])
