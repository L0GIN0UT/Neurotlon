"""Подделки для тестов игр: мост без сети и готовый `LaunchInfo` (годятся и для тестов игры)."""

from __future__ import annotations

from pathlib import Path

from neurotlon_bridge.source import (
    PROFILES,
    CalibrationProgress,
    CalibrationStep,
    Reading,
    SensorState,
)

from .calibration import STEP_DURATION_S
from .launch import LaunchInfo, Participant
from .signals import Signals

SESSION_ID = "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5"


class FakeBridge:
    """Мост по умолчанию «подключён», калибровка проходит сама за `auto_calibrate` вызовов."""

    def __init__(self, names: tuple[str, ...], *, auto_calibrate: bool = True) -> None:
        self.names = names
        self.is_connected = True
        self.readings: dict[str, Reading | None] = {n: Reading(0.0) for n in names}
        self.states: dict[str, SensorState | None] = {n: "emulated" for n in names}
        self.progress: dict[str, CalibrationProgress | None] = {}
        self.calibrate_calls: list[tuple[str, CalibrationStep]] = []
        self.auto_calibrate = auto_calibrate
        self.closed = False

    @property
    def connected(self) -> bool:
        return self.is_connected

    def latest(self, signal: str) -> Reading | None:
        return self.readings.get(signal)

    def sensor_state(self, signal: str) -> SensorState | None:
        return self.states.get(signal)

    def calibration(self, signal: str) -> CalibrationProgress | None:
        return self.progress.get(signal)

    def calibrate(self, signal: str, step: CalibrationStep) -> bool:
        if not self.is_connected:
            return False
        self.calibrate_calls.append((signal, step))
        if self.auto_calibrate:
            self.progress[signal] = CalibrationProgress(step, "done", 1.0)
        else:
            self.progress[signal] = CalibrationProgress(step, "running", 0.0)
        return True

    def reset(self) -> bool:
        self.progress.clear()
        return True

    def close(self) -> None:
        self.closed = True

    def set_value(self, signal: str, value: float) -> None:
        self.readings[signal] = Reading(value)

    def fail_next(self, signal: str, step: CalibrationStep, reason: str = "нет контакта") -> None:
        self.progress[signal] = CalibrationProgress(step, "failed", 0.0, reason)

    def step_seconds(self, step: CalibrationStep) -> float:
        return STEP_DURATION_S[step]


def make_launch(
    discipline: str = "darts",
    result_path: Path | None = None,
    duration_s: int = 10,
    max_points: int | None = None,
) -> LaunchInfo:
    people: tuple[Participant, ...]
    if discipline == "pong":
        people = (Participant("NT03", "Аня", "left"), Participant("NT14", None, "right"))
    else:
        people = (Participant("NT07", "Аня"),)
    return LaunchInfo(
        session_id=SESSION_ID,
        discipline=discipline,
        duration_s=duration_s,
        participants=people,
        bridge_host="127.0.0.1",
        bridge_port=8765,
        result_path=result_path or Path("result.json"),
        fullscreen=False,
        max_points=max_points,
    )


def make_signals(launch: LaunchInfo) -> tuple[Signals, FakeBridge]:
    bridge = FakeBridge(PROFILES[launch.discipline])
    return Signals(bridge, launch.signals), bridge
