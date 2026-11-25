"""Сценарий `scripted`: импульсы дают по событию на нажатие, ровное и медленное — ни одного."""

from neurotlon_bridge import scripted
from neurotlon_bridge.emulator import EmulatedSource


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def run_cycles(profile: str, cycles: int) -> tuple[list[float], list[float]]:
    """Время нажатий «ключа» и время событий за `cycles` кругов сценария."""
    clock = FakeClock()
    src = EmulatedSource(profile, clock)
    presses: list[float] = []
    events: list[float] = []
    was_held = False
    steps = round(cycles * scripted.CYCLE_S / scripted.TICK_S)
    for i in range(steps):
        t = i * scripted.TICK_S
        keys = scripted.keys_at(profile, t)
        held = "emg" in keys
        if held and not was_held:
            presses.append(t)
        was_held = held
        src.set_keys(keys)
        clock.now += scripted.TICK_S
        src.tick(scripted.TICK_S)
        events += [e.t_s for e in src.drain_bursts("emg")]
    return presses, events


def phase_of(t: float) -> str:
    u = t % scripted.CYCLE_S
    if u < scripted.PULSE_PHASE_S:
        return "pulses"
    if u < scripted.PULSE_PHASE_S + scripted.STEADY_PHASE_S:
        return "steady"
    return "ramp"


def test_each_pulse_gives_exactly_one_event_and_nothing_else_does() -> None:
    presses, events = run_cycles("darts", 3)
    pulse_presses = [t for t in presses if phase_of(t) == "pulses"]
    assert len(pulse_presses) == 3 * 7
    assert len(events) == len(pulse_presses), "события вне фазы импульсов"
    for press, event in zip(pulse_presses, events, strict=True):
        assert 0.0 < event - press < 0.35, (press, event)


def test_steady_tension_phase_gives_no_events() -> None:
    _, events = run_cycles("darts", 3)
    assert [t for t in events if phase_of(t) == "steady"] == []


def test_slow_ramp_phase_gives_no_events() -> None:
    _, events = run_cycles("darts", 3)
    assert [t for t in events if phase_of(t) == "ramp"] == []


def test_football_profile_behaves_the_same() -> None:
    presses, events = run_cycles("football", 1)
    assert len(events) == len([t for t in presses if phase_of(t) == "pulses"])


def test_ramp_phase_really_climbs_to_full_scale() -> None:
    clock = FakeClock()
    src = EmulatedSource("darts", clock)
    top = 0.0
    start = scripted.PULSE_PHASE_S + scripted.STEADY_PHASE_S
    for i in range(round(scripted.CYCLE_S / scripted.TICK_S)):
        t = i * scripted.TICK_S
        src.set_keys(scripted.keys_at("darts", t))
        src.tick(scripted.TICK_S)
        if t > start:
            top = max(top, src.read(0)["emg"].value)
    assert top > 0.9
