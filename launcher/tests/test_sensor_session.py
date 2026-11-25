"""`SensorSession`: живой список, назначение ролей, автоостановка; мост подменён."""

from typing import Any

from neurotlon_contracts.sensor_devices import DeviceRef
from neurotlon_launcher import texts
from neurotlon_launcher.sensor_session import SCAN_AUTO_STOP_S, SensorSession
from neurotlon_launcher.testing_discovery import (
    Clock,
    Spawner,
    devices,
    item,
    link,
    wait_until,
)

BB = "AA:00:00:00:00:01"
CA1 = "AA:00:00:00:00:02"
CA2 = "AA:00:00:00:00:03"


def make(
    spawner: Spawner | None = None, clock: Clock | None = None, busy: bool = False
) -> tuple[SensorSession, Spawner, Clock]:
    spawner = spawner or Spawner()
    clock = clock or Clock()
    return SensorSession(spawner, clock, bridge_busy=lambda: busy), spawner, clock


def started(session: SensorSession, spawner: Spawner, *items: dict[str, Any]) -> None:
    assert session.scan_start()
    spawner.last.feed(devices(*items))
    wait_until(lambda: {i["id"] for i in items} <= {d["id"] for d in session.view()["devices"]})


def rows(session: SensorSession) -> dict[str, dict[str, Any]]:
    return {d["id"]: d for d in session.view()["devices"]}


def test_idle_session_has_an_empty_view_and_no_process() -> None:
    session, spawner, _ = make()
    assert session.view() == {"phase": "idle", "error": None, "devices": []}
    assert spawner.processes == []


def test_a_session_without_a_bridge_is_unavailable() -> None:
    session = SensorSession(None)
    assert not session.available
    assert not session.scan_start()
    assert session.view()["phase"] == "idle"


def test_scan_start_spawns_the_process_and_turns_the_search_on() -> None:
    session, spawner, _ = make()
    assert session.scan_start()
    wait_until(lambda: bool(spawner.last.sent("scan")))
    assert spawner.last.sent("scan") == [{"cmd": "scan", "on": True}]
    assert session.view()["phase"] == "scanning"
    assert session.view()["error"] is None


def test_devices_keep_the_bridge_order_and_carry_all_fields() -> None:
    session, spawner, _ = make()
    started(
        session,
        spawner,
        item(BB, "brainbit", "BrainBit", "BB-1", -50),
        item(CA1, rssi=-70),
        item(CA2, rssi=None),
    )
    assert list(rows(session)) == [BB, CA1, CA2]
    assert rows(session)[BB] == {
        "id": BB,
        "name": "BrainBit",
        "kind": "brainbit",
        "serial": "BB-1",
        "address": BB,
        "rssi": -50,
        "in_range": True,
        "age_s": 0,
        "role": None,
        "link": None,
        "battery": None,
        "contact": None,
        "signal": False,
        "level": None,
        "error": None,
    }
    assert rows(session)[CA2]["rssi"] is None
    spawner.last.feed(devices(item(CA1), item(BB, "brainbit", "BrainBit", "BB-1")))
    wait_until(lambda: len(rows(session)) == 2)
    assert list(rows(session)) == [CA1, BB]  # порядок задаёт мост


def test_age_counts_up_only_for_devices_that_left_the_air() -> None:
    session, spawner, clock = make()
    started(session, spawner, item(CA1, age_ms=300), item(CA2, age_ms=20000))
    assert rows(session)[CA1]["in_range"] is True and rows(session)[CA1]["age_s"] == 0
    assert rows(session)[CA2]["in_range"] is False and rows(session)[CA2]["age_s"] == 20
    clock.advance(5)
    assert rows(session)[CA1]["in_range"] is True  # мост не слал: значит, всё ещё видно
    assert rows(session)[CA2]["age_s"] == 25
    session.scan_stop()
    clock.advance(30)
    assert rows(session)[CA2]["age_s"] == 25  # поиск стоит: возраст замер, как и список


def test_assign_connects_and_the_link_updates_the_view() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(BB, "brainbit", "BB-1"), item(CA1))
    version = session.version
    assert session.assign("emg", CA1)
    assert session.version == version + 1
    wait_until(lambda: bool(spawner.last.sent("connect")))
    assert spawner.last.sent("connect") == [{"cmd": "connect", "id": CA1, "kind": "callibri"}]
    row = rows(session)[CA1]
    assert row["role"] == "emg" and row["link"] == "connecting"
    spawner.last.feed(
        link(CA1, serial="CA-204816", battery=87, contact=True, signal=True, level=0.52)
    )
    wait_until(lambda: rows(session)[CA1]["link"] == "connected")
    row = rows(session)[CA1]
    assert (row["serial"], row["battery"], row["contact"], row["signal"], row["level"]) == (
        "CA-204816",
        87,
        True,
        True,
        0.52,
    )
    # серийный номер из пробы становится вторым ключом назначения
    assert session.assigned()["emg"] == DeviceRef(CA1, "CA-204816", "Callibri_Red", "callibri")


