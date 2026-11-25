import json
import sys
from pathlib import Path

import pytest

from neurotlon_bridge.source import Reading
from neurotlon_games.sdk import (
    LaunchError,
    LaunchInfo,
    ResultError,
    ResultWriter,
    Timer,
    completed,
    not_completed,
)
from neurotlon_games.sdk.testing import SESSION_ID, FakeBridge, make_launch, make_signals


def launch_dict(discipline: str = "darts", **over: object) -> dict[str, object]:
    people: list[dict[str, object]] = [{"code": "NT07", "display_name": None}]
    if discipline == "pong":
        people = [
            {"code": "NT03", "display_name": "Аня", "side": "left"},
            {"code": "NT14", "display_name": None, "side": "right"},
        ]
    data: dict[str, object] = {
        "protocol": 1,
        "session_id": SESSION_ID,
        "discipline": discipline,
        "duration_s": 60,
        "participants": people,
        "bridge": {"host": "127.0.0.1", "port": 9000},
        "result_path": "res/result.json",
        "language": "ru",
    }
    return {**data, **over}


# --- LaunchInfo ---


def test_launch_parses_darts() -> None:
    info = LaunchInfo.from_dict(launch_dict())
    assert info.signals == ("eeg", "emg")
    assert info.bridge_port == 9000
    assert info.fullscreen is True
    assert info.result_path == Path("res/result.json")


def test_launch_parses_pong_sides() -> None:
    info = LaunchInfo.from_dict(launch_dict("pong"))
    assert info.by_side("right").code == "NT14"
    assert info.signal_of(info.by_side("left")) == "emg_left"
    assert info.signals == ("emg_left", "emg_right")


def test_launch_from_args_and_file(tmp_path: Path) -> None:
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(launch_dict()), encoding="utf-8")
    assert LaunchInfo.from_args(["game.exe", "--launch", str(path)]).session_id == SESSION_ID
    assert LaunchInfo.from_args([f"--launch={path}"]).discipline == "darts"


@pytest.mark.parametrize("argv", [[], ["--launch"], ["--other", "x"]])
def test_launch_from_args_missing(argv: list[str]) -> None:
    with pytest.raises(LaunchError):
        LaunchInfo.from_args(argv)


