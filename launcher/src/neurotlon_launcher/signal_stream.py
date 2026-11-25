"""Кадры `GET /api/signals`: живые значения датчиков для графика проверки сигнала.

Окно (Electron) ходит только на порт лаунчера, поэтому значения моста идут через ядро.
Кадр собирается из недавних `sample` и событий `burst` связи с мостом; курсор у каждого
подключения свой, так что несколько слушателей не мешают друг другу.

Форма кадра (JSON, одна строка в `data:` SSE):

    {"gen": 3,
     "samples": [{"t_ms": 120450, "signals": {"emg": {"v": 0.73, "ok": true},
                                              "eeg": {"v": 0.0, "ok": false, "r": "artifact"}}}],
     "bursts": [{"signal": "emg", "t_ms": 120490, "rise": 0.8}]}

`v` — значение 0…1, `ok` — можно ли ему верить, `r` — причина (только при `ok: false`):
`artifact`, `no_contact`, `disconnected`, `stale`, `not_calibrated`. `gen` растёт, когда мост
перезапустился или связь переподключилась (шкала `t_ms` началась заново). `rise` может
отсутствовать.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bridge_link import BridgeLink, SignalBatch

FRAME_SAMPLES = 10  # кадр уходит 10 раз в секунду, значения идут около 50 раз в секунду
VALUE_DIGITS = 3


@dataclass
class SignalCursor:
    """Что уже отправлено одному слушателю."""

    epoch: int = -1
    seq: int = 0
    burst: int = 0


def frame_dict(batch: SignalBatch) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for sample in batch.samples:
        signals: dict[str, dict[str, Any]] = {}
        for name, reading in sample.signals.items():
            item: dict[str, Any] = {"v": round(reading.v, VALUE_DIGITS), "ok": reading.ok}
            if not reading.ok:
                item["r"] = reading.reason
            signals[name] = item
        samples.append({"t_ms": sample.t_ms, "signals": signals})
    bursts: list[dict[str, Any]] = []
    for burst in batch.bursts:
        entry: dict[str, Any] = {"signal": burst.signal, "t_ms": burst.t_ms}
        if burst.rise is not None:
            entry["rise"] = round(burst.rise, VALUE_DIGITS)
        bursts.append(entry)
    return {"gen": batch.generation, "samples": samples, "bursts": bursts}


def next_frame(cursor: SignalCursor, epoch: int, link: BridgeLink | None) -> dict[str, Any] | None:
    """Следующий кадр слушателя или `None`, если слать нечего. Сдвигает `cursor`."""
    if link is None:
        return None
    if cursor.epoch != epoch:  # новая калибровка: старые курсоры не относятся к этой связи
        cursor.epoch, cursor.seq, cursor.burst = epoch, 0, 0
    batch = link.recent(cursor.seq, cursor.burst, FRAME_SAMPLES)
    cursor.seq = batch.cursor
    if batch.bursts:
        cursor.burst = max(cursor.burst, *(b.n for b in batch.bursts))
    if not batch.samples and not batch.bursts:
        return None
    return frame_dict(batch)