def test_assigned_devices_go_first_in_role_order_even_when_not_found() -> None:
    session, spawner, _ = make()
    session.load_assigned(
        {
            "emg": DeviceRef(serial="CA-OLD"),  # из bridge.toml старого вида; в эфире нет
            "eeg": DeviceRef(address=BB, name="BrainBit", kind="brainbit"),
        }
    )
    started(session, spawner, item(CA1), item(BB, "brainbit", "BrainBit"))
    view = session.view()["devices"]
    assert [d["role"] for d in view] == ["eeg", "emg", None]
    assert [d["id"] for d in view] == [BB, "saved:emg", CA1]
    missing = view[1]
    assert (
        missing["in_range"] is False and missing["link"] is None and missing["serial"] == "CA-OLD"
    )
    assert missing["name"] == "Callibri" and missing["kind"] == "callibri"


def test_a_saved_serial_finds_its_device_and_learns_the_address() -> None:
    session, spawner, _ = make()
    session.load_assigned({"emg": DeviceRef(serial="ca-1")})
    started(session, spawner, item(CA1, serial="CA-1"))
    assert rows(session)[CA1]["role"] == "emg"
    assert session.assigned()["emg"].address == CA1


def test_saved_assignment_is_connected_once_when_the_device_shows_up() -> None:
    session, spawner, _ = make()
    session.load_assigned({"emg": DeviceRef(address=CA1, serial="CA-1", kind="callibri")})
    started(session, spawner, item(CA1))
    wait_until(lambda: bool(spawner.last.sent("connect")))
    spawner.last.feed(devices(item(CA1)), devices(item(CA1)))
    wait_until(lambda: len(rows(session)) == 1)
    assert len(spawner.last.sent("connect")) == 1


def test_assign_rejects_unknown_devices_roles_and_the_wrong_kind() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(BB, "brainbit", "BrainBit"), item(CA1))
    assert not session.assign("emg", "nothing")
    assert not session.assign("emg", BB)  # BrainBit для ЭМГ не годится
    assert not session.assign("eeg", CA1)
    assert not session.assign("nose", CA1)
    assert not session.assign("emg", "")
    assert not session.assign("emg", "x" * 65)
    assert session.assigned() == {}
    assert spawner.last.sent("connect") == []


def test_assigning_a_device_to_another_role_moves_it_without_reconnecting() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1), item(CA2))
    session.assign("emg_left", CA1)
    spawner.last.feed(link(CA1, serial="CA-1"))
    wait_until(lambda: rows(session)[CA1]["link"] == "connected")
    assert session.assign("emg_right", CA1)  # тот же датчик в другую роль
    assert list(session.assigned()) == ["emg_right"]
    assert len(spawner.last.sent("connect")) == 1  # связь держится, повторного подключения нет
    assert spawner.last.sent("release") == []
    assert rows(session)[CA1]["role"] == "emg_right"
    assert rows(session)[CA1]["link"] == "connected"


def test_replacing_the_device_of_a_role_releases_the_old_one() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1), item(CA2))
    session.assign("emg", CA1)
    spawner.last.feed(link(CA1))
    wait_until(lambda: rows(session)[CA1]["link"] == "connected")
    assert session.assign("emg", CA2)
    assert spawner.last.sent("release") == [{"cmd": "release", "id": CA1}]
    assert rows(session)[CA1]["role"] is None and rows(session)[CA1]["link"] is None
    assert rows(session)[CA2]["role"] == "emg"


def test_unassign_releases_the_device_and_keeps_it_in_the_list() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    spawner.last.feed(link(CA1, serial="CA-1"))
    wait_until(lambda: rows(session)[CA1]["link"] == "connected")
    version = session.version
    assert session.unassign("emg")
    assert session.version == version + 1
    assert spawner.last.sent("release") == [{"cmd": "release", "id": CA1}]
    assert session.assigned() == {}
    assert rows(session)[CA1]["role"] is None and rows(session)[CA1]["link"] is None
    assert session.unassign("emg")  # повтор безвреден и версию не двигает
    assert session.version == version + 1
    assert not session.unassign("nose")


def test_a_failed_link_shows_its_reason_and_can_be_retried() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    spawner.last.feed(link(CA1, "failed", error="Не удалось подключиться: занято"))
    wait_until(lambda: rows(session)[CA1]["link"] == "failed")
    assert rows(session)[CA1]["error"] == "Не удалось подключиться: занято"
    assert session.assign("emg", CA1)  # «Подключить» ещё раз
    assert len(spawner.last.sent("connect")) == 2


