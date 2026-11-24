import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import segno
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

Layout = Literal["sheet", "single"]

# Badge for the printing house: 95 x 135 mm, portrait. Origin is its lower-left corner.
BADGE_W = 95 * mm
BADGE_H = 135 * mm
MARGIN = 5 * mm
COLUMNS = 2
ROWS = 2
BADGES_PER_PAGE = COLUMNS * ROWS

QR_SIDE = 31 * mm  # participant-code.md requires at least 30 mm
QUIET_MODULES = 4
TEXT_SIZE = 24

BRAND_BLUE = HexColor("#3B6FE0")
_GREY_FRAME = HexColor("#9AA0A6")
_GREY_FILL = HexColor("#C9CDD2")
_GREY_TEXT = HexColor("#7A7F85")
_GREY_GUIDE = HexColor("#C4C7CB")
_TABLE_LINE = HexColor("#4A4F55")

_FONTS = Path(__file__).parent / "fonts"
_LOGO = Path(__file__).parent / "assets" / "logo.png"
FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"


@dataclass(frozen=True)
class Box:
    """Rectangle in points, relative to the badge's lower-left corner."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2


def _top_box(x: float, top_mm: float, w: float, h: float) -> Box:
    return Box(x, BADGE_H - top_mm * mm - h, w, h)


PHOTO = _top_box(MARGIN, 5, 38 * mm, 50 * mm)
CODE_BASELINE = PHOTO.y - 9.5 * mm
LOGO_W = 40 * mm
LOGO_H = LOGO_W * 310 / 1000
LOGO = Box(BADGE_W - MARGIN - LOGO_W, BADGE_H - MARGIN - LOGO_H, LOGO_W, LOGO_H)
_QR_QUIET = QUIET_MODULES * QR_SIDE / 21  # version 1; larger versions have a thinner quiet zone
QR_X = (PHOTO.right + BADGE_W - MARGIN) / 2 - QR_SIDE / 2
QR_Y = LOGO.y - 1 * mm - _QR_QUIET - QR_SIDE
TABLE_HEAD_H = 7 * mm
TABLE_ROW_H = 9.6 * mm
_TABLE_H = TABLE_HEAD_H + 3 * TABLE_ROW_H
TABLE = Box(MARGIN, 66 * mm - _TABLE_H, BADGE_W - 2 * MARGIN, _TABLE_H)
TABLE_COLUMNS = (15 * mm, 35 * mm, 35 * mm)
PARTNERS_STRIP = Box(MARGIN, MARGIN, BADGE_W - 2 * MARGIN, 18 * mm)
PARTNERS_LABEL_BASELINE = PARTNERS_STRIP.top + 1.8 * mm
PARTNERS_COUNT = 3
PARTNERS_GAP = 3 * mm


def _register_fonts() -> None:
    # Idempotent; the standard reportlab fonts have no Cyrillic.
    registered = pdfmetrics.getRegisteredFontNames()
    if FONT not in registered:
        pdfmetrics.registerFont(TTFont(FONT, str(_FONTS / "DejaVuSans.ttf")))
    if FONT_BOLD not in registered:
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_FONTS / "DejaVuSans-Bold.ttf")))


def qr_for(code: str) -> segno.QRCode:
    # micro=False: Micro QR is not read by common scanners.
    # boost_error=False: segno would otherwise raise the level above M when it fits.
    return segno.make(code, error="m", boost_error=False, micro=False)


def qr_module_size(code: str) -> float:
    """Module side in points; the QR (without quiet zone) is always QR_SIDE wide."""
    return float(QR_SIDE / len(qr_for(code).matrix))


def draw_qr(pdf: Canvas, code: str, x: float, y: float) -> None:
    """Draw the QR with its lower-left dark corner at (x, y), on a white quiet zone."""
    matrix = [list(row) for row in qr_for(code).matrix]
    module = QR_SIDE / len(matrix)
    quiet = QUIET_MODULES * module
    pdf.setFillColorRGB(1, 1, 1)
    pdf.rect(x - quiet, y - quiet, QR_SIDE + 2 * quiet, QR_SIDE + 2 * quiet, stroke=0, fill=1)
    pdf.setFillColorRGB(0, 0, 0)
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                pdf.rect(
                    x + c * module,
                    y + QR_SIDE - (r + 1) * module,
                    module,
                    module,
                    stroke=0,
                    fill=1,
                )


def _draw_photo_placeholder(pdf: Canvas, x0: float, y0: float) -> None:
    """Frame with a grey head-and-shoulders silhouette ("no photo")."""
    frame = Box(x0 + PHOTO.x, y0 + PHOTO.y, PHOTO.w, PHOTO.h)
    radius = 3 * mm
    pdf.saveState()
    clip = pdf.beginPath()
    clip.roundRect(frame.x, frame.y, frame.w, frame.h, radius)
    pdf.clipPath(clip, stroke=0, fill=0)
    pdf.setFillColor(_GREY_FILL)
    head_r = 8 * mm
    pdf.circle(frame.cx, frame.y + frame.h * 0.60, head_r, stroke=0, fill=1)
    pdf.ellipse(
        frame.cx - 15 * mm,
        frame.y - 14 * mm,
        frame.cx + 15 * mm,
        frame.y + 20 * mm,
        stroke=0,
        fill=1,
    )
    pdf.restoreState()
    pdf.setStrokeColor(_GREY_FRAME)
    pdf.setLineWidth(0.6)
    pdf.roundRect(frame.x, frame.y, frame.w, frame.h, radius, stroke=1, fill=0)


def _icon_darts(pdf: Canvas, cx: float, cy: float, r: float) -> None:
    for scale, color in ((1.0, _TABLE_LINE), (0.66, HexColor("#FFFFFF")), (0.33, BRAND_BLUE)):
        pdf.setFillColor(color)
        pdf.circle(cx, cy, r * scale, stroke=0, fill=1)
    pdf.setStrokeColor(_TABLE_LINE)
    pdf.setLineWidth(0.6)
    pdf.circle(cx, cy, r * 0.66, stroke=1, fill=0)


def _icon_football(pdf: Canvas, cx: float, cy: float, r: float) -> None:
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setStrokeColor(_TABLE_LINE)
    pdf.setLineWidth(0.8)
    pdf.circle(cx, cy, r, stroke=1, fill=1)
    pdf.setFillColor(_TABLE_LINE)
    patch = pdf.beginPath()
    pdf.setLineWidth(0.5)
    points = [
        (cx + 0.38 * r * math.sin(a), cy + 0.38 * r * math.cos(a))
        for a in (i * 2 * math.pi / 5 for i in range(5))
    ]
    patch.moveTo(*points[0])
    for point in points[1:]:
        patch.lineTo(*point)
    patch.close()
    pdf.drawPath(patch, stroke=0, fill=1)
    for px, py in points:
        pdf.line(px, py, cx + (px - cx) * 2.4, cy + (py - cy) * 2.4)


def _icon_pong(pdf: Canvas, cx: float, cy: float, r: float) -> None:
    pdf.saveState()
    pdf.translate(cx - 0.15 * r, cy + 0.1 * r)
    pdf.rotate(35)
    pdf.setFillColor(BRAND_BLUE)
    pdf.roundRect(-0.55 * r, -0.2 * r, 1.1 * r, 1.0 * r, 0.45 * r, stroke=0, fill=1)
    pdf.setFillColor(_TABLE_LINE)
    pdf.rect(-0.1 * r, -0.85 * r, 0.2 * r, 0.7 * r, stroke=0, fill=1)
    pdf.restoreState()
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setStrokeColor(_TABLE_LINE)
    pdf.setLineWidth(0.7)
    pdf.circle(cx + 0.65 * r, cy - 0.55 * r, 0.28 * r, stroke=1, fill=1)


_ICONS = (_icon_darts, _icon_football, _icon_pong)  # one per row: darts, football, pong


def _draw_table(pdf: Canvas, x0: float, y0: float) -> None:
    table = Box(x0 + TABLE.x, y0 + TABLE.y, TABLE.w, TABLE.h)
    head_y = table.top - TABLE_HEAD_H
    pdf.setFillColor(BRAND_BLUE)
    pdf.rect(table.x, head_y, table.w, TABLE_HEAD_H, stroke=0, fill=1)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont(FONT_BOLD, 10)
    x = table.x
    for label, width in zip(("", "BCI", "Реальная"), TABLE_COLUMNS, strict=True):
        if label:
            pdf.drawCentredString(x + width / 2, head_y + 2.3 * mm, label)
        x += width
    pdf.setStrokeColor(_TABLE_LINE)
    pdf.setLineWidth(0.5)
    pdf.rect(table.x, table.y, table.w, table.h, stroke=1, fill=0)
    for i in range(1, 3):
        y = head_y - i * TABLE_ROW_H
        pdf.line(table.x, y, table.right, y)
    pdf.line(table.x, head_y, table.right, head_y)
    x = table.x
    for width in TABLE_COLUMNS[:-1]:
        x += width
        pdf.line(x, table.y, x, table.top)
    for i, icon in enumerate(_ICONS):
        row_cy = head_y - (i + 0.5) * TABLE_ROW_H
        icon(pdf, table.x + TABLE_COLUMNS[0] / 2, row_cy, 3.3 * mm)


def _draw_partner_slots(pdf: Canvas, x0: float, y0: float) -> None:
    pdf.setFillColor(_GREY_TEXT)
    pdf.setFont(FONT, 6)
    pdf.drawString(x0 + PARTNERS_STRIP.x, y0 + PARTNERS_LABEL_BASELINE, "Партнёры")
    slot_w = (PARTNERS_STRIP.w - (PARTNERS_COUNT - 1) * PARTNERS_GAP) / PARTNERS_COUNT
    pdf.setStrokeColor(_GREY_GUIDE)
    pdf.setLineWidth(0.5)
    pdf.setDash(2, 2)
    for i in range(PARTNERS_COUNT):
        pdf.rect(
            x0 + PARTNERS_STRIP.x + i * (slot_w + PARTNERS_GAP),
            y0 + PARTNERS_STRIP.y,
            slot_w,
            PARTNERS_STRIP.h,
            stroke=1,
            fill=0,
        )
    pdf.setDash()


def draw_badge(pdf: Canvas, code: str, x0: float, y0: float, guides: bool = True) -> None:
    """One 95 x 135 mm badge whose lower-left corner is (x0, y0).

    There is no team, name or category on it: the team is shown on the screens.
    """
    _register_fonts()
    _draw_photo_placeholder(pdf, x0, y0)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont(FONT_BOLD, TEXT_SIZE)
    pdf.drawCentredString(x0 + PHOTO.cx, y0 + CODE_BASELINE, code)
    pdf.drawImage(
        str(_LOGO), x0 + LOGO.x, y0 + LOGO.y, LOGO.w, LOGO.h, mask="auto", preserveAspectRatio=True
    )
    draw_qr(pdf, code, x0 + QR_X, y0 + QR_Y)
    _draw_table(pdf, x0, y0)
    if guides:
        _draw_partner_slots(pdf, x0, y0)


def _draw_sheet_guides(pdf: Canvas, left: float, bottom: float) -> None:
    right = left + COLUMNS * BADGE_W
    top = bottom + ROWS * BADGE_H
    pdf.setStrokeColorRGB(0.6, 0.6, 0.6)
    pdf.setLineWidth(0.5)
    pdf.setDash(3, 3)
    for c in range(COLUMNS + 1):
        pdf.line(left + c * BADGE_W, bottom, left + c * BADGE_W, top)
    for r in range(ROWS + 1):
        pdf.line(left, bottom + r * BADGE_H, right, bottom + r * BADGE_H)
    pdf.setDash()
    pdf.setStrokeColorRGB(0, 0, 0)  # cut marks at the corners of the sheet's grid
    mark, gap = 4 * mm, 1 * mm
    for x in (left, right):
        for y in (bottom, top):
            sx = -1 if x == left else 1
            sy = -1 if y == bottom else 1
            pdf.line(x + sx * gap, y, x + sx * (gap + mark), y)
            pdf.line(x, y + sy * gap, x, y + sy * (gap + mark))


def build_badges_pdf(codes: Sequence[str], layout: Layout = "sheet", guides: bool = True) -> bytes:
    """Badges with a photo placeholder, QR (content is exactly the code), results table.

    "single": one 95 x 135 mm page per badge, for the printing house.
    "sheet": A4, 2x2 badges per page with cut marks and a dashed grid.
    """
    _register_fonts()
    buffer = io.BytesIO()
    page_size = (BADGE_W, BADGE_H) if layout == "single" else A4
    pdf = Canvas(buffer, pagesize=page_size, invariant=True)
    pdf.setTitle("Badges")
    if layout == "single":
        for code in codes:
            draw_badge(pdf, code, 0, 0, guides)
            pdf.showPage()
        if not codes:
            pdf.showPage()
    else:
        page_w, page_h = A4
        left = (page_w - COLUMNS * BADGE_W) / 2
        bottom = (page_h - ROWS * BADGE_H) / 2
        for start in range(0, max(len(codes), 1), BADGES_PER_PAGE):
            _draw_sheet_guides(pdf, left, bottom)
            for index, code in enumerate(codes[start : start + BADGES_PER_PAGE]):
                row, col = divmod(index, COLUMNS)
                draw_badge(
                    pdf,
                    code,
                    left + col * BADGE_W,
                    bottom + (ROWS - 1 - row) * BADGE_H,
                    guides,
                )
            pdf.showPage()
    pdf.save()
    return buffer.getvalue()
