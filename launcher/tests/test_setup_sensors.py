"""Экран настройки: живой список датчиков, назначение ролей, проверка и сохранение."""

import json
import subprocess
import threading
import time
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from neurotlon_contracts.sensor_devices import DeviceRef
from neurotlon_launcher import setup, setup_station, texts
from neurotlon_launcher.api import DisciplineConfig, Offline, Unauthorized
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
from neurotlon_launcher.web_bridge import CommandRejected

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
    calls = 0  # сколько раз спросили дисциплину (на все клиенты разом)

    def __init__(
        self, outcome: DisciplineConfig | Exception, gate: threading.Event | None = None
    ) -> None:
        self.outcome = outcome
        self.gate = gate

    def get_config(self) -> DisciplineConfig:
        Client.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        if isinstance(self.outcome, Exception):
            raise self.outcome
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
        outcome: DisciplineConfig | Exception | None = None,
    ) -> None:
        Client.calls = 0
        self.tmp = tmp_path
        self.clock = Clock()
        self.spawner = Spawner(bridge)
        self.game = tmp_path / "Game.exe"
        self.game.write_bytes(b"MZ")
        outcome = outcome or DisciplineConfig(discipline, "bci", 240)
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
        self.station = SetupStation(self.service, session=session, clock=self.clock)
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
    assert rig.state()["roles"] == []  # роли станут известны после ввода токена
    assert rig.state()["roles_known"] is False
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
    with pytest.raises(CommandRejected, match="токен станции"):
        rig.assign("eeg", BB)  # дисциплина ещё неизвестна: ролей нет
    assert rig.state()["roles_known"] is False
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


# --- роли определяются сами после ввода токена ---


def settle(rig: Rig, seconds: float) -> None:
    """Сдвинуть виртуальные часы и дать фоновому шагу сработать."""
    rig.clock.advance(seconds)
    time.sleep(0.15)  # несколько тактов фонового шага (TICK_S подменён на 0,02 с)


def test_devices_are_listed_before_any_token_or_check(rig: Rig) -> None:
    rig.start()
    state = rig.state()
    assert [d["id"] for d in state["sensors"]["devices"]] == [BB, CA1, CA2]
    assert state["roles_known"] is False and state["phase"] == "form"
    assert Client.calls == 0


def test_token_is_checked_automatically_after_a_pause_and_roles_become_known(rig: Rig) -> None:
    rig.start()
    assert rig.station.command("setup_form", rig.form())
    settle(rig, 0.5)
    assert Client.calls == 0 and rig.state()["roles_known"] is False  # пауза ещё не прошла
    settle(rig, 0.3)
    wait_until(lambda: rig.state()["roles_known"])
    state = rig.state()
    assert state["roles"] == ["eeg", "emg"] and state["discipline"] == "darts"
    assert state["phase"] == "form" and state["error"] is None
    assert Client.calls == 1
    assert rig.assign("eeg", BB)  # теперь назначение принимается
    assert [d["role"] for d in rig.sensors()["devices"]][:1] == ["eeg"]


def test_every_keystroke_restarts_the_pause_and_checks_once(rig: Rig) -> None:
    rig.start()
    for end in (20, 25, 30, len(TOKEN)):
        assert rig.station.command("setup_form", rig.form(token=TOKEN[:end]))
        settle(rig, 0.3)
    assert Client.calls == 0  # каждая правка отодвигает проверку
    settle(rig, 0.5)
    wait_until(lambda: rig.state()["roles_known"])
    assert Client.calls == 1
    assert rig.station.command("setup_form", rig.form(game_path="другое"))  # токен тот же
    settle(rig, 1.0)
    assert Client.calls == 1 and rig.state()["roles_known"] is True


def test_changing_the_token_forgets_the_roles_until_it_is_checked_again(rig: Rig) -> None:
    rig.start()
    assert rig.station.command("setup_form", rig.form())
    settle(rig, 1.0)
    wait_until(lambda: rig.state()["roles_known"])
    assert rig.station.command("setup_form", rig.form(token=TOKEN + "9"))
    assert rig.state()["roles_known"] is False and rig.state()["roles"] == []
    settle(rig, 1.0)
    wait_until(lambda: rig.state()["roles_known"])
    assert Client.calls == 2


