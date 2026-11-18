"""Чтение QR с вебки в отдельном потоке. cv2 подключается лениво: без камеры он не нужен."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from .codes import normalize_code

log = logging.getLogger(__name__)

DEBOUNCE_S = 3.0
FRAME_PAUSE_S = 0.03


class FrameSource(Protocol):
    def read(self) -> Any | None:
        """Следующий кадр (BGR, numpy) или `None`, если кадра нет."""
        ...

    def release(self) -> None: ...


class QrDecoder(Protocol):
    def decode(self, frame: Any) -> str:
        """Текст QR на кадре или пустая строка."""
        ...


class CodeSource(Protocol):
    """Что нужно интерфейсу от сканера."""

    @property
    def available(self) -> bool: ...

    def poll(self) -> str | None: ...

    def frame(self) -> Any | None: ...

    def stop(self) -> None: ...


class CodeDebouncer:
    """Пропускает только ID и не повторяет один и тот же ID чаще раза в `window_s`."""

    def __init__(
        self, window_s: float = DEBOUNCE_S, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._window_s = window_s
        self._monotonic = monotonic
        self._seen: dict[str, float] = {}

    def accept(self, raw: str) -> str | None:
        code = normalize_code(raw)
        if code is None:
            return None
        now = self._monotonic()
        last = self._seen.get(code)
        if last is not None and now - last < self._window_s:
            return None
        self._seen[code] = now
        return code


class CvCamera:
    def __init__(self, index: int) -> None:
        import cv2

        self._capture = cv2.VideoCapture(index)

    def is_opened(self) -> bool:
        return bool(self._capture.isOpened())

    def read(self) -> Any | None:
        ok, frame = self._capture.read()
        return frame if ok else None

    def release(self) -> None:
        self._capture.release()


class CvQrDecoder:
    def __init__(self) -> None:
        import cv2

        self._detector = cv2.QRCodeDetector()

    def decode(self, frame: Any) -> str:
        text, _points, _straight = self._detector.detectAndDecode(frame)
        return str(text)


def open_camera(index: int) -> CvCamera | None:
    try:
        camera = CvCamera(index)
    except Exception:
        log.exception("camera init failed")
        return None
    if camera.is_opened():
        return camera
    camera.release()
    return None


class QrScanner:
    """Поток: кадры → QR → фильтр по ID → очередь кодов. Последний кадр — для превью."""

    def __init__(
        self,
        source: FrameSource | None,
        decoder: QrDecoder,
        debouncer: CodeDebouncer | None = None,
        *,
        pause_s: float = FRAME_PAUSE_S,
    ) -> None:
        self._source = source
        self._decoder = decoder
        self._debouncer = debouncer or CodeDebouncer()
        self._pause_s = pause_s
        self._codes: queue.Queue[str] = queue.Queue()
        self._frame: Any | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self._source is not None

    def start(self) -> None:
        if self._source is not None:
            self._thread = threading.Thread(target=self._run, name="qr", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._source is not None:
            self._source.release()

    def poll(self) -> str | None:
        try:
            return self._codes.get_nowait()
        except queue.Empty:
            return None

    def frame(self) -> Any | None:
        return self._frame

    def scan_frame(self, frame: Any) -> None:
        """Разобрать один кадр (вызывается потоком; открыт для тестов)."""
        text = self._decoder.decode(frame)
        if text:
            code = self._debouncer.accept(text)
            if code is not None:
                self._codes.put(code)

    def _run(self) -> None:
        assert self._source is not None
        while not self._stop.is_set():
            try:
                frame = self._source.read()
                if frame is not None:
                    self._frame = frame
                    self.scan_frame(frame)
            except Exception:
                log.exception("qr pass failed")
            self._stop.wait(self._pause_s)


def create_scanner(camera_index: int, *, enabled: bool = True) -> QrScanner:
    """Сканер с реальной камерой; камеры нет или `enabled=False` — сканер без источника."""
    source = open_camera(camera_index) if enabled else None
    scanner = QrScanner(source, CvQrDecoder() if source is not None else _NoDecoder())
    scanner.start()
    return scanner


class _NoDecoder:
    def decode(self, frame: Any) -> str:
        return ""
