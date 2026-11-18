import io
from collections.abc import Sequence

import segno
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

COLUMNS = 2
ROWS = 3
BADGES_PER_PAGE = COLUMNS * ROWS
QR_SIDE = 40 * mm  # participant-code.md requires at least 30 mm
QUIET_MODULES = 4
TEXT_SIZE = 36
TEXT_BASELINE = 9 * mm
QR_BOTTOM = 28 * mm  # quiet zone (4 modules) stays clear of the code text
_CELL_W = 90 * mm
_CELL_H = 85 * mm


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


def draw_badge(pdf: Canvas, code: str, x0: float, y0: float) -> None:
    """One badge in the cell whose lower-left corner is (x0, y0)."""
    draw_qr(pdf, code, x0 + (_CELL_W - QR_SIDE) / 2, y0 + QR_BOTTOM)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", TEXT_SIZE)
    pdf.drawCentredString(x0 + _CELL_W / 2, y0 + TEXT_BASELINE, code)


def _draw_cut_lines(pdf: Canvas, left: float, bottom: float) -> None:
    pdf.setStrokeColorRGB(0.6, 0.6, 0.6)
    pdf.setDash(3, 3)
    pdf.setLineWidth(0.5)
    for c in range(COLUMNS + 1):
        pdf.line(left + c * _CELL_W, bottom, left + c * _CELL_W, bottom + ROWS * _CELL_H)
    for r in range(ROWS + 1):
        pdf.line(left, bottom + r * _CELL_H, left + COLUMNS * _CELL_W, bottom + r * _CELL_H)
    pdf.setDash()


def build_badges_pdf(codes: Sequence[str]) -> bytes:
    """A4 sheets, 2x3 badges each: QR (content is exactly the code) and the code below it."""
    buffer = io.BytesIO()
    pdf = Canvas(buffer, pagesize=A4, invariant=True)
    pdf.setTitle("Badges")
    page_w, page_h = A4
    left = (page_w - COLUMNS * _CELL_W) / 2
    bottom = (page_h - ROWS * _CELL_H) / 2
    for start in range(0, max(len(codes), 1), BADGES_PER_PAGE):
        _draw_cut_lines(pdf, left, bottom)
        for index, code in enumerate(codes[start : start + BADGES_PER_PAGE]):
            row, col = divmod(index, COLUMNS)
            x0 = left + col * _CELL_W
            y0 = bottom + (ROWS - 1 - row) * _CELL_H
            draw_badge(pdf, code, x0, y0)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
