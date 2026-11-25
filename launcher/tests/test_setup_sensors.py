"""Экран настройки: живой список датчиков, назначение ролей, проверка и сохранение."""

import json
import subprocess
import threading
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from neurotlon_contracts.sensor_devices import DeviceRef
from neurotlon_launcher import setup_station, texts
from neurotlon_launcher.api import DisciplineConfig
from neurotlon_launcher.sensor_session import SCAN_AUTO_STOP_S, SensorSession
from neurotlon_launcher.sensors import SCAN_JSON_MARK, SensorService
from neurotlon_launcher.setup import SENSORS_DUPLICATE, SetupService
from neurotlon_launcher.setup_station import SetupStation
from neurotlon_launcher.testing_discovery import (
    Clock,
    Spawner,
    devices,
    item,
    link,
    wait_until,
)

TOKEN = "a-very-long-station-token-0123456789"
BB = "AA:00:00:00:00:01"
CA1 = "AA:00:00:00:00:02"
CA2 = "AA:00:00:00:00:03"


def bridge(command: dict[str, Any]) -> list[dict[str, Any]]:
    """Мост-подделка: на «искать» отвечает списком, на «подключить» — готовым подключением."""
    if command["cmd"] == "scan" and command["on"]:
        return [
            devices(
                item(BB, "brainbit", "BrainBit", "BB-1", -50),
                item(CA1, rssi=-60),
                item(CA2, rssi=-70),
            )
        ]
    if command["cmd"] == "connect":
        return [link(command["id"], serial="", battery=80, signal=True, level=0.1)]
    return []


class Client:
    def __init__(self, outcome: DisciplineConfig, gate: threading.Event | None = None) -> None:
        self.outcome = outcome
        self.gate = gate

    def get_config(self) -> DisciplineConfig:
        if self.gate is not None:
            self.gate.wait(5)
        return self.outcome

    def close(self) -> None:
        pass


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        discipline: str = "darts",
        *,
        busy: bool = False,
        gate: threading.Event | None = None,
        runner: Any = None,
    ) -> None:
        self.tmp = tmp_path
        self.clock = Clock()
        self.spawner = Spawner(bridge)
        self.game = tmp_path / "Game.exe"
        self.game.write_bytes(b"MZ")
        outcome = DisciplineConfig(discipline, "bci", 240)
        sensors = (
            SensorService(tmp_path / "cfg", "bridge.exe", runner)
            if runner
            else SensorService(tmp_path / "cfg", "bridge.exe")
        )
        self.service = SetupService(
            tmp_path / "cfg" / "launcher.toml",
            lambda url, token, ca: Client(outcome, gate),
            sensors=sensors,
        )
        session = SensorSession(self.spawner, self.clock, bridge_busy=lambda: busy)
        self.station = SetupStation(self.service, session=session)
        self.session = session

    def form(self, **changes: Any) -> dict[str, Any]:
        base = {
            "server_url": "https://h",
            "token": TOKEN,
            "game_path": str(self.game),
            "sensors": "hardware",
        }
        return base | changes

    def state(self) -> dict[str, Any]:
        state: dict[str, Any] = json.loads(self.station.body)["state"]
        return state

    def sensors(self) -> dict[str, Any]:
        sensors: dict[str, Any] = self.state()["sensors"]
        return sensors

    def row(self, address: str) -> dict[str, Any]:
        return next(d for d in self.sensors()["devices"] if d["id"] == address)

    def wait_phase(self, phase: str) -> dict[str, Any]:
        wait_until(lambda: self.state()["phase"] == phase)
        return self.state()

    def check(self) -> dict[str, Any]:
        assert self.station.command("setup_check", self.form())
        wait_until(lambda: self.state()["phase"] != "checking")
        return self.state()

    def start(self) -> None:
        self.station.start()
        wait_until(lambda: len(self.sensors()["devices"]) >= 3)

    def assign(self, role: str, address: str) -> bool:
        return self.station.command("sensors_assign", {"role": role, "id": address})


@pytest.fixture(autouse=True)
def fast_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_station, "TICK_S", 0.02)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    made = Rig(tmp_path)
    yield made
    made.station.stop()


