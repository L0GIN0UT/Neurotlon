"""Настройки моста из `bridge.toml`: серийные номера датчиков и параметры обработки."""

from __future__ import annotations

import dataclasses
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .processing.eeg import EegConfig
from .processing.emg import EmgConfig
from .source import PROFILES

CONFIG_NAME = "bridge.toml"
DEVICE_KEYS = ("eeg", "emg", "emg_left", "emg_right")
DEFAULT_SCAN_S = 12.0


class ConfigError(Exception):
    """Ошибка настроек; сообщение по-русски, для оператора."""


@dataclass(frozen=True)
class BridgeConfig:
    devices: dict[str, str] = field(default_factory=dict)
    scan_s: float = DEFAULT_SCAN_S
    emg: EmgConfig = field(default_factory=EmgConfig)
    eeg: EegConfig = field(default_factory=EegConfig)


def default_config_path() -> Path | None:
    """`bridge.toml` в текущей папке, затем рядом с исполняемым файлом."""
    for folder in (Path.cwd(), Path(sys.executable).resolve().parent):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None) -> BridgeConfig:
    """`path=None` — искать по умолчанию; файла нет — `ConfigError`."""
    if path is None:
        path = default_config_path()
        if path is None:
            raise ConfigError(
                f"не найден {CONFIG_NAME}: скопируйте bridge.example.toml в {CONFIG_NAME} "
                "и впишите серийные номера датчиков (список: neurotlon-bridge --scan)"
            )
    elif not path.is_file():
        raise ConfigError(f"файл настроек не найден: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: не удалось разобрать файл: {exc}") from exc
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> BridgeConfig:
    unknown = set(data) - {"devices", "emg", "eeg"}
    if unknown:
        raise ConfigError(f"неизвестные разделы: {', '.join(sorted(unknown))}")
    devices_raw = dict(data.get("devices", {}))
    scan_s = devices_raw.pop("scan_s", DEFAULT_SCAN_S)
    if isinstance(scan_s, bool) or not isinstance(scan_s, int | float) or scan_s <= 0:
        raise ConfigError("[devices] scan_s: нужно положительное число")
    devices: dict[str, str] = {}
    for key, value in devices_raw.items():
        if key not in DEVICE_KEYS:
            raise ConfigError(f"[devices] неизвестный ключ: {key}")
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ConfigError(f"[devices] {key}: нужна строка с серийным номером")
        if str(value).strip():
            devices[key] = str(value).strip()
    return BridgeConfig(
        devices=devices,
        scan_s=float(scan_s),
        emg=_section(EmgConfig, data.get("emg", {}), "emg"),
        eeg=_section(EegConfig, data.get("eeg", {}), "eeg"),
    )


def _section[T](cls: type[T], raw: dict[str, Any], name: str) -> T:
    """Собрать dataclass из таблицы, отвергая неизвестные ключи и неверные типы."""
    defaults = {f.name: f.default for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    values: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in defaults:
            raise ConfigError(f"[{name}] неизвестный ключ: {key}")
        default = defaults[key]
        if isinstance(value, bool):
            raise ConfigError(f"[{name}] {key}: нужно число")
        if isinstance(default, int):
            if not isinstance(value, int):
                raise ConfigError(f"[{name}] {key}: нужно целое число")
            values[key] = value
        else:
            if not isinstance(value, int | float):
                raise ConfigError(f"[{name}] {key}: нужно число")
            values[key] = float(value)
    return cls(**values)


def required_devices(profile: str, config: BridgeConfig) -> dict[str, str]:
    """Сигнал -> серийный номер для профиля; не задан или повторяется — `ConfigError`."""
    result: dict[str, str] = {}
    for signal in PROFILES[profile]:
        serial = config.devices.get(signal)
        if not serial:
            raise ConfigError(
                f"для профиля {profile} в {CONFIG_NAME} не задан серийный номер: [devices] {signal}"
            )
        result[signal] = serial
    folded = [s.lower() for s in result.values()]
    if len(set(folded)) != len(folded):
        raise ConfigError("один и тот же серийный номер указан для двух сигналов")
    return result
