"""Фоновый поиск: `DiscoveryService` на подделке сканера с расписанием и виртуальными часами."""

import threading
import time
from typing import Any

from neurotlon_bridge.devices.base import (
    BluetoothUnavailableError,
    DeviceInfo,
    DeviceKind,
    DeviceNotFoundError,
)
from neurotlon_bridge.devices.discovery import (
    DROP_S,
    MIN_DEVICES_EMIT_S,
    STALE_S,
    DiscoveryService,
)
from neurotlon_bridge.devices.fakes import FakeClock, FakeDevice, FakeRawSensor, FakeScanner
from neurotlon_contracts.discovery import discovery_problem

BB = "AA:00:00:00:00:01"
CA1 = "AA:00:00:00:00:02"
CA2 = "AA:00:00:00:00:03"


def brainbit(at: float = 0.0, vanish: float | None = None, rssi: int | None = -50) -> FakeDevice:
    return FakeDevice(DeviceInfo("brainbit", "BrainBit", "BB-100", BB, rssi), at, vanish)


def callibri(
    address: str = CA1, at: float = 0.0, *, error: str | None = None, vanish: float | None = None
) -> FakeDevice:
    info = DeviceInfo("callibri", "Callibri_Red", "", address, -60)
    return FakeDevice(
        info, at, vanish, connect_error=error, serial_after_connect="CA-" + address[-2:]
    )


class Rig:
    def __init__(self, *devices: FakeDevice, **service_args: Any) -> None:
        self.clock = FakeClock()
        self.scanner = FakeScanner(list(devices), self.clock)
        self.service = DiscoveryService(
            self.scanner, self.clock, self.clock.advance, **service_args
        )
        self.messages: list[dict[str, Any]] = []

    def step(self, seconds: float = 0.5) -> list[dict[str, Any]]:
        self.clock.advance(seconds)
        self.service.poll()
        return self.pull()

    def pull(self) -> list[dict[str, Any]]:
        out = self.service.drain()
        for message in out:
            assert discovery_problem("BridgeMessage", message) is None, message
        self.messages += out
        return out

    def last(self, kind: str) -> dict[str, Any]:
        return next(m for m in reversed(self.messages) if m["type"] == kind)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == kind]

    def raw(self, address: str) -> FakeRawSensor:
        return self.scanner.raws[address]


def emit_signal(raw: FakeRawSensor, amplitude_v: float = 100e-6, rows: int = 250) -> None:
    raw.emit_samples([(amplitude_v if i % 2 else -amplitude_v,) for i in range(rows)])


# --- список ---


def test_nothing_is_sent_until_scan_starts_and_first_message_is_idle_list() -> None:
    rig = Rig(brainbit())
    assert rig.step() == [{"type": "devices", "scanning": False, "items": []}]
    assert rig.scanner.events == []
    assert rig.step(5) == []  # без изменений ничего не шлём


def test_devices_appear_one_by_one_in_first_seen_order() -> None:
    rig = Rig(callibri(CA1, at=3.0), brainbit(at=1.0), callibri(CA2, at=5.0))
    rig.pull()
    rig.service.set_scan(True)
    rig.step()
    assert rig.last("devices")["scanning"] is True
    assert rig.last("devices")["items"] == []
    counts = []
    for _ in range(12):
        rig.step()
        counts.append(len(rig.last("devices")["items"]))
    assert counts[0] <= 1 and counts[-1] == 3
    assert counts == sorted(counts)
    assert [i["id"] for i in rig.last("devices")["items"]] == [BB, CA1, CA2]
    assert rig.scanner.events == ["start"]


def test_two_callibri_with_the_same_name_have_different_ids() -> None:
    rig = Rig(callibri(CA1), callibri(CA2))
    rig.service.set_scan(True)
    rig.step()
    items = rig.last("devices")["items"]
    assert [i["name"] for i in items] == ["Callibri_Red", "Callibri_Red"]
    assert {i["id"] for i in items} == {CA1, CA2}
    assert all(i["id"] == i["address"] and i["serial"] == "" for i in items)


def test_sensors_are_polled_twice_a_second_not_faster() -> None:
    rig = Rig(brainbit())
    rig.service.set_scan(True)
    for _ in range(10):
        rig.clock.advance(0.1)
        rig.service.poll()
    assert rig.scanner.sensors_calls == 2


