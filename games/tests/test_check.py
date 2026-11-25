import sys
import time
from pathlib import Path

import pytest

from neurotlon_bridge.client import BridgeClient
from neurotlon_bridge.scripted import keys_at
from neurotlon_games.check.__main__ import main, split_command
from neurotlon_games.check.checks import Options, Report, resolve_command, run_check
from neurotlon_games.check.harness import CheckBridge

FAKE = [sys.executable, str(Path(__file__).with_name("fake_game.py"))]
STUB = [sys.executable, "-m", "neurotlon_games.stub", "--connect", "--seconds", "0"]
TEMPLATE = [sys.executable, "-m", "neurotlon_games.template"]


def check(discipline: str, command: list[str], **kwargs: object) -> Report:
    options = Options(discipline, tuple(command), **kwargs)  # type: ignore[arg-type]
    return run_check(options)


def statuses(report: Report) -> dict[str, str]:
    return {c.name: c.status for c in report.checks}


def details(report: Report, name: str) -> str:
    return next(c.detail for c in report.checks if c.name == name)


# --- мелочи ---


def test_split_command() -> None:
    assert split_command(["--discipline", "pong", "--", "python", "-m", "g"]) == (
        ["--discipline", "pong"],
        ["python", "-m", "g"],
    )
    assert split_command(["--discipline", "pong"]) == (["--discipline", "pong"], [])


def test_resolve_command_replaces_python() -> None:
    assert resolve_command(["python", "-m", "x"]) == (sys.executable, "-m", "x")
    assert resolve_command(["game.exe", "--fast"]) == ("game.exe", "--fast")


def test_scripted_input_moves_signals() -> None:
    held = [keys_at("darts", t / 10) for t in range(0, 70)]
    assert any("emg" in k for k in held) and any("emg" not in k for k in held)
    assert {"eeg_up", "eeg_down"} <= {k for keys in held for k in keys}
    pong = [keys_at("pong", t / 10) for t in range(0, 32)]
    assert any("emg_left" in k and "emg_right" not in k for k in pong)
    assert any("emg_right" in k and "emg_left" not in k for k in pong)


def test_scripted_input_has_a_steady_tension_phase_for_braking() -> None:
    """После импульсов идёт ровное напряжение (около 0,3): им останавливают мяч в зоне."""
    from neurotlon_bridge import scripted

    steady_from = scripted.PULSE_PHASE_S
    ticks = [
        "emg" in keys_at("darts", steady_from + i * scripted.TICK_S)
        for i in range(int(scripted.STEADY_PHASE_S / scripted.TICK_S))
    ]
    duty = sum(ticks) / len(ticks)
    assert 0.1 < duty < 0.3, "ключ включён на малую долю времени: сглаженное значение около 0,3"
    # импульсная фаза начинается снова после круга
    pulses = [keys_at("darts", scripted.CYCLE_S + t / 10) for t in range(0, 12)]
    assert any("emg" in k for k in pulses) and any("emg" not in k for k in pulses)


def test_bridge_records_what_the_game_does() -> None:
    with CheckBridge("pong", speed=100) as bridge:
        client = BridgeClient("127.0.0.1", bridge.port)
        try:
            deadline = time.monotonic() + 5
            while not (client.connected and bridge.source.reads) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert bridge.source.reads > 0
            client.calibrate("emg_left", "rest")
            deadline = time.monotonic() + 5
            while not bridge.source.calibrations and time.monotonic() < deadline:
                time.sleep(0.01)
            assert bridge.source.calibrations == [("emg_left", "rest")]
            seen: set[float] = set()
            end = time.monotonic() + 1.6
            while time.monotonic() < end:
                reading = client.latest("emg_left")
                if reading is not None:
                    seen.add(round(reading.value, 1))
                time.sleep(0.02)
            assert min(seen) < 0.3 < 0.7 < max(seen)
        finally:
            client.close()


def test_report_format_and_verdict() -> None:
    report = Report()
    report.add("PASS", "запуск", "ок")
    report.add("WARN", "калибровка", "нет")
    assert report.passed
    assert "ИТОГ: PASS (1 PASS, 0 FAIL, 1 WARN, 0 SKIP)" in report.format()
    report.add("FAIL", "result.json", "нет файла")
    assert not report.passed
    assert "ИТОГ: FAIL" in report.format()


# --- настоящие игры ---


@pytest.mark.parametrize("discipline", ["darts", "pong"])
def test_stub_passes(discipline: str) -> None:
    report = check(discipline, STUB)
    assert report.passed, report.format()
    assert statuses(report)["мост"] == "PASS"
    assert statuses(report)["калибровка"] == "WARN"  # заглушка не калибруется


