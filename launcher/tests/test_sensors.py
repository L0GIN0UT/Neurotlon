import json
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from neurotlon_launcher import sensors
from neurotlon_launcher.api import DisciplineConfig
from neurotlon_launcher.config import ConfigError, parse_config
from neurotlon_launcher.runtime import StationRuntime
from neurotlon_launcher.sensors import (
    BridgeProcess,
    SensorDevice,
    SensorService,
    duplicate_serials,
    missing_roles,
    roles_for,
)
from neurotlon_launcher.setup import SetupForm, SetupService
from neurotlon_launcher.setup_station import SetupStation, form_from

SCAN = [
    {"kind": "brainbit", "name": "BrainBit", "serial": "BB-777", "address": "AA:01"},
    {"kind": "callibri", "name": "Callibri_L", "serial": "", "address": "AA:02"},
]


def completed(
    stdout: str = "", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def runner_returning(result: subprocess.CompletedProcess[str] | Exception) -> Any:
    calls: list[list[str]] = []

    def run(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if isinstance(result, Exception):
            raise result
        return result

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_roles_per_discipline() -> None:
    assert roles_for("darts") == roles_for("football") == ("eeg", "emg")
    assert roles_for("pong") == ("emg_left", "emg_right")
    assert roles_for(None) == roles_for("chess") == ()
    assert missing_roles("pong", {"emg_left": "C1"}) == ["emg_right"]
    assert missing_roles("darts", {"eeg": " ", "emg": "C1"}) == ["eeg"]
    assert duplicate_serials("pong", {"emg_left": "c1", "emg_right": "C1"})
    assert not duplicate_serials("pong", {"emg_left": "C1", "emg_right": "C2"})


def test_scan_parses_the_bridge_output(tmp_path: Path) -> None:
    run = runner_returning(completed("Поиск...\n" + json.dumps(SCAN, ensure_ascii=False)))
    service = SensorService(tmp_path, "bridge.exe", run)
    devices, error = service.scan()
    assert error is None
    assert devices == [
        SensorDevice("brainbit", "BrainBit", "BB-777", "AA:01"),
        SensorDevice("callibri", "Callibri_L", "", "AA:02"),
    ]
    assert run.calls == [["bridge.exe", "--scan", "--json"]]


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (completed(code=3, stderr="Ошибка: нет Bluetooth-адаптера\n"), "нет Bluetooth-адаптера"),
        (completed("не json"), sensors.SCAN_FAILED),
        (completed(""), sensors.SCAN_FAILED),
        (subprocess.TimeoutExpired("bridge", 1), sensors.SCAN_TIMEOUT),
        (FileNotFoundError("нет файла"), "нет файла"),
    ],
)
def test_scan_reports_failures(tmp_path: Path, result: Any, message: str) -> None:
    devices, error = SensorService(tmp_path, "bridge.exe", runner_returning(result)).scan()
    assert devices == []
    assert error is not None and message in error


def test_scan_without_a_bridge_in_the_build(tmp_path: Path) -> None:
    service = SensorService(tmp_path, "")
    assert not service.available
    assert service.scan() == ([], sensors.NO_BRIDGE)


def test_bridge_toml_roundtrip_matches_the_bridge_config(tmp_path: Path) -> None:
    service = SensorService(tmp_path, "bridge.exe")
    service.save_devices({"eeg": " BB-1 ", "emg": 'CA "2"', "emg_left": "", "junk": "x"})
    saved = service.saved_devices()
    assert saved == {"eeg": "BB-1", "emg": 'CA "2"'}
    from neurotlon_bridge.config import load_config as bridge_load

    config = bridge_load(service.toml_path)  # тот самый разбор, который сделает мост
    assert config.devices == {"eeg": "BB-1", "emg": 'CA "2"'}
    assert SensorService(tmp_path / "none", "x").saved_devices() == {}


# --- надзор за мостом ----------------------------------------------------------------------


class FakeProc:
    def __init__(self, code: int, stderr: str, block: threading.Event | None = None) -> None:
        self.returncode: int | None = None
        self.stderr = _Pipe(stderr, block)
        self._code = code
        self._block = block
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._block is not None:
            self._block.wait(timeout)
        self.returncode = self._code
        return self._code

    def terminate(self) -> None:
        self.terminated = True
        if self._block is not None:
            self._block.set()

    def kill(self) -> None:
        self.terminate()


