"""Сохранение калибровки моста на диск: чистые типы, проверка и файловое хранилище.

Калибровка живёт в источнике сигнала, но процесс моста могут перезапустить (сбой, лаунчер
перезапускает его сам). Параметры шкалы пишутся в `calibration.json` после каждого успешного
шага и читаются при старте. Файл, которому нельзя верить (битый, просроченный, от другого метода
ЭЭГ или профиля, с неверными числами), игнорируется и стирается: калибровку лучше пройти заново,
чем играть на чужой шкале.

Модуль не знает ни датчиков, ни сокета: `HardwareSource` собирает записи и применяет проверенные.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast, get_args

from .source import EegMethod

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILE_NAME = "calibration.json"
DEFAULT_TTL_H = 4.0
MAX_FILE_BYTES = 64 * 1024
EMG_FS_TOLERANCE = 0.1  # допуск к номинальной частоте ЭМГ: датчик может мерить чуть иначе
MAX_FUTURE_S = (
    60.0  # метка времени из будущего дальше этого значения - часы сбились, файлу не верим
)

_EEG_METHODS = frozenset(get_args(EegMethod))


@dataclass(frozen=True)
class EmgScale:
    """Шкала ЭМГ: уровень RMS покоя и максимума."""

    rest: float
    peak: float
    fs: float


@dataclass(frozen=True)
class EegScale:
    """Шкала ЭЭГ-альфа: относительная альфа, дающая 0 и 1."""

    low: float
    high: float
    fs: float


Scale = EmgScale | EegScale


@dataclass(frozen=True)
class Stamped:
    """Шкала и время её калибровки (секунды Unix)."""

    scale: Scale
    at: float


@dataclass(frozen=True)
class CalibrationRecord:
    eeg_method: EegMethod | None
    signals: dict[str, Stamped]


class CalibrationStore(Protocol):
    def load(self) -> CalibrationRecord | None:
        """Сохранённая запись; нет файла или он нечитаем - None (нечитаемый стирается)."""
        ...

    def save(self, record: CalibrationRecord) -> None:
        """Заменить запись целиком; `OSError`, если записать не удалось (прежняя цела)."""
        ...

    def clear(self) -> None: ...


class MemoryStore:
    """Хранилище в памяти: для тестов и для моста без каталога данных."""

    def __init__(self) -> None:
        self.record: CalibrationRecord | None = None

    def load(self) -> CalibrationRecord | None:
        return self.record

    def save(self, record: CalibrationRecord) -> None:
        self.record = record

    def clear(self) -> None:
        self.record = None


def same_scale(a: Scale, b: Scale) -> bool:
    """Одна и та же шкала: сравниваются параметры, частота дискретизации не в счёт."""
    if isinstance(a, EmgScale) and isinstance(b, EmgScale):
        return (a.rest, a.peak) == (b.rest, b.peak)
    if isinstance(a, EegScale) and isinstance(b, EegScale):
        return (a.low, a.high) == (b.low, b.high)
    return False


def _finite(x: float) -> bool:
    return math.isfinite(x)


def _scale_problem(name: str, scale: Scale) -> str | None:
    if isinstance(scale, EmgScale):
        if name == "eeg":
            return "для eeg нужна шкала ЭЭГ"
        if not (_finite(scale.rest) and _finite(scale.peak) and _finite(scale.fs)):
            return "числа не конечны"
        if scale.rest < 0 or not scale.peak > scale.rest:
            return "peak должен быть больше rest"
    else:
        if name != "eeg":
            return f"для {name} нужна шкала ЭМГ"
        if not (_finite(scale.low) and _finite(scale.high) and _finite(scale.fs)):
            return "числа не конечны"
        if not scale.low < scale.high:
            return "low должен быть меньше high"
    return None if scale.fs > 0 else "частота дискретизации должна быть положительной"


def record_problem(
    record: CalibrationRecord,
    *,
    now: float,
    ttl_s: float,
    signals: Collection[str],
    eeg_method: EegMethod | None,
    eeg_fs: float,
    emg_fs: float,
) -> str | None:
    """Почему запись нельзя применять к этому мосту; None - можно.

    `eeg_method` - метод текущего запуска (None, если в профиле нет ЭЭГ).
    """
    if not record.signals:
        return "пустая запись"
    if record.eeg_method != eeg_method:
        return f"метод ЭЭГ {record.eeg_method} вместо {eeg_method}"
    for name, stamped in record.signals.items():
        if name not in signals:
            return f"сигнала {name} нет в профиле"
        if problem := _scale_problem(name, stamped.scale):
            return f"{name}: {problem}"
        if not _finite(stamped.at):
            return f"{name}: время калибровки не число"
        if now - stamped.at > ttl_s:
            return f"{name}: калибровка устарела"
        if stamped.at - now > MAX_FUTURE_S:
            return f"{name}: время калибровки в будущем"
        if isinstance(stamped.scale, EegScale) and stamped.scale.fs != eeg_fs:
            return f"{name}: другая частота дискретизации"
        if isinstance(stamped.scale, EmgScale) and not (
            abs(stamped.scale.fs - emg_fs) <= EMG_FS_TOLERANCE * emg_fs
        ):
            return f"{name}: другая частота дискретизации"
    return None


def _num(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"не число: {raw!r}")
    try:
        value = float(raw)
    except OverflowError as exc:  # целое из сотен цифр
        raise ValueError("число слишком велико") from exc
    if not math.isfinite(value):
        raise ValueError(f"число не конечно: {raw!r}")
    return value


def _parse_signal(name: str, raw: object) -> Stamped:
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: не объект")
    at = _num(raw.get("calibrated_at"))
    fs = _num(raw.get("fs"))
    scale: Scale
    if raw.get("kind") == "eeg":
        scale = EegScale(_num(raw.get("low")), _num(raw.get("high")), fs)
    elif raw.get("kind") == "emg":
        scale = EmgScale(_num(raw.get("rest")), _num(raw.get("peak")), fs)
    else:
        raise ValueError(f"{name}: неизвестный вид шкалы")
    return Stamped(scale, at)


def parse_record(text: str) -> CalibrationRecord:
    """`ValueError`, если текст не запись текущей версии."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"не JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("другая версия файла")
    method = data.get("eeg_method")
    if method is not None and method not in _EEG_METHODS:
        raise ValueError(f"неизвестный метод ЭЭГ: {method!r}")
    raw_signals = data.get("signals")
    if not isinstance(raw_signals, dict):
        raise ValueError("нет signals")
    signals = {str(name): _parse_signal(str(name), raw) for name, raw in raw_signals.items()}
    return CalibrationRecord(cast(EegMethod | None, method), signals)