def test_entering_setup_in_hardware_mode_starts_the_search_by_itself(rig: Rig) -> None:
    assert rig.sensors() == {"phase": "idle", "error": None, "devices": []}
    rig.start()
    sensors = rig.sensors()
    assert sensors["phase"] == "scanning" and sensors["error"] is None
    assert [d["id"] for d in sensors["devices"]] == [BB, CA1, CA2]
    assert rig.state()["sensors_available"] is True
    assert rig.state()["roles"] == []  # роли станут известны после проверки подключения
    assert rig.spawner.last.sent("scan") == [{"cmd": "scan", "on": True}]


def test_the_snapshot_keeps_the_old_scan_block_next_to_the_new_sensors(rig: Rig) -> None:
    state = rig.state()
    assert set(state["scan"]) == {"seconds", "phase", "devices", "error"}
    assert set(state["sensors"]) == {"phase", "error", "devices"}
    assert state["form"]["devices"] == {}  # для прежнего окна: сигнал -> серийный номер


def test_emulator_mode_does_not_search(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "launcher.toml").write_text(
        'server_url = "https://h"\ntoken_file = "station.token"\n'
        '[game]\ncommand = ["g.exe"]\n[bridge]\nmode = "emulate"\n',
        encoding="utf-8",
    )
    made = Rig(tmp_path)
    made.station.start()
    assert made.state()["form"]["sensors"] == "emulate"
    assert made.spawner.processes == []
    assert made.sensors()["phase"] == "idle"
    made.station.stop()


def test_a_running_bridge_blocks_the_search(tmp_path: Path) -> None:
    made = Rig(tmp_path, busy=True)
    made.station.start()
    wait_until(lambda: made.sensors()["phase"] == "error")
    assert made.sensors()["error"] == texts.SENSORS_BRIDGE_BUSY
    assert made.spawner.processes == []
    made.station.stop()


def test_assigning_and_unassigning_need_the_discipline_and_valid_arguments(rig: Rig) -> None:
    rig.start()
    assert not rig.assign("eeg", BB)  # дисциплина ещё неизвестна: ролей нет
    assert not rig.station.command("sensors_frobnicate", None)
    assert rig.check()["phase"] == "form"  # назначения нет
    assert rig.state()["roles"] == ["eeg", "emg"]
    bad_values: list[Any] = [
        None,
        "eeg",
        [],
        {},
        {"role": "eeg"},
        {"role": 5, "id": BB},
        {"role": "eeg", "id": 5},
        {"role": "eeg", "id": ""},
        {"role": "eeg", "id": "x" * 65},
        {"role": "x" * 33, "id": BB},
        {"role": "emg_left", "id": CA1},  # роль не из этой дисциплины
        {"role": "nose", "id": CA1},
        {"role": "emg", "id": "AA:99"},  # такого устройства нет в списке
        {"role": "emg", "id": BB},  # BrainBit не для ЭМГ
    ]
    for value in bad_values:
        assert not rig.station.command("sensors_assign", value), value
    for value in (None, "emg", {}, {"role": 7}, {"role": "x" * 33}, {"role": "emg_left"}):
        assert not rig.station.command("sensors_unassign", value), value
    assert rig.session.assigned() == {}
    assert rig.spawner.last.sent("connect") == []


def test_scan_commands_take_no_arguments_and_work(rig: Rig) -> None:
    rig.start()
    assert rig.station.command("sensors_scan_stop", None)
    wait_until(lambda: rig.sensors()["phase"] == "stopped")
    assert len(rig.sensors()["devices"]) == 3  # список остался
    assert rig.station.command("sensors_scan_start", None)
    wait_until(lambda: rig.sensors()["phase"] == "scanning")


def test_darts_flow_check_save_writes_the_new_bridge_toml_and_frees_the_sensors(rig: Rig) -> None:
    rig.start()
    first = rig.check()
    assert (
        first["phase"] == "form"
        and first["error"] == "Назначьте датчики: ЭЭГ (BrainBit), ЭМГ (Callibri)"
    )
    assert rig.assign("eeg", BB) and rig.assign("emg", CA1)
    wait_until(lambda: rig.row(CA1)["link"] == "connected")
    assert rig.row(CA1)["role"] == "emg" and rig.row(BB)["role"] == "eeg"
    assert [d["role"] for d in rig.sensors()["devices"]][:2] == [
        "eeg",
        "emg",
    ]  # назначенные первыми
    rig.spawner.last.feed(link(CA1, serial="CA-204816", battery=80, signal=True, level=0.5))
    wait_until(lambda: rig.row(CA1)["serial"] == "CA-204816")
    assert rig.check()["phase"] == "ok"
    assert rig.station.command("setup_save", rig.form())
    assert rig.state()["phase"] == "saved"
    assert rig.station.saved.is_set()
    saved = tomllib.loads((rig.tmp / "cfg" / "bridge.toml").read_text(encoding="utf-8"))
    assert saved["devices"]["emg"] == {
        "address": CA1,
        "serial": "CA-204816",
        "name": "Callibri_Red",
        "kind": "callibri",
    }
    assert saved["devices"]["eeg"]["address"] == BB
    assert saved["devices"]["eeg"]["serial"] == "BB-1"
    assert rig.spawner.last.sent("quit") and rig.spawner.last.input_closed
    assert (
        tomllib.loads((rig.tmp / "cfg" / "launcher.toml").read_text(encoding="utf-8"))["bridge"][
            "mode"
        ]
        == "hardware"
    )


