"""Живой список датчиков для экрана настройки: поиск, подключение, назначение ролям.

Источник истины здесь, а не в окне: окно только показывает снимок (`view()`) и шлёт команды.
Состояние поиска приходит из процесса `neurotlon-bridge --discover` (`discovery.py`), назначение
`роль -> датчик` хранится по адресу устройства с серийным номером как запасным ключом.

Блокировка одна, вызовы клиента, которые ждут потоки (`close`), под ней не делаются.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from neurotlon_contracts.sensor_devices import DEVICE_ROLES, ROLE_KIND, DeviceRef

from . import texts
from .discovery import ERROR_MAX, DiscoveryClient, DiscoveryListener

log = logging.getLogger(__name__)

SCAN_AUTO_STOP_S = 60.0  # столько ищем без нажатий, потом останавливаемся (список остаётся)
STALE_S = 15.0  # устройство не видно дольше: «нет в эфире»
MAX_ID = 64

ClientFactory = Callable[[DiscoveryListener], DiscoveryClient]

PHASES = ("idle", "scanning", "stopped", "error")


@dataclass(frozen=True)
class _Found:
    """Устройство из сообщения `devices` и когда оно пришло."""

    item: Mapping[str, Any]
    received: float
    idle: float = 0.0  # сколько простоя поиска набралось к моменту прихода

    @property
    def id(self) -> str:
        return str(self.item["id"])

    @property
    def serial(self) -> str:
        return str(self.item["serial"])


@dataclass(frozen=True)
class _Link:
    state: str
    serial: str
    battery: int | None
    contact: bool | None
    signal: bool
    level: float | None
    error: str | None


class _Listener:
    """Слушатель одного клиента: сообщения прежних клиентов (после перезапуска) отбрасываются."""

    def __init__(self, session: SensorSession, generation: int) -> None:
        self._session = session
        self._generation = generation

    def on_message(self, message: dict[str, Any]) -> None:
        self._session.handle_message(self._generation, message)

    def on_exit(self, error: str | None) -> None:
        self._session.handle_exit(self._generation, error)


class SensorSession:
    def __init__(
        self,
        factory: ClientFactory | None,
        clock: Callable[[], float] = time.monotonic,
        bridge_busy: Callable[[], bool] = lambda: False,
    ) -> None:
        self._factory = factory
        self._clock = clock
        self._bridge_busy = bridge_busy
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()  # вся операция запуска и закрытия: одна за раз
        self._closed = False
        self._client: DiscoveryClient | None = None
        self._generation = 0
        self._phase = "idle"
        self._error: str | None = None
        self._devices: dict[str, _Found] = {}
        self._links: dict[str, _Link] = {}
        self._assigned: dict[str, DeviceRef] = {}
        self._deadline: float | None = None
        self._tried: set[str] = set()  # назначенные, к которым уже пробовали подключиться сами
        self._frozen_at: float | None = None  # поиск остановлен: возраст «нет в эфире» замирает
        self._idle_total = 0.0  # сумма прошлых простоев: в возраст они не входят
        self.version = 0  # растёт при каждом изменении назначения

    @property
    def available(self) -> bool:
        return self._factory is not None

    # --- назначение ---
    def load_assigned(self, devices: Mapping[str, DeviceRef]) -> None:
        with self._lock:
            self._assigned = {r: d for r, d in devices.items() if r in DEVICE_ROLES}

    def keep_roles(self, roles: tuple[str, ...]) -> None:
        """Забыть назначение ролей, которых у дисциплины нет (остатки прежней настройки)."""
        with self._lock:
            self._assigned = {r: d for r, d in self._assigned.items() if r in roles}

    def assigned(self) -> dict[str, DeviceRef]:
        with self._lock:
            return dict(self._assigned)

    def assign(self, role: str, device_id: str) -> bool:
        """Назначить найденное устройство роли (датчик уже в другой роли переносится)."""
        if role not in ROLE_KIND or not 0 < len(device_id) <= MAX_ID:
            return False
        with self._lock:
            found = self._devices.get(device_id)
            if found is None or found.item["kind"] != ROLE_KIND[role]:
                return False
            self._touch()
            link = self._links.get(device_id)
            previous = self._assigned.get(role)
            for other, ref in list(self._assigned.items()):
                if other != role and _is_device(ref, found, link):
                    del self._assigned[other]  # перенос: датчик остаётся подключённым
            serial = found.serial or (link.serial if link else "")
            self._assigned[role] = DeviceRef(
                address=device_id, serial=serial, name=str(found.item["name"]), kind=ROLE_KIND[role]
            )
            self.version += 1
            stale = self._stale_address(previous, keep=device_id)
            need_connect = link is None or link.state in ("failed", "lost")
            reconnect = (
                link is not None and link.state == "lost"
            )  # мост держит lost: сперва отпустить
            if need_connect:
                self._tried.add(device_id)
            client = self._client
        if client is not None:
            if stale is not None:
                self._release(client, stale)
            if reconnect:
                self._release(client, device_id)
            if need_connect:
                self._connect(client, device_id, ROLE_KIND[role])
        return True

    def unassign(self, role: str) -> bool:
        if role not in ROLE_KIND:
            return False
        with self._lock:
            self._touch()
            previous = self._assigned.pop(role, None)
            if previous is not None:
                self.version += 1
            stale = self._stale_address(previous)
            client = self._client
        if client is not None and stale is not None:
            self._release(client, stale)
        return True

    def _stale_address(self, previous: DeviceRef | None, keep: str = "") -> str | None:
        """Адрес прежнего датчика роли, если он больше никому не нужен. Под замком."""
        if previous is None or not previous.address or previous.address == keep:
            return None
        if any(ref.address == previous.address for ref in self._assigned.values()):
            return None
        return previous.address if previous.address in self._links else None

    def _release(self, client: DiscoveryClient, address: str) -> None:
        with self._lock:
            self._links.pop(address, None)
            self._tried.discard(address)
        client.send({"cmd": "release", "id": address})

    def _connect(self, client: DiscoveryClient, address: str, kind: str) -> None:
        with self._lock:
            self._links[address] = _Link("connecting", "", None, None, False, None, None)
        if not client.send({"cmd": "connect", "id": address, "kind": kind}):
            with self._lock:
                self._links.pop(address, None)

    # --- поиск ---
    def scan_start(self) -> bool:
        """Включить поиск (при необходимости запустить процесс); повторный вызов перезапускает."""
        if self._factory is None:
            return False
        with self._start_lock:  # два нажатия подряд не запустят два процесса
            with self._lock:
                if self._closed:
                    return False
                self._touch()
                client = self._live_client()
                dead = self._client if client is None else None
                if dead is not None:
                    self._client = None
            if dead is not None:
                dead.close()  # прежний процесс не оставляем с открытыми ручками
            if client is None:
                if self._bridge_busy():
                    self._fail(texts.SENSORS_BRIDGE_BUSY)
                    return True
                client = self._spawn()
                if client is None:
                    return True
            elif not client.send({"cmd": "scan", "on": False}):  # принудительный перезапуск
                log.info("поиск не принял команду остановки, продолжаем")
            with self._lock:
                self._tried.clear()
                self._set_phase("scanning")
                self._deadline = self._clock() + SCAN_AUTO_STOP_S
            if not client.send({"cmd": "scan", "on": True}):
                self._fail(texts.SENSORS_DISCOVERY_LOST)
            return True

    def scan_stop(self) -> bool:
        with self._lock:
            client = self._live_client()
            if self._phase == "scanning":
                self._set_phase("stopped")
            self._deadline = None
        if client is not None:
            client.send({"cmd": "scan", "on": False})
        return True

    def tick(self) -> None:
        """Остановить поиск, если на экране давно не нажимали."""
        with self._lock:
            expired = (
                self._phase == "scanning"
                and self._deadline is not None
                and self._clock() >= self._deadline
            )
        if expired:
            self.scan_stop()

    def close(self) -> None:
        """Отпустить датчики и закрыть процесс поиска насовсем (при сохранении и выходе)."""
        self.halt(final=True)

    def halt(self, final: bool = False) -> None:
        """Остановить процесс поиска и отпустить соединения; назначение остаётся.

        Без `final` поиск потом можно запустить снова (например, режим вернули на датчики).
        """
        with self._start_lock:  # дожидаемся идущего запуска: процесс не останется сиротой
            with self._lock:
                self._closed = self._closed or final  # после закрытия поиск не запускается
                client, self._client = self._client, None
                self._generation += 1  # поздние сообщения этого клиента больше не нужны
                self._links.clear()
                self._deadline = None
                if self._phase == "scanning":
                    self._set_phase("stopped")
            if client is not None:
                client.close()

    # --- внутреннее ---
    def _live_client(self) -> DiscoveryClient | None:
        """Живой клиент или `None`. Под замком."""
        client = self._client
        return client if client is not None and client.alive else None

    def _spawn(self) -> DiscoveryClient | None:
        assert self._factory is not None
        with self._lock:
            if self._closed:
                return None
            self._generation += 1
            listener = _Listener(self, self._generation)
            self._devices = {}
            self._links = {}
        try:
            client = self._factory(listener)
            client.start()
        except OSError as exc:
            self._fail(texts.sensors_discovery_failed(str(exc)))
            return None
        with self._lock:
            self._client = client
            self._error = None
        return client

    def _touch(self) -> None:
        """Нажатие на экране: срок автоматической остановки отсчитывается заново. Под замком."""
        if self._phase == "scanning":
            self._deadline = self._clock() + SCAN_AUTO_STOP_S

    def _set_phase(self, phase: str) -> None:
        """Под замком; замораживает возраст «нет в эфире», пока поиск не идёт."""
        if phase == "scanning":
            self._error = None
            if self._frozen_at is not None:
                self._idle_total += self._clock() - self._frozen_at
            self._frozen_at = None
        elif self._phase == "scanning":
            self._frozen_at = self._clock()
        self._phase = phase

    def _fail(self, message: str) -> None:
        with self._lock:
            self._set_phase("error")
            self._error = message
            self._deadline = None

    # --- сообщения моста (из потока чтения) ---
    def handle_message(self, generation: int, message: dict[str, Any]) -> None:
        connects: list[tuple[str, str]] = []
        with self._lock:
            if generation != self._generation:
                return
            kind = message["type"]
            if kind == "devices":
                self._on_devices(message)
                connects = self._reconnect_plan()
            elif kind == "link":
                self._on_link(message)
            elif kind == "error":
                self._set_phase("error")
                self._error = str(message["message"])
                self._deadline = None
            client = self._client
        for address, device_kind in connects:
            if client is not None:
                self._connect(client, address, device_kind)

    def handle_exit(self, generation: int, error: str | None) -> None:
        with self._lock:
            if generation != self._generation:
                return
            client, self._client = self._client, None
            self._links.clear()
            self._deadline = None
            if self._phase != "error":
                self._set_phase("error")
                self._error = (error or texts.SENSORS_DISCOVERY_LOST)[:ERROR_MAX]
        if client is not None:
            client.close()  # Job Object и ручки процесса освобождаются сразу

    def _on_devices(self, message: Mapping[str, Any]) -> None:
        now = self._clock()
        self._devices = {str(i["id"]): _Found(i, now, self._idle_total) for i in message["items"]}
        for role, ref in list(self._assigned.items()):
            found = self._match(ref)
            if found is not None and (ref.address != found.id or (found.serial and not ref.serial)):
                self._assigned[role] = replace(
                    ref,
                    address=found.id,
                    serial=ref.serial or found.serial,
                    name=ref.name or str(found.item["name"]),
                )

    def _reconnect_plan(self) -> list[tuple[str, str]]:
        """Назначенные (в том числе из файла), которые нашлись: подключаемся один раз сами."""
        plan: list[tuple[str, str]] = []
        for role, ref in self._assigned.items():
            found = self._match(ref)
            if found is None or found.id in self._links or found.id in self._tried:
                continue
            if found.item["kind"] != ROLE_KIND[role]:
                continue
            if int(found.item["age_ms"]) >= STALE_S * 1000:
                continue  # не в эфире: не подключаемся вслепую (попробуем, когда вернётся)
            self._tried.add(found.id)
            plan.append((found.id, ROLE_KIND[role]))
        return plan

    def _on_link(self, message: Mapping[str, Any]) -> None:
        address = str(message["id"])
        if address not in self._links and message["state"] != "failed":
            return  # отпущенное или чужое
        self._links[address] = _Link(
            state=str(message["state"]),
            serial=str(message["serial"]),
            battery=message["battery"],
            contact=message["contact"],
            signal=bool(message["signal"]),
            level=message["level"],
            error=message.get("error"),
        )
        serial = str(message["serial"])
        if serial:
            for role, ref in list(self._assigned.items()):
                if ref.address == address and ref.serial != serial:
                    self._assigned[role] = replace(ref, serial=serial)

    # --- сопоставление и снимок ---
    def _match(self, ref: DeviceRef) -> _Found | None:
        """Живое устройство для записи назначения: по адресу, затем по серийному номеру."""
        if ref.address:
            found = next((f for f in self._devices.values() if _same(f.id, ref.address)), None)
            if found is not None:
                return found
        if ref.serial:
            for found in self._devices.values():
                link = self._links.get(found.id)
                shown = found.serial or (link.serial if link else "")
                if (
                    shown
                    and _same(shown, ref.serial)
                    and found.item["kind"] == (ref.kind or found.item["kind"])
                ):
                    return found
        return None

    def view(self) -> dict[str, Any]:
        """Снимок `state.sensors`: назначенные первыми, затем остальные в порядке обнаружения."""
        now = self._clock()
        with self._lock:
            rows: list[dict[str, Any]] = []
            used: set[str] = set()
            for role in DEVICE_ROLES:
                ref = self._assigned.get(role)
                if ref is None:
                    continue
                found = self._match(ref)
                if found is not None and found.id not in used:
                    used.add(found.id)
                    rows.append(self._row(found, role, ref, now))
                else:
                    rows.append(_missing_row(role, ref))
            rows += [
                self._row(f, None, None, now) for f in self._devices.values() if f.id not in used
            ]
            return {"phase": self._phase, "error": self._error, "devices": rows}

    def _row(
        self, found: _Found, role: str | None, ref: DeviceRef | None, now: float
    ) -> dict[str, Any]:
        item = found.item
        link = self._links.get(found.id)
        age_ms = int(item["age_ms"])
        in_range = age_ms < STALE_S * 1000
        age_s = 0  # в эфире: возраст не нужен
        if not in_range:
            end = self._frozen_at if self._frozen_at is not None else now
            waited = end - found.received - (self._idle_total - found.idle)
            age_s = int((age_ms + max(0.0, waited) * 1000) / 1000)
        return {
            "id": found.id,
            "name": str(item["name"]),
            "kind": str(item["kind"]),
            "serial": found.serial or (link.serial if link else "") or (ref.serial if ref else ""),
            "address": str(item["address"]),
            "rssi": item["rssi"],
            "in_range": in_range,
            "age_s": age_s,
            "role": role,
            "link": link.state if link else None,
            "battery": link.battery if link else None,
            "contact": link.contact if link else None,
            "signal": link.signal if link else False,
            "level": link.level if link else None,
            "error": link.error if link else None,
        }


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _is_device(ref: DeviceRef, found: _Found, link: _Link | None) -> bool:
    if ref.address and _same(ref.address, found.id):
        return True
    shown = found.serial or (link.serial if link else "")
    return bool(ref.serial and shown and _same(ref.serial, shown))


def _missing_row(role: str, ref: DeviceRef) -> dict[str, Any]:
    """Назначен, но в эфире не найден (например, прочитан из `bridge.toml`)."""
    return {
        "id": f"saved:{role}",
        "name": ref.name or ROLE_KIND[role].capitalize(),
        "kind": ref.kind or ROLE_KIND[role],
        "serial": ref.serial,
        "address": ref.address,
        "rssi": None,
        "in_range": False,
        "age_s": 0,
        "role": role,
        "link": None,
        "battery": None,
        "contact": None,
        "signal": False,
        "level": None,
        "error": None,
    }
