"""Резкие сокращения в `EmgProcessor`: синтетический сигнал, пачки отсчётов, 500 и 1000 Гц."""

import numpy as np
import pytest

from neurotlon_bridge.processing.emg import EmgConfig, EmgProcessor

REST_SIGMA = 3.0
STRONG_SIGMA = 100.0
CHUNK_S = 0.02


class Rig:
    def __init__(self, fs: int, settle_s: float = 0.0, seed: int = 0) -> None:
        cfg = EmgConfig(
            fs_nominal=fs,
            settle_s=settle_s,
            calib_rest_s=2.0,
            calib_contractions=2,
            calib_contraction_s=1.0,
            calib_pause_s=0.5,
        )
        self.fs = fs
        self.proc = EmgProcessor(cfg, fs)
        self.rng = np.random.default_rng(seed)
        self.t = 0.0

    def feed(self, seconds: float, sigma: float, chunk: int | None = None) -> None:
        total = round(seconds * self.fs)
        done = 0
        while done < total:
            n = min(chunk or round(CHUNK_S * self.fs), total - done)
            self.t += n / self.fs
            self.proc.push(self.rng.normal(0.0, sigma, n), self.t)
            done += n
        self.proc.update(self.t)

    def ramp(self, seconds: float, start: float, stop: float) -> None:
        steps = round(seconds / CHUNK_S)
        for sigma in np.linspace(start, stop, steps):
            self.feed(CHUNK_S, float(sigma))

    def calibrate(self) -> None:
        self.proc.start_calibration("rest", self.t)
        self.feed(2.1, REST_SIGMA)
        self.proc.start_calibration("contract", self.t)
        for _ in range(2):
            self.feed(1.0, STRONG_SIGMA)
            self.feed(0.5, REST_SIGMA)
        self.feed(0.1, REST_SIGMA)
        status = self.proc.calibration_status()
        assert status is not None and status.status == "done"

    def calm(self, seconds: float = 1.5) -> None:
        self.feed(seconds, REST_SIGMA)


@pytest.fixture(params=[500, 1000], ids=["500Hz", "1000Hz"])
def rig(request: pytest.FixtureRequest) -> Rig:
    r = Rig(request.param)
    r.calibrate()
    r.calm()
    return r


def test_sharp_contraction_gives_one_event_soon_after_onset(rig: Rig) -> None:
    onset = rig.t
    rig.feed(1.0, STRONG_SIGMA)
    events = rig.proc.drain_bursts()
    assert len(events) == 1
    assert 0.0 < events[0].t_s - onset < 0.35
    assert rig.proc.drain_bursts() == []


def test_event_time_does_not_depend_on_batch_size(rig: Rig) -> None:
    """BLE отдаёт пачками: момент события считается по номеру точки, а не по приходу пачки."""
    onset = rig.t
    rig.feed(1.0, STRONG_SIGMA, chunk=rig.fs // 2)  # пачки по полсекунды
    events = rig.proc.drain_bursts()
    assert len(events) == 1
    assert 0.0 < events[0].t_s - onset < 0.35


def test_unequal_batches_give_the_same_event_count() -> None:
    counts = []
    for chunk in (7, 20, 33, 100, 333):
        r = Rig(1000, seed=5)
        r.calibrate()
        r.calm()
        r.feed(1.0, STRONG_SIGMA, chunk=chunk)
        r.calm(0.8)
        counts.append(len(r.proc.drain_bursts()))
    assert counts == [1] * len(counts)


def test_slow_rise_gives_no_event(rig: Rig) -> None:
    rig.ramp(1.5, REST_SIGMA, STRONG_SIGMA)
    rig.feed(1.0, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []


def test_steady_moderate_tension_gives_no_event(rig: Rig) -> None:
    rig.ramp(1.0, REST_SIGMA, 30.0)
    rig.feed(3.0, 30.0)
    assert rig.proc.drain_bursts() == []


def test_two_contractions_with_relaxation_give_two_events(rig: Rig) -> None:
    rig.feed(0.5, STRONG_SIGMA)
    rig.calm(1.5)
    rig.feed(0.5, STRONG_SIGMA)
    assert len(rig.proc.drain_bursts()) == 2


def test_no_events_before_calibration() -> None:
    r = Rig(1000)
    r.calm()
    r.feed(1.0, STRONG_SIGMA)
    assert r.proc.drain_bursts() == []


def test_no_events_while_calibrating_again(rig: Rig) -> None:
    rig.proc.start_calibration("rest", rig.t)
    rig.calm(0.5)
    rig.feed(0.5, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []


def test_no_events_without_contact_and_arm_is_dropped(rig: Rig) -> None:
    rig.proc.set_contact(False)
    rig.feed(1.0, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []
    rig.proc.set_contact(True)
    rig.feed(1.0, STRONG_SIGMA)  # контакт вернулся на высоком уровне: взвода нет
    assert rig.proc.drain_bursts() == []
    rig.calm()
    rig.feed(0.5, STRONG_SIGMA)
    assert len(rig.proc.drain_bursts()) == 1


def test_contact_lost_in_the_middle_of_the_edge_gives_no_event(rig: Rig) -> None:
    rig.feed(0.03, STRONG_SIGMA)
    rig.proc.set_contact(False)
    rig.feed(0.5, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []


def pending_after_edge(fs: int, action: str | None) -> list[object]:
    """Резкий фронт без забора событий; затем действие над процессором; что осталось в очереди."""
    r = Rig(fs, seed=11)
    r.calibrate()
    r.calm()
    r.feed(0.5, STRONG_SIGMA)
    if action == "reset_stream":
        r.proc.reset_stream()
    elif action == "reset":
        r.proc.reset()
    elif action == "set_fs":
        r.proc.set_fs(fs * 2 if fs == 500 else 500)
    return list(r.proc.drain_bursts())


@pytest.mark.parametrize("action", ["reset_stream", "reset", "set_fs"])
def test_pending_events_are_dropped_by_resets(action: str) -> None:
    assert len(pending_after_edge(1000, None)) == 1  # без сброса событие есть
    assert pending_after_edge(1000, action) == []


def test_reset_stream_drops_arm(rig: Rig) -> None:
    rig.feed(0.03, STRONG_SIGMA)  # фронт начался, подтверждения не набрано
    rig.proc.reset_stream()
    rig.feed(1.0, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []


def test_events_during_settling_are_not_given() -> None:
    r = Rig(1000, settle_s=1.0)
    r.feed(1.2, REST_SIGMA)  # первое оседание прошло
    r.calibrate()
    r.calm()
    r.proc.reset_stream()  # связь прервалась: фильтры оседают заново
    r.feed(0.8, STRONG_SIGMA)
    assert r.proc.drain_bursts() == []
    r.calm(2.0)
    r.feed(0.5, STRONG_SIGMA)
    assert len(r.proc.drain_bursts()) == 1


def test_reset_clears_calibration_so_no_events(rig: Rig) -> None:
    rig.proc.reset()
    rig.calm()
    rig.feed(1.0, STRONG_SIGMA)
    assert rig.proc.drain_bursts() == []
