"""Схемы из `shared/`: правила лежат в `neurotlon_games.contract`, здесь только реэкспорт."""

from __future__ import annotations

from neurotlon_contracts.contract import SHARED_ENV, launch_validator, shared_dir

__all__ = ["SHARED_ENV", "launch_validator", "shared_dir"]