def test_rssi_changes_below_five_db_are_not_news() -> None:
    rig = Rig(brainbit(rssi=-60))
    rig.service.set_scan(True)
    rig.step()
    rig.scanner.rssi_override[BB] = -63
    assert rig.step(1) == []
    rig.scanner.rssi_override[BB] = -65  # от последнего отправленного (-60) уже 5 дБ
    sent = rig.step(1)
    assert [m["items"][0]["rssi"] for m in sent] == [-65]


def test_devices_are_sent_at_most_twice_a_second() -> None:
    rig = Rig(brainbit(at=0.0), callibri(CA1, at=0.6))
    rig.service.set_scan(True)
    rig.step(0.5)  # BB найден: отправлено
    before = len(rig.of("devices"))
    sent = rig.step(0.5)  # на 1,0 с найден Callibri, но прошло ровно 0,5 с
    assert len(rig.of("devices")) == before + 1
    assert len(sent) == 1
    rig.scanner.rssi_override[BB] = -90
    assert rig.step(0.2) == []  # слишком рано
    assert len(rig.step(MIN_DEVICES_EMIT_S)) == 1  # дождались: отправлено накопленное


def test_device_goes_out_of_range_then_is_dropped() -> None:
    rig = Rig(brainbit(vanish=2.0))
    rig.service.set_scan(True)
    for _ in range(4):
        rig.step()
    assert rig.last("devices")["items"][0]["age_ms"] < 1500
    for _ in range(int(STALE_S) + 1):
        rig.step(1)
    item = rig.last("devices")["items"][0]
    assert item["age_ms"] >= STALE_S * 1000  # UI показывает «нет в эфире»
    for _ in range(int(DROP_S)):
        rig.step(1)
    assert rig.last("devices")["items"] == []


def test_list_does_not_age_while_the_search_is_off_or_paused() -> None:
    rig = Rig(brainbit())
    rig.service.set_scan(True)
    for _ in range(3):
        rig.step()
    rig.service.set_scan(False)
    rig.step(0.6)
    stopped = rig.last("devices")
    assert stopped["scanning"] is False
    for _ in range(int(DROP_S) + 10):  # минута и больше без поиска: список замер
        rig.step(1)
    assert rig.last("devices") is stopped or rig.last("devices")["items"] == stopped["items"]
    assert len(rig.last("devices")["items"]) == 1
    assert rig.last("devices")["items"][0]["age_ms"] < STALE_S * 1000
    rig.service.set_scan(True)  # поиск включили: старение продолжается с того же места
    rig.step()
    assert rig.last("devices")["items"][0]["age_ms"] < STALE_S * 1000


def test_stopping_the_scan_keeps_the_list_and_stops_polling() -> None:
    rig = Rig(brainbit(), callibri())
    rig.service.set_scan(True)
    rig.step()
    calls = rig.scanner.sensors_calls
    rig.service.set_scan(False)
    rig.step(1)
    assert rig.scanner.sensors_calls == calls
    assert rig.last("devices")["scanning"] is False
    assert len(rig.last("devices")["items"]) == 2
    assert rig.scanner.events == ["start", "stop"]


def test_bluetooth_off_is_an_error_and_scan_stays_off() -> None:
    rig = Rig(brainbit())
    rig.scanner.start_error = BluetoothUnavailableError("Bluetooth-адаптер не найден или выключен")
    rig.service.set_scan(True)
    sent = rig.step()
    assert {"type": "error", "message": "Bluetooth-адаптер не найден или выключен"} in sent
    assert rig.last("devices")["scanning"] is False
    assert rig.service.scanning is False
    assert rig.scanner.sensors_calls == 0


def test_scanner_failure_while_polling_stops_the_scan() -> None:
    rig = Rig(brainbit())
    rig.service.set_scan(True)
    rig.step()
    rig.scanner.sensors_error = BluetoothUnavailableError("Bluetooth выключили")
    rig.step()
    assert rig.last("error")["message"] == "Bluetooth выключили"
    assert rig.last("devices")["scanning"] is False
    rig.scanner.sensors_error = RuntimeError("странный сбой SDK")
    rig.service.set_scan(True)
    rig.step()
    assert "странный сбой SDK" in rig.last("error")["message"]


# --- подключение ---


def connected_rig(*devices: FakeDevice, signal: bool = True, **service_args: Any) -> Rig:
    rig = Rig(*devices, **service_args)
    rig.service.set_scan(True)
    rig.step()
    return rig


