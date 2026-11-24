import pytest

from neurotlon_server.jpeg import InvalidJpegError, sanitize_jpeg


def seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload


def make_jpeg(*extra: bytes, scan: bytes = b"\x12\x34\xff\x00\x56", tail: bytes = b"") -> bytes:
    """A structurally valid JPEG (not decodable, the sanitizer only walks segments)."""
    return (
        b"\xff\xd8"
        + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + b"".join(extra)
        + seg(0xDB, b"\x00" + b"\x08" * 64)
        + seg(0xC0, b"\x08\x00\x08\x00\x08\x01\x01\x11\x00")
        + seg(0xC4, b"\x00" + b"\x00" * 16)
        + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        + scan
        + b"\xff\xd9"
        + tail
    )


def test_clean_jpeg_is_unchanged() -> None:
    clean = make_jpeg()
    assert sanitize_jpeg(clean) == clean
    assert sanitize_jpeg(sanitize_jpeg(clean)) == clean


def test_exif_gps_and_comment_are_removed() -> None:
    dirty = make_jpeg(
        seg(0xE1, b"Exif\x00\x00GPS-55.75-37.61"), seg(0xFE, b"secret"), seg(0xED, b"Photoshop")
    )
    result = sanitize_jpeg(dirty)
    assert result == make_jpeg()
    assert b"GPS" not in result
    assert b"secret" not in result


def test_trailing_data_after_eoi_is_dropped() -> None:
    result = sanitize_jpeg(make_jpeg(tail=b"<html><script>alert(1)</script></html>"))
    assert result == make_jpeg()
    assert result.endswith(b"\xff\xd9")


def test_restart_markers_and_stuffed_bytes_stay() -> None:
    scan = b"\x01\xff\x00\xff\xd0\x02\xff\xd1\x03"
    assert sanitize_jpeg(make_jpeg(scan=scan)) == make_jpeg(scan=scan)


def test_progressive_second_scan_is_kept() -> None:
    first = seg(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x11\x22"
    base = make_jpeg(scan=b"\x01\x02")
    two_scans = base[:-2] + first + seg(0xE1, b"Exif-in-the-middle") + b"\xff\xd9"
    result = sanitize_jpeg(two_scans)
    assert b"Exif" not in result
    assert result.count(b"\xff\xda") == 2
    assert result.endswith(b"\x11\x22\xff\xd9")


@pytest.mark.parametrize(
    "broken",
    [
        b"",
        b"\xff\xd8",
        b"not a jpeg",
        make_jpeg()[:-2],  # no EOI
        make_jpeg()[:30],  # segment length beyond the buffer
        b"\xff\xd8" + seg(0xE0, b"JFIF\x00") + b"\xff\xd9",  # no SOF or SOS
        b"\xff\xd8"
        + seg(0xDB, b"\x00" * 65)
        + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        + b"\x01\xff\xd9",
        b"\xff\xd8\xff\xe0\x00\x01" + b"\xff\xd9",  # length below 2
    ],
)
def test_broken_structure_is_rejected(broken: bytes) -> None:
    with pytest.raises(InvalidJpegError):
        sanitize_jpeg(broken)
