"""Настройки стенда из `launcher.toml`. Сам токен в файл настроек не пишется."""

from __future__ import annotations

import logging
import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISCIPLINES = ("darts", "football", "pong")
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8765
DEFAULT_FALLBACK_DURATION_S = 240

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Ошибка настроек; сообщение по-русски, для оператора."""


def warn_if_token_is_shared(path: Path) -> None:
    """Предупреждение в журнал: токен читают другие пользователи ПК (на Windows пропуск)."""
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        log.warning("token file %s is readable by other users, run chmod 600", path)


@dataclass(frozen=True)
class LauncherConfig:
    server_url: str
    token_file: Path
    discipline: str | None  # None: станция узнаёт её у сервера по токену
    game_command: tuple[str, ...]
    game_workdir: Path | None
    bridge_host: str
    bridge_port: int
    data_dir: Path
    camera_index: int
    camera_name: str | None = None  # имя камеры для QR в веб-интерфейсе; None — по умолчанию
    ca_file: Path | None = None
    allow_insecure_http: bool = False
    fallback_duration_s: int = DEFAULT_FALLBACK_DURATION_S

    def read_token(self) -> str:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"не удалось прочитать файл токена {self.token_file}: {exc}") from exc
        if not token:
            raise ConfigError(f"файл токена пуст: {self.token_file}")
        warn_if_token_is_shared(self.token_file)
        return token


def load_config(path: Path) -> LauncherConfig:
    if not path.is_file():
        raise ConfigError(f"файл настроек не найден: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: не удалось разобрать файл: {exc}") from exc
    return parse_config(data, base_dir=path.resolve().parent)


def _string(data: dict[str, Any], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"в настройках нет поля «{key}» или оно не строка")
    return value


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"раздел [{key}] должен быть таблицей")
    return value


def parse_config(data: dict[str, Any], base_dir: Path) -> LauncherConfig:
    """Относительные пути считаются от папки с `launcher.toml`."""

    def path_of(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else base_dir / path

    discipline = data.get("discipline")
    if discipline is not None and discipline not in DISCIPLINES:
        raise ConfigError(f"discipline должна быть одной из: {', '.join(DISCIPLINES)}")
    game = _table(data, "game")
    command = game.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) for part in command)
    ):
        raise ConfigError("в [game] нужен command — непустой список строк")
    workdir = game.get("workdir")
    if workdir is not None and not isinstance(workdir, str):
        raise ConfigError("game.workdir должен быть строкой")
    bridge = _table(data, "bridge")
    host = bridge.get("host", DEFAULT_BRIDGE_HOST)
    port = bridge.get("port", DEFAULT_BRIDGE_PORT)
    if (
        not isinstance(host, str)
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
    ):
        raise ConfigError("в [bridge] host — строка, port — число 1…65535")
    camera = data.get("camera_index", 0)
    if not isinstance(camera, int) or isinstance(camera, bool) or camera < 0:
        raise ConfigError("camera_index должен быть целым числом, не меньше 0")
    camera_name = data.get("camera_name")
    if camera_name is not None and (not isinstance(camera_name, str) or not camera_name.strip()):
        raise ConfigError("camera_name должен быть непустой строкой — именем камеры")
    server_url = _string(data, "server_url").rstrip("/")
    insecure = data.get("allow_insecure_http", False)
    if not isinstance(insecure, bool):
        raise ConfigError("allow_insecure_http должен быть true или false")
    if server_url.startswith("http://"):
        if not insecure:
            raise ConfigError(
                "server_url начинается с http://: токен станции пойдёт по сети открыто. "
                "Используйте https:// (и ca_file для локального сертификата); "
                "для разработки можно allow_insecure_http = true"
            )
        log.warning("server_url uses plain http: the station token is sent unencrypted")
    elif not server_url.startswith("https://"):
        raise ConfigError("server_url должен начинаться с https://")
    ca_file = data.get("ca_file")
    if ca_file is not None and not isinstance(ca_file, str):
        raise ConfigError("ca_file должен быть строкой — путём к сертификату")
    fallback = data.get("fallback_duration_s", DEFAULT_FALLBACK_DURATION_S)
    if not isinstance(fallback, int) or isinstance(fallback, bool) or not 10 <= fallback <= 3600:
        raise ConfigError("fallback_duration_s должен быть целым числом 10…3600")
    return LauncherConfig(
        server_url=server_url,
        token_file=path_of(_string(data, "token_file")),
        discipline=discipline,
        game_command=tuple(command),
        game_workdir=path_of(workdir) if workdir else None,
        bridge_host=host,
        bridge_port=port,
        data_dir=path_of(_string(data, "data_dir", "data")),
        camera_index=camera,
        camera_name=camera_name.strip() if camera_name else None,
        ca_file=path_of(ca_file) if ca_file else None,
        allow_insecure_http=insecure,
        fallback_duration_s=fallback,
    )