def test_the_window_cannot_dictate_the_assignment(rig: Rig) -> None:
    rig.start()
    state = rig.check()
    assert state["phase"] == "form"
    assert rig.station.command("setup_check", rig.form(devices={"eeg": "BB-1", "emg": "CA-2"}))
    wait_until(lambda: rig.state()["phase"] != "checking")
    assert "Назначьте датчики" in rig.state()["error"]


def test_the_same_sensor_for_two_roles_is_refused_on_check(tmp_path: Path) -> None:
    made = Rig(tmp_path, "pong")
    made.start()
    made.check()
    made.session.load_assigned(
        {"emg_left": DeviceRef(address=CA1), "emg_right": DeviceRef(serial="x", address=CA1)}
    )
    assert made.check()["error"] == SENSORS_DUPLICATE
    made.station.stop()


def test_changing_the_assignment_after_the_check_asks_for_a_new_check(rig: Rig) -> None:
    rig.start()
    rig.check()
    rig.assign("eeg", BB)
    rig.assign("emg", CA1)
    assert rig.check()["phase"] == "ok"
    assert rig.station.command("sensors_unassign", {"role": "emg"})
    assert rig.state()["phase"] == "form"  # проверенное устарело
    assert rig.station.command("setup_save", rig.form())
    assert rig.state()["phase"] == "form" and rig.state()["error"] == texts.SETUP_CHECK_FIRST
    assert not rig.station.saved.is_set()
    rig.assign("emg", CA2)
    assert rig.check()["phase"] == "ok"
    assert rig.station.command("setup_save", rig.form())
    assert rig.state()["phase"] == "saved"
    saved = tomllib.loads((rig.tmp / "cfg" / "bridge.toml").read_text(encoding="utf-8"))
    assert saved["devices"]["emg"]["address"] == CA2


def test_the_serial_learned_by_the_probe_does_not_invalidate_the_check(rig: Rig) -> None:
    rig.start()
    rig.check()
    rig.assign("eeg", BB)
    rig.assign("emg", CA1)
    wait_until(lambda: rig.row(CA1)["link"] == "connected")
    assert rig.check()["phase"] == "ok"
    rig.spawner.last.feed(link(CA1, serial="CA-204816", battery=79, signal=True, level=0.3))
    wait_until(lambda: rig.row(CA1)["serial"] == "CA-204816")
    assert rig.state()["phase"] == "ok"
    assert rig.station.command("setup_save", rig.form())
    assert rig.state()["phase"] == "saved"
    saved = tomllib.loads((rig.tmp / "cfg" / "bridge.toml").read_text(encoding="utf-8"))
    assert saved["devices"]["emg"]["serial"] == "CA-204816"


def test_assigning_during_a_check_discards_its_result(tmp_path: Path) -> None:
    gate = threading.Event()
    made = Rig(tmp_path, gate=gate)
    made.start()
    assert made.station.command("setup_check", made.form())
    wait_until(lambda: made.state()["phase"] == "checking")
    gate.set()  # проверка закончится, но назначение к тому времени сменится
    assert made.session.assign("eeg", BB)  # назначение меняется, пока проверка идёт
    wait_until(lambda: made.state()["phase"] != "checking")
    assert made.state()["phase"] == "form"
    made.station.stop()


def test_leftover_roles_of_another_discipline_are_dropped_after_the_check(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "bridge.toml").write_text('[devices]\neeg = "BB-1"\nemg = "CA-1"\n', encoding="utf-8")
    made = Rig(tmp_path, "pong")
    made.start()
    assert set(made.session.assigned()) == {"eeg", "emg"}
    state = made.check()
    assert state["phase"] == "form" and "Назначьте датчики" in state["error"]
    assert made.session.assigned() == {}
    made.station.stop()


