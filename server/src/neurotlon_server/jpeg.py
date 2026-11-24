"""Strip everything but the picture from a JPEG (EXIF, GPS, thumbnails, comments, trailing data)."""

_SOI = b"\xff\xd8"
_EOI = 0xD9
_SOS = 0xDA
_DROPPED = frozenset([*range(0xE1, 0xF0), 0xFE])  # APP1..APP15, COM
_STANDALONE = frozenset([0x01, *range(0xD0, 0xD8)])  # TEM, RST0..7
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}  # not DHT, JPG, DAC


class InvalidJpegError(ValueError):
    pass


def _next_marker(data: bytes, pos: int) -> tuple[int, int]:
    """Marker code and the position after it, skipping fill bytes."""
    if pos >= len(data) or data[pos] != 0xFF:
        raise InvalidJpegError("marker expected")
    while pos < len(data) and data[pos] == 0xFF:
        pos += 1
    if pos >= len(data) or data[pos] == 0x00:
        raise InvalidJpegError("bad marker")
    return data[pos], pos + 1


def _scan_end(data: bytes, pos: int) -> int:
    """Position of the first marker that is not part of the entropy-coded data."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            raise InvalidJpegError("no EOI")
        nxt = data[pos + 1]
        if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
            pos += 2
        elif nxt == 0xFF:
            pos += 1
        else:
            return pos


def sanitize_jpeg(data: bytes) -> bytes:
    """Keep the structural segments and compressed data; raise InvalidJpegError otherwise."""
    if not data.startswith(_SOI):
        raise InvalidJpegError("no SOI")
    out = bytearray(_SOI)
    pos = 2
    has_frame = has_scan = False
    while True:
        marker, after = _next_marker(data, pos)
        if marker == _EOI:
            if not (has_frame and has_scan):
                raise InvalidJpegError("no frame or scan")
            out += b"\xff\xd9"
            return bytes(out)
        if marker in _STANDALONE:
            out += bytes([0xFF, marker])
            pos = after
            continue
        if after + 2 > len(data):
            raise InvalidJpegError("truncated")
        length = int.from_bytes(data[after : after + 2], "big")
        end = after + length
        if length < 2 or end > len(data):
            raise InvalidJpegError("bad segment length")
        if marker not in _DROPPED:
            out += bytes([0xFF, marker]) + data[after:end]
        has_frame = has_frame or marker in _SOF
        pos = end
        if marker == _SOS:
            if not has_frame:
                raise InvalidJpegError("scan before frame")
            has_scan = True
            stop = _scan_end(data, pos)
            out += data[pos:stop]
            pos = stop
