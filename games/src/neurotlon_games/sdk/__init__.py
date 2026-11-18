"""SDK игр Нейротлона: запуск, датчики, калибровка, таймер, результат.

Игра на pygame-ce наследует `GameApp`; игра на другом движке берёт те же правила из
`shared/game-launch.md`. Модуль не импортирует pygame при загрузке.
"""

from __future__ import annotations

from .app import GameApp, Phase, draw_bar, draw_text, run_game
from .calibration import Calibration, instruction, phases_for
from .launch import LaunchError, LaunchInfo, Participant
from .result import ResultEntry, ResultError, ResultWriter, completed, not_completed
from .signals import Signals
from .timer import Timer

__all__ = [
    "Calibration",
    "GameApp",
    "LaunchError",
    "LaunchInfo",
    "Participant",
    "Phase",
    "ResultEntry",
    "ResultError",
    "ResultWriter",
    "Signals",
    "Timer",
    "completed",
    "draw_bar",
    "draw_text",
    "instruction",
    "not_completed",
    "phases_for",
    "run_game",
]
