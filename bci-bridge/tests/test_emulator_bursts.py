"""Резкие сокращения в эмуляторе: события по нажатию клавиши на виртуальных часах."""

import pytest

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.processing.burst import BurstConfig
from neurotlon_bridge.source import BurstEvent


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Rig:
    def __init__(self, profile: str = "darts", burst: BurstConfig | None = None) -> None:
        self.clock = FakeClock()
        self.src = EmulatedSource(profile, self.clock, burst=burst)

    def hold(self, keys: set[str], seconds: float, dt: float = 0.02) -> None:
        self.src.set_keys(keys)
        steps = round(seconds / dt)
        for _ in range(steps):
            self.clock.now += dt
            self.src.tick(dt)


def test_key_press_after_calm_gives_one_event_soon_after_the_press() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    pressed_at = rig.clock.now
    rig.hold({"emg"}, 1.0)
    events = rig.src.drain_bursts("emg")
    assert len(events) == 1
    delay = events[0].t_s - pressed_at
    assert 0.05 < delay < 0.3, delay  # фронт 0,15 с + три подтверждающие точки


def test_holding_the_key_gives_no_more_events() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 5.0)
    assert len(rig.src.drain_bursts("emg")) == 1
    assert rig.src.drain_bursts("emg") == []


def test_release_and_press_again_gives_a_second_event() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 0.6)
    rig.hold(set(), 1.2)
    rig.hold({"emg"}, 0.6)
    assert len(rig.src.drain_bursts("emg")) == 2


def test_quick_second_press_gives_no_second_event() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 0.6)
    rig.hold(set(), 0.3)
    rig.hold({"emg"}, 0.6)
    assert len(rig.src.drain_bursts("emg")) == 1


@pytest.mark.parametrize("dt", [0.005, 0.02, 1 / 60, 0.1, 0.25])
def test_result_does_not_depend_on_tick_length(dt: float) -> None:
    rig = Rig()
    rig.hold(set(), 1.0, dt)
    rig.hold({"emg"}, 1.0, dt)
    assert len(rig.src.drain_bursts("emg")) == 1


def test_press_right_after_start_has_no_calm_window() -> None:
    rig = Rig()
    rig.hold({"emg"}, 1.0)
    assert rig.src.drain_bursts("emg") == []


def test_reset_drops_the_arm_and_pending_events() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 0.6)
    rig.src.reset()
    assert rig.src.drain_bursts("emg") == []
    rig.hold(set(), 0.1)
    rig.hold({"emg"}, 0.6)
    assert rig.src.drain_bursts("emg") == []  # после сброса снова нужен спокойный уровень


def test_pong_signals_are_independent() -> None:
    rig = Rig("pong")
    rig.hold(set(), 1.0)
    rig.hold({"emg_left"}, 1.0)
    assert len(rig.src.drain_bursts("emg_left")) == 1
    assert rig.src.drain_bursts("emg_right") == []


def test_eeg_has_no_bursts_and_unknown_signal_is_an_error() -> None:
    rig = Rig()
    rig.hold({"eeg_up"}, 0.5)
    assert rig.src.drain_bursts("eeg") == []
    with pytest.raises(ValueError):
        rig.src.drain_bursts("emg_left")


def test_burst_thresholds_come_from_the_config() -> None:
    cfg = BurstConfig(fire_level=0.6, rise_ref=0.5)
    rig = Rig(burst=cfg)
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 0.1)  # за 0,1 с уровень доходит только до 0,49
    assert rig.src.drain_bursts("emg") == []
    rig = Rig(burst=cfg)
    rig.hold(set(), 1.0)
    rig.hold({"emg"}, 1.0)  # 0,6 достигается за 0,14 с
    events = rig.src.drain_bursts("emg")
    assert len(events) == 1
    assert isinstance(events[0], BurstEvent)
    assert events[0].rise == 1.0  # прирост 1,0 при rise_ref 0,5 обрезан до 1


def test_event_is_dated_inside_the_tick_that_produced_it() -> None:
    rig = Rig()
    rig.hold(set(), 1.0)
    before = rig.clock.now
    rig.hold({"emg"}, 1.0, dt=0.5)  # две длинные пачки: события не позже конца пачки
    events = rig.src.drain_bursts("emg")
    assert len(events) == 1
    assert before <= events[0].t_s <= rig.clock.now