def test_template_darts_passes_with_calibration() -> None:
    report = check("darts", TEMPLATE, time_scale=20, bridge_speed=50)
    assert report.passed, report.format()
    assert statuses(report)["калибровка"] == "PASS"
    assert statuses(report)["записи"] == "PASS"


def test_template_pong_passes_with_one_winner() -> None:
    report = check("pong", TEMPLATE, time_scale=20, bridge_speed=50)
    assert report.passed, report.format()
    assert statuses(report)["победитель"] == "PASS"
    assert "WARN" not in statuses(report).values()


def test_template_abort_test_sees_aborted_result() -> None:
    report = check(
        "darts", TEMPLATE, time_scale=30, bridge_speed=50, duration_s=600, abort_test=True
    )
    assert report.passed, report.format()
    assert statuses(report)["потеря датчиков"] == "PASS"


def test_abort_test_warns_when_game_ignores_lost_sensors() -> None:
    cmd = [*FAKE, "--mode", "hang"]
    report = check("darts", cmd, abort_test=True, abort_wait_s=1.0, duration_s=600)
    assert report.passed, report.format()
    assert statuses(report)["потеря датчиков"] == "WARN"


# --- сломанные игры ---


@pytest.mark.parametrize(
    ("mode", "discipline", "failed", "text"),
    [
        ("no-result", "darts", "result.json", "не записав"),
        ("garbage", "darts", "result.json", "не читается"),
        ("crash", "darts", "выход", "кодом 3"),
        ("wrong-session", "darts", "session_id", "00000000"),
        ("two-winners", "pong", "победитель", "ровно у одного"),
        ("no-winner", "pong", "победитель", "ровно у одного"),
        ("wins-outside-pong", "darts", "записи", "wins допустимы только в понге"),
        ("wrong-participant", "darts", "записи", "не соответствуют"),
        ("points-too-big", "darts", "result.json", "схем"),
        ("fractional-points", "darts", "result.json", "integer"),
        ("self-abort", "darts", "статус", "сам прервался"),
    ],
)
def test_broken_game_fails_with_clear_message(
    mode: str, discipline: str, failed: str, text: str
) -> None:
    report = check(discipline, [*FAKE, "--mode", mode])
    assert not report.passed
    assert statuses(report)[failed] == "FAIL", report.format()
    assert text in details(report, failed)
    assert "ИТОГ: FAIL" in report.format()


def test_hanging_game_is_killed_after_grace() -> None:
    started = time.monotonic()
    # срок выхода = duration_s + grace_s = 10 - 9.5 с; дольше нельзя ждать в тестах
    report = check("darts", [*FAKE, "--mode", "hang"], grace_s=-9.5, duration_s=10)
    assert time.monotonic() - started < 30
    assert statuses(report)["выход"] == "FAIL"
    assert "убита" in details(report, "выход")
    assert statuses(report)["result.json"] == "SKIP"


def test_game_that_never_connects_fails_bridge_check() -> None:
    report = check("darts", [*FAKE, "--no-bridge"])
    assert statuses(report)["мост"] == "FAIL"
    assert not report.passed


def test_missing_executable_fails() -> None:
    report = check("darts", ["definitely-not-a-game-binary"])
    assert not report.passed
    assert statuses(report) == {"запуск": "FAIL"}


# --- CLI ---


def test_cli_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--discipline", "darts", "--", *STUB]) == 0
    assert "ИТОГ: PASS" in capsys.readouterr().out
    assert main(["--discipline", "darts", "--", *FAKE, "--mode", "no-result"]) == 1
    assert "ИТОГ: FAIL" in capsys.readouterr().out


def test_cli_requires_command_and_valid_duration() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--discipline", "darts"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["--discipline", "darts", "--duration-s", "3", "--", "x"])
    assert exc.value.code == 2


def test_points_above_max_points_fail_the_check() -> None:
    report = check("darts", [*FAKE, "--mode", "points-over-limit"], max_points=10, grace_s=20)
    assert statuses(report)["записи"] == "FAIL"
    assert "лимита" in details(report, "записи")


def test_points_over_limit_pass_without_max_points() -> None:
    report = check("darts", [*FAKE, "--mode", "points-over-limit"], grace_s=20)
    assert statuses(report)["записи"] == "PASS"


def test_max_points_option_is_validated() -> None:
    with pytest.raises(SystemExit):
        main(["--discipline", "darts", "--max-points", "0", "--", *STUB])
