import os

import pytest

from neurotlon_bridge.devices.fakes import FakeBackend, FakeClock, FakeRawSensor
from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.source import CalibrationProgress, Reading
from neurotlon_bridge.window import calibration_text, run_window


class QuittingSource:
    """Источник, который на третьем чтении просит окно закрыться."""

    def __init__(self) -> None:
        self.reads = 0

    def signals(self) -> tuple[str, ...]:
        return ("emg_left", "emg_right")

    def read(self, now_ms: int) -> dict[str, Reading]:
        import pygame

        self.reads += 1
        if self.reads >= 3:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        return {"emg_left": Reading(0.4), "emg_right": Reading(0.0, False, "no_contact")}

    def state(self, signal: str) -> str:
        return "connected"

    def start_calibration(self, signal: str, step: str) -> None: ...

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        return CalibrationProgress("rest", "running", 0.5)

    def reset(self) -> None: ...

    def battery(self, signal: str) -> int | None:
        return 90


def test_hardware_window_renders_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SDL_VIDEODRIVER", "dummy")
    source = QuittingSource()
    run_window(source, "pong", keyboard=False)  # type: ignore[arg-type]
    assert source.reads >= 3


def test_keyboard_requires_emulator() -> None:
    with pytest.raises(TypeError):
        run_window(QuittingSource(), "pong", keyboard=True)  # type: ignore[arg-type]


def test_emulator_window_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "SDL_VIDEODRIVER", "dummy")
    import pygame

    source = EmulatedSource("darts", FakeClock())
    original = source.read
    calls = 0

    def read(now_ms: int) -> dict[str, Reading]:
        nonlocal calls
        calls += 1
        if calls >= 3:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        return original(now_ms)

    source.read = read  # type: ignore[method-assign]
    run_window(source, "darts")
    assert calls >= 3


def test_calibration_text() -> None:
    assert calibration_text(None) == ""
    assert "50%" in calibration_text(CalibrationProgress("rest", "running", 0.5))
    assert "готово" in calibration_text(CalibrationProgress("rest", "done", 1.0))
    assert "сбой" in calibration_text(CalibrationProgress("rest", "failed", 0.0, "нет данных"))


def test_fakes_scan_shape() -> None:
    found = FakeBackend([FakeRawSensor("callibri", "S1")]).scan(1.0)
    assert found[0].serial == "S1"


def test_calibration_text_shows_cycle_phase_and_time_left() -> None:
    tense = CalibrationProgress("cycle", "running", 0.2, None, 1, "tense", 3.5)
    assert "напрячь ещё 3.5 с" in calibration_text(tense)
    relax = CalibrationProgress("cycle", "running", 0.6, None, 2, "relax", 1.0)
    assert "расслабить ещё 1.0 с" in calibration_text(relax)
