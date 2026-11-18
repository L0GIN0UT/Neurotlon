"""Схемы из `shared/`: путь к папке и валидаторы файлов обмена с игрой."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SHARED_ENV = "NEUROTLON_SHARED"


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
