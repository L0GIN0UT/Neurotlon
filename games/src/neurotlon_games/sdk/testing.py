"""Подделки для тестов игр: мост без сети и готовый `LaunchInfo` (годятся и для тестов игры)."""

from __future__ import annotations

from pathlib import Path

from neurotlon_bridge.source import PROFILES, Feature, Reading, SensorState

from .launch import LaunchInfo, Participant
from .signals import Signals

SESSION_ID = "7b1d3e00-5a4f-4c2b-8e7a-91c0d2f3a4b5"


class FakeBridge:
    """Мост по умолчанию «подключён», датчики эмулируются (калибровка не нужна).

    `make_real()` превращает его в мост с реальными датчиками: они откалиброваны или нет.
    """

    def __init__(
        self,
        names: tuple[str, ...],
        *,
        features: tuple[Feature, ...] = (
            "burst",
            "emg_cycle",
            "baseline_duration",
            "calibration_state",
        ),
    ) -> None:
        self.names = names
        self.bridge_features = features
        self.is_connected = True
        self.readings: dict[str, Reading | None] = {n: Reading(0.0) for n in names}
        self.states: dict[str, SensorState | None] = {n: "emulated" for n in names}
        self.calibrated_names: set[str] = set()
        self.closed = False

    @property
    def connected(self) -> bool:
        return self.is_connected

    @property
    def features(self) -> tuple[Feature, ...]:
        return self.bridge_features

    def latest(self, signal: str) -> Reading | None:
        return self.readings.get(signal)

    def sensor_state(self, signal: str) -> SensorState | None:
        return self.states.get(signal)

    def calibrated(self, signal: str) -> bool:
        return "calibration_state" in self.bridge_features and signal in self.calibrated_names

    def close(self) -> None:
        self.closed = True

    def set_value(self, signal: str, value: float) -> None:
        self.readings[signal] = Reading(value)

    def make_real(self, *, calibrated: bool = True) -> None:
        """Реальные датчики: состояние `connected`, шкала готова только у откалиброванных."""
        self.states = {n: "connected" for n in self.names}
        self.calibrated_names = set(self.names) if calibrated else set()

    def lose_calibration(self) -> None:
        """Мост перезапустился и калибровку не вернул: значения `not_calibrated`."""
        self.calibrated_names = set()
        for name in self.names:
            self.readings[name] = Reading(0.0, False, "not_calibrated")


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


def make_signals(
    launch: LaunchInfo, features: tuple[Feature, ...] | None = None
) -> tuple[Signals, FakeBridge]:
    """`features=()` — старый мост без `hello.features`; по умолчанию мост современный."""
    names = PROFILES[launch.discipline]
    bridge = FakeBridge(names) if features is None else FakeBridge(names, features=features)
    return Signals(bridge, launch.signals), bridge
