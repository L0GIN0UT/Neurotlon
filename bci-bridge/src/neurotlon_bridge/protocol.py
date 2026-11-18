"""Сообщения протокола «мост → игра» (shared/bridge-protocol.md), NDJSON."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast, get_args

from .source import (
    CalibrationStatus,
    CalibrationStep,
    InvalidReason,
    Reading,
    SensorState,
)

PROTOCOL_VERSION = 1

_SIGNALS = frozenset({"eeg", "emg", "emg_left", "emg_right"})
_STATES = frozenset(get_args(SensorState))
_STEPS = frozenset(get_args(CalibrationStep))
_STATUSES = frozenset(get_args(CalibrationStatus))
_REASONS = frozenset(get_args(InvalidReason))


@dataclass(frozen=True)
class Hello:
    signals: tuple[tuple[str, SensorState], ...]
    protocol: int = PROTOCOL_VERSION


@dataclass(frozen=True)
class Sample:
    t_ms: int
    signals: dict[str, Reading]


@dataclass(frozen=True)
class Sensor:
    signal: str
    state: SensorState
    battery: int | None = None


@dataclass(frozen=True)
class Calibration:
    signal: str
    step: CalibrationStep
    status: CalibrationStatus
    progress: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Calibrate:
    signal: str
    step: CalibrationStep


@dataclass(frozen=True)
class Reset:
    pass


Message = Hello | Sample | Sensor | Calibration | Calibrate | Reset


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _reading_to_dict(reading: Reading) -> dict[str, Any]:
    out: dict[str, Any] = {"value": _clamp(reading.value), "valid": reading.valid}
    if not reading.valid:
        out["reason"] = reading.reason or "disconnected"
    return out


def to_dict(msg: Message) -> dict[str, Any]:
    match msg:
        case Hello():
            return {
                "type": "hello",
                "protocol": msg.protocol,
                "signals": [{"name": n, "state": s} for n, s in msg.signals],
            }
        case Sample():
            return {
                "type": "sample",
                "t_ms": msg.t_ms,
                "signals": {n: _reading_to_dict(r) for n, r in msg.signals.items()},
            }
        case Sensor():
            out: dict[str, Any] = {"type": "sensor", "signal": msg.signal, "state": msg.state}
            if msg.battery is not None:
                out["battery"] = msg.battery
            return out
        case Calibration():
            out = {
                "type": "calibration",
                "signal": msg.signal,
                "step": msg.step,
                "status": msg.status,
            }
            if msg.progress is not None:
                out["progress"] = _clamp(msg.progress)
            if msg.reason is not None:
                out["reason"] = msg.reason
            return out
        case Calibrate():
            return {"type": "calibrate", "signal": msg.signal, "step": msg.step}
        case Reset():
            return {"type": "reset"}


def encode(msg: Message) -> bytes:
    """Одна NDJSON-строка в UTF-8."""
    text = json.dumps(to_dict(msg), separators=(",", ":"), ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def _enum(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"bad {field}: {value!r}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"bad {field}: {value!r}")
    return float(value)


def _parse_reading(raw: object) -> Reading:
    if not isinstance(raw, dict):
        raise ValueError("bad reading")
    valid = raw.get("valid")
    if not isinstance(valid, bool):
        raise ValueError("bad valid")
    value = _clamp(_number(raw.get("value"), "value"))
    reason = None
    if not valid:
        reason = cast(InvalidReason, _enum(raw.get("reason"), _REASONS, "reason"))
    return Reading(value, valid, reason)


def _step(data: dict[str, Any]) -> CalibrationStep:
    return cast(CalibrationStep, _enum(data.get("step"), _STEPS, "step"))


def _state(value: object) -> SensorState:
    return cast(SensorState, _enum(value, _STATES, "state"))


def _reject_constant(name: str) -> None:
    raise ValueError(f"недопустимая константа JSON: {name}")


def decode(line: bytes | str) -> Message | None:
    """Разбирает строку. Неизвестный `type` -> None; битое сообщение -> ValueError.

    Неизвестные поля игнорируются.
    """
    try:
        return _decode(line)
    except (OverflowError, RecursionError) as exc:
        raise ValueError(f"invalid message: {exc!r}") from exc


def _decode(line: bytes | str) -> Message | None:
    try:
        data = json.loads(line, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("message is not an object")
    match data.get("type"):
        case "hello":
            raw = data.get("signals")
            if not isinstance(raw, list):
                raise ValueError("bad signals")
            items: list[tuple[str, SensorState]] = []
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("bad signal item")
                items.append((_enum(item.get("name"), _SIGNALS, "name"), _state(item.get("state"))))
            return Hello(tuple(items), int(_number(data.get("protocol"), "protocol")))
        case "sample":
            raw_signals = data.get("signals")
            if not isinstance(raw_signals, dict):
                raise ValueError("bad signals")
            readings = {
                _enum(n, _SIGNALS, "name"): _parse_reading(r) for n, r in raw_signals.items()
            }
            return Sample(int(_number(data.get("t_ms"), "t_ms")), readings)
        case "sensor":
            battery = data.get("battery")
            return Sensor(
                _enum(data.get("signal"), _SIGNALS, "signal"),
                _state(data.get("state")),
                None if battery is None else int(_number(battery, "battery")),
            )
        case "calibration":
            progress = data.get("progress")
            reason = data.get("reason")
            return Calibration(
                _enum(data.get("signal"), _SIGNALS, "signal"),
                _step(data),
                cast(CalibrationStatus, _enum(data.get("status"), _STATUSES, "status")),
                None if progress is None else _number(progress, "progress"),
                reason if isinstance(reason, str) else None,
            )
        case "calibrate":
            return Calibrate(_enum(data.get("signal"), _SIGNALS, "signal"), _step(data))
        case "reset":
            return Reset()
        case _:
            return None