def test_saved_assignment_shows_up_and_is_connected_when_found(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "bridge.toml").write_text(
        f'[devices.emg]\naddress = "{CA1}"\nserial = "CA-1"\n', encoding="utf-8"
    )
    made = Rig(tmp_path)
    assert made.sensors()["devices"][0]["id"] == "saved:emg"  # до поиска: назначен, не найден
    made.start()
    wait_until(lambda: made.row(CA1)["link"] == "connected")
    assert made.row(CA1)["role"] == "emg"
    made.station.stop()


def test_search_stops_after_a_minute_and_the_list_stays(rig: Rig) -> None:
    rig.start()
    rig.clock.advance(SCAN_AUTO_STOP_S + 1)
    wait_until(lambda: rig.sensors()["phase"] == "stopped")
    assert len(rig.sensors()["devices"]) == 3
    assert rig.spawner.last.sent("scan")[-1] == {"cmd": "scan", "on": False}


def test_leaving_without_saving_releases_the_sensors(rig: Rig) -> None:
    rig.start()
    rig.check()
    rig.assign("eeg", BB)
    process = rig.spawner.last
    rig.station.stop()
    assert process.sent("quit") and process.input_closed


def test_no_commands_are_accepted_after_saving(rig: Rig) -> None:
    rig.start()
    rig.check()
    rig.assign("eeg", BB)
    rig.assign("emg", CA1)
    rig.check()
    rig.station.command("setup_save", rig.form())
    assert rig.state()["phase"] == "saved"
    assert not rig.assign("emg", CA2)
    assert not rig.station.command("sensors_unassign", {"role": "emg"})
    assert not rig.station.command("sensors_scan_start", None)  # поиск заново не поднимается
    assert len(rig.spawner.processes) == 1


def test_a_build_without_a_bridge_ignores_sensor_commands(tmp_path: Path) -> None:
    service = SetupService(
        tmp_path / "cfg" / "launcher.toml",
        lambda u, t, c: Client(DisciplineConfig("darts", "bci", 240)),
    )
    station = SetupStation(service)
    station.start()
    assert station.command("sensors_scan_start", None) is False
    assert json.loads(station.body)["state"]["sensors"]["phase"] == "idle"
    station.stop()


def completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout, "")


def test_the_old_blocking_scan_still_works_and_pauses_the_new_search(tmp_path: Path) -> None:
    scan = [{"kind": "brainbit", "name": "BrainBit", "serial": "BB-777", "address": "AA:01"}]

    def runner(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        return completed(SCAN_JSON_MARK + json.dumps(scan))

    made = Rig(tmp_path, runner=runner)
    made.start()
    assert made.station.command("sensors_scan", None)
    wait_until(lambda: made.state()["scan"]["phase"] == "done")
    assert [d["serial"] for d in made.state()["scan"]["devices"]] == ["BB-777"]
    assert made.spawner.last.sent("scan")[-1] == {"cmd": "scan", "on": False}
    made.station.stop()


def test_saving_closes_the_search_outside_the_station_lock_and_before_saved(rig: Rig) -> None:
    rig.start()
    rig.check()
    rig.assign("eeg", BB)
    rig.assign("emg", CA1)
    rig.check()
    seen: dict[str, bool] = {}
    real_close = rig.session.close

    def close() -> None:
        seen["lock_free"] = not rig.station._lock.locked()
        seen["saved_set"] = rig.station.saved.is_set()
        real_close()

    rig.session.close = close  # type: ignore[method-assign]
    assert rig.station.command("setup_save", rig.form())
    assert seen == {"lock_free": True, "saved_set": False}
    assert rig.station.saved.is_set()


def test_switching_the_mode_to_the_emulator_releases_bluetooth(rig: Rig) -> None:
    rig.start()
    process = rig.spawner.last
    assert rig.station.command("setup_check", rig.form(sensors="emulate"))
    wait_until(lambda: rig.state()["phase"] != "checking")
    assert process.sent("quit") and process.killed
    assert rig.sensors()["phase"] == "stopped"
    assert rig.station.command("sensors_scan_start", None)  # вернули датчики и ищем снова
    wait_until(lambda: len(rig.spawner.processes) == 2)