class _Pipe:
    def __init__(self, text: str, block: threading.Event | None) -> None:
        self._text = text
        self._block = block

    def read(self) -> str:
        if self._block is not None:
            self._block.wait()
        return self._text


def test_bridge_is_restarted_with_growing_pauses_and_reports_the_last_error() -> None:
    attempts = [FakeProc(3, "x\nОшибка: нет Bluetooth-адаптера\n") for _ in range(3)]
    delays: list[float] = []
    done = threading.Event()
    spawned: list[Sequence[str]] = []

    def popen(args: Sequence[str]) -> Any:
        spawned.append(args)
        return attempts[len(spawned) - 1]

    def sleep(delay: float) -> bool:
        delays.append(delay)
        if len(delays) == 3:
            done.set()
            return True  # хватит: просим надзор остановиться
        return False

    bridge = BridgeProcess(["bridge.exe", "--profile", "pong"], "hardware", popen, sleep)
    bridge.start()
    assert done.wait(5)
    bridge.stop()
    assert delays == [3.0, 6.0, 12.0]
    assert len(spawned) == 3
    status = bridge.status()
    assert (status.mode, status.ok) == ("hardware", False)
    assert status.error == "Ошибка: нет Bluetooth-адаптера"


def test_running_bridge_is_ok_and_is_stopped_with_the_launcher() -> None:
    block = threading.Event()
    proc = FakeProc(0, "", block)
    started = threading.Event()

    def popen(args: Sequence[str]) -> Any:
        started.set()
        return proc

    bridge = BridgeProcess(["bridge.exe"], "emulate", popen)
    bridge.start()
    assert started.wait(5)
    assert bridge.status().ok
    bridge.stop()
    assert proc.terminated


def test_bridge_that_cannot_start_reports_the_reason() -> None:
    stop_after = threading.Event()

    def popen(args: Sequence[str]) -> Any:
        raise FileNotFoundError("neurotlon-bridge.exe")

    def sleep(delay: float) -> bool:
        stop_after.set()
        return True

    bridge = BridgeProcess(["bridge.exe"], "hardware", popen, sleep)
    bridge.start()
    assert stop_after.wait(5)
    bridge.stop()
    assert "не запустился" in (bridge.status().error or "")


# --- настройки и запуск ---------------------------------------------------------------------


def test_config_accepts_a_bridge_mode_and_rejects_others() -> None:
    base: dict[str, Any] = {
        "server_url": "https://x",
        "token_file": "t",
        "game": {"command": ["g"]},
    }
    assert parse_config(base, Path("/c")).bridge_mode == "external"
    assert (
        parse_config({**base, "bridge": {"mode": "hardware"}}, Path("/c")).bridge_mode == "hardware"
    )
    with pytest.raises(ConfigError):
        parse_config({**base, "bridge": {"mode": "magic"}}, Path("/c"))


def test_runtime_builds_the_bridge_command_from_the_mode(tmp_path: Path) -> None:
    def config(mode: str) -> Any:
        return parse_config(
            {
                "server_url": "https://x",
                "token_file": "t",
                "game": {"command": ["g"]},
                "bridge": {"mode": mode, "port": 9100},
            },
            tmp_path,
        )

    make = StationRuntime._make_bridge
    assert make(config("external"), "pong", "bridge.exe") is None
    assert make(config("hardware"), "pong", "") is None  # моста в установке нет
    hardware = make(config("hardware"), "pong", "bridge.exe")
    assert hardware is not None
    assert hardware._args == [
        "bridge.exe", "--profile", "pong", "--port", "9100",
        "--headless", "--config", str(tmp_path / "bridge.toml"),
    ]  # fmt: skip
    emulate = make(config("emulate"), "darts", "bridge.exe")
    assert emulate is not None
    assert emulate._args == ["bridge.exe", "--profile", "darts", "--port", "9100", "--emulate"]


# --- экран настройки: датчики ---------------------------------------------------------------


def make_service(tmp_path: Path, outcome: DisciplineConfig, scan: Any = None) -> SetupService:
    class Client:
        def get_config(self) -> DisciplineConfig:
            return outcome

        def close(self) -> None:
            pass

    run = scan or runner_returning(completed(json.dumps(SCAN)))
    return SetupService(
        tmp_path / "cfg" / "launcher.toml",
        lambda url, token, ca: Client(),
        sensors=SensorService(tmp_path / "cfg", "bridge.exe", run),
    )