def test_launch_file_unreadable(tmp_path: Path) -> None:
    with pytest.raises(LaunchError):
        LaunchInfo.from_file(tmp_path / "none.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(LaunchError):
        LaunchInfo.from_file(bad)


def test_launch_rejects_schema_violation() -> None:
    with pytest.raises(LaunchError, match="схем"):
        LaunchInfo.from_dict(launch_dict(duration_s=1))


def test_launch_rejects_wrong_participant_count() -> None:
    two = launch_dict("pong")
    with pytest.raises(LaunchError):
        LaunchInfo.from_dict({**two, "discipline": "darts"})
    one = launch_dict("pong", participants=[{"code": "NT03", "display_name": None, "side": "left"}])
    with pytest.raises(LaunchError):
        LaunchInfo.from_dict(one)


def test_pong_needs_distinct_sides() -> None:
    same = launch_dict(
        "pong",
        participants=[
            {"code": "NT03", "display_name": None, "side": "left"},
            {"code": "NT14", "display_name": None, "side": "left"},
        ],
    )
    with pytest.raises(LaunchError, match="left и right"):
        LaunchInfo.from_dict(same)


# --- Timer ---


def test_timer_counts_down_and_expires() -> None:
    timer = Timer(10)
    assert timer.label() == "0:10"
    timer.tick(2.5)
    assert timer.remaining_s == 7.5
    assert timer.label() == "0:08"
    assert not timer.expired
    timer.tick(100)
    assert timer.expired
    assert timer.remaining_s == 0
    assert timer.elapsed_s == 10
    assert timer.label() == "0:00"


def test_timer_ignores_negative_dt_and_rejects_zero_duration() -> None:
    timer = Timer(60)
    timer.tick(-5)
    assert timer.elapsed_s == 0
    assert timer.label() == "1:00"
    with pytest.raises(ValueError):
        Timer(0)


# --- ResultWriter ---


def test_writer_finished_is_atomic_and_valid(tmp_path: Path) -> None:
    launch = make_launch("pong", tmp_path / "out" / "result.json")
    ResultWriter(launch).write_finished(
        [completed("NT03", 12, wins=1), completed("NT14", 7, wins=0)]
    )
    data = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert data["status"] == "finished"
    assert data["entries"][0] == {
        "participant_code": "NT03",
        "outcome": "completed",
        "points": 12,
        "wins": 1,
    }
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_writer_aborted(tmp_path: Path) -> None:
    launch = make_launch("darts", tmp_path / "result.json")
    ResultWriter(launch).write_aborted("х" * 500)
    data = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert data["status"] == "aborted"
    assert data["entries"] == []
    assert len(data["reason"]) == 200


def test_writer_not_completed(tmp_path: Path) -> None:
    launch = make_launch("darts", tmp_path / "result.json")
    ResultWriter(launch).write_finished([not_completed("NT07", "health")])
    entry = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["entries"][0]
    assert entry == {"participant_code": "NT07", "outcome": "not_completed", "reason": "health"}


@pytest.mark.parametrize(
    "entries",
    [
        [completed("NT03", 1, wins=1), completed("NT14", 1, wins=1)],  # два победителя
        [completed("NT03", 1, wins=0), completed("NT14", 1, wins=0)],  # нет победителя
        [completed("NT03", 1, wins=1)],  # не хватает участника
        [completed("NT03", 1, wins=1), completed("NT99", 1, wins=0)],  # чужой код
        [completed("NT03", 5000, wins=1), completed("NT14", 1, wins=0)],  # points > 1000
    ],
)
def test_writer_refuses_invalid_pong(tmp_path: Path, entries: list) -> None:  # type: ignore[type-arg]
    launch = make_launch("pong", tmp_path / "result.json")
    with pytest.raises(ResultError):
        ResultWriter(launch).write_finished(entries)
    assert not (tmp_path / "result.json").exists()


def test_writer_refuses_wins_in_darts(tmp_path: Path) -> None:
    launch = make_launch("darts", tmp_path / "result.json")
    with pytest.raises(ResultError):
        ResultWriter(launch).write_finished([completed("NT07", 5, wins=1)])


# --- Signals ---


def test_value_is_none_when_invalid_or_missing() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    bridge.set_value("emg", 0.7)
    assert signals.value("emg") == 0.7
    bridge.readings["emg"] = Reading(0.0, False, "artifact")
    assert signals.value("emg") is None
    bridge.readings["eeg"] = None
    assert signals.value("eeg") is None


def test_lost_signals() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    assert signals.lost_signals() == []
    bridge.readings["emg"] = Reading(0.0, False, "artifact")  # артефакт не потеря
    assert signals.lost_signals() == []
    bridge.readings["emg"] = Reading(0.0, False, "stale")
    assert signals.lost_signals() == ["emg"]
    bridge.readings["emg"] = Reading(0.3)
    bridge.states["eeg"] = "disconnected"
    assert signals.lost_signals() == ["eeg"]
    bridge.is_connected = False
    assert signals.lost_signals() == ["eeg", "emg"]


def test_wait_connected_times_out_then_succeeds() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    now = [0.0]

    def sleep(s: float) -> None:
        now[0] += s

    bridge.is_connected = False
    assert signals.wait_connected(0.1, clock=lambda: now[0], sleep=sleep) is False
    bridge.is_connected = True
    assert signals.wait_connected(0.1, clock=lambda: now[0], sleep=sleep) is True
    bridge.states["emg"] = None  # hello ещё не пришёл
    assert signals.wait_connected(0.1, clock=lambda: now[0], sleep=sleep) is False


# --- готовность калибровки ---


def test_signals_supports_reads_bridge_features() -> None:
    signals, _ = make_signals(make_launch("darts"), features=("burst",))
    assert signals.supports("burst")
    assert not signals.supports("emg_cycle")


def test_emulated_sensors_need_no_calibration() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    assert bridge.states == {"eeg": "emulated", "emg": "emulated"}
    assert not signals.calibrated("emg")
    assert signals.uncalibrated() == []


def test_real_sensors_are_ready_only_when_calibrated() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    bridge.make_real(calibrated=False)
    assert signals.uncalibrated() == ["eeg", "emg"]
    bridge.calibrated_names = {"emg"}
    assert signals.calibrated("emg")
    assert signals.uncalibrated() == ["eeg"]
    bridge.make_real(calibrated=True)
    assert signals.uncalibrated() == []


def test_pong_needs_both_emg_signals_calibrated() -> None:
    signals, bridge = make_signals(make_launch("pong"))
    bridge.make_real(calibrated=False)
    bridge.calibrated_names = {"emg_left"}
    assert signals.uncalibrated() == ["emg_right"]


def test_old_bridge_without_calibration_state_is_not_checked() -> None:
    signals, bridge = make_signals(make_launch("darts"), features=())
    bridge.make_real(calibrated=False)
    assert signals.uncalibrated() == []


def test_calibration_lost_follows_not_calibrated_readings() -> None:
    signals, bridge = make_signals(make_launch("darts"))
    assert signals.calibration_lost() == []
    bridge.readings["emg"] = Reading(0.0, False, "artifact")
    assert signals.calibration_lost() == []
    bridge.readings["emg"] = Reading(0.0, False, "not_calibrated")
    assert signals.calibration_lost() == ["emg"]
    assert signals.lost_signals() == []  # это не потеря датчика


def test_sdk_import_does_not_load_pygame() -> None:
    import subprocess

    code = "import sys, neurotlon_games.sdk; sys.exit('pygame' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_fake_bridge_is_a_bridge() -> None:
    assert FakeBridge(("emg",)).connected


def test_launch_reads_max_points() -> None:
    assert LaunchInfo.from_dict(launch_dict(max_points=10)).max_points == 10
    assert LaunchInfo.from_dict(launch_dict()).max_points is None


def test_launch_rejects_bad_max_points() -> None:
    for bad in (0, 1001):
        with pytest.raises(LaunchError):
            LaunchInfo.from_dict(launch_dict(max_points=bad))


def test_writer_refuses_points_above_max_points(tmp_path: Path) -> None:
    launch = make_launch("darts", tmp_path / "result.json", max_points=10)
    with pytest.raises(ResultError, match="лимита"):
        ResultWriter(launch).write_finished([completed("NT07", 11)])
    assert not (tmp_path / "result.json").exists()
    ResultWriter(launch).write_finished([completed("NT07", 10)])
    assert (tmp_path / "result.json").exists()


def test_writer_pong_points_ignore_max_points(tmp_path: Path) -> None:
    launch = make_launch("pong", tmp_path / "result.json", max_points=10)
    ResultWriter(launch).write_finished(
        [completed("NT03", 50, wins=1), completed("NT14", 7, wins=0)]
    )


def test_completed_requires_whole_points(tmp_path: Path) -> None:
    for bad in (4.5, 0.1, True):
        with pytest.raises(ResultError, match="целым"):
            completed("NT07", bad)  # type: ignore[arg-type]
    assert completed("NT07", 7.0).points == 7  # type: ignore[arg-type]
    assert isinstance(completed("NT07", 7.0).points, int)  # type: ignore[arg-type]
