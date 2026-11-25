"""Локальный HTTP-мост между машиной состояний и веб-интерфейсом (Electron).

Слушает только 127.0.0.1. Каждый запрос должен нести токен запуска: его знают лаунчер и окно,
которое он открыл, а чужие страницы в браузере — нет. Машина не потокобезопасна, поэтому весь
доступ к ней идёт под одним замком, а `tick()` крутится в отдельном потоке.

- `GET  /api/state`   — текущий снимок;
- `GET  /api/events`  — поток Server-Sent Events, снимок при каждом изменении;
- `GET  /api/signals` — SSE с живыми значениями датчиков, пока идёт калибровка (`signal_stream`);
- `POST /api/command` — `{"action": "...", "value": "..."}` из белого списка.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .machine import StationMachine
from .sensors import BridgeStatus
from .signal_stream import SignalCursor, next_frame
from .snapshot import snapshot
from .status import StationStatus

log = logging.getLogger(__name__)

TICK_S = 0.05
KEEPALIVE_S = 15.0
SIGNALS_PERIOD_S = 0.1  # кадры значений датчиков 10 раз в секунду
SIGNALS_KEEPALIVE_S = 5.0
MAX_STREAMS = 4  # одновременных SSE-подписчиков на сервер (`/api/events` и `/api/signals`)
MAX_BODY = 16384

# Команды без аргумента и с одним строковым аргументом `value`.
PLAIN_ACTIONS = frozenset(
    {
        "backspace",
        "submit_input",
        "confirm",
        "cancel",
        "retry",
        "back",
        "show_rejected",
        "close_rejected",
        "export_rejected",
        "calibration_continue",
        "calibration_restart",
    }
)
VALUE_ACTIONS = frozenset({"type_char", "enter_code", "calibration_retry"})


class CommandRejected(Exception):
    """Команда отклонена с понятным текстом: HTTP 400 с телом `{"error": "..."}`."""


class LiveState:
    """Последний снимок и рассылка слушателям: общая часть рабочего и настроечного режимов."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._stop = threading.Event()
        self.version = 0
        self.body = b""

    def publish(self, snapshot_data: dict[str, Any]) -> None:
        body = json.dumps(
            snapshot_data, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        with self._changed:
            if body != self.body:
                self.body = body
                self.version += 1
                self._changed.notify_all()

    def wait_change(self, seen: int, timeout: float) -> tuple[int, bytes]:
        """Дождаться версии новее `seen` (или таймаута); вернуть версию и тело."""
        with self._changed:
            self._changed.wait_for(lambda: self.version != seen or self._stop.is_set(), timeout)
            return self.version, self.body

    def start(self) -> None:
        """Запустить фоновую работу, если она нужна."""

    def stop(self) -> None:
        self._stop.set()
        with self._changed:
            self._changed.notify_all()

    def command(self, action: str, value: Any) -> bool:
        raise NotImplementedError

    def signal_frame(self, cursor: SignalCursor) -> dict[str, Any] | None:
        """Следующий кадр значений датчиков для слушателя; по умолчанию их нет."""
        return None


class Station(LiveState):
    """Машина под замком плюс последний снимок; будит слушателей при изменении."""

    def __init__(
        self,
        machine: StationMachine,
        status: Callable[[], StationStatus],
        camera: str | None = None,
        sensors: Callable[[], BridgeStatus | None] | None = None,
    ) -> None:
        super().__init__()
        self._sensors = sensors or (lambda: None)
        self._machine = machine
        self._status = status
        self._camera = camera
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._refresh()

    def _refresh(self) -> None:
        self.publish(snapshot(self._machine, self._status(), self._camera, self._sensors()))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="station-tick", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        super().stop()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    self._machine.tick()
                    self._refresh()
            except Exception:
                log.exception("station tick failed")
            self._stop.wait(TICK_S)

    def signal_frame(self, cursor: SignalCursor) -> dict[str, Any] | None:
        with self._lock:
            found = self._machine.signal_link
        epoch, link = found if found is not None else (cursor.epoch, None)
        return next_frame(cursor, epoch, link)

    def command(self, action: str, value: Any) -> bool:
        """Выполнить команду из белого списка; `False` — команда неизвестна или без аргумента."""
        with self._lock:
            if action in PLAIN_ACTIONS:
                getattr(self._machine, action)()
            elif action in VALUE_ACTIONS and isinstance(value, str):
                getattr(self._machine, action)(value)
            else:
                return False
            self._refresh()
        return True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: BridgeServer

    def log_message(self, format: str, *args: Any) -> None:
        return  # в строке запроса может быть токен

    # --- общее ----------------------------------------------------------------------------

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Station-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, status: HTTPStatus, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if status >= HTTPStatus.BAD_REQUEST:
            # тело запроса могло остаться непрочитанным: соединение дальше не используем
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in {"127.0.0.1", "localhost"}:  # защита от DNS rebinding
            return False
        query = parse_qs(urlsplit(self.path).query)
        given = self.headers.get("X-Station-Token") or (query.get("token") or [""])[0]
        return hmac.compare_digest(given.encode(), self.server.token.encode())

    def _route(self) -> str:
        return urlsplit(self.path).path

    # --- методы ---------------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        self._send(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(HTTPStatus.FORBIDDEN)
        elif self._route() == "/api/state":
            self._send(HTTPStatus.OK, self.server.station.body)
        elif self._route() == "/api/events":
            self._events()
        elif self._route() == "/api/signals":
            self._signals()
        else:
            self._send(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        raw = self._read_body()  # всегда читаем тело: иначе ответ оборвёт соединение клиента
        if not self._authorized():
            self._send(HTTPStatus.FORBIDDEN)
        elif self._route() != "/api/command":
            self._send(HTTPStatus.NOT_FOUND)
        else:
            try:
                data = json.loads(raw or b"")
                action, value = data["action"], data.get("value")
                ok = isinstance(action, str) and self.server.station.command(action, value)
            except CommandRejected as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
                self._send(HTTPStatus.BAD_REQUEST, body)
                return
            except (ValueError, KeyError, TypeError):
                ok = False
            self._send(HTTPStatus.NO_CONTENT if ok else HTTPStatus.BAD_REQUEST)

    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if not 0 < length <= MAX_BODY:
            return None
        return self.rfile.read(length)

    def _events(self) -> None:
        if not self.server.acquire_stream():
            self._send(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            self._events_stream()
        finally:
            self.server.release_stream()

    def _events_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        station = self.server.station
        seen = -1
        try:
            while not self.server.closing.is_set():
                version, body = station.wait_change(seen, KEEPALIVE_S)
                if version != seen:
                    seen = version
                    self.wfile.write(b"data: " + body + b"\n\n")
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _signals(self) -> None:
        if not self.server.acquire_stream():
            self._send(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            self._signals_stream()
        finally:
            self.server.release_stream()

    def _signals_stream(self) -> None:
        """Кадры значений датчиков 10 раз в секунду, пока идёт калибровка; иначе keepalive."""
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        station = self.server.station
        cursor = SignalCursor()
        silent_for = 0.0
        try:
            while not self.server.closing.is_set():
                frame = station.signal_frame(cursor)
                if frame is not None:
                    body = json.dumps(
                        frame, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    )
                    self.wfile.write(b"data: " + body.encode() + b"\n\n")
                    silent_for = 0.0
                elif silent_for >= SIGNALS_KEEPALIVE_S:
                    self.wfile.write(b": keepalive\n\n")
                    silent_for = 0.0
                else:
                    silent_for += SIGNALS_PERIOD_S
                    self.server.closing.wait(SIGNALS_PERIOD_S)
                    continue
                self.wfile.flush()
                self.server.closing.wait(SIGNALS_PERIOD_S)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, station: LiveState, token: str, port: int = 0) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.station = station
        self.token = token
        self.closing = threading.Event()
        self._streams = 0
        self._streams_lock = threading.Lock()

    def acquire_stream(self) -> bool:
        """Занять место SSE-подписчика; `False`, если все `MAX_STREAMS` мест заняты."""
        with self._streams_lock:
            if self._streams >= MAX_STREAMS:
                return False
            self._streams += 1
            return True

    def release_stream(self) -> None:
        with self._streams_lock:
            self._streams -= 1

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def close(self) -> None:
        self.closing.set()
        self.station.stop()
        self.shutdown()
        self.server_close()