def test_stale_link_messages_for_released_devices_are_ignored() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    spawner.last.feed(link(CA1, serial="CA-1", battery=50))
    spawner.last.feed(devices(item(CA1)))
    wait_until(lambda: spawner.last._out.empty())
    assert rows(session)[CA1]["link"] is None


def test_scan_stop_keeps_the_list_and_scan_start_restarts_the_search() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    assert session.scan_stop()
    assert session.view()["phase"] == "stopped"
    assert len(session.view()["devices"]) == 1
    assert spawner.last.sent("scan")[-1] == {"cmd": "scan", "on": False}
    assert session.scan_start()
    assert len(spawner.processes) == 1  # процесс прежний
    ons = [c["on"] for c in spawner.last.sent("scan")]
    assert ons == [True, False, False, True]  # «Искать снова»: перезапуск поиска
    assert session.view()["phase"] == "scanning"


def test_search_stops_by_itself_after_a_minute_without_presses() -> None:
    session, spawner, clock = make()
    started(session, spawner, item(CA1))
    clock.advance(SCAN_AUTO_STOP_S - 1)
    session.tick()
    assert session.view()["phase"] == "scanning"
    clock.advance(2)
    session.tick()
    assert session.view()["phase"] == "stopped"
    assert spawner.last.sent("scan")[-1] == {"cmd": "scan", "on": False}
    assert len(session.view()["devices"]) == 1  # список остаётся
    session.tick()
    assert len(spawner.last.sent("scan")) == 2  # повторно не останавливает


def test_a_press_postpones_the_auto_stop() -> None:
    session, spawner, clock = make()
    started(session, spawner, item(CA1), item(CA2))
    clock.advance(50)
    session.assign("emg", CA1)  # нажатие
    clock.advance(50)
    session.tick()
    assert session.view()["phase"] == "scanning"
    clock.advance(11)
    session.tick()
    assert session.view()["phase"] == "stopped"
    session.scan_start()  # «Искать снова» запускает вручную и снова на минуту
    clock.advance(59)
    session.tick()
    assert session.view()["phase"] == "scanning"


def test_process_crash_is_an_error_and_search_again_respawns() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    spawner.last.exit(3, "Ошибка: не загрузился NeuroSDK")
    wait_until(lambda: session.view()["phase"] == "error")
    view = session.view()
    assert view["error"] == "Ошибка: не загрузился NeuroSDK"
    assert rows(session)[CA1]["link"] is None  # связей не осталось
    assert session.assigned()["emg"].address == CA1  # а назначение осталось
    assert session.scan_start()
    assert len(spawner.processes) == 2
    wait_until(lambda: bool(spawner.last.sent("scan")))
    assert session.view()["phase"] == "scanning" and session.view()["error"] is None


def test_bridge_error_message_is_shown_and_search_again_recovers() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    spawner.last.feed({"type": "error", "message": "Bluetooth-адаптер не найден или выключен"})
    wait_until(lambda: session.view()["phase"] == "error")
    assert session.view()["error"] == "Bluetooth-адаптер не найден или выключен"
    assert session.scan_start()
    assert len(spawner.processes) == 1  # процесс жив: просто включаем поиск заново
    assert session.view()["phase"] == "scanning" and session.view()["error"] is None


def test_running_bridge_blocks_the_search_with_a_hint() -> None:
    session, spawner, _ = make(busy=True)
    assert session.scan_start()
    view = session.view()
    assert view["phase"] == "error" and view["error"] == texts.SENSORS_BRIDGE_BUSY
    assert "уже запущен" in view["error"]
    assert spawner.processes == []


def test_spawn_failure_is_reported() -> None:
    def broken(_listener: Any) -> Any:
        raise FileNotFoundError("neurotlon-bridge.exe не найден")

    session = SensorSession(broken)
    assert session.scan_start()
    assert session.view()["phase"] == "error"
    assert "neurotlon-bridge.exe не найден" in session.view()["error"]


def test_messages_from_a_replaced_process_are_ignored() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    first = spawner.last
    first.exit(1, "упал")
    wait_until(lambda: session.view()["phase"] == "error")
    session.scan_start()
    first.feed(devices(item(CA2)))  # позднее сообщение прежнего процесса
    spawner.last.feed(devices(item(BB, "brainbit", "BrainBit")))
    wait_until(lambda: BB in rows(session))
    assert CA2 not in rows(session) and CA1 not in rows(session)


