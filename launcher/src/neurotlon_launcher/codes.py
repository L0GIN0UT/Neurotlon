"""ID участника: нормализация ввода по `shared/participant-code.md`."""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"NT(0[1-9]|[1-9][0-9])")
_INPUT_RE = re.compile(r"(?:NT)?([0-9]{1,2})")
_STRIP_RE = re.compile(r"[\s\-_]+")
# Cyrillic EN and TE (U+041D, U+0422) in the prefix stand for the letters N and T.
_PREFIX_FIX = str.maketrans({0x041D: "N", 0x0422: "T"})


def normalize_code(raw: str) -> str | None:
    """Привести ввод или содержимое QR к `NT01`..`NT99`; не ID — `None`."""
    text = _STRIP_RE.sub("", raw).upper()
    text = text[:2].translate(_PREFIX_FIX) + text[2:]
    match = _INPUT_RE.fullmatch(text)
    if match is None:
        return None
    code = f"NT{match.group(1).zfill(2)}"
    return code if _CODE_RE.fullmatch(code) else None
