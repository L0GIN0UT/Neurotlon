import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from neurotlon_games.sdk.testing import make_launch, make_signals
from neurotlon_games.template import TemplateGame


def play(tmp_path: Path, discipline: str, values: dict[str, float]) -> dict[str, Any]:
    launch = make_launch(discipline, tmp_path / "result.json", 10)
    signals, bridge = make_signals(launch)
    game = TemplateGame(launch, signals)
    surface = pygame.Surface((640, 360))
    pygame.font.init()
    for name, value in values.items():
        bridge.set_value(name, value)
    for _ in range(500):
        game.tick(0.1)
        game.render(surface)
        if game.phase.value == "finished":
            break
    data: dict[str, Any] = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    return data


def test_darts_points_accumulate_above_threshold(tmp_path: Path) -> None:
    data = play(tmp_path, "darts", {"eeg": 0.9, "emg": 0.9})
    entry = data["entries"][0]
    assert entry["participant_code"] == "NT07"
    assert "wins" not in entry
    assert 19 <= entry["points"] <= 21  # 2 сигнала x 10 с


def test_below_threshold_gives_no_points(tmp_path: Path) -> None:
    data = play(tmp_path, "football", {"eeg": 0.5, "emg": 0.2})
    assert data["entries"][0]["points"] == 0


def test_pong_stronger_side_wins(tmp_path: Path) -> None:
    data = play(tmp_path, "pong", {"emg_left": 0.2, "emg_right": 0.9})
    by_code = {e["participant_code"]: e for e in data["entries"]}
    assert by_code["NT14"]["wins"] == 1
    assert by_code["NT03"]["wins"] == 0
    assert by_code["NT14"]["points"] > by_code["NT03"]["points"]


def test_pong_tie_still_has_exactly_one_winner(tmp_path: Path) -> None:
    data = play(tmp_path, "pong", {"emg_left": 0.1, "emg_right": 0.1})
    assert sorted(e["wins"] for e in data["entries"]) == [0, 1]