def connect(rig: Rig, address: str, kind: DeviceKind = "callibri", *, signal: bool = True) -> None:
    def on_start() -> None:
        raw = rig.raw(address)
        raw.emit_battery(87)
        if kind == "callibri":
            raw.emit_electrode(True)
        if signal:
            emit_signal(raw)

    def hook(raw: FakeRawSensor) -> None:
        raw.on_start = on_start

    rig.scanner.on_connected = hook
    rig.service.connect(address, kind)
    rig.pull()


def test_connect_reads_serial_battery_contact_and_signal_and_pauses_search() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    states = [m["state"] for m in rig.of("link")]
    assert states[0] == "connecting" and states[-1] == "connected"
    link = rig.last("link")
    assert link["serial"] == "CA-02"
    assert link["battery"] == 87
    assert link["contact"] is True
    assert link["signal"] is True
    assert link["level"] is not None
    # поиск стоял на паузе на время подключения и снова включён
    assert rig.scanner.events == ["start", "stop", f"connect:{CA1}", "start"]
    # серийный номер, узнанный после подключения, попадает и в список
    rig.step(1)
    assert rig.last("devices")["items"][0]["serial"] == "CA-02"
    assert rig.raw(CA1).start_calls == 1


def test_connect_without_samples_reports_no_signal_after_probe_wait() -> None:
    rig = connected_rig(callibri(CA1))
    started = rig.clock.now
    connect(rig, CA1, signal=False)
    link = rig.last("link")
    assert link["state"] == "connected" and link["signal"] is False and link["level"] is None
    assert rig.clock.now - started >= 2.0  # ждали отсчёты, пока поиск на паузе


def test_level_follows_the_amplitude_of_raw_signal() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    emit_signal(rig.raw(CA1), 20e-6)
    quiet = rig.step(0.3)
    emit_signal(rig.raw(CA1), 250e-6)
    loud = rig.step(0.3)
    levels = [m["level"] for m in quiet + loud if m["type"] == "link"]
    assert levels[0] < 0.2 < 0.8 < levels[-1] <= 1.0


def test_level_updates_are_throttled_and_small_moves_are_ignored() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    rig.messages.clear()
    for _ in range(5):
        emit_signal(rig.raw(CA1), 300e-6)
        rig.clock.advance(0.05)
        rig.pull()
    assert len(rig.of("link")) <= 2
    rig.messages.clear()
    emit_signal(rig.raw(CA1), 300e-6)  # то же значение
    rig.step(1)
    assert rig.of("link") == []


def test_signal_goes_false_when_samples_stop() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    sent = rig.step(3)
    link = [m for m in sent if m["type"] == "link"][-1]
    assert link["signal"] is False and link["level"] is None


def test_brainbit_has_no_contact_and_no_level() -> None:
    rig = connected_rig(brainbit())
    connect(rig, BB, "brainbit")
    link = rig.last("link")
    assert link["state"] == "connected" and link["signal"] is True
    assert link["contact"] is None and link["level"] is None
    assert link["serial"] == "BB-100"


def test_failed_connect_reports_reason_and_resumes_search() -> None:
    rig = connected_rig(callibri(CA1, error="Не удалось подключиться: занято"))
    rig.service.connect(CA1, "callibri")
    rig.pull()
    link = rig.last("link")
    assert link["state"] == "failed" and link["error"] == "Не удалось подключиться: занято"
    assert rig.scanner.events[-2:] == [f"connect:{CA1}", "start"]
    # можно подключиться снова, прежняя неудача не держит устройство
    rig.scanner.devices = [callibri(CA1)]
    rig.service.connect(CA1, "callibri")
    assert rig.pull()[-1]["state"] == "connected"


def test_connect_to_unknown_or_wrong_kind_fails_without_touching_the_scanner() -> None:
    rig = connected_rig(callibri(CA1))
    events = list(rig.scanner.events)
    rig.service.connect("FF:FF", "callibri")
    rig.service.connect(CA1, "brainbit")
    failed = [m for m in rig.pull() if m["type"] == "link"]
    assert [m["state"] for m in failed] == ["failed", "failed"]
    assert all(m["error"] for m in failed)
    assert rig.scanner.events == events


def test_unexpected_sdk_error_gets_a_russian_prefix() -> None:
    rig = connected_rig(callibri(CA1))

    rig.scanner.connect_error = RuntimeError("0x80070005")
    rig.service.connect(CA1, "callibri")
    rig.pull()
    assert rig.last("link")["error"] == "Не удалось подключиться: 0x80070005"


