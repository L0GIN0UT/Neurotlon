"""Режим настройки для веб-интерфейса: форма, проверка подключения, сохранение.

Работает вместо обычной станции, пока настроек нет (или админ вызвал настройку сам).
Снимок состояния — `kind: "setup"`; команды — `setup_check` и `setup_save` с полями формы.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import texts
from .config import ConfigError
from .setup import CheckResult, SetupForm, SetupService
from .web_bridge import LiveState

log = logging.getLogger(__name__)

SETUP_ACTIONS = frozenset({"setup_check", "setup_save"})


def form_from(value: Any) -> SetupForm | None:
    """Поля формы из JSON; `None`, если пришло что-то другое."""
    if not isinstance(value, dict):
        return None
    fields: dict[str, str] = {}
    for key in ("server_url", "token", "game_path", "ca_file"):
        item = value.get(key, "")
        if not isinstance(item, str) or len(item) > 4096:
            return None
        fields[key] = item
    return SetupForm(**fields)


class SetupStation(LiveState):
    def __init__(self, service: SetupService, error: str | None = None) -> None:
        super().__init__()
        self._service = service
        self._lock = threading.Lock()
        self._phase = "form"  # form → checking → ok → saved
        self._error = error
        self._discipline: str | None = None
        self._checked: SetupForm | None = None
        self.saved = threading.Event()
        self._publish()

    def _publish(self) -> None:
        defaults = self._service.defaults()
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
                    "form": {k: defaults[k] for k in ("server_url", "game_path", "ca_file")},
                    "has_token": defaults["has_token"],
                },
            }
        )

    def command(self, action: str, value: Any) -> bool:
        if action not in SETUP_ACTIONS:
            return False
        form = form_from(value)
        if form is None:
            return False
        with self._lock:
            if self._phase in {"checking", "saved"}:
                return False
            if action == "setup_check":
                self._phase, self._error, self._discipline = "checking", None, None
                threading.Thread(target=self._check, args=(form,), name="setup-check").start()
            else:
                self._save(form)
            self._publish()
        return True

    def _check(self, form: SetupForm) -> None:
        try:
            result = self._service.check(form)
        except Exception:
            log.exception("setup check failed")
            result = CheckResult(None, texts.SETUP_FAILED)
        with self._lock:
            self._phase = "ok" if result.ok else "form"
            self._error, self._discipline = result.error, result.discipline
            self._checked = form if result.ok else None
            self._publish()

    def _save(self, form: SetupForm) -> None:
        """Сохранить можно только то, что только что прошло проверку."""
        if self._phase != "ok" or form != self._checked:
            self._error = texts.SETUP_CHECK_FIRST
            return
        try:
            self._service.save(form)
        except (ConfigError, OSError) as exc:
            self._error = str(exc)
            return
        self._phase, self._error = "saved", None
        self.saved.set()