def full_form(tmp_path: Path, **changes: Any) -> SetupForm:
    game = tmp_path / "Game.exe"
    game.write_bytes(b"MZ")
    values: dict[str, Any] = {
        "server_url": "https://h",
        "token": "a-very-long-station-token-0123",
        "game_path": str(game),
        "sensors": "hardware",
        "devices": {},
    }
    values.update(changes)
    return SetupForm(**values)


def test_hardware_mode_needs_a_serial_for_each_role_of_the_discipline(tmp_path: Path) -> None:
    service = make_service(tmp_path, DisciplineConfig("pong", "bci", 240))
    result = service.check(full_form(tmp_path))
    assert result.discipline == "pong"  # дисциплина известна: форма покажет нужные поля
    assert (
        result.error is not None and "левая рука" in result.error and "правая рука" in result.error
    )
    same = full_form(tmp_path, devices={"emg_left": "C1", "emg_right": "c1"})
    assert service.check(same).error == "Один и тот же датчик указан для двух сигналов"
    ok = full_form(tmp_path, devices={"emg_left": "C1", "emg_right": "C2"})
    assert service.check(ok).ok


def test_emulator_and_external_modes_need_no_serials(tmp_path: Path) -> None:
    service = make_service(tmp_path, DisciplineConfig("darts", "bci", 240))
    assert service.check(full_form(tmp_path, sensors="emulate")).ok
    assert service.check(full_form(tmp_path, sensors="")).ok
    assert service.check(full_form(tmp_path, sensors="warp")).error == sensors_mode_error()


def sensors_mode_error() -> str:
    from neurotlon_launcher.setup import SENSORS_MODE

    return SENSORS_MODE


def test_saving_writes_the_bridge_mode_and_bridge_toml(tmp_path: Path) -> None:
    service = make_service(tmp_path, DisciplineConfig("darts", "bci", 240))
    service.save(full_form(tmp_path, devices={"eeg": "BB-1", "emg": "CA-2"}))
    from neurotlon_launcher.config import load_config

    config = load_config(tmp_path / "cfg" / "launcher.toml")
    assert config.bridge_mode == "hardware"
    assert service.sensors.saved_devices() == {"eeg": "BB-1", "emg": "CA-2"}
    defaults = service.defaults()
    assert defaults["sensors"] == "hardware"
    assert defaults["devices"] == {"eeg": "BB-1", "emg": "CA-2"}


def test_a_build_without_a_bridge_refuses_hardware_mode(tmp_path: Path) -> None:
    class Client:
        def get_config(self) -> DisciplineConfig:
            return DisciplineConfig("darts", "bci", 240)

        def close(self) -> None:
            pass

    service = SetupService(tmp_path / "cfg" / "launcher.toml", lambda u, t, c: Client())
    assert service.defaults()["sensors"] == ""
    result = service.check(full_form(tmp_path, devices={"eeg": "BB-1", "emg": "CA-2"}))
    assert result.error is not None and "Мост датчиков" in result.error


def test_scan_action_fills_the_state_and_roles_follow_the_discipline(tmp_path: Path) -> None:
    station = SetupStation(make_service(tmp_path, DisciplineConfig("pong", "bci", 240)))
    assert station.command("sensors_scan", None)
    deadline = threading.Event()
    for _ in range(100):
        state = json.loads(station.body)["state"]
        if state["scan"]["phase"] == "done":
            break
        deadline.wait(0.05)
    assert state["scan"]["phase"] == "done"
    assert [d["serial"] for d in state["scan"]["devices"]] == ["BB-777", ""]
    assert state["sensors_available"] is True
    assert state["roles"] == []  # дисциплина станет известна после проверки подключения


def test_form_from_reads_sensor_fields_and_rejects_bad_ones() -> None:
    form = form_from({"sensors": "hardware", "devices": {"eeg": "BB"}})
    assert form is not None and form.sensors == "hardware" and form.devices == {"eeg": "BB"}
    assert form_from({"devices": "nope"}) is None
    assert form_from({"devices": {"eeg": 5}}) is None
    assert form_from({"devices": {f"r{i}": "x" for i in range(9)}}) is None
    assert form_from({"devices": {"eeg": "x" * 200}}) is None
