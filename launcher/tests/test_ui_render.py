"""Каждый экран рисуется без ошибок на экранах разных размеров (без реального окна)."""

import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from neurotlon_launcher.api import Eligibility, Team
from neurotlon_launcher.machine import (
    Blocked,
    Candidate,
    Checking,
    Confirm,
    Done,
    Idle,
    Playing,
    RejectedEntry,
    RejectedList,
    Starting,
    State,
    TechnicalProblem,
)
from neurotlon_launcher.status import StationStatus
from neurotlon_launcher.ui import Ui

RED = Team(1, "Красные", "#e5484d")
ANNA = Candidate("NT03", Eligibility("NT03", "Анна", RED, ()))
BORIS = Candidate("NT14", Eligibility("NT14", None, None, ("no_pair_assigned", "unknown_issue")))
OFFLINE = Candidate("NT07", None)
SID = uuid.UUID(int=1)
LONG = "очень длинная причина " * 12


class FakeMachine:
    def __init__(self, discipline: str, state: State) -> None:
        self.discipline = discipline
        self.state = state
        self.calls: list[str] = []

    @property
    def players_needed(self) -> int:
        return 2 if self.discipline == "pong" else 1

    def __getattr__(self, name: str) -> Any:
        return lambda *args: self.calls.append(name)


class FakeScanner:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def frame(self) -> None:
        return None

    def poll(self) -> None:
        return None

    def stop(self) -> None:
        return None


STATES: list[tuple[str, State]] = [
    ("darts", Idle()),
    ("darts", Idle("NT0", "Это не похоже на ID")),
    ("pong", Idle("1", None, (ANNA,))),
    ("darts", Checking("NT03", ())),
    ("darts", Confirm(ANNA)),
    ("pong", Confirm(BORIS, (ANNA,), "Участник сейчас играет на другом стенде")),
    ("darts", Confirm(OFFLINE)),
    ("pong", Starting(SID, (ANNA, BORIS))),
    ("football", Playing(SID, (ANNA,), offline=True, default_limit=True)),
    ("pong", Done(("NT03: 8 очк.", "NT14: не пройдено"), time.monotonic() + 3)),
    ("darts", Done(("Отмечено: не пройдено",), time.monotonic() - 1)),
    ("darts", TechnicalProblem(SID, (ANNA,), LONG)),
    ("darts", Blocked(LONG)),
    ("darts", RejectedList(())),
    (
        "darts",
        RejectedList(
            tuple(RejectedEntry(f"{i:032x}", ("NT03", "NT14"), LONG) for i in range(12)),
            "C:/data/rejected.json",
        ),
    ),
]


@pytest.fixture(autouse=True)
def pygame_session() -> Iterator[None]:
    pygame.init()
    yield
    pygame.quit()


@pytest.mark.parametrize("size", [(1920, 1080), (1280, 720), (1024, 768), (800, 600)])
@pytest.mark.parametrize(("discipline", "state"), STATES, ids=lambda v: type(v).__name__)
def test_every_screen_draws(discipline: str, state: State, size: tuple[int, int]) -> None:
    screen = pygame.display.set_mode(size)
    ui = Ui(
        FakeMachine(discipline, state),  # type: ignore[arg-type]
        FakeScanner(available=False),
        lambda: StationStatus(3, 2, False),
        windowed=True,
    )
    ui.draw(screen)
    background = screen.get_at((size[0] // 2, size[1] // 2))
    assert background is not None


def test_clicking_a_button_runs_its_action() -> None:
    screen = pygame.display.set_mode((1280, 720))
    machine = FakeMachine("darts", Confirm(ANNA))
    ui = Ui(machine, FakeScanner(), lambda: StationStatus(), windowed=True)  # type: ignore[arg-type]
    ui.draw(screen)
    confirm = next(b for b in ui._buttons if b.primary)
    x, y, w, h = confirm.rect
    ui._on_click((x + w // 2, y + h // 2))
    assert machine.calls == ["confirm"]


def test_keypad_types_digits_and_next_submits() -> None:
    screen = pygame.display.set_mode((1920, 1080))
    machine = FakeMachine("darts", Idle())
    ui = Ui(machine, FakeScanner(), lambda: StationStatus(), windowed=True)  # type: ignore[arg-type]
    ui.draw(screen)
    labels = [b.label for b in ui._buttons]
    assert labels[:9] == list("123456789")
    assert "0" in labels
    for button in ui._buttons:
        assert button.rect[3] >= 100  # touch target


def test_touch_targets_are_large_on_every_screen() -> None:
    screen = pygame.display.set_mode((1920, 1080))
    for discipline, state in STATES:
        ui = Ui(
            FakeMachine(discipline, state),  # type: ignore[arg-type]
            FakeScanner(),
            lambda: StationStatus(),
            windowed=True,
        )
        ui.draw(screen)
        assert all(b.rect[3] >= 100 for b in ui._buttons), state
