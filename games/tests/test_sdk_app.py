import json
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from neurotlon_bridge.source import Reading
from neurotlon_games.sdk import GameApp, Phase, ResultEntry, Signals, completed
from neurotlon_games.sdk.testing import FakeBridge, make_launch, make_signals


class Probe(GameApp):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.updates = 0
        self.started_calls = 0
        self.drawn = 0
        self.bad_result = False

    def start(self) -> None:
        self.started_calls += 1

    def update(self, dt: float, signals: Signals) -> None:
        self.updates += 1

    def draw(self, surface: pygame.Surface) -> None:
        self.drawn += 1

    def result(self) -> Sequence[ResultEntry]:
        if self.bad_result:
            return [completed("NT99", 1)]
        if self.launch.is_pong:
            return [completed("NT03", 4, wins=1), completed("NT14", 2, wins=0)]
        return [completed("NT07", 4)]


@pytest.fixture(autouse=True)
def pygame_session() -> Iterator[None]:
    pygame.init()
    yield
    pygame.quit()


def make_game(
    tmp_path: Path, discipline: str = "darts", scale: float = 1.0
) -> tuple[Probe, FakeBridge]:
    launch = make_launch(discipline, tmp_path / "result.json", 10)
    signals, bridge = make_signals(launch)
    return Probe(launch, signals, time_scale=scale), bridge


def key(k: int) -> Any:
    return pygame.event.Event(pygame.KEYDOWN, key=k)


def advance(game: Probe, seconds: float, step: float = 0.1) -> None:
    for _ in range(round(seconds / step)):
        game.tick(step)


def phase_of(game: Probe) -> Phase:
    return game.phase


def to_playing(game: Probe) -> None:
    for _ in range(200):
        game.tick(0.1)
        if game.phase is Phase.PLAYING:
            return
    raise AssertionError(f"stuck in {game.phase}")


