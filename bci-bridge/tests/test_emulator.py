import pytest

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.keymap import KEY_MAPS, logical_keys
from neurotlon_bridge.source import PROFILES


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(profile: str = "darts", speed: float = 1.0) -> tuple[EmulatedSource, FakeClock]:
    clock = FakeClock()
    return EmulatedSource(profile, clock, speed), clock


def test_profiles_signals() -> None:
    assert make("darts")[0].signals() == ("eeg", "emg")
    assert make("football")[0].signals() == ("eeg", "emg")
    assert make("pong")[0].signals() == ("emg_left", "emg_right")


def test_unknown_profile() -> None:
    with pytest.raises(ValueError):
        EmulatedSource("chess", FakeClock())


def test_eeg_ramps_and_clamps() -> None:
    src, _ = make()
    src.set_keys({"eeg_up"})
    src.tick(0.2)
    assert src.read(0)["eeg"].value == pytest.approx(0.6)
    src.tick(10)
    assert src.read(0)["eeg"].value == 1.0
    src.set_keys({"eeg_down"})
    src.tick(1.0)
    assert src.read(0)["eeg"].value == pytest.approx(0.5)
    src.tick(10)
    assert src.read(0)["eeg"].value == 0.0


def test_eeg_artifact_invalid_only_while_held() -> None:
    src, _ = make()
    src.set_keys({"eeg_artifact"})
    reading = src.read(0)["eeg"]
    assert (reading.valid, reading.reason) == (False, "artifact")
    assert src.read(0)["emg"].valid
    src.set_keys(set())
    assert src.read(0)["eeg"].valid


def test_emg_rises_and_decays() -> None:
    src, _ = make()
    src.set_keys({"emg"})
    src.tick(0.15)
    rising = src.read(0)["emg"].value
    assert 0.55 < rising < 0.7
    src.tick(2.0)
    assert src.read(0)["emg"].value > 0.99
    src.set_keys(set())
    src.tick(0.25)
    assert 0.3 < src.read(0)["emg"].value < 0.4
    src.tick(3.0)
    assert src.read(0)["emg"].value < 0.01


def test_pong_channels_independent() -> None:
    src, _ = make("pong")
    src.set_keys({"emg_left"})
    src.tick(2.0)
    readings = src.read(0)
    assert readings["emg_left"].value > 0.99
    assert readings["emg_right"].value == 0.0
    src.set_keys({"emg_right"})
    src.tick(2.0)
    readings = src.read(0)
    assert readings["emg_left"].value < 0.01
    assert readings["emg_right"].value > 0.99


def test_states_emulated_and_unknown_signal() -> None:
    src, _ = make()
    assert src.state("eeg") == "emulated"
    with pytest.raises(ValueError):
        src.state("emg_left")


def test_readings_valid_without_calibration() -> None:
    src, _ = make()
    assert all(r.valid for r in src.read(0).values())
    assert src.calibration_status("emg") is None


def test_calibration_progress_then_done() -> None:
    src, clock = make()
    src.start_calibration("emg", "rest")
    status = src.calibration_status("emg")
    assert status is not None and status.status == "running" and status.progress == 0.0
    clock.now = 2.5
    status = src.calibration_status("emg")
    assert status is not None and status.progress == pytest.approx(0.5)
    clock.now = 5.0
    status = src.calibration_status("emg")
    assert status is not None and status.status == "done" and status.progress == 1.0


def test_calibration_durations_and_speed() -> None:
    src, clock = make(speed=2.0)
    src.start_calibration("eeg", "baseline")
    clock.now = 4.0  # 8 секунд на скорости 2
    status = src.calibration_status("eeg")
    assert status is not None and status.status == "done"
    src.start_calibration("emg", "contract")
    clock.now = 7.0  # 3 секунды на скорости 2 из 12 с шага
    status = src.calibration_status("emg")
    assert status is not None and status.progress == pytest.approx(0.5)


def test_calibration_wrong_step_fails() -> None:
    src, _ = make()
    src.start_calibration("emg", "baseline")
    status = src.calibration_status("emg")
    assert status is not None and status.status == "failed" and status.reason


def test_reset_clears_calibration() -> None:
    src, _ = make()
    src.start_calibration("emg", "rest")
    src.reset()
    assert src.calibration_status("emg") is None


def test_keymap_covers_all_profile_keys() -> None:
    for profile, signals in PROFILES.items():
        logical = set(KEY_MAPS[profile].values())
        for signal in signals:
            assert signal in logical or signal == "eeg"
    assert logical_keys("pong", {"left shift", "p", "z"}) == {"emg_left", "emg_right"}
    assert logical_keys("darts", {"w", "space", "a"}) == {"eeg_up", "emg", "eeg_artifact"}
    assert logical_keys("pong", {"q"}) == {"emg_left"}
    assert logical_keys("darts", set()) == set()