def test_device_not_found_by_scanner_is_reported() -> None:
    rig = connected_rig(callibri(CA1))

    rig.scanner.connect_error = DeviceNotFoundError("Устройство не найдено: включите датчик")
    rig.service.connect(CA1, "callibri")
    rig.pull()
    assert rig.last("link")["error"] == "Устройство не найдено: включите датчик"


def test_start_signal_failure_closes_the_sensor_and_fails() -> None:
    rig = connected_rig(callibri(CA1))

    def break_start(raw: FakeRawSensor) -> None:
        raw.fail_start = True

    rig.scanner.on_connected = break_start
    rig.service.connect(CA1, "callibri")
    rig.pull()
    assert rig.last("link")["state"] == "failed"
    assert rig.raw(CA1).closed


def test_lost_and_back() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    rig.raw(CA1).emit_state(False)
    assert rig.pull()[-1]["state"] == "lost"
    rig.raw(CA1).emit_state(True)
    assert rig.pull()[-1]["state"] == "connected"


def test_connected_device_stays_in_range_even_if_it_stops_advertising() -> None:
    rig = connected_rig(callibri(CA1, vanish=3.0))
    connect(rig, CA1)
    for _ in range(40):
        emit_signal(rig.raw(CA1))
        rig.step(1)
    item = rig.last("devices")["items"][0]
    assert item["age_ms"] == 0


def test_release_frees_the_sensor_and_allows_connecting_again() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    first = rig.raw(CA1)
    rig.service.release(CA1)
    assert first.closed and first.stop_calls == 1
    rig.messages.clear()
    rig.step(2)
    assert rig.of("link") == []
    connect(rig, CA1)
    assert rig.raw(CA1) is not first
    assert rig.last("link")["state"] == "connected"


def test_release_of_an_unknown_id_is_harmless() -> None:
    rig = Rig()
    rig.service.release("nothing")


def test_connecting_twice_does_not_open_the_sensor_twice() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    rig.service.connect(CA1, "callibri")
    assert rig.scanner.events.count(f"connect:{CA1}") == 1


def test_search_is_paused_while_connecting_and_does_not_poll_the_scanner() -> None:
    rig = connected_rig(callibri(CA1))
    gate = threading.Event()
    rig.scanner.connect_gate = gate
    worker = threading.Thread(target=rig.service.connect, args=(CA1, "callibri"))
    worker.start()
    deadline = time.monotonic() + 5
    while f"connect:{CA1}" not in rig.scanner.events and time.monotonic() < deadline:
        time.sleep(0.005)
    calls = rig.scanner.sensors_calls
    rig.clock.advance(5)
    rig.service.poll()
    assert rig.scanner.sensors_calls == calls  # поиск на паузе
    assert rig.scanner.events[-2:] == ["stop", f"connect:{CA1}"]
    gate.set()
    worker.join(5)
    assert not worker.is_alive()
    assert rig.scanner.events[-1] == "start"
    rig.service.poll()
    rig.clock.advance(1)
    rig.service.poll()
    assert rig.scanner.sensors_calls > calls


def test_scan_switched_off_during_connect_is_not_resumed() -> None:
    rig = connected_rig(callibri(CA1))
    gate = threading.Event()
    rig.scanner.connect_gate = gate
    worker = threading.Thread(target=rig.service.connect, args=(CA1, "callibri"))
    worker.start()
    deadline = time.monotonic() + 5
    while f"connect:{CA1}" not in rig.scanner.events and time.monotonic() < deadline:
        time.sleep(0.005)
    rig.service.set_scan(False)
    gate.set()
    worker.join(5)
    assert rig.scanner.events.count("start") == 1
    assert rig.scanner.scanning is False


def test_hanging_connect_times_out_and_the_late_sensor_is_released() -> None:
    rig = connected_rig(callibri(CA1), connect_timeout_s=0.05)
    gate = threading.Event()
    rig.scanner.connect_gate = gate
    rig.service.connect(CA1, "callibri")
    rig.pull()
    link = rig.last("link")
    assert link["state"] == "failed" and "не завершилось" in link["error"]
    assert rig.scanner.events[-1] == "start"  # поиск вернулся, хотя SDK ещё висит
    gate.set()
    deadline = time.monotonic() + 5
    while CA1 not in rig.scanner.raws and time.monotonic() < deadline:
        time.sleep(0.005)
    while not rig.raw(CA1).closed and time.monotonic() < deadline:
        time.sleep(0.005)
    assert rig.raw(CA1).closed  # опоздавший датчик не остаётся занятым


