import json
import sys
from pathlib import Path

import pytest

from neurotlon_bridge.source import CalibrationProgress, Feature, Reading
from neurotlon_games.sdk import (
    Calibration,
    LaunchError,
    LaunchInfo,
    ResultError,
    ResultWriter,
    Timer,
    completed,
    instruction,
    not_completed,
    phases_for,
)
from neurotlon_games.sdk.calibration import (
    STEP_DURATION_S,
    TEXT_BASELINE,
    TEXT_NO_SIGNAL,
    TEXT_RELEASE,
    TEXT_REST,
    TEXT_SQUEEZE,
    TEXT_WEAK,
    reason_text,
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


# --- Calibration ---


def test_phases_match_protocol() -> None:
    assert [(p.step, p.signals) for p in phases_for("darts")] == [
        ("rest", ("emg",)),
        ("contract", ("emg",)),
        ("baseline", ("eeg",)),
    ]
    assert [p.step for p in phases_for("pong")] == ["rest", "contract"]
    assert phases_for("pong")[0].signals == ("emg_left", "emg_right")


def test_phases_use_cycle_when_bridge_announces_it() -> None:
    assert [(p.step, p.signals) for p in phases_for("darts", emg_cycle=True)] == [
        ("cycle", ("emg",)),
        ("baseline", ("eeg",)),
    ]
    pong = phases_for("pong", emg_cycle=True)
    assert [(p.step, p.signals) for p in pong] == [("cycle", ("emg_left", "emg_right"))]


def test_calibration_picks_cycle_only_with_emg_cycle_feature() -> None:
    launch = make_launch("darts")
    legacy = [("emg", "rest"), ("emg", "contract"), ("eeg", "baseline")]
    cases: list[tuple[tuple[Feature, ...], list[tuple[str, str]]]] = [
        (("burst", "emg_cycle"), [("emg", "cycle"), ("eeg", "baseline")]),
        (("burst",), legacy),
        ((), legacy),
    ]
    for features, steps in cases:
        signals, bridge = make_signals(launch, features=features)
        calibration = Calibration.for_launch(signals, launch)
        run_calibration(calibration)
        assert calibration.state == "done"
        assert bridge.calibrate_calls == steps


def test_cycle_pong_runs_on_both_sensors() -> None:
    launch = make_launch("pong")
    signals, bridge = make_signals(launch)
    calibration = Calibration.for_launch(signals, launch)
    run_calibration(calibration)
    assert bridge.calibrate_calls == [("emg_left", "cycle"), ("emg_right", "cycle")]


def test_cycle_text_and_countdown_follow_bridge_phase() -> None:
    launch = make_launch("darts")
    signals, bridge = make_signals(launch)
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    assert calibration.text == TEXT_SQUEEZE  # до первого сообщения моста
    bridge.progress["emg"] = CalibrationProgress("cycle", "running", 0.3, None, 2, "relax", 3.5)
    calibration.update(0.1)
    assert calibration.text == TEXT_REST
    assert calibration.cycle_phase == "relax"
    assert calibration.phase_left_s == 3.5
    bridge.progress["emg"] = CalibrationProgress("cycle", "running", 0.5, None, 3, "tense", 4.0)
    calibration.update(0.1)
    assert calibration.text == TEXT_SQUEEZE
    assert calibration.progress == 0.5


def test_instruction_for_cycle_uses_phase() -> None:
    assert instruction("cycle", 0.3, "tense") == TEXT_SQUEEZE
    assert instruction("cycle", 0.3, "relax") == TEXT_REST
    assert instruction("cycle", 0.0) == TEXT_SQUEEZE


def test_cycle_failure_shows_human_reason_and_retries() -> None:
    launch = make_launch("darts")
    signals, bridge = make_signals(launch)
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    bridge.fail_next("emg", "cycle", "сокращение слабое, нет отличия от покоя")
    calibration.update(0.1)
    assert calibration.retrying
    assert calibration.retry_reason == TEXT_WEAK
    calibration.update(0.1)
    assert bridge.calibrate_calls == [("emg", "cycle"), ("emg", "cycle")]
    bridge.progress["emg"] = CalibrationProgress("cycle", "failed", 0.0, "странная причина")
    calibration.update(0.1)
    assert calibration.state == "failed"
    assert calibration.failure_reason == "странная причина"


def test_reason_text_maps_known_reasons_only() -> None:
    assert reason_text("нет данных в покое") == TEXT_NO_SIGNAL
    assert reason_text("нет данных при напряжении") == TEXT_NO_SIGNAL
    assert reason_text("мост сломался") == "мост сломался"


def test_baseline_is_twelve_seconds_with_a_dot() -> None:
    assert STEP_DURATION_S["baseline"] == 12.0
    assert STEP_DURATION_S["cycle"] == 20.0
    launch = make_launch("darts")
    signals, bridge = make_signals(launch)
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    assert not calibration.shows_dot
    bridge.progress["emg"] = CalibrationProgress("cycle", "done", 1.0)
    calibration.update(0.1)
    calibration.update(0.1)
    assert calibration.shows_dot
    assert calibration.text == TEXT_BASELINE


def test_signals_supports_reads_bridge_features() -> None:
    signals, _ = make_signals(make_launch("darts"), features=("burst",))
    assert signals.supports("burst")
    assert not signals.supports("emg_cycle")


def test_instruction_texts_follow_12_second_rhythm() -> None:
    assert instruction("rest", 0.3) == TEXT_REST
    assert instruction("baseline", 0.3) == TEXT_BASELINE
    assert TEXT_REST == "Расслабьте мышцу с датчиком"
    assert TEXT_BASELINE == "Расслабьтесь и смотрите на точку на экране"
    by_second = {
        0.5: TEXT_SQUEEZE,
        2.9: TEXT_SQUEEZE,
        3.5: TEXT_RELEASE,
        4.5: TEXT_SQUEEZE,
        7.5: TEXT_RELEASE,
        8.5: TEXT_SQUEEZE,
        11.5: TEXT_RELEASE,
    }
    for second, text in by_second.items():
        assert instruction("contract", second / 12) == text, second


def state_of(calibration: Calibration) -> str:
    return calibration.state


def run_calibration(calibration: Calibration, ticks: int = 50) -> None:
    calibration.start()
    for _ in range(ticks):
        calibration.update(0.1)
        if calibration.finished:
            return


def test_calibration_runs_all_steps_in_order() -> None:
    launch = make_launch("darts")
    signals, bridge = make_signals(launch, features=())
    calibration = Calibration.for_launch(signals, launch)
    run_calibration(calibration)
    assert calibration.state == "done"
    assert bridge.calibrate_calls == [("emg", "rest"), ("emg", "contract"), ("eeg", "baseline")]
    assert calibration.total_progress == 1.0


def test_calibration_pong_runs_both_sensors_together() -> None:
    launch = make_launch("pong")
    signals, bridge = make_signals(launch, features=())
    calibration = Calibration.for_launch(signals, launch)
    run_calibration(calibration)
    assert calibration.state == "done"
    assert bridge.calibrate_calls == [
        ("emg_left", "rest"),
        ("emg_right", "rest"),
        ("emg_left", "contract"),
        ("emg_right", "contract"),
    ]


def test_calibration_progress_and_text_follow_bridge() -> None:
    launch = make_launch("darts")
    signals, bridge = make_signals(launch, features=())
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    assert calibration.phase_number == 1
    assert calibration.text == TEXT_REST
    bridge.progress["emg"] = CalibrationProgress("rest", "running", 0.4)
    calibration.update(0.1)
    assert calibration.progress == 0.4
    bridge.progress["emg"] = CalibrationProgress("rest", "done", 1.0)
    calibration.update(0.1)
    bridge.progress["emg"] = CalibrationProgress("contract", "running", 0.5)
    calibration.update(0.1)
    assert calibration.phase_number == 2
    assert calibration.text == TEXT_SQUEEZE  # 6 с от начала: вторая секунда второго сжатия
    assert 0 < calibration.total_progress < 1


def test_calibration_retries_once_then_reports() -> None:
    launch = make_launch("darts")
    signals, bridge = make_signals(launch, features=())
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    bridge.fail_next("emg", "rest", "нет контакта")
    calibration.update(0.1)
    assert state_of(calibration) == "running"
    assert calibration.retrying
    # прежний `failed` от первой попытки за новый сбой не считается
    calibration.update(0.1)
    assert bridge.calibrate_calls == [("emg", "rest"), ("emg", "rest")]
    assert state_of(calibration) == "running"
    bridge.progress["emg"] = CalibrationProgress("rest", "failed", 0.0, "снова нет контакта")
    calibration.update(0.1)
    assert state_of(calibration) == "failed"
    assert calibration.failure_reason == "снова нет контакта"


def test_calibration_retry_can_succeed() -> None:
    launch = make_launch("pong")
    signals, bridge = make_signals(launch, features=())
    bridge.auto_calibrate = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    calibration.update(0.1)
    bridge.fail_next("emg_left", "rest")
    bridge.progress["emg_right"] = CalibrationProgress("rest", "running", 0.5)
    calibration.update(0.1)
    assert calibration.retrying
    calibration.update(0.1)  # повторная отправка
    for name in ("emg_left", "emg_right"):
        bridge.progress[name] = CalibrationProgress("rest", "done", 1.0)
    calibration.update(0.1)
    assert calibration.phase_number == 2


def test_calibration_waits_for_bridge_and_times_out() -> None:
    launch = make_launch("pong")
    signals, bridge = make_signals(launch, features=())
    bridge.is_connected = False
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    for _ in range(50):
        calibration.update(0.1)
    assert state_of(calibration) == "running"
    assert bridge.calibrate_calls == []
    bridge.is_connected = True
    bridge.auto_calibrate = True
    run_calibration_continue(calibration)
    assert state_of(calibration) == "done"


def run_calibration_continue(calibration: Calibration) -> None:
    for _ in range(50):
        calibration.update(0.1)


def test_calibration_without_answer_fails_after_retry() -> None:
    launch = make_launch("pong")
    signals, bridge = make_signals(launch, features=())
    bridge.auto_calibrate = False  # мост молчит: прогресс остаётся 0
    calibration = Calibration.for_launch(signals, launch)
    calibration.start()
    for _ in range(2000):
        calibration.update(1.0)
        if calibration.finished:
            break
    assert calibration.state == "failed"
    assert "мост" in (calibration.failure_reason or "")


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
