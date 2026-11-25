"""Отладочный журнал ЭЭГ: один ряд на шаг окна, CSV с ограничением размера.

Нужен, чтобы записать на стенде сессию «спокойно / сосредоточенно / глаза закрыты» и сравнить
сырую относительную альфу с `concentration`. Выключен по умолчанию,
включается в `[debug] eeg_trace` файла `bridge.toml`.
Персональных данных нет: только время, числа и причина.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

log = logging.getLogger(__name__)

TRACE_NAME = "eeg-trace.csv"
HEADER = "wall_time,t_s,phase,rel_alpha,concentration,valid,reason,low,high"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
MIN_MAX_BYTES = 1024


@dataclass(frozen=True)
class TraceRow:
    t_s: float
    phase: str  # calibrating / uncalibrated / live
    rel_alpha: float  # nan: окно с артефактом или значение не посчиталось
    concentration: float  # nan: шкалы ещё нет
    valid: bool
    reason: str  # ok / ptp / jump / no_value
    low: float  # границы калибровки, nan: их ещё нет
    high: float


class TraceSink(Protocol):
    def write(self, row: TraceRow) -> None: ...


def _num(value: float) -> str:
    return f"{value:.6g}" if math.isfinite(value) else ""


class CsvTraceWriter:
    """Пишет `eeg-trace.csv`; при достижении предела старый файл уходит в `.old.csv`.

    На диске не больше двух пределов. Ошибка записи отключает журнал, но не обработку сигнала.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int = DEFAULT_MAX_BYTES,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if max_bytes < MIN_MAX_BYTES:
            raise ValueError(f"max_bytes: не меньше {MIN_MAX_BYTES}")
        self._path = path
        self._max_bytes = max_bytes
        self._wall = wall_clock
        self._file: IO[str] | None = None
        self._size = 0
        self._failed = False

    def write(self, row: TraceRow) -> None:
        if self._failed:
            return
        try:
            if self._file is None or self._size >= self._max_bytes:
                self._open()
            if self._file is None:
                return
            stamp = time.strftime("%H:%M:%S", time.localtime(self._wall()))
            line = (
                f"{stamp},{row.t_s:.3f},{row.phase},{_num(row.rel_alpha)},{_num(row.concentration)},"
                f"{int(row.valid)},{row.reason},{_num(row.low)},{_num(row.high)}\n"
            )
            self._file.write(line)
            self._file.flush()
            self._size += len(line.encode("utf-8"))
        except OSError:
            self._failed = True
            log.warning("журнал ЭЭГ отключён: файл %s недоступен", self._path, exc_info=True)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _open(self) -> None:
        self.close()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
            self._path.replace(self._path.with_suffix(".old.csv"))
        self._file = self._path.open("a", encoding="utf-8", newline="")
        self._size = self._path.stat().st_size
        if self._size == 0:
            self._file.write(HEADER + "\n")
            self._size = len(HEADER) + 1
