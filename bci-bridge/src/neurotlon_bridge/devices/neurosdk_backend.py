"""Настоящий NeuroSDK (pyneurosdk2 1.0.15). Импортируется только лениво, из `NeuroSdkBackend`.

Не проверялся без железа: обход особенностей SDK взят из neuro-biathlon.
- Callibri: первым выставляется тип сигнала EMG (он может сбросить остальное), затем частота
  1000 Гц и входы электродов.
- Колбэки SDK не бросают исключений наружу (иначе падение в ctypes).
- Освобождение: SDK держит ссылки на нативные колбэки, поэтому `__del__()` зовётся явно.
- Подключения (`create_sensor`) идут строго по очереди под одним замком.
- Фоновый поиск (`ScannerPort`): `start()`, опрос `sensors()` снаружи раз в 0,5 с, `stop()`.
  Колбэк SDK `sensorsChanged` не используется: он приходит из нативного потока.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from neurotlon_contracts.sensor_devices import MAX_ADDRESS, MAX_NAME, clean_text

from .base import (
    BluetoothUnavailableError,
    DeviceError,
    DeviceInfo,
    DeviceKind,
    DeviceNotFoundError,
    RawSensor,
    SdkUnavailableError,
    SensorHandlers,
)

log = logging.getLogger(__name__)

CALLIBRI_HZ = 1000
BRAINBIT_HZ = 250
DEFAULT_SCAN_S = 10.0
POLL_S = 0.5

SDK_HINT = (
    "Не удалось загрузить NeuroSDK (pyneurosdk2). Переустановите зависимости "
    "(uv sync) или проверьте, что нативные библиотеки SDK не блокирует антивирус"
)
NOT_FOUND_HINT = "Устройство не найдено: включите датчик и подождите, пока оно появится в списке"
BLUETOOTH_HINT = (
    "Bluetooth-адаптер не найден или выключен: вставьте USB-адаптер и включите Bluetooth в Windows"
)


def _translate(exc: Exception) -> DeviceError:
    if "adapter" in str(exc).lower():
        return BluetoothUnavailableError(BLUETOOTH_HINT)
    return DeviceError(f"ошибка NeuroSDK: {exc}")


class NeuroSdkBackend:
    def __init__(
        self, scan_s: float = DEFAULT_SCAN_S, *, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._scan_s = scan_s
        self._sleep = sleep
        self._scan_lock = threading.Lock()  # поиск и объект Scanner
        self._connect_lock = threading.Lock()  # create_sensor строго по очереди
        self._state_lock = threading.Lock()  # _known и _claimed, держится недолго
        self._init_lock = threading.Lock()  # создание Scanner
        self._scanner: Any = None
        self._families: dict[Any, DeviceKind] = {}
        self._known: dict[str, tuple[DeviceInfo, Any]] = {}  # адрес -> (инфо, SensorInfo SDK)
        self._claimed: set[str] = set()
        self._streaming = False  # scanner.start() вызван, stop() ещё нет
        try:
            from neurosdk.cmn_types import SensorFamily

            self._families = {
                SensorFamily.LEBrainBit: "brainbit",
                SensorFamily.LECallibri: "callibri",
                SensorFamily.LEKolibri: "callibri",
            }
        except Exception as exc:
            raise SdkUnavailableError(f"{SDK_HINT}: {exc}") from exc

    # --- DeviceBackend ---
    def check(self) -> None:
        with self._scan_lock:
            try:
                scanner = self._ensure_scanner()
                scanner.start()
                scanner.stop()
            except DeviceError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

    def scan(self, seconds: float) -> list[DeviceInfo]:
        with self._scan_lock:
            self._scan_locked(seconds)
        with self._state_lock:
            return [info for info, _ in self._known.values()]

    # --- ScannerPort: фоновый поиск ---
    def start(self) -> None:
        with self._scan_lock:
            try:
                scanner = self._ensure_scanner()
                if not self._streaming:
                    scanner.start()
                    self._streaming = True
            except DeviceError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

    def stop(self) -> None:
        with self._scan_lock:
            if self._scanner is None or not self._streaming:
                return
            self._streaming = False
            try:
                self._scanner.stop()
            except Exception as exc:
                log.warning("остановка поиска: %s", exc)

    def sensors(self) -> list[DeviceInfo]:
        with self._scan_lock:
            try:
                return self._collect(self._ensure_scanner().sensors())
            except DeviceError:
                raise
            except Exception as exc:
                raise _translate(exc) from exc

    def connect(self, address: str, kind: DeviceKind, handlers: SensorHandlers) -> RawSensor:
        with self._state_lock:
            known = self._known.get(address)
            claimed = address in self._claimed
        if known is None or known[0].kind != kind:
            raise DeviceNotFoundError(NOT_FOUND_HINT)
        if claimed:
            raise DeviceError("Датчик уже подключён")
        with self._connect_lock:
            sensor = self._try_open(address, kind, handlers, None)
        if sensor is None:
            raise DeviceNotFoundError(NOT_FOUND_HINT)
        return sensor

    # --- DeviceBackend: рабочий режим ---
    def open_sensor(
        self, serial: str, kind: DeviceKind, handlers: SensorHandlers, address: str = ""
    ) -> RawSensor:
        wanted = serial.strip().lower()
        by_address = address.strip()
        # С адресом сначала ищем только его: безымянные датчики не пробуем подключением.
        sensor = self._open_known(wanted, by_address, kind, handlers, probe=not by_address)
        if sensor is None:
            # Нужного датчика нет в списке: ищем один раз и выходим, как только он появился.
            # Поиск идёт под своим замком и не мешает подключению других датчиков.
            with self._scan_lock:
                if not self._knows(wanted, by_address, kind):
                    self._scan_locked(
                        self._scan_s, until=lambda: self._knows(wanted, by_address, kind)
                    )
            sensor = self._open_known(wanted, by_address, kind, handlers, probe=True)
        if sensor is None:
            raise DeviceNotFoundError(
                f"{kind} с серийным номером {serial} не найден"
                if serial.strip()
                else f"{kind} с адресом {address} не найден"
            )
        return sensor

    def close(self) -> None:
        with self._scan_lock:
            scanner, self._scanner = self._scanner, None
            if scanner is not None:
                try:
                    scanner.__del__()
                except Exception as exc:
                    log.warning("освобождение сканера: %s", exc)

    # --- внутреннее ---
    def _ensure_scanner(self) -> Any:
        with self._init_lock:
            if self._scanner is None:
                from neurosdk.scanner import Scanner

                try:
                    self._scanner = Scanner(list(self._families))
                except Exception as exc:
                    raise _translate(exc) from exc
            return self._scanner

    def _scan_locked(self, seconds: float, until: Callable[[], bool] | None = None) -> None:
        """Вызывать под `_scan_lock`. `until` — ранний выход, когда нужное уже найдено."""
        scanner = self._ensure_scanner()
        try:
            scanner.start()
            deadline = time.monotonic() + seconds
            try:
                while True:
                    self._collect(scanner.sensors())
                    if until is not None and until():
                        break
                    if time.monotonic() >= deadline:
                        break
                    self._sleep(POLL_S)
            finally:
                scanner.stop()
        except DeviceError:
            raise
        except Exception as exc:
            raise _translate(exc) from exc

    def _collect(self, sdk_infos: Sequence[Any]) -> list[DeviceInfo]:
        """Запомнить найденное; вернуть то, что SDK показал в этот раз (без повторов)."""
        seen: dict[str, DeviceInfo] = {}
        for sdk_info in sdk_infos:
            kind = self._families.get(sdk_info.SensFamily)
            if kind is None:
                continue
            # всё из эфира недоверенное: без управляющих знаков и ограниченной длины
            address = clean_text(str(sdk_info.Address), MAX_ADDRESS + 1)
            if not address or len(address) > MAX_ADDRESS or address != str(sdk_info.Address):
                log.warning("устройство с недопустимым адресом пропущено")
                continue
            serial = clean_text(str(sdk_info.SerialNumber or ""), MAX_NAME)
            name = clean_text(str(sdk_info.Name or ""), MAX_NAME) or kind
            info = DeviceInfo(kind, name, serial, address, _rssi(sdk_info))
            seen[address] = info
            # не теряем ранее найденные: SDK иногда отдаёт неполный список
            with self._state_lock:
                self._known[address] = (info, sdk_info)
        return list(seen.values())

    def _knows(self, wanted: str, address: str, kind: DeviceKind) -> bool:
        """Нужный адрес или серийный номер уже есть в списке найденных (в том числе занятый)."""
        with self._state_lock:
            return any(
                info.kind == kind
                and (
                    (address and info.address == address)
                    or (wanted and info.serial.strip().lower() == wanted)
                )
                for info, _ in self._known.values()
            )

    def _open_known(
        self, wanted: str, address: str, kind: DeviceKind, handlers: SensorHandlers, probe: bool
    ) -> RawSensor | None:
        """Подключить датчик из уже найденных; None, если подходящего нет.

        Порядок: адрес, затем серийный номер из эфира, затем (если `probe`) пробное
        подключение к безымянным: у Callibri серийный номер в эфире пуст.
        """
        with self._state_lock:
            candidates = [
                (addr, info.serial.strip().lower())
                for addr, (info, _) in self._known.items()
                if info.kind == kind and addr not in self._claimed
            ]
        by_address = [a for a, _ in candidates if address and a == address]
        named = [a for a, serial in candidates if wanted and serial == wanted]
        unnamed = [a for a, serial in candidates if wanted and not serial] if probe else []
        with self._connect_lock:  # подключения идут по одному
            for found in by_address + [a for a in named if a not in by_address]:
                sensor = self._try_open(found, kind, handlers, None)
                if sensor is not None:
                    return sensor
            # Серийный номер из поиска пуст: подключаем безымянные устройства по очереди.
            for found in unnamed:
                sensor = self._try_open(found, kind, handlers, wanted)
                if sensor is not None:
                    return sensor
        return None

    def _try_open(
        self, address: str, kind: DeviceKind, handlers: SensorHandlers, wanted: str | None
    ) -> RawSensor | None:
        """Подключить; если задан `wanted` и серийный номер другой, освободить и вернуть None.

        Адрес занят, пока жив датчик: `close()` датчика его освобождает.
        """
        from neurosdk.cmn_types import SensorState

        with self._state_lock:
            if address in self._claimed:
                return None
            sdk_info = self._known[address][1]
        sdk_sensor = self._ensure_scanner().create_sensor(sdk_info)
        try:
            if sdk_sensor.state != SensorState.StateInRange:
                raise DeviceError("устройство не на связи")
            if wanted is not None and str(sdk_sensor.serial_number).strip().lower() != wanted:
                _release(sdk_sensor)
                return None
            raw = _SdkRawSensor(kind, sdk_sensor, handlers, lambda: self._unclaim(address))
        except Exception:
            _release(sdk_sensor)
            raise
        with self._state_lock:
            self._claimed.add(address)
        return raw

    def _unclaim(self, address: str) -> None:
        with self._state_lock:
            self._claimed.discard(address)


def _rssi(sdk_info: Any) -> int | None:
    """RSSI из SDK; 0 и неподходящее значение — «неизвестен»."""
    try:
        value = int(sdk_info.RSSI)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if -127 <= value < 0 else None


def _release(sdk_sensor: Any) -> None:
    for attr in (
        "signalDataReceived",
        "sensorStateChanged",
        "batteryChanged",
        "electrodeStateChanged",
    ):
        with contextlib.suppress(Exception):
            setattr(sdk_sensor, attr, None)
    for method in ("disconnect", "__del__"):
        try:
            getattr(sdk_sensor, method)()
        except Exception as exc:
            log.warning("освобождение датчика (%s): %s", method, exc)


class _SdkRawSensor:
    """Адаптер объекта SDK к `RawSensor`: все исключения колбэков гасятся."""

    def __init__(
        self,
        kind: DeviceKind,
        sensor: Any,
        handlers: SensorHandlers,
        on_release: Callable[[], None] = lambda: None,
    ) -> None:
        self._on_release = on_release
        self._kind = kind
        self._sensor = sensor
        self._handlers = handlers
        self.notes: list[str] = []
        self._hz = BRAINBIT_HZ
        sensor.sensorStateChanged = self._on_state
        try:
            self.battery_value: int | None = int(sensor.batt_power)
            sensor.batteryChanged = self._on_battery
        except Exception:
            self.battery_value = None
        if kind == "callibri":
            self._configure_callibri()
            sensor.electrodeStateChanged = self._on_electrode

    @property
    def sampling_hz(self) -> int:
        return self._hz

    def _configure_callibri(self) -> None:
        from neurosdk.cmn_types import (
            CallibriSignalType,
            SensorADCInput,
            SensorExternalSwitchInput,
            SensorParameter,
            SensorSamplingFrequency,
        )

        sensor = self._sensor

        def attempt(what: str, action: Callable[[], None]) -> None:
            try:
                action()
            except Exception as exc:
                self.notes.append(f"{what}: {exc}")
                log.warning("Callibri: не удалось %s: %s", what, exc)

        # Тип сигнала первым: он может сбросить остальные настройки.
        attempt("signal_type=EMG", lambda: setattr(sensor, "signal_type", CallibriSignalType.EMG))
        freq = getattr(SensorSamplingFrequency, f"FrequencyHz{CALLIBRI_HZ}")
        attempt("частота 1000", lambda: setattr(sensor, "sampling_frequency", freq))
        if sensor.is_supported_parameter(SensorParameter.ADCInputState):
            attempt(
                "ADC=Electrodes", lambda: setattr(sensor, "adc_input", SensorADCInput.Electrodes)
            )
        if sensor.is_supported_parameter(SensorParameter.ExternalSwitchState):
            attempt(
                "вход=Electrodes",
                lambda: setattr(sensor, "ext_sw_input", SensorExternalSwitchInput.Electrodes),
            )
        self._hz = int(sensor.sampling_frequency.name.removeprefix("FrequencyHz"))
        if self._hz != CALLIBRI_HZ:
            self.notes.append(f"режим ЭМГ не включился: {self._hz} Гц вместо {CALLIBRI_HZ}")
            log.warning("Callibri: %s", self.notes[-1])

    def start_signal(self) -> None:
        from neurosdk.cmn_types import SensorCommand

        self._sensor.signalDataReceived = self._on_signal
        self._sensor.exec_command(SensorCommand.StartSignal)

    def stop_signal(self) -> None:
        from neurosdk.cmn_types import SensorCommand

        self._sensor.signalDataReceived = None
        self._sensor.exec_command(SensorCommand.StopSignal)

    def battery(self) -> int | None:
        return self.battery_value

    def serial_number(self) -> str:
        try:
            return clean_text(str(self._sensor.serial_number or ""), MAX_NAME)
        except Exception:
            return ""

    def close(self) -> None:
        try:
            _release(self._sensor)
        finally:
            self._on_release()  # повторное подключение к этому датчику снова возможно

    # --- колбэки SDK ---
    def _on_signal(self, _sensor: Any, packets: Sequence[Any]) -> None:
        with contextlib.suppress(Exception):
            rows: list[tuple[float, ...]]
            if self._kind == "brainbit":
                rows = [(float(p.O1), float(p.O2), float(p.T3), float(p.T4)) for p in packets]
            else:
                rows = [(float(v),) for p in packets for v in p.Samples]
            self._handlers.on_samples(rows)

    def _on_state(self, _sensor: Any, state: Any) -> None:
        with contextlib.suppress(Exception):
            self._handlers.on_state(getattr(state, "name", "") == "StateInRange")

    def _on_battery(self, _sensor: Any, value: Any) -> None:
        with contextlib.suppress(Exception):
            self._handlers.on_battery(int(value))

    def _on_electrode(self, _sensor: Any, state: Any) -> None:
        with contextlib.suppress(Exception):
            self._handlers.on_electrode(getattr(state, "name", "") == "Normal")
