"""Досылка результатов из буфера: по порядку, с нарастающей паузой при неудаче."""

from __future__ import annotations

import logging
import threading
from typing import Any, Protocol

from .api import ApiProblem, Offline, StationApiError
from .outbox import Outbox

log = logging.getLogger(__name__)

BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0)
POLL_S = 5.0
STOP_TIMEOUT_S = 10.0  # дольше одного запроса с таймаутом 3 с
# Сервер окончательно не принял результат (в том числе чужая дисциплина или неизвестный
# участник): повтор бессмыслен, решает оператор.
REJECT_STATUSES = frozenset({403, 404, 409, 422})


def backoff_delay(failures: int) -> float:
    """Пауза после `failures`-й подряд неудачной попытки (с нуля)."""
    return BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]


class ResultSubmitter(Protocol):
    def submit_result(self, payload: dict[str, Any]) -> None: ...


class Sender:
    def __init__(self, outbox: Outbox, api: ResultSubmitter, *, poll_s: float = POLL_S) -> None:
        self._outbox = outbox
        self._api = api
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def send_pending(self) -> bool:
        """Один проход по очереди. `False`, если остановились на ошибке и нужен повтор.

        Порядок сохраняется: на первой ошибке повтора проход прекращается. Отклонённый
        результат (409/422) остаётся в буфере со статусом rejected, очередь идёт дальше.
        """
        for item in self._outbox.pending():
            if self._stop.is_set():
                return True  # остановка: остальное уйдёт при следующем запуске
            try:
                self._api.submit_result(item.payload)
            except Offline as exc:
                self._outbox.record_failure(item.session_id, f"нет связи: {exc}")
                return False
            except ApiProblem as exc:
                if exc.status in REJECT_STATUSES:
                    log.warning("result %s rejected: %s", item.session_id, exc)
                    self._outbox.mark_rejected(item.session_id, str(exc))
                    self._export_rejected()
                    continue
                self._outbox.record_failure(item.session_id, str(exc))
                return False
            except StationApiError as exc:
                self._outbox.record_failure(item.session_id, str(exc))
                return False
            self._outbox.mark_sent(item.session_id)
        return True

    def _export_rejected(self) -> None:
        try:
            self._outbox.export_rejected()
        except OSError:
            log.exception("could not export rejected results")

    def kick(self) -> None:
        """Попробовать отправить сразу (например, после добавления результата)."""
        self._wake.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sender", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        """Остановить поток; `True`, если он завершился (после этого буфер можно закрывать)."""
        self._stop.set()
        self._wake.set()
        if self._thread is None:
            return True
        self._thread.join(timeout=STOP_TIMEOUT_S)
        return not self._thread.is_alive()

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                ok = self.send_pending()
            except Exception:
                log.exception("sender pass failed")
                ok = False
            delay = self._poll_s if ok else backoff_delay(failures)
            failures = 0 if ok else failures + 1
            self._wake.wait(delay)
            self._wake.clear()
