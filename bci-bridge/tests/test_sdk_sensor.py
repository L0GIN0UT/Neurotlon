import threading
import time
from typing import Any

from neurotlon_bridge.devices.base import DeviceError
from neurotlon_bridge.devices.fakes import FakeBackend, FakeClock, FakeRawSensor
from neurotlon_bridge.devices.sdk_sensor import SdkSensor


def make(kind: str = "callibri") -> tuple[SdkSensor, FakeRawSensor, FakeBackend, FakeClock]:
    raw = FakeRawSensor(kind, "SN1")  # type: ignore[arg-type]
    backend = FakeBackend([raw])
    clock = FakeClock(100.0)
    return SdkSensor("SN1", kind, backend, clock), raw, backend, clock  # type: ignore[arg-type]


def test_connect_starts_signal_and_reports_connected() -> None:
    sensor, raw, _, _ = make()
    assert sensor.state == "disconnected"
    sensor.connect()
    assert sensor.state == "connected"
    assert raw.start_calls == 1
    assert sensor.battery == 80
    assert sensor.sampling_hz == 1000


def test_connect_async_goes_through_connecting() -> None:
    sensor, raw, _, _ = make()
    gate = threading.Event()
    original = raw.start_signal

    def slow_start() -> None:
        gate.wait(2)
        original()

    raw.start_signal = slow_start  # type: ignore[method-assign]
    sensor.connect_async()
    assert sensor.state == "connecting"
    gate.set()
    deadline = time.monotonic() + 2
    while sensor.state != "connected" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sensor.state == "connected"


def test_samples_are_buffered_and_drained() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    raw.emit_samples([[1e-6], [2e-6]])
    clock.advance(0.02)
    raw.emit_samples([[3e-6]])
    batches = sensor.drain()
    assert [round(t, 2) for t, _ in batches] == [100.0, 100.02]
    assert batches[0][1].shape == (2, 1)
    assert sensor.drain() == []


def test_eeg_rows_keep_four_columns() -> None:
    sensor, raw, _, _ = make("brainbit")
    sensor.connect()
    raw.emit_samples([[1e-6, 2e-6, 3e-6, 4e-6]])
    assert sensor.drain()[0][1].shape == (1, 4)


def test_bad_callback_data_does_not_raise() -> None:
    sensor, raw, _, _ = make()
    sensor.connect()
    raw.emit_samples([[1.0], [1.0, 2.0]])  # рваный массив
    raw.emit_samples([])
    assert sensor.drain() == []
    assert sensor.callback_errors >= 1


def test_exception_in_callback_does_not_propagate() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()

    def broken() -> float:
        raise RuntimeError("часы сломались")

    sensor._clock = broken
    raw.emit_samples([[1e-6]])  # не должно бросить
    assert sensor.callback_errors == 1
    sensor._clock = clock


def test_samples_before_start_are_ignored() -> None:
    sensor, _, backend, _ = make()
    handlers = backend.open_sensor("SN1", "callibri", sensor._handlers()).handlers
    assert handlers is not None
    handlers.on_samples([[1.0]])
    assert sensor.drain() == []


def test_failed_connect_sets_error_and_stays_disconnected() -> None:
    sensor = SdkSensor("NOPE", "callibri", FakeBackend(), FakeClock())
    sensor.connect()
    assert sensor.state == "disconnected"
    assert "не найден" in sensor.error


def test_failed_start_signal_releases_sensor() -> None:
    sensor, raw, _, _ = make()
    raw.fail_start = True
    sensor.connect()
    assert sensor.state == "disconnected"
    assert raw.closed


def test_poll_retries_connection_after_interval() -> None:
    raw = FakeRawSensor("callibri", "SN1")
    backend = FakeBackend()
    clock = FakeClock()
    sensor = SdkSensor("SN1", "callibri", backend, clock, retry_interval_s=3.0)
    sensor.connect()
    assert sensor.state == "disconnected"
    clock.advance(1.0)
    sensor.poll()
    assert backend.open_calls == ["SN1"]  # ещё рано
    backend.sensors["SN1"] = raw
    clock.advance(3.0)
    sensor.poll()
    deadline = time.monotonic() + 2
    while sensor.state != "connected" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sensor.state == "connected"


