"""Сообщения протокола «мост → игра» (shared/bridge-protocol.md), NDJSON."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast, get_args

from .source import (
    BASELINE_MAX_S,
    BASELINE_MIN_S,
    SEGMENT_MAX_S,
    SEGMENT_MIN_S,
    SEGMENTS_MAX_COUNT,
    SEGMENTS_MAX_TOTAL_S,
    SEGMENTS_MIN_COUNT,
    CalibrationStatus,
    CalibrationStep,
    EegMethod,
    Feature,
    InvalidReason,
    Phase,
    Reading,
    Segment,
    SensorState,
)

PROTOCOL_VERSION = 1

_SIGNALS = frozenset({"eeg", "emg", "emg_left", "emg_right"})
_BURST_SIGNALS = frozenset({"emg", "emg_left", "emg_right"})
_STATES = frozenset(get_args(SensorState))
_STEPS = frozenset(get_args(CalibrationStep))
_STATUSES = frozenset(get_args(CalibrationStatus))
_REASONS = frozenset(get_args(InvalidReason))
_PHASES = frozenset(get_args(Phase))
_EEG_METHODS = frozenset(get_args(EegMethod))
_FEATURES = frozenset(get_args(Feature))


@dataclass(frozen=True)
class Hello:
    signals: tuple[tuple[str, SensorState], ...]
    protocol: int = PROTOCOL_VERSION
    features: tuple[Feature, ...] | None = None
    eeg_method: EegMethod | None = None


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
    segment: int | None = None
    phase: Phase | None = None
    phase_left_s: float | None = None


@dataclass(frozen=True)
class Burst:
    """Резкое сокращение мышцы; `seq` растёт отдельно для каждого сигнала."""

    signal: str
    t_ms: int
    seq: int
    rise: float | None = None


@dataclass(frozen=True)
class Calibrate:
    signal: str
    step: CalibrationStep
    segments: tuple[Segment, ...] | None = None
    duration_s: float | None = None


@dataclass(frozen=True)
class Reset:
    pass


Message = Hello | Sample | Sensor | Calibration | Burst | Calibrate | Reset


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
            hello: dict[str, Any] = {
                "type": "hello",
                "protocol": msg.protocol,
                "signals": [{"name": n, "state": s} for n, s in msg.signals],
            }
            if msg.features is not None:
                hello["features"] = list(msg.features)
            if msg.eeg_method is not None:
                hello["eeg_method"] = msg.eeg_method
            return hello
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
            if msg.segment is not None:
                out["segment"] = msg.segment
            if msg.phase is not None:
                out["phase"] = msg.phase
            if msg.phase_left_s is not None:
                out["phase_left_s"] = max(0.0, msg.phase_left_s)
            return out
        case Burst():
            burst: dict[str, Any] = {
                "type": "burst",
                "signal": msg.signal,
                "t_ms": msg.t_ms,
                "seq": msg.seq,
            }
            if msg.rise is not None:
                burst["rise"] = _clamp(msg.rise)
            return burst
        case Calibrate():
            request: dict[str, Any] = {
                "type": "calibrate",
                "signal": msg.signal,
                "step": msg.step,
            }
            if msg.segments is not None:
                request["segments"] = [{"phase": s.phase, "s": s.s} for s in msg.segments]
            if msg.duration_s is not None:
                request["duration_s"] = msg.duration_s
            return request
        case Reset():
            return {"type": "reset"}


def encode(msg: Message) -> bytes:
    """Одна NDJSON-строка в UTF-8."""
    text = json.dumps(to_dict(msg), separators=(",", ":"), ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def calibrate_problem(msg: Calibrate) -> str | None:
    """Почему запрос не годится (текст для `calibration failed`); None — запрос допустим.

    Границы заданы в схеме, но сумму длин сегментов она проверить не может. Поле, не
    относящееся к шагу (`segments` вне `cycle`, `duration_s` вне `baseline`), игнорируется.
    """
    if msg.step == "cycle" and msg.segments is not None:
        segments = msg.segments
        if not SEGMENTS_MIN_COUNT <= len(segments) <= SEGMENTS_MAX_COUNT:
            return f"сегментов должно быть от {SEGMENTS_MIN_COUNT} до {SEGMENTS_MAX_COUNT}"
        if any(not SEGMENT_MIN_S <= s.s <= SEGMENT_MAX_S for s in segments):
            return f"длина сегмента должна быть от {SEGMENT_MIN_S:g} до {SEGMENT_MAX_S:g} с"
        if sum(s.s for s in segments) > SEGMENTS_MAX_TOTAL_S:
            return f"сумма сегментов больше {SEGMENTS_MAX_TOTAL_S:g} с"
        if {s.phase for s in segments} != _PHASES:
            return "нужен хотя бы один сегмент напряжения и один расслабления"
    if (
        msg.step == "baseline"
        and msg.duration_s is not None
        and not BASELINE_MIN_S <= msg.duration_s <= BASELINE_MAX_S
    ):
        return f"duration_s должно быть от {BASELINE_MIN_S:g} до {BASELINE_MAX_S:g} с"
    return None


def _enum(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"bad {field}: {value!r}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"bad {field}: {value!r}")
    return float(value)


def _optional_number(data: dict[str, Any], field: str) -> float | None:
    value = data.get(field)
    return None if value is None else _number(value, field)


def _optional_int(data: dict[str, Any], field: str) -> int | None:
    value = _optional_number(data, field)
    return None if value is None else int(value)


def _optional_phase(value: object) -> Phase | None:
    """Неизвестная фаза из будущей версии не ломает сообщение."""
    return cast(Phase, value) if isinstance(value, str) and value in _PHASES else None


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


def _parse_segments(raw: object) -> tuple[Segment, ...] | None:
    # Unity JsonUtility не умеет опускать поля: пустой массив значит «не задано»
    if raw is None or raw == []:
        return None
    if not isinstance(raw, list):
        raise ValueError("bad segments")
    segments: list[Segment] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("bad segment")
        phase = cast(Phase, _enum(item.get("phase"), _PHASES, "phase"))
        segments.append(Segment(phase, _number(item.get("s"), "s")))
    return tuple(segments)


def _step(data: dict[str, Any]) -> CalibrationStep:
    return cast(CalibrationStep, _enum(data.get("step"), _STEPS, "step"))


def _state(value: object) -> SensorState:
    return cast(SensorState, _enum(value, _STATES, "state"))


def _reject_constant(name: str) -> None:
    raise ValueError(f"недопустимая константа JSON: {name}")


def decode(line: bytes | str) -> Message | None:
    """Разбирает строку. Неизвестный `type` -> None; битое сообщение -> ValueError.

    Неизвестные поля игнорируются; неизвестное имя сигнала внутри `hello` и `sample`
    пропускается, остальное сообщение сохраняется.
    """
    try:
        return _decode(line)
    except (OverflowError, RecursionError) as exc:
        raise ValueError(f"invalid message: {exc!r}") from exc


def _decode_hello(data: dict[str, Any]) -> Hello:
    raw = data.get("signals")
    if not isinstance(raw, list):
        raise ValueError("bad signals")
    items: list[tuple[str, SensorState]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("bad signal item")
        name = item.get("name")
        if isinstance(name, str) and name not in _SIGNALS:
            continue
        items.append((_enum(name, _SIGNALS, "name"), _state(item.get("state"))))
    raw_features = data.get("features")
    features = (
        tuple(cast(Feature, f) for f in raw_features if isinstance(f, str) and f in _FEATURES)
        if isinstance(raw_features, list)
        else None
    )
    method = data.get("eeg_method")
    eeg_method = (
        cast(EegMethod, method) if isinstance(method, str) and method in _EEG_METHODS else None
    )
    return Hello(tuple(items), int(_number(data.get("protocol"), "protocol")), features, eeg_method)


def _decode_burst(data: dict[str, Any]) -> Burst | None:
    signal = data.get("signal")
    if isinstance(signal, str) and signal not in _BURST_SIGNALS:
        return None  # сигнал из будущей версии
    rise = _optional_number(data, "rise")
    return Burst(
        _enum(signal, _BURST_SIGNALS, "signal"),
        int(_number(data.get("t_ms"), "t_ms")),
        int(_number(data.get("seq"), "seq")),
        None if rise is None else _clamp(rise),
    )


def _decode(line: bytes | str) -> Message | None:
    try:
        data = json.loads(line, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("message is not an object")
    match data.get("type"):
        case "hello":
            return _decode_hello(data)
        case "sample":
            raw_signals = data.get("signals")
            if not isinstance(raw_signals, dict):
                raise ValueError("bad signals")
            readings = {n: _parse_reading(r) for n, r in raw_signals.items() if n in _SIGNALS}
            return Sample(int(_number(data.get("t_ms"), "t_ms")), readings)
        case "sensor":
            battery = data.get("battery")
            return Sensor(
                _enum(data.get("signal"), _SIGNALS, "signal"),
                _state(data.get("state")),
                None if battery is None else int(_number(battery, "battery")),
            )
        case "calibration":
            reason = data.get("reason")
            return Calibration(
                _enum(data.get("signal"), _SIGNALS, "signal"),
                _step(data),
                cast(CalibrationStatus, _enum(data.get("status"), _STATUSES, "status")),
                _optional_number(data, "progress"),
                reason if isinstance(reason, str) else None,
                _optional_int(data, "segment"),
                _optional_phase(data.get("phase")),
                _optional_number(data, "phase_left_s"),
            )
        case "burst":
            return _decode_burst(data)
        case "calibrate":
            duration = _optional_number(data, "duration_s")
            return Calibrate(
                _enum(data.get("signal"), _SIGNALS, "signal"),
                _step(data),
                _parse_segments(data.get("segments")),
                duration or None,  # 0 — незаданное поле Unity
            )
        case "reset":
            return Reset()
        case _:
            return None
