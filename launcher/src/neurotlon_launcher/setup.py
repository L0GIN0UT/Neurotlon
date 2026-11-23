"""Первая настройка стенда: проверка подключения и запись `launcher.toml` с токеном.

Админ вводит адрес сервера, токен станции и путь к игре один раз. Дисциплина в настройки
не пишется: её сообщает сервер по токену, поэтому токен станции «Понг» сам включает двух игроков.
"""

from __future__ import annotations

import json
import os
import ssl
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .api import (
    DisciplineConfig,
    HttpStationApi,
    Offline,
    StationApiError,
    Unauthorized,
)
from .config import ConfigError, load_config
from .sensors import SensorService, duplicate_serials, missing_roles

TOKEN_FILE = "station.token"
MIN_TOKEN_LENGTH = 16
ROLE_TITLES = {
    "eeg": "ЭЭГ (BrainBit)",
    "emg": "ЭМГ (Callibri)",
    "emg_left": "левая рука (Callibri)",
    "emg_right": "правая рука (Callibri)",
}
SENSORS_MODE = "Режим датчиков: настоящие датчики или эмулятор"
NO_BRIDGE_IN_BUILD = "Мост датчиков не входит в эту установку: выберите «запускаю мост отдельно»"
SENSORS_MISSING = "Укажите серийные номера датчиков: {roles}"
SENSORS_DUPLICATE = "Один и тот же датчик указан для двух сигналов"

URL_REQUIRED = "Введите адрес сервера, например https://192.168.1.10"
URL_SCHEME = "Адрес должен начинаться с https://: токен станции не отправляется открыто"
TOKEN_REQUIRED = "Вставьте токен станции из админки"
TOKEN_SHORT = "Токен слишком короткий: скопируйте его целиком"
GAME_REQUIRED = "Укажите игру: путь к .exe"
GAME_MISSING = "Файл игры не найден"
CERT_MISSING = "Файл сертификата не найден"
CERT_BAD = "Сертификат зала не принят: проверьте, что выбран корневой сертификат (.crt или .pem)"
OFFLINE = "Нет связи с сервером"
UNAUTHORIZED = "Токен не подходит: возможно, он скопирован не полностью или станцию пересоздали"
CERT_REJECTED = "Сертификат сервера не принят: укажите файл сертификата зала"


class ConfigSource(Protocol):
    """То, что нужно проверке от API: узнать дисциплину станции."""

    def get_config(self) -> DisciplineConfig: ...

    def close(self) -> None: ...


# Подключение проверяется без повторов: админ ждёт ответа.
ClientFactory = Callable[[str, str, Path | None], ConfigSource]


@dataclass(frozen=True)
class SetupForm:
    server_url: str = ""
    token: str = ""  # пусто — оставить уже сохранённый
    game_path: str = ""
    ca_file: str = ""  # необязательно
    camera: str = ""  # имя камеры для QR; пусто — камера по умолчанию
    sensors: str = ""  # hardware | emulate; пусто — мост запускают отдельно (external)
    devices: dict[str, str] = field(default_factory=dict)  # сигнал -> серийный номер датчика


@dataclass(frozen=True)
class CheckResult:
    discipline: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def _clean_path(raw: str) -> str:
    return raw.strip().strip('"').strip()


def _http_client(url: str, token: str, ca_file: Path | None) -> ConfigSource:
    return HttpStationApi(url, token, ca_file=ca_file, timeout_s=8.0)