def test_wrong_token_shows_the_error_and_keeps_the_device_list(tmp_path: Path) -> None:
    made = Rig(tmp_path, outcome=Unauthorized(401, "unauthorized"))
    made.start()
    assert made.station.command("setup_form", made.form())
    settle(made, 1.0)
    wait_until(lambda: made.state()["error"] is not None)
    state = made.state()
    assert state["error"] == setup.UNAUTHORIZED and state["roles_known"] is False
    assert [d["id"] for d in state["sensors"]["devices"]] == [BB, CA1, CA2]
    assert made.sensors()["phase"] == "scanning"  # поиск продолжается
    assert made.station.command("setup_form", made.form(token=TOKEN + "x"))
    assert made.state()["error"] is None  # правка токена убирает старую ошибку
    made.station.stop()


def test_short_token_or_plain_http_address_is_not_checked(rig: Rig) -> None:
    rig.start()
    assert rig.station.command("setup_form", rig.form(token="short"))
    assert rig.station.command("setup_form", rig.form(server_url="http://h"))
    settle(rig, 2.0)
    assert Client.calls == 0
    assert rig.state()["error"] is None and rig.state()["roles_known"] is False


def test_saved_token_is_checked_automatically_when_setup_opens(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "launcher.toml").write_text(
        'server_url = "https://h"\ntoken_file = "station.token"\n'
        '[game]\ncommand = ["g.exe"]\n[bridge]\nmode = "hardware"\n',
        encoding="utf-8",
    )
    (cfg / "station.token").write_text(TOKEN + "\n", encoding="utf-8")
    made = Rig(tmp_path)
    made.station.start()
    assert made.state()["roles_known"] is False
    settle(made, 1.0)
    wait_until(lambda: made.state()["roles_known"])
    assert made.state()["roles"] == ["eeg", "emg"] and Client.calls == 1
    made.station.stop()


def test_manual_check_still_works_and_is_not_repeated_by_the_form_command(rig: Rig) -> None:
    rig.start()
    assert rig.check()["roles_known"] is True
    assert Client.calls == 1
    assert rig.station.command("setup_form", rig.form())
    settle(rig, 1.0)
    assert Client.calls == 1


def test_full_check_is_not_overwritten_by_a_late_probe_answer(rig: Rig) -> None:
    started, release = threading.Event(), threading.Event()

    def slow_probe(form: Any) -> setup.CheckResult:
        started.set()
        release.wait(5)
        return setup.CheckResult(None, "старый ответ")

    rig.service.probe = slow_probe  # type: ignore[method-assign]
    rig.start()
    assert rig.station.command("setup_form", rig.form())
    settle(rig, 1.0)
    assert started.wait(5)
    assert rig.station.command("setup_check", rig.form(sensors=""))
    wait_until(lambda: rig.state()["phase"] == "ok")
    release.set()
    time.sleep(0.2)
    state = rig.state()
    assert state["phase"] == "ok" and state["error"] is None and state["roles_known"] is True


def test_setup_form_during_check_or_after_saving_is_ignored_quietly(tmp_path: Path) -> None:
    gate = threading.Event()
    made = Rig(tmp_path, gate=gate)
    made.start()
    assert made.station.command("setup_check", made.form(sensors=""))
    assert made.state()["phase"] == "checking"
    assert made.station.command("setup_form", made.form(token=TOKEN + "z"))  # 204, без эффекта
    gate.set()
    wait_until(lambda: made.state()["phase"] == "ok")
    assert made.state()["roles_known"] is True
    assert made.station.command("setup_save", made.form(sensors=""))
    assert made.state()["phase"] == "saved"
    assert made.station.command("setup_form", made.form(token=TOKEN + "q"))
    assert made.state()["roles_known"] is True
    made.station.stop()


def test_probe_is_retried_once_after_a_network_error(tmp_path: Path) -> None:
    made = Rig(tmp_path, outcome=Offline("нет сети"))
    made.start()
    assert made.station.command("setup_form", made.form())
    settle(made, 1.0)
    wait_until(lambda: Client.calls == 1)
    time.sleep(0.1)
    assert made.state()["error"] is None  # первая ошибка не показывается
    settle(made, 4.0)
    assert Client.calls == 1
    settle(made, 1.5)
    wait_until(lambda: Client.calls == 2)
    wait_until(lambda: made.state()["error"] == setup.OFFLINE)
    settle(made, 20.0)
    assert Client.calls == 2  # дальше сами не мучаем сеть
    made.station.stop()


def test_probe_and_check_threads_do_not_keep_the_process_alive(rig: Rig) -> None:
    rig.start()
    assert rig.station.command("setup_form", rig.form())
    settle(rig, 1.0)
    rig.check()
    for thread in threading.enumerate():
        if thread.name in {"setup-probe", "setup-check"}:
            assert thread.daemon