def test_close_releases_the_sensors_and_ends_the_process() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    process = spawner.last
    session.close()
    assert process.sent("quit") and process.input_closed
    assert session.view()["phase"] == "stopped"
    assert session.assigned()["emg"].address == CA1  # назначение для записи остаётся
    session.close()  # повторно безопасно


def test_keep_roles_forgets_roles_of_another_discipline() -> None:
    session, _, _ = make()
    session.load_assigned({"eeg": DeviceRef(serial="BB"), "emg": DeviceRef(serial="CA")})
    version = session.version
    session.keep_roles(("emg_left", "emg_right"))
    assert session.assigned() == {}
    assert session.version == version  # проверенное из-за этого не устаревает


def test_double_scan_start_runs_one_process() -> None:
    import threading
    import time

    calls: list[int] = []

    def slow_busy() -> bool:
        calls.append(1)
        time.sleep(0.1)  # окно, в которое влезает второй вызов
        return False

    spawner = Spawner()
    session = SensorSession(spawner, Clock(), bridge_busy=slow_busy)
    threads = [threading.Thread(target=session.scan_start) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(spawner.processes) == 1
    assert len(calls) == 1
    assert session.view()["phase"] == "scanning"


def test_a_closed_session_never_starts_a_process() -> None:
    session, spawner, _ = make()
    session.close()
    assert not session.scan_start()
    assert spawner.processes == []
    assert session.view()["phase"] == "idle"


def test_close_waits_for_a_start_in_progress_and_leaves_no_orphan() -> None:
    import threading
    import time

    release = threading.Event()

    def busy() -> bool:
        release.wait(5)
        return False

    spawner = Spawner()
    session = SensorSession(spawner, Clock(), bridge_busy=busy)
    starter = threading.Thread(target=session.scan_start)
    starter.start()
    time.sleep(0.05)
    closer = threading.Thread(target=session.close)
    closer.start()
    time.sleep(0.05)
    release.set()
    starter.join(5)
    closer.join(5)
    assert len(spawner.processes) == 1
    assert spawner.last.sent("quit") and spawner.last.killed  # запущенный процесс закрыт


def test_long_exit_error_is_cut() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    spawner.last.exit(3, "Ошибка: " + "я" * 5000)
    wait_until(lambda: session.view()["phase"] == "error")
    assert len(session.view()["error"]) == 300


def test_crashed_process_is_closed_at_once() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    first = spawner.last
    first.exit(3, "упал")
    wait_until(lambda: session.view()["phase"] == "error")
    wait_until(lambda: first.killed)  # Job Object и ручки не ждут следующего запуска


def test_stale_saved_device_is_not_connected_blindly() -> None:
    session, spawner, _ = make()
    session.load_assigned({"emg": DeviceRef(address=CA1, serial="CA-1", kind="callibri")})
    started(session, spawner, item(CA1, age_ms=20000))
    spawner.last.feed(devices(item(CA1, age_ms=20000)))
    wait_until(lambda: rows(session)[CA1]["in_range"] is False)
    assert spawner.last.sent("connect") == []
    spawner.last.feed(devices(item(CA1, age_ms=100)))  # вернулся в эфир
    wait_until(lambda: bool(spawner.last.sent("connect")))


def test_age_does_not_grow_while_the_search_was_stopped() -> None:
    session, spawner, clock = make()
    started(session, spawner, item(CA2, age_ms=20000))
    clock.advance(5)
    assert rows(session)[CA2]["age_s"] == 25
    session.scan_stop()
    clock.advance(500)  # простой
    session.scan_start()
    assert rows(session)[CA2]["age_s"] == 25  # простой в возраст не вошёл
    clock.advance(3)
    assert rows(session)[CA2]["age_s"] == 28


def test_connect_again_after_the_link_was_lost_or_never_made() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    spawner.last.feed(link(CA1, "lost", serial="CA-1"))
    wait_until(lambda: rows(session)[CA1]["link"] == "lost")
    assert session.assign("emg", CA1)  # «Подключить» ещё раз
    assert spawner.last.sent("release") == [{"cmd": "release", "id": CA1}]
    assert len(spawner.last.sent("connect")) == 2
    session.unassign("emg")
    session.load_assigned({"emg": DeviceRef(address=CA1, kind="callibri")})  # из файла, связи нет
    session.scan_stop()
    assert session.assign("emg", CA1)
    assert len(spawner.last.sent("connect")) == 3


def test_halt_releases_everything_but_search_can_start_again() -> None:
    session, spawner, _ = make()
    started(session, spawner, item(CA1))
    session.assign("emg", CA1)
    first = spawner.last
    session.halt()
    assert first.sent("quit") and first.killed
    assert session.assigned()["emg"].address == CA1
    assert session.view()["phase"] == "stopped"
    assert session.scan_start()  # режим вернули на датчики
    assert len(spawner.processes) == 2
