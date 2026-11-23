"""Heartbeat станции раз в 5 с. Датчики не опрашиваем: мост пускает одного клиента — игру."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Protocol

from .api import StationApiError

log = logging.getLogger(__name__)

INTERVAL_S = 5.0


class HeartbeatSink(Protocol):
    def heartbeat(
        self,
        state: str,
        session_id: uuid.UUID | None,
        queue_length: int,
        sensors: dict[str, str],
    ) -> None: ...


class HeartbeatLoop:
    def __init__(
        self,
        api: HeartbeatSink,
        view: Callable[[], tuple[str, uuid.UUID | None]],
        queue_length: Callable[[], int],
        *,
        interval_s: float = INTERVAL_S,
    ) -> None:
        self._api = api
        self._view = view
        self._queue_length = queue_length
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.online: bool | None = None  # итог последнего heartbeat; `None` — ещё не было

    def beat(self) -> bool:
        """Один heartbeat; `False`, если не дошёл (сервер недоступен или отклонил)."""
        state, session_id = self._view()
        try:
            self._api.heartbeat(state, session_id, self._queue_length(), {})
        except StationApiError as exc:
            log.debug("heartbeat failed: %s", exc)
            self.online = False
            return False
        self.online = True
        return True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.beat()
            except Exception:
                log.exception("heartbeat pass failed")
            self._stop.wait(self._interval_s)