def test_start_signal_resent_after_silence() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    raw.emit_samples([[1e-6]])
    clock.advance(1.9)
    assert not sensor.poll()
    assert raw.start_calls == 1
    clock.advance(0.2)  # 2,1 с тишины
    assert sensor.poll()
    assert raw.start_calls == 2
    clock.advance(1.0)
    assert not sensor.poll()  # не чаще раза в 3 с
    clock.advance(2.5)
    assert sensor.poll()
    assert raw.start_calls == 3


def test_no_restart_while_data_flows() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    for _ in range(100):
        clock.advance(0.1)
        raw.emit_samples([[1e-6]])
        assert not sensor.poll()
    assert raw.start_calls == 1


def test_restart_when_no_data_ever_arrived() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    clock.advance(2.5)
    assert sensor.poll()
    assert raw.start_calls == 2


def test_failed_restart_is_recorded_not_raised() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    raw.fail_start = True
    clock.advance(5.0)
    assert not sensor.poll()
    assert "StartSignal" in sensor.error


def test_state_callbacks_track_reconnects() -> None:
    sensor, raw, _, clock = make()
    sensor.connect()
    raw.emit_samples([[1e-6]])
    raw.emit_state(False)
    assert sensor.state == "disconnected"
    assert sensor.reconnects == 0
    assert not sensor.poll()  # SDK переподключается сам, новое подключение не нужно
    clock.advance(10.0)
    raw.emit_state(True)
    assert sensor.state == "connected"
    assert sensor.reconnects == 1
    # после возврата связи тишина отсчитывается заново
    assert not sensor.poll()
    clock.advance(2.5)
    assert sensor.poll()


def test_battery_and_electrode_callbacks() -> None:
    sensor, raw, _, _ = make()
    sensor.connect()
    assert sensor.electrode_ok is None
    raw.emit_electrode(False)
    assert sensor.electrode_ok is False
    assert raw.handlers is not None
    raw.handlers.on_battery(55)
    assert sensor.battery == 55


def test_close_stops_and_releases() -> None:
    sensor, raw, _, _ = make()
    sensor.connect()
    sensor.close()
    assert raw.stop_calls == 1
    assert raw.closed
    assert sensor.state == "disconnected"
    raw.emit_samples([[1e-6]])
    assert sensor.drain() == []
    sensor.connect_async()  # после close не оживает
    assert sensor.state == "disconnected"


def test_close_survives_sdk_errors() -> None:
    sensor, raw, _, _ = make()
    sensor.connect()

    def boom() -> None:
        raise DeviceError("нет")

    raw.stop_signal = boom  # type: ignore[method-assign]
    raw.close = boom  # type: ignore[method-assign]
    sensor.close()
    assert sensor.state == "disconnected"


def test_electrode_state_is_reset_on_new_connection() -> None:
    sensor, raw, _, _ = make()
    sensor.connect()
    raw.emit_electrode(False)
    assert sensor.electrode_ok is False
    sensor.close()
    sensor._closing = False
    sensor.connect()
    assert sensor.electrode_ok is None


def test_connect_time_battery_does_not_override_newer_callback() -> None:
    sensor, raw, backend, _ = make()
    original = backend.open_sensor

    def open_with_early_callback(*args: Any) -> FakeRawSensor:
        opened = original(*args)
        opened.emit_battery(55)  # колбэк пришёл раньше, чем connect прочитал заряд
        return opened

    backend.open_sensor = open_with_early_callback  # type: ignore[method-assign,assignment]
    raw.battery_value = 90  # устаревшее чтение
    sensor.connect()
    assert sensor.battery == 55


def test_not_found_retries_back_off() -> None:
    backend = FakeBackend()
    clock = FakeClock()
    sensor = SdkSensor("SN1", "callibri", backend, clock, retry_interval_s=3.0)

    def attempts_after(gap: float) -> int:
        clock.advance(gap)
        sensor.poll()
        deadline = time.monotonic() + 2
        while sensor.state == "connecting" and time.monotonic() < deadline:
            time.sleep(0.005)
        time.sleep(0.02)
        return len(backend.open_calls)

    assert attempts_after(0.0) == 1
    assert attempts_after(2.9) == 1
    assert attempts_after(0.2) == 2  # первая пауза 3 с
    assert attempts_after(5.9) == 2
    assert attempts_after(0.2) == 3  # 6 с
    assert attempts_after(11.9) == 3
    assert attempts_after(0.2) == 4  # 12 с
    assert attempts_after(29.0) == 4
    assert attempts_after(1.2) == 5  # 30 с
    assert attempts_after(29.0) == 5  # потолок остаётся 30 с
    assert attempts_after(1.2) == 6