class SetupService:
    def __init__(
        self,
        config_path: Path,
        client_factory: ClientFactory = _http_client,
        default_game: str = "",
        sensors: SensorService | None = None,
    ) -> None:
        self.sensors = sensors or SensorService(config_path.parent)
        self._path = config_path
        self._client_factory = client_factory
        self._default_game = default_game  # игра, вложенная в установщик: подставляется в форму

    # --- что уже сохранено ----------------------------------------------------------------

    @property
    def token_path(self) -> Path:
        return self._path.parent / TOKEN_FILE

    def saved_token(self) -> str:
        try:
            return self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def defaults(self) -> dict[str, Any]:
        """Прежние значения для формы. Токен не отдаётся: только признак, что он сохранён."""
        form: dict[str, Any] = {
            "server_url": "",
            "game_path": self._default_game,
            "ca_file": "",
            "camera": "",
            "sensors": "hardware" if self.sensors.available else "",
            "devices": self.sensors.saved_devices(),
            "has_token": bool(self.saved_token()),
        }
        try:
            config = load_config(self._path)
        except ConfigError:
            return form
        form["server_url"] = config.server_url
        saved_game = config.game_command[0]
        # Сохранённая игра пропала (например, переустановка в другую папку): берём вложенную.
        form["game_path"] = (
            saved_game
            if Path(saved_game).is_file() or not self._default_game
            else self._default_game
        )
        form["ca_file"] = str(config.ca_file) if config.ca_file else ""
        form["camera"] = config.camera_name or ""
        if config.bridge_mode in ("hardware", "emulate"):
            form["sensors"] = config.bridge_mode
        elif self.sensors.available:
            form["sensors"] = ""  # админ сознательно оставил внешний мост
        return form

    # --- проверка -------------------------------------------------------------------------

    def _validate(self, form: SetupForm) -> tuple[str, str, Path | None, str | None]:
        """(адрес, токен, сертификат, ошибка)."""
        url = form.server_url.strip().rstrip("/")
        if not url:
            return url, "", None, URL_REQUIRED
        if not url.startswith("https://"):
            return url, "", None, URL_SCHEME
        token = form.token.strip() or self.saved_token()
        if not token:
            return url, token, None, TOKEN_REQUIRED
        if len(token) < MIN_TOKEN_LENGTH:
            return url, token, None, TOKEN_SHORT
        game = _clean_path(form.game_path)
        if not game:
            return url, token, None, GAME_REQUIRED
        if not Path(game).is_file():
            return url, token, None, GAME_MISSING
        ca_text = _clean_path(form.ca_file)
        ca_file = Path(ca_text) if ca_text else None
        if ca_file is not None and not ca_file.is_file():
            return url, token, ca_file, CERT_MISSING
        return url, token, ca_file, None

    def check(self, form: SetupForm) -> CheckResult:
        url, token, ca_file, error = self._validate(form)
        if error:
            return CheckResult(None, error)
        try:
            client = self._client_factory(url, token, ca_file)
        except (ssl.SSLError, OSError):
            return CheckResult(None, CERT_BAD)
        try:
            config = client.get_config()
        except Unauthorized:
            return CheckResult(None, UNAUTHORIZED)
        except Offline as exc:
            hint = CERT_REJECTED if "CERTIFICATE_VERIFY_FAILED" in str(exc) else OFFLINE
            return CheckResult(None, hint)
        except StationApiError as exc:
            return CheckResult(None, f"Сервер ответил ошибкой: {exc}")
        finally:
            client.close()
        return CheckResult(config.discipline, self._sensor_problem(form, config.discipline))

    def _sensor_problem(self, form: SetupForm, discipline: str) -> str | None:
        if form.sensors not in ("", "hardware", "emulate"):
            return SENSORS_MODE
        if form.sensors and not self.sensors.available:
            return NO_BRIDGE_IN_BUILD
        if form.sensors == "hardware":
            missing = missing_roles(discipline, form.devices)
            if missing:
                return SENSORS_MISSING.format(roles=", ".join(ROLE_TITLES[r] for r in missing))
            if duplicate_serials(discipline, form.devices):
                return SENSORS_DUPLICATE
        return None

    # --- запись ---------------------------------------------------------------------------

    def save(self, form: SetupForm) -> None:
        """Записать токен и `launcher.toml` рядом друг с другом. Бросает `ConfigError`."""
        url, token, ca_file, error = self._validate(form)
        if error:
            raise ConfigError(error)
        game = Path(_clean_path(form.game_path))
        folder = self._path.parent
        folder.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Записано экраном настройки стенда. Дисциплину сообщает сервер по токену.",
            f"server_url = {_toml(url)}",
            f"token_file = {_toml(TOKEN_FILE)}",
            'data_dir = "data"',
        ]
        if ca_file is not None:
            lines.append(f"ca_file = {_toml(str(ca_file))}")
        camera = form.camera.strip()
        if camera:
            lines.append(f"camera_name = {_toml(camera)}")
        lines += [
            "",
            "[game]",
            f"command = [{_toml(str(game))}]",
            f"workdir = {_toml(str(game.parent))}",
            "",
        ]
        if form.sensors in ("hardware", "emulate"):
            lines += ["[bridge]", f'mode = "{form.sensors}"', ""]
            if form.sensors == "hardware":
                self.sensors.save_devices(form.devices)
        _atomic_write(self.token_path, token + "\n", private=True)
        _atomic_write(self._path, "\n".join(lines), private=False)
        tomllib.loads(self._path.read_text(encoding="utf-8"))  # записали читаемый файл


def _toml(value: str) -> str:
    """Строка TOML: JSON-экранирование подходит для базовых строк (кавычки, `\\`)."""
    return json.dumps(value, ensure_ascii=False)


def _atomic_write(path: Path, text: str, *, private: bool) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    if private and os.name != "nt":
        temp.chmod(0o600)
    temp.replace(path)