def test_close_releases_everything() -> None:
    rig = connected_rig(callibri(CA1), brainbit())
    connect(rig, CA1)
    connect(rig, BB, "brainbit")
    rig.service.close()
    assert rig.raw(CA1).closed and rig.raw(BB).closed
    assert rig.scanner.closed
    assert rig.scanner.events[-2:] == ["stop", "close"]
    assert rig.service.scanning is False


def test_the_list_never_exceeds_the_schema_limits() -> None:
    from neurotlon_bridge.devices.discovery import MAX_ITEMS

    many = [
        FakeDevice(DeviceInfo("callibri", "n" * 300, "s\x7f" * 300, f"AA:{i:03d}", -30 - i), 0.0)
        for i in range(MAX_ITEMS + 20)
    ]
    rig = Rig(*many)
    rig.service.set_scan(True)
    rig.step()
    items = rig.last("devices")["items"]  # каждое сообщение уже прошло схему в `pull`
    assert len(items) == MAX_ITEMS
    assert {i["id"] for i in items} == {f"AA:{i:03d}" for i in range(MAX_ITEMS)}  # самые сильные
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)  # порядок обнаружения
    assert all(len(i["name"]) == 128 and "\x7f" not in i["serial"] for i in items)


def test_empty_names_fall_back_to_the_kind_and_age_is_capped() -> None:
    rig = Rig(FakeDevice(DeviceInfo("brainbit", "\x7f", "", BB, None), 0.0))
    rig.service.set_scan(True)
    rig.step()
    assert rig.last("devices")["items"][0]["name"] == "brainbit"


def test_scan_error_text_is_never_empty_and_never_over_300() -> None:
    from neurotlon_bridge.devices.base import DeviceError

    rig = Rig(brainbit())
    rig.scanner.start_error = DeviceError("")
    rig.service.set_scan(True)
    rig.step()
    assert rig.last("error")["message"] == "Ошибка поиска датчиков"
    rig.scanner.start_error = DeviceError("я" * 1000)
    rig.service.set_scan(True)
    rig.step()
    assert len(rig.last("error")["message"]) == 300


def test_release_during_connect_frees_the_worker_and_lifts_the_pause() -> None:
    rig = connected_rig(callibri(CA1))
    gate = threading.Event()
    rig.scanner.connect_gate = gate  # SDK «висит» в подключении
    worker = threading.Thread(target=rig.service.connect, args=(CA1, "callibri"))
    worker.start()
    deadline = time.monotonic() + 5
    while f"connect:{CA1}" not in rig.scanner.events and time.monotonic() < deadline:
        time.sleep(0.005)
    started = time.monotonic()
    rig.service.release(CA1)  # «Отключить» во время подключения
    worker.join(3)
    assert not worker.is_alive()
    assert time.monotonic() - started < 2  # не 20 с
    assert rig.scanner.events[-1] == "start"  # пауза поиска снята
    rig.pull()
    assert rig.of("link")[-1]["state"] == "connecting"  # «неудачи» после отмены не шлём
    gate.set()  # SDK наконец ответил: опоздавший датчик освобождается
    deadline = time.monotonic() + 5
    while (CA1 not in rig.scanner.raws or not rig.raw(CA1).closed) and time.monotonic() < deadline:
        time.sleep(0.005)
    assert rig.raw(CA1).closed


def test_connected_devices_stay_in_the_list_when_it_is_cut_to_the_limit() -> None:
    from neurotlon_bridge.devices.discovery import MAX_ITEMS

    many = [
        FakeDevice(DeviceInfo("callibri", "C", "", f"AA:{i:03d}", -30 - i), 0.0)
        for i in range(MAX_ITEMS + 10)
    ]
    rig = connected_rig(*many)
    weakest = f"AA:{MAX_ITEMS + 9:03d}"
    assert weakest not in {i["id"] for i in rig.last("devices")["items"]}
    connect(rig, weakest)
    rig.step(1)
    items = rig.last("devices")["items"]
    assert len(items) == MAX_ITEMS and weakest in {i["id"] for i in items}


def test_closing_a_link_twice_releases_the_sensor_once() -> None:
    rig = connected_rig(callibri(CA1))
    connect(rig, CA1)
    raw = rig.raw(CA1)
    rig.service.release(CA1)
    rig.service.close()
    assert raw.stop_calls == 1
