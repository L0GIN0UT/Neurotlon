"""The web colour picker palette must match the server draw palette.

The server image does not copy shared/, so the two lists are kept by hand and compared here.
"""

import re
from pathlib import Path

from neurotlon_server.draw import PALETTE

ROOT = Path(__file__).parent.parent.parent
COLORS_TS = ROOT / "web" / "src" / "staff" / "colors.ts"


def test_web_palette_matches_server_palette() -> None:
    source = COLORS_TS.read_text(encoding="utf-8")
    block = re.search(r"TEAM_PALETTE[^=]*=\s*\[(.*?)\]", source, re.S)
    assert block is not None
    assert tuple(re.findall(r"'(#[0-9A-Fa-f]{6})'", block.group(1))) == PALETTE
