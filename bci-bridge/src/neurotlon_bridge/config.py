"""Настройки моста из `bridge.toml`: серийные номера датчиков и параметры обработки."""

from __future__ import annotations

import dataclasses
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neurotlon_contracts.sensor_devices import DeviceRef, DevicesFormatError, parse_devices

from .calibration_store import DEFAULT_TTL_H
from .processing.alpha import AlphaConfig
from .processing.burst import BurstConfig
from .processing.eeg import EegConfig
from .processing.emg import EmgConfig
from .source import PROFILES

CONFIG_NAME = "bridge.toml"
DEFAULT_SCAN_S = 12.0
MAX_TTL_H = 24.0 * 7


class ConfigError(Exception):
    """Ошибка настроек; сообщение по-русски, для оператора."""


@dataclass(frozen=True)
class CalibrationConfig:
    """Раздел `[calibration]`: сколько часов сохранённой калибровке можно верить."""

    ttl_h: float = DEFAULT_TTL_H

    def __post_init__(self) -> None:
        if not 0 < self.ttl_h < MAX_TTL_H:
            raise ValueError(f"ttl_h: нужно число больше 0 и меньше {MAX_TTL_H:g}")

    @property
    def ttl_s(self) -> float:
        return self.ttl_h * 3600.0


@dataclass(frozen=True)
class BridgeConfig:
    devices: dict[str, DeviceRef] = field(default_factory=dict)
    scan_s: float = DEFAULT_SCAN_S
    emg: EmgConfig = field(default_factory=EmgConfig)
    eeg: EegConfig = field(default_factory=EegConfig)
    burst: BurstConfig = field(default_factory=BurstConfig)
    alpha: AlphaConfig = field(default_factory=AlphaConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)


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
                "и назначьте датчики на экране настройки стенда "
                "(или впишите их вручную, список: neurotlon-bridge --scan)"
            )
    elif not path.is_file():
        raise ConfigError(f"файл настроек не найден: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: не удалось разобрать файл: {exc}") from exc
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> BridgeConfig:
    unknown = set(data) - {"devices", "emg", "eeg", "burst", "alpha", "calibration"}
    if unknown:
        raise ConfigError(f"неизвестные разделы: {', '.join(sorted(unknown))}")
    devices_raw = dict(data.get("devices", {}))
    scan_s = devices_raw.pop("scan_s", DEFAULT_SCAN_S)
    if isinstance(scan_s, bool) or not isinstance(scan_s, int | float) or scan_s <= 0:
        raise ConfigError("[devices] scan_s: нужно положительное число")
    try:
        devices = parse_devices(devices_raw)
    except DevicesFormatError as exc:
        raise ConfigError(str(exc)) from exc
    config = BridgeConfig(
        devices=devices,
        scan_s=float(scan_s),
        emg=_section(EmgConfig, data.get("emg", {}), "emg"),
        eeg=_section(EegConfig, data.get("eeg", {}), "eeg"),
        burst=_section(BurstConfig, data.get("burst", {}), "burst"),
        alpha=_section(AlphaConfig, data.get("alpha", {}), "alpha"),
        calibration=_section(CalibrationConfig, data.get("calibration", {}), "calibration"),
    )
    if config.alpha.band_high_hz >= config.eeg.sampling_rate / 2:
        raise ConfigError("[alpha] band_high_hz должна быть меньше половины [eeg] sampling_rate")
    return config


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
    try:
        return cls(**values)
    except ValueError as exc:
        raise ConfigError(f"[{name}] {exc}") from exc


def required_devices(profile: str, config: BridgeConfig) -> dict[str, DeviceRef]:
    """Сигнал -> датчик для профиля; не задан или повторяется — `ConfigError`."""
    result: dict[str, DeviceRef] = {}
    for signal in PROFILES[profile]:
        ref = config.devices.get(signal)
        if ref is None:
            raise ConfigError(
                f"для профиля {profile} в {CONFIG_NAME} не назначен датчик: [devices] {signal}"
            )
        result[signal] = ref
    refs = list(result.values())
    if any(a.same_device(b) for i, a in enumerate(refs) for b in refs[i + 1 :]):
        raise ConfigError("один и тот же датчик указан для двух сигналов")
    return result