def dump_record(record: CalibrationRecord) -> str:
    signals: dict[str, dict[str, Any]] = {}
    for name, stamped in record.signals.items():
        scale = stamped.scale
        if isinstance(scale, EmgScale):
            body: dict[str, Any] = {"kind": "emg", "rest": scale.rest, "peak": scale.peak}
        else:
            body = {"kind": "eeg", "low": scale.low, "high": scale.high}
        body["fs"] = scale.fs
        body["calibrated_at"] = stamped.at
        signals[name] = body
    payload = {
        "schema_version": SCHEMA_VERSION,
        "eeg_method": record.eeg_method,
        "signals": signals,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)


class FileCalibrationStore:
    """`calibration.json` в каталоге данных; запись атомарна, права только пользователю."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._path = directory / FILE_NAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> CalibrationRecord | None:
        try:
            with self._path.open("rb") as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                log.warning("файл калибровки больше %d байт, стёрт", MAX_FILE_BYTES)
                self.clear()
                return None
            text = raw.decode("utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("файл калибровки нечитаем (%s), стёрт", exc)
            self.clear()
            return None
        try:
            return parse_record(text)
        except (ValueError, RecursionError, OverflowError, TypeError) as exc:
            log.warning("файл калибровки повреждён (%s), стёрт", exc)
            self.clear()
            return None

    def save(self, record: CalibrationRecord) -> None:
        text = dump_record(record)
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._dir, prefix=FILE_NAME + ".", suffix=".tmp")
        # mkstemp: права 0600 на POSIX; на Windows наследуются от ACL каталога.
        # Персональных данных в файле нет, только числа шкал и время.
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError, OSError):
            self._path.unlink()
