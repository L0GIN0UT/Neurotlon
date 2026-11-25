"""Режим настройки для веб-интерфейса: форма, проверка подключения, датчики, сохранение.

Работает вместо обычной станции, пока настроек нет (или админ вызвал настройку сам).
Снимок состояния — `kind: "setup"`; команды:
- `setup_check`, `setup_save` с полями формы;
- `setup_form` с полями формы: окно шлёт её при вводе токена и адреса, ядро через 0,7 с само
  узнаёт дисциплину станции (роли датчиков); при открытии с сохранённым токеном то же;
- `sensors_scan_start`, `sensors_scan_stop` — фоновый поиск датчиков (`SensorSession`);
- `sensors_assign` `{role, id}`, `sensors_unassign` `{role}` — назначение датчика роли;
- `sensors_scan` — прежний блокирующий поиск (останется до обновления окна).

Назначение датчиков ведёт ядро: окно присылает только команды, а в проверку и сохранение
берётся то, что назначено сейчас.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from . import texts
from .config import DEFAULT_EEG_METHOD, ConfigError
from .game import bridge_listening
from .sensor_session import MAX_ID, SensorSession
from .sensors import SCAN_SECONDS, SensorDevice, roles_for
from .setup import OFFLINE, CheckResult, SetupForm, SetupService
from .web_bridge import CommandRejected, LiveState

log = logging.getLogger(__name__)

SETUP_ACTIONS = frozenset({"setup_check", "setup_save", "sensors_scan", "setup_form"})
PROBE_RETRY_S = 5.0  # повтор пробы после сетевой ошибки
AUTO_CHECK_DELAY_S = 0.7  # пауза после ввода токена: проверка не бежит на каждую букву
SENSOR_ACTIONS = frozenset(
    {"sensors_scan_start", "sensors_scan_stop", "sensors_assign", "sensors_unassign"}
)
TICK_S = 0.25  # как часто снимок обновляется из потока поиска: не чаще четырёх раз в секунду
MAX_ROLE = 32


def form_from(value: Any) -> SetupForm | None:
    """Поля формы из JSON; `None`, если пришло что-то другое.

    Назначение датчиков (`devices`) из окна не берётся: его ведёт ядро.
    """
    if not isinstance(value, dict):
        return None
    fields: dict[str, Any] = {}
    for key in ("server_url", "token", "game_path", "ca_file", "camera", "sensors"):
        item = value.get(key, "")
        if not isinstance(item, str) or len(item) > 4096:
            return None
        fields[key] = item
    method = value.get("eeg_method", DEFAULT_EEG_METHOD)
    if not isinstance(method, str) or len(method) > 64:
        return None
    fields["eeg_method"] = method
    return SetupForm(**fields)


def _probe_key(form: SetupForm) -> tuple[str, str, str]:
    return form.server_url.strip().rstrip("/"), form.token.strip(), form.ca_file.strip()


def _same_fields(a: SetupForm, b: SetupForm) -> bool:
    """Формы совпадают без учёта назначения датчиков (его сверяют по версии)."""
    return dataclasses.replace(a, devices={}) == dataclasses.replace(b, devices={})


def _sensor_args(action: str, value: Any) -> tuple[str, str] | None:
    """Проверенные `(role, id)` команды назначения; `None` — аргументы не годятся."""
    if not isinstance(value, dict):
        return None
    role = value.get("role")
    if not isinstance(role, str) or not 0 < len(role) <= MAX_ROLE:
        return None
    if action == "sensors_unassign":
        return role, ""
    device_id = value.get("id")
    if not isinstance(device_id, str) or not 0 < len(device_id) <= MAX_ID:
        return None
    return role, device_id


class SetupStation(LiveState):
    def __init__(
        self,
        service: SetupService,
        error: str | None = None,
        *,
        session: SensorSession | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._service = service
        self._clock = clock
        self._lock = threading.Lock()
        self._phase = "form"  # form → checking → ok → saved
        self._error = error
        self._discipline: str | None = None
        self._game = ""
        self._checked: SetupForm | None = None
        self._checked_version = -1
        self._scan_phase = "idle"  # прежний поиск: idle → scanning → done
        self._scan_devices: list[SensorDevice] = []
        self._scan_error: str | None = None
        self._probe_form: SetupForm | None = None  # форма, по которой роли ждут проверки
        self._probe_key: tuple[str, str, str] | None = None  # адрес, токен, сертификат
        self._probe_due: float | None = None
        self._probing = False
        self._probe_retried = False  # после сетевой ошибки одна повторная проба
        self._probe_error = False  # `error` пришла из автопроверки: при правке формы уходит
        self._defaults = service.defaults()
        self._session = session or self._make_session()
        self._session.load_assigned(service.sensors.saved_devices())
        self._ticker: threading.Thread | None = None
        self.saved = threading.Event()
        self._publish()

    def _make_session(self) -> SensorSession:
        host, port = self._service.bridge_endpoint()
        return SensorSession(
            self._service.sensors.discovery_factory(),
            bridge_busy=lambda: bridge_listening(host, port),
        )

    def _publish(self) -> None:
        defaults = self._defaults
        self.publish(
            {
                "discipline": "",
                "players_needed": 1,
                "status": {"pending": 0, "rejected": 0, "online": None},
                "state": {
                    "kind": "setup",
                    "phase": self._phase,
                    "error": self._error,
                    "discipline": self._discipline,
                    "players_needed": (2 if self._discipline == "pong" else 1)
                    if self._discipline
                    else None,
                    "form": {
                        k: defaults[k]
                        for k in (
                            "server_url",
                            "game_path",
                            "ca_file",
                            "camera",
                            "sensors",
                            "devices",
                            "eeg_method",
                        )
                    },
                    "has_token": defaults["has_token"],
                    "games_bundled": defaults["games_bundled"],
                    "game": self._game,
                    "sensors_available": self._service.sensors.available,
                    "roles": list(roles_for(self._discipline)),
                    "roles_known": self._discipline is not None,
                    "sensors": self._session.view(),
                    "scan": {
                        "seconds": SCAN_SECONDS,
                        "phase": self._scan_phase,
                        "devices": [d.view() for d in self._scan_devices],
                        "error": self._scan_error,
                    },
                },
            }
        )

    # --- жизнь ----------------------------------------------------------------------------

    def start(self) -> None:
        """Поиск стартует сам при входе в настройку в режиме «настоящие датчики»."""
        if self._service.sensors.available and self._defaults["sensors"] == "hardware":
            self._session.scan_start()
        saved = self._defaults
        if saved["has_token"] and saved["server_url"]:
            with self._lock:  # открыли с сохранённым токеном: роли узнаются сами
                self._plan_probe(
                    SetupForm(server_url=saved["server_url"], ca_file=saved["ca_file"])
                )
        self._ticker = threading.Thread(target=self._run, name="setup-ticker", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        super().stop()
        if self._ticker is not None:
            self._ticker.join(timeout=2)
        self._session.close()  # датчики отпускаются при выходе без сохранения

    def _run(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception:
                log.exception("setup tick failed")

    def tick(self) -> None:
        """Шаг фоновой работы: поиск датчиков, автопроверка токена, свежий снимок."""
        self._session.tick()
        form: SetupForm | None = None
        with self._lock:
            due = self._probe_due
            if (
                due is not None
                and self._clock() >= due
                and not self._probing
                and self._phase not in {"checking", "saved"}
            ):
                form, self._probe_due, self._probing = self._probe_form, None, True
            self._publish()
        if form is not None:
            threading.Thread(
                target=self._probe, args=(form,), name="setup-probe", daemon=True
            ).start()

    # --- команды --------------------------------------------------------------------------

    def command(self, action: str, value: Any) -> bool:
        if action in SENSOR_ACTIONS:
            return self._sensor_command(action, value)
        if action not in SETUP_ACTIONS:
            return False
        if action == "sensors_scan":
            return self._start_scan()
        form = form_from(value)
        if form is None:
            return False
        if action == "setup_form":
            with self._lock:
                if self._phase in {"checking", "saved"}:
                    return True  # поздняя форма из окна: тихо игнорируем
                self._plan_probe(form)
                self._publish()
            return True
        with self._lock:
            if self._phase in {"checking", "saved"}:
                return False
            if form.sensors != "hardware":
                self._session.halt()  # режим сменили на эмулятор: Bluetooth не держим
            version = self._session.version  # раньше назначения: гонка даст лишнюю проверку
            form = dataclasses.replace(form, devices=self._session.assigned())
            if action == "setup_check":
                self._phase, self._error, self._discipline = "checking", None, None
                self._game = ""
                self._probe_key, self._probe_due = _probe_key(form), None
                self._probe_form = None  # ответ прежней пробы не затрёт полную проверку
                self._probe_error = False
                threading.Thread(
                    target=self._check, args=(form, version), name="setup-check", daemon=True
                ).start()
                self._publish()
                return True
            just_saved = self._save(form)
            self._publish()
        if just_saved:
            self._session.close()  # без замка станции: закрытие ждёт процесс до нескольких секунд
            self.saved.set()
        return True

    def _plan_probe(self, form: SetupForm) -> None:
        """Токен или адрес сменились: роли неизвестны, проверка через паузу. Под замком."""
        key = _probe_key(form)
        if key == self._probe_key:
            return  # то же самое уже проверено или проверяется
        self._probe_key = key
        self._discipline, self._game, self._probe_due = None, "", None
        if self._probe_error:
            self._error, self._probe_error = None, False
        if self._phase == "ok":
            self._phase, self._checked = "form", None
        ready = self._service.probe_ready(form)
        self._probe_form = form if ready else None
        self._probe_retried = False
        if ready:
            self._probe_due = self._clock() + AUTO_CHECK_DELAY_S

    def _probe(self, form: SetupForm) -> None:
        try:
            result = self._service.probe(form)
        except Exception:
            log.exception("setup probe failed")
            result = CheckResult(None, texts.SETUP_FAILED)
        with self._lock:
            self._probing = False
            if self._probe_form is not form or self._phase in {"checking", "saved"}:
                return  # форму успели поменять или запустили полную проверку: результат устарел
            if result.error == OFFLINE and not self._probe_retried:
                self._probe_retried = True
                self._probe_due = self._clock() + PROBE_RETRY_S  # сеть могла моргнуть
                return
            self._discipline = result.discipline
            if result.discipline is not None:
                self._session.keep_roles(roles_for(result.discipline))
            self._error, self._probe_error = result.error, result.error is not None
            self._publish()

    def _sensor_command(self, action: str, value: Any) -> bool:
        with self._lock:
            allowed = roles_for(self._discipline)
            if self._phase == "saved":
                return False  # датчики уже отпущены для рабочего моста
            if self._discipline is None and action == "sensors_assign":
                raise CommandRejected(texts.ENTER_TOKEN)
        if not self._service.sensors.available:
            return False
        if action == "sensors_scan_start":
            ok = self._session.scan_start()
        elif action == "sensors_scan_stop":
            ok = self._session.scan_stop()
        else:
            args = _sensor_args(action, value)
            unknown_roles = self._discipline is None and action == "sensors_unassign"
            if args is None or (args[0] not in allowed and not unknown_roles):
                return False
            before = self._session.version
            if action == "sensors_assign":
                ok = self._session.assign(*args)
            else:
                ok = self._session.unassign(args[0])
            if ok and self._session.version != before:
                self._assignment_changed()
        with self._lock:
            self._publish()
        return ok

    def _assignment_changed(self) -> None:
        """Проверенное устарело: перед сохранением нужна новая проверка."""
        with self._lock:
            if self._phase == "ok":
                self._phase, self._checked = "form", None

    def _start_scan(self) -> bool:
        with self._lock:
            if self._scan_phase == "scanning" or not self._service.sensors.available:
                return False
            self._scan_phase, self._scan_error = "scanning", None
        self._session.scan_stop()  # два поиска разом Bluetooth не любит
        with self._lock:
            threading.Thread(target=self._scan, name="sensors-scan").start()
            self._publish()
        return True

    def _scan(self) -> None:
        try:
            devices, error = self._service.sensors.scan()
        except Exception:
            log.exception("sensor scan failed")
            devices, error = [], texts.SETUP_FAILED
        with self._lock:
            self._scan_devices, self._scan_error, self._scan_phase = devices, error, "done"
            self._publish()

    def _check(self, form: SetupForm, version: int) -> None:
        try:
            result = self._service.check(form)
        except Exception:
            log.exception("setup check failed")
            result = CheckResult(None, texts.SETUP_FAILED)
        with self._lock:
            self._discipline, self._game = result.discipline, result.game
            if result.discipline is not None:
                self._session.keep_roles(roles_for(result.discipline))
            changed = self._session.version != version  # назначение менялось, пока проверяли
            ok = result.ok and not changed
            self._phase = "ok" if ok else "form"
            self._error = result.error
            self._checked = form if ok else None
            self._checked_version = version
            self._publish()

    def _save(self, form: SetupForm) -> bool:
        """Сохранить можно только то, что только что прошло проверку, с тем же назначением."""
        if (
            self._phase != "ok"
            or self._checked is None
            or not _same_fields(form, self._checked)
            or self._session.version != self._checked_version
        ):
            self._error = texts.SETUP_CHECK_FIRST
            return False
        try:
            self._service.save(form, self._discipline)
        except (ConfigError, OSError) as exc:
            self._error = str(exc)
            return False
        self._phase, self._error = "saved", None
        self._defaults = self._service.defaults()
        return True