def read_result(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    return data


def test_full_flow_writes_finished_result(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    assert phase_of(game) is Phase.CONNECTING
    to_playing(game)
    assert game.started_calls == 1
    assert [c[1] for c in bridge.calibrate_calls] == ["rest", "contract", "baseline"]
    advance(game, 9.5)
    assert phase_of(game) is Phase.PLAYING
    assert not (tmp_path / "result.json").exists()
    advance(game, 1.0)
    assert phase_of(game) is Phase.FINISHED
    assert not game.done  # экран «Игра окончена» ещё показывается
    data = read_result(tmp_path)
    assert data["status"] == "finished"
    assert data["entries"] == [{"participant_code": "NT07", "outcome": "completed", "points": 4}]
    advance(game, 3.0)
    assert game.done
    assert game.updates > 50


def test_pong_result_has_one_winner(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path, "pong")
    to_playing(game)
    advance(game, 11)
    wins = [e["wins"] for e in read_result(tmp_path)["entries"]]
    assert sorted(wins) == [0, 1]


def test_time_scale_speeds_up_countdown_and_timer(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path, scale=10)
    for _ in range(40):
        game.tick(0.1)
        if game.phase is Phase.FINISHED:
            break
    assert phase_of(game) is Phase.FINISHED
    assert game.timer.expired


def test_countdown_counts_3_2_1(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    seen: list[int] = []
    for _ in range(100):
        game.tick(0.1)
        if game.phase is Phase.COUNTDOWN and (not seen or seen[-1] != game.countdown_number):
            seen.append(game.countdown_number)
    assert seen == [3, 2, 1]


def test_escape_asks_then_resumes(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    to_playing(game)
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    assert phase_of(game) is Phase.CONFIRM_ABORT
    before = game.timer.elapsed_s
    advance(game, 2)
    assert game.timer.elapsed_s == before  # на паузе
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    assert phase_of(game) is Phase.PLAYING
    assert not (tmp_path / "result.json").exists()


def test_escape_then_enter_aborts(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    to_playing(game)
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    game.tick(0.1, [key(pygame.K_RETURN)])
    assert phase_of(game) is Phase.FINISHED
    assert game.done
    data = read_result(tmp_path)
    assert data["status"] == "aborted"
    assert data["entries"] == []
    assert "оператор" in data["reason"]


def test_enter_without_confirmation_does_nothing(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    to_playing(game)
    game.tick(0.1, [key(pygame.K_RETURN)])
    assert phase_of(game) is Phase.PLAYING


def test_escape_during_calibration_can_abort(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    bridge.auto_calibrate = False
    advance(game, 1)
    assert phase_of(game) is Phase.CALIBRATING
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    game.tick(0.1, [key(pygame.K_RETURN)])
    assert read_result(tmp_path)["status"] == "aborted"


def test_window_close_aborts(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    game.tick(0.1, [pygame.event.Event(pygame.QUIT)])
    assert read_result(tmp_path)["status"] == "aborted"


def test_sensor_lost_pauses_then_resumes(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    to_playing(game)
    advance(game, 2)
    elapsed = game.timer.elapsed_s
    updates = game.updates
    bridge.readings["emg"] = Reading(0.0, False, "stale")
    advance(game, 5)
    assert phase_of(game) is Phase.SENSOR_LOST
    assert game.timer.elapsed_s <= elapsed + 0.11
    assert game.updates <= updates + 1
    bridge.readings["emg"] = Reading(0.5)
    advance(game, 0.2)
    assert phase_of(game) is Phase.PLAYING
    advance(game, 1)
    assert game.timer.elapsed_s > elapsed + 0.5


def test_sensor_lost_for_30_seconds_aborts(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    to_playing(game)
    bridge.is_connected = False
    advance(game, 29)
    assert phase_of(game) is Phase.SENSOR_LOST
    assert not (tmp_path / "result.json").exists()
    advance(game, 2)
    assert phase_of(game) is Phase.FINISHED
    data = read_result(tmp_path)
    assert data["status"] == "aborted"
    assert "30" in data["reason"]


def test_sensor_lost_during_countdown_waits(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    for _ in range(100):
        game.tick(0.1)
        if game.phase is Phase.COUNTDOWN:
            break
    bridge.readings["eeg"] = Reading(0.0, False, "disconnected")
    game.tick(0.1)
    assert phase_of(game) is Phase.SENSOR_LOST
    bridge.readings["eeg"] = Reading(0.2)
    game.tick(0.1)
    assert phase_of(game) is Phase.COUNTDOWN


def test_no_bridge_aborts_after_timeout(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    bridge.is_connected = False
    advance(game, 14)
    assert phase_of(game) is Phase.CONNECTING
    advance(game, 2)
    data = read_result(tmp_path)
    assert data["status"] == "aborted"
    assert "мост" in data["reason"]


def test_calibration_failure_aborts_with_reason(tmp_path: Path) -> None:
    game, bridge = make_game(tmp_path)
    bridge.auto_calibrate = False
    advance(game, 0.5)
    for _ in range(3):
        bridge.fail_next("emg", "rest", "нет контакта")
        advance(game, 0.3)
    data = read_result(tmp_path)
    assert data["status"] == "aborted"
    assert "нет контакта" in data["reason"]


def test_invalid_game_result_becomes_aborted(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path)
    game.bad_result = True
    to_playing(game)
    advance(game, 11)
    data = read_result(tmp_path)
    assert data["status"] == "aborted"
    assert "NT99" in data["reason"] or "не соответствуют" in data["reason"]
    assert game.aborted_reason


def test_render_every_phase(tmp_path: Path) -> None:
    surface = pygame.Surface((640, 360))
    game, bridge = make_game(tmp_path)
    bridge.auto_calibrate = False
    painted: set[Phase] = set()

    def snap() -> None:
        game.render(surface)
        painted.add(game.phase)

    snap()
    bridge.is_connected = True
    for _ in range(3):
        game.tick(0.1)
        snap()
    bridge.auto_calibrate = True
    game.calibration.start()
    to_playing(game)
    snap()
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    snap()
    game.tick(0.1, [key(pygame.K_ESCAPE)])
    bridge.is_connected = False
    game.tick(0.1)
    snap()
    bridge.is_connected = True
    game.tick(0.1)
    game.tick(0.1, [pygame.event.Event(pygame.QUIT)])
    snap()
    assert {
        Phase.CALIBRATING,
        Phase.PLAYING,
        Phase.CONFIRM_ABORT,
        Phase.SENSOR_LOST,
        Phase.FINISHED,
    } <= painted


def test_default_font_has_cyrillic() -> None:
    font = pygame.font.Font(None, 40)
    assert all(m is not None for m in font.metrics("Напрягите мышцу с датчиком Расслабьте"))
    assert font.size("Привет")[0] > font.size("..")[0]


def test_run_loop_headless(tmp_path: Path) -> None:
    game, _ = make_game(tmp_path, scale=200)
    game.finish_show_s = 0.0
    assert game.run(windowed=True) == 0
    assert read_result(tmp_path)["status"] == "finished"
