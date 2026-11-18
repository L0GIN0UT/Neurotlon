import threading
from typing import Any

import numpy as np
import pytest
import segno

from neurotlon_launcher.qr import CodeDebouncer, CvQrDecoder, QrScanner


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_debouncer_accepts_only_ids_and_normalizes() -> None:
    debouncer = CodeDebouncer(3.0, Clock())
    assert debouncer.accept("https://example.org/NT07") is None
    assert debouncer.accept("") is None
    assert debouncer.accept(" nt-07 ") == "NT07"


def test_debouncer_blocks_same_code_for_window() -> None:
    clock = Clock()
    debouncer = CodeDebouncer(3.0, clock)
    assert debouncer.accept("NT07") == "NT07"
    clock.now += 2.9
    assert debouncer.accept("NT07") is None
    assert debouncer.accept("NT08") == "NT08"  # другой код не задержан
    clock.now += 0.2
    assert debouncer.accept("NT07") == "NT07"


class ListDecoder:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def decode(self, frame: Any) -> str:
        return self.texts.pop(0) if self.texts else ""


def test_scan_frame_queues_filtered_codes() -> None:
    scanner = QrScanner(
        None, ListDecoder(["junk", "NT07", "NT07", "", "9"]), CodeDebouncer(3, Clock())
    )
    for _ in range(5):
        scanner.scan_frame(object())
    assert scanner.poll() == "NT07"
    assert scanner.poll() == "NT09"
    assert scanner.poll() is None
    assert scanner.available is False


class OneShotSource:
    def __init__(self) -> None:
        self.frames = [np.zeros((4, 4, 3), dtype=np.uint8)]
        self.released = False
        self.read_all = threading.Event()

    def read(self) -> Any | None:
        if self.frames:
            return self.frames.pop()
        self.read_all.set()
        return None

    def release(self) -> None:
        self.released = True


def test_thread_exposes_frame_and_code_then_releases() -> None:
    source = OneShotSource()
    scanner = QrScanner(source, ListDecoder(["NT05"]), pause_s=0.001)
    scanner.start()
    try:
        assert source.read_all.wait(5)
    finally:
        scanner.stop()
    assert scanner.available
    assert scanner.poll() == "NT05"
    assert scanner.frame() is not None
    assert source.released


@pytest.mark.parametrize("text", ["NT07", "NT20"])
def test_cv_decoder_reads_generated_badge_qr(text: str) -> None:
    matrix = segno.make(text, error="m", micro=False).matrix
    scale, border = 8, 4
    size = (len(matrix) + 2 * border) * scale
    image = np.full((size, size), 255, dtype=np.uint8)
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                top, left = (y + border) * scale, (x + border) * scale
                image[top : top + scale, left : left + scale] = 0
    frame = np.stack([image] * 3, axis=-1)
    assert CvQrDecoder().decode(frame) == text


def test_cv_decoder_blank_frame() -> None:
    assert CvQrDecoder().decode(np.full((120, 160, 3), 255, dtype=np.uint8)) == ""
