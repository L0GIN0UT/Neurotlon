import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
import segno
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.audit import write_audit
from neurotlon_server.badges import (
    BADGE_H,
    BADGE_W,
    BADGES_PER_PAGE,
    CODE_BASELINE,
    LOGO,
    PARTNERS_STRIP,
    PHOTO,
    QR_SIDE,
    QR_X,
    QR_Y,
    TABLE,
    TEXT_SIZE,
    Box,
    build_badges_pdf,
    draw_badge,
    draw_qr,
    qr_for,
    qr_module_size,
)
from neurotlon_server.codes import normalize_code
from neurotlon_server.models import AuditLog, Participant, Team

from .conftest import FakeClock, login_as, make_user

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "participant-code.cases.json").read_text(
        encoding="utf-8"
    )
)
API = "/api/v1/participants"


@pytest.fixture
def admin(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "boss", role="admin")
    return login_as(app, "boss")


def _generate(admin: TestClient, count: int = 20) -> None:
    assert admin.post(f"{API}/generate", json={"count": count}).status_code == 200


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


# --- normalization ---


@pytest.mark.parametrize(("raw", "expected"), CASES["valid"].items())
def test_normalize_valid(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", CASES["invalid"])
def test_normalize_invalid(raw: str) -> None:
    assert normalize_code(raw) is None


# --- generate ---


def test_generate_is_idempotent_and_extends(admin: TestClient, db: Session) -> None:
    first = admin.post(f"{API}/generate", json={"count": 3})
    assert first.status_code == 200
    assert first.json() == {"created": ["NT01", "NT02", "NT03"], "total": 3}
    again = admin.post(f"{API}/generate", json={"count": 3}).json()
    assert again == {"created": [], "total": 3}
    more = admin.post(f"{API}/generate", json={"count": 5}).json()
    assert more == {"created": ["NT04", "NT05"], "total": 5}
    assert len(list(db.scalars(select(Participant)))) == 5


@pytest.mark.parametrize("count", [0, 100, -1])
def test_generate_bounds(admin: TestClient, count: int) -> None:
    assert admin.post(f"{API}/generate", json={"count": count}).status_code == 422


def test_generate_accepts_99(admin: TestClient) -> None:
    assert admin.post(f"{API}/generate", json={"count": 99}).json()["total"] == 99


def test_generate_rejects_extra_fields(admin: TestClient) -> None:
    assert admin.post(f"{API}/generate", json={"count": 2, "x": 1}).status_code == 422


@pytest.mark.parametrize("role", ["judge", "volunteer"])
def test_generate_forbidden_for_other_roles(app: FastAPI, db: Session, role: str) -> None:
    make_user(db, "other", role=role, discipline="darts" if role == "volunteer" else None)
    other = login_as(app, "other")
    assert other.post(f"{API}/generate", json={"count": 2}).status_code == 403


def test_generate_writes_audit(admin: TestClient, db: Session) -> None:
    _generate(admin, 2)
    row = db.scalars(select(AuditLog).where(AuditLog.action == "participant.generate")).one()
    assert row.after == {"created": ["NT01", "NT02"]}
    assert row.object_id == "bulk"


# --- list ---


def test_list_for_admin_includes_category_and_team(
    app: FastAPI, admin: TestClient, db: Session
) -> None:
    _generate(admin, 2)
    team = Team(number=1, name="Red", color="#FF0000", order=1)
    db.add(team)
    db.flush()
    db.scalars(select(Participant).where(Participant.code == "NT02")).one().team_id = team.id
    db.commit()
    admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "Ann"})
    rows = admin.get(API).json()
    assert [r["code"] for r in rows] == ["NT01", "NT02"]
    assert rows[0]["category"] == "general"
    assert rows[0]["checked_in"] is True
    assert rows[0]["checked_in_at"] is not None
    assert rows[0]["display_name"] == "Ann"
    assert rows[0]["team"] is None
    assert rows[1]["checked_in"] is False
    assert rows[1]["team"] == {"number": 1, "name": "Red", "color": "#FF0000"}


def test_list_for_judge_has_no_category(app: FastAPI, admin: TestClient, db: Session) -> None:
    _generate(admin, 2)
    admin.post(f"{API}/NT01/check-in", json={"category": "general"})
    make_user(db, "jd", role="judge")
    response = login_as(app, "jd").get(API)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert all("category" not in row for row in rows)
    assert "general" not in response.text


def test_list_forbidden_for_volunteer(app: FastAPI, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="darts")
    assert login_as(app, "vol").get(API).status_code == 403


def test_list_requires_login(client: TestClient) -> None:
    assert client.get(API).status_code == 401


# --- badges ---


def test_badges_pdf_all(admin: TestClient) -> None:
    _generate(admin, 20)
    response = admin.get(f"{API}/badges.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="badges.pdf"'
    assert response.content.startswith(b"%PDF")
    assert _pages(response.content) == 5  # 20 badges, 4 per page
    assert b"DejaVuSans" in response.content  # Cyrillic needs an embedded font


def test_badges_pdf_selected_codes(admin: TestClient) -> None:
    _generate(admin, 20)
    response = admin.get(f"{API}/badges.pdf", params={"codes": "NT01,7"})
    assert response.status_code == 200
    assert _pages(response.content) == 1


def test_badges_pdf_unknown_code(admin: TestClient) -> None:
    _generate(admin, 3)
    assert admin.get(f"{API}/badges.pdf", params={"codes": "NT01,NT09"}).status_code == 404
    assert admin.get(f"{API}/badges.pdf", params={"codes": "zzz"}).status_code == 404


def test_badges_pdf_without_participants(admin: TestClient) -> None:
    assert admin.get(f"{API}/badges.pdf").status_code == 404


def test_badges_pdf_forbidden_for_judge(app: FastAPI, db: Session) -> None:
    make_user(db, "jd", role="judge")
    assert login_as(app, "jd").get(f"{API}/badges.pdf").status_code == 403


def test_badges_pdf_single_layout(admin: TestClient) -> None:
    _generate(admin, 3)
    response = admin.get(f"{API}/badges.pdf", params={"layout": "single"})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="badges-print.pdf"'
    assert _pages(response.content) == 3
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d. -]+?)\s*\]", response.content)
    assert boxes
    for box in boxes:
        x0, y0, x1, y1 = (float(v) for v in box.split())
        assert (x0, y0) == (0, 0)
        assert x1 == pytest.approx(95 * mm, abs=0.01)
        assert y1 == pytest.approx(135 * mm, abs=0.01)


def test_badges_pdf_sheet_layout_is_default(admin: TestClient) -> None:
    _generate(admin, 5)
    explicit = admin.get(f"{API}/badges.pdf", params={"layout": "sheet"})
    assert explicit.headers["content-disposition"] == 'attachment; filename="badges.pdf"'
    assert _pages(explicit.content) == 2


def test_badges_pdf_unknown_layout(admin: TestClient) -> None:
    _generate(admin, 3)
    assert admin.get(f"{API}/badges.pdf", params={"layout": "poster"}).status_code == 422


@pytest.mark.parametrize(("count", "pages"), [(1, 1), (4, 1), (5, 2), (8, 2), (9, 3)])
def test_pdf_page_count(count: int, pages: int) -> None:
    codes = [f"NT{n:02d}" for n in range(1, count + 1)]
    assert _pages(build_badges_pdf(codes)) == pages
    assert BADGES_PER_PAGE == 4


@pytest.mark.parametrize("count", [1, 3])
def test_single_layout_one_page_per_badge(count: int) -> None:
    codes = [f"NT{n:02d}" for n in range(1, count + 1)]
    assert _pages(build_badges_pdf(codes, "single")) == count


def test_guides_can_be_turned_off() -> None:
    with_guides = build_badges_pdf(["NT01"], "single")
    without = build_badges_pdf(["NT01"], "single", guides=False)
    assert len(without) < len(with_guides)


def test_pdf_embeds_dejavu_fonts_and_logo() -> None:
    pdf = build_badges_pdf(["NT01"], "single")
    assert b"/FontFile2" in pdf
    assert b"DejaVuSans-Bold" in pdf
    assert b"/SMask" in pdf  # the RGBA logo


class RecordingCanvas(Canvas):  # type: ignore[misc]
    """Records dark and white rects and text instead of producing output."""

    def __init__(self) -> None:
        super().__init__(io.BytesIO())
        self.fill: tuple[float, ...] = (0.0, 0.0, 0.0)
        self.dark: list[tuple[float, float, float, float]] = []
        self.white: list[tuple[float, float, float, float]] = []
        self.texts: list[tuple[float, float, str]] = []

    def setFillColorRGB(self, r: float, g: float, b: float, alpha: float | None = None) -> None:
        self.fill = (r, g, b)

    def rect(
        self, x: float, y: float, width: float, height: float, stroke: int = 1, fill: int = 0
    ) -> None:
        if self.fill == (1, 1, 1):
            self.white.append((x, y, width, height))
        elif self.fill == (0, 0, 0):
            self.dark.append((x, y, width, height))

    def drawCentredString(self, x: float, y: float, text: str, **kwargs: Any) -> None:
        self.texts.append((x, y, text))


def _matrix_from_rects(
    canvas: RecordingCanvas, x: float, y: float, module: float
) -> list[list[bool]]:
    size = round(QR_SIDE / module)
    grid = [[False] * size for _ in range(size)]
    for rx, ry, w, h in canvas.dark:
        assert w == pytest.approx(module)
        assert h == pytest.approx(module)
        col = round((rx - x) / module)
        row = size - 1 - round((ry - y) / module)
        grid[row][col] = True
    return grid


def test_drawn_qr_is_the_code_at_level_m() -> None:
    canvas = RecordingCanvas()
    draw_qr(canvas, "NT07", 100.0, 200.0)
    expected = segno.make("NT07", error="m", boost_error=False, micro=False)
    assert expected.error == "M"
    drawn = _matrix_from_rects(canvas, 100.0, 200.0, qr_module_size("NT07"))
    assert drawn == [[bool(v) for v in row] for row in expected.matrix]
    other = RecordingCanvas()
    draw_qr(other, "NT08", 100.0, 200.0)
    assert other.dark != canvas.dark


def test_qr_extent_and_quiet_zone() -> None:
    canvas = RecordingCanvas()
    draw_qr(canvas, "NT07", 100.0, 200.0)
    module = qr_module_size("NT07")
    xs = [r[0] for r in canvas.dark] + [r[0] + r[2] for r in canvas.dark]
    ys = [r[1] for r in canvas.dark] + [r[1] + r[3] for r in canvas.dark]
    assert max(xs) - min(xs) >= 30 * mm
    assert max(ys) - min(ys) >= 30 * mm
    wx, wy, ww, wh = canvas.white[0]
    assert min(xs) - wx == pytest.approx(4 * module)
    assert wx + ww - max(xs) == pytest.approx(4 * module)
    assert min(ys) - wy == pytest.approx(4 * module)
    assert wy + wh - max(ys) == pytest.approx(4 * module)
    # no dark module inside the quiet zone ring
    for rx, ry, w, h in canvas.dark:
        assert rx >= wx + 4 * module - 1e-6
        assert ry >= wy + 4 * module - 1e-6
        assert rx + w <= wx + ww - 4 * module + 1e-6
        assert ry + h <= wy + wh - 4 * module + 1e-6


def _overlap(a: Box, b: Box) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.top and b.y < a.top


def test_badge_blocks_fit_and_do_not_overlap() -> None:
    canvas = RecordingCanvas()
    draw_badge(canvas, "NT07", 0.0, 0.0)
    (code,) = (t for t in canvas.texts if t[2] == "NT07")
    wx, wy, ww, wh = canvas.white[0]
    quiet = Box(wx, wy, ww, wh)
    code_w = pdfmetrics.stringWidth("NT07", "DejaVuSans-Bold", TEXT_SIZE)
    code_box = Box(code[0] - code_w / 2, code[1], code_w, TEXT_SIZE * 0.76)
    blocks = {
        "photo": PHOTO,
        "code": code_box,
        "logo": LOGO,
        "qr": quiet,
        "table": TABLE,
        "partners": PARTNERS_STRIP,
    }
    for name, box in blocks.items():
        assert box.x >= 0, name
        assert box.y >= 0, name
        assert box.right <= BADGE_W + 1e-6, name
        assert box.top <= BADGE_H + 1e-6, name
    names = list(blocks)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            assert not _overlap(blocks[first], blocks[second]), (first, second)
    assert code_box.cx == pytest.approx(PHOTO.cx)
    assert PHOTO.y > CODE_BASELINE
    assert 30 * mm <= QR_SIDE
    assert quiet.x == pytest.approx(QR_X - 4 * qr_module_size("NT07"))
    assert quiet.y == pytest.approx(QR_Y - 4 * qr_module_size("NT07"))
    assert LOGO.w == pytest.approx(40 * mm)


def test_badge_has_no_team_or_category_text() -> None:
    canvas = RecordingCanvas()
    draw_badge(canvas, "NT07", 0.0, 0.0)
    texts = {t[2] for t in canvas.texts}
    assert texts == {"NT07", "BCI", "Реальная"}


def test_pdf_builder_encodes_each_code(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def spy(code: str) -> segno.QRCode:
        seen.append(code)
        return qr_for(code)

    monkeypatch.setattr("neurotlon_server.badges.qr_for", spy)
    build_badges_pdf(["NT01", "NT02"])
    assert "NT01" in seen
    assert "NT02" in seen


# --- check-in ---


def test_check_in_sets_fields(admin: TestClient, clock: FakeClock, db: Session) -> None:
    _generate(admin)
    response = admin.post(
        f"{API}/7/check-in", json={"category": "general", "display_name": " Ann "}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "NT07"
    assert body["display_name"] == "Ann"
    assert body["checked_in"] is True
    assert body["checked_in_at"].startswith("2027-01-01T09:00:00")
    participant = db.scalars(select(Participant).where(Participant.code == "NT07")).one()
    assert participant.category == "general"
    assert participant.checked_in_at == clock.now


def test_check_in_without_name_and_blank_name(admin: TestClient) -> None:
    _generate(admin)
    assert (
        admin.post(f"{API}/NT01/check-in", json={"category": "general"}).json()["display_name"]
        is None
    )
    blank = admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "  "})
    assert blank.json()["display_name"] is None
    null = admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": None})
    assert null.status_code == 200


def test_recheck_in_updates_fields(admin: TestClient, clock: FakeClock) -> None:
    _generate(admin)
    admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "Ann"})
    clock.advance(minutes=5)
    response = admin.post(f"{API}/NT01/check-in", json={"category": "ovz", "display_name": "Bob"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Bob"
    assert response.json()["checked_in_at"].startswith("2027-01-01T09:05:00")


def test_undo_check_in(admin: TestClient, db: Session) -> None:
    _generate(admin)
    admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "Ann"})
    response = admin.delete(f"{API}/NT01/check-in")
    assert response.status_code == 200
    assert response.json()["checked_in"] is False
    participant = db.scalars(select(Participant).where(Participant.code == "NT01")).one()
    db.refresh(participant)
    assert participant.checked_in_at is None
    assert participant.category is None


def test_unknown_participant_404(admin: TestClient) -> None:
    _generate(admin, 3)
    for path_code in ("NT09", "xyz"):
        response = admin.post(f"{API}/{path_code}/check-in", json={"category": "general"})
        assert response.status_code == 404
        assert response.json()["code"] == "unknown_participant"
        assert admin.delete(f"{API}/{path_code}/check-in").status_code == 404
        assert admin.patch(f"{API}/{path_code}", json={"display_name": "A"}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"category": "general", "display_name": "x" * 25},
        {"category": "other"},
        {},
        {"category": "general", "extra": 1},
    ],
)
def test_check_in_validation(admin: TestClient, payload: dict[str, object]) -> None:
    _generate(admin)
    assert admin.post(f"{API}/NT01/check-in", json=payload).status_code == 422


def test_display_name_length_boundary(admin: TestClient) -> None:
    _generate(admin)
    ok = admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "x" * 24})
    assert ok.status_code == 200
    padded = {"category": "general", "display_name": " " + "x" * 24 + " "}
    assert admin.post(f"{API}/NT01/check-in", json=padded).status_code == 200


def test_check_in_forbidden_for_judge_and_anonymous(
    app: FastAPI, admin: TestClient, client: TestClient, db: Session
) -> None:
    _generate(admin)
    make_user(db, "jd", role="judge")
    judge = login_as(app, "jd")
    body = {"category": "general"}
    assert judge.post(f"{API}/NT01/check-in", json=body).status_code == 403
    assert judge.delete(f"{API}/NT01/check-in").status_code == 403
    assert judge.patch(f"{API}/NT01", json={"display_name": "A"}).status_code == 403
    assert client.post(f"{API}/NT01/check-in", json=body).status_code == 401


# --- patch ---


def test_patch_display_name(admin: TestClient) -> None:
    _generate(admin)
    response = admin.patch(f"{API}/NT03", json={"display_name": " Zed "})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Zed"
    assert admin.patch(f"{API}/NT03", json={"display_name": "x" * 25}).status_code == 422
    assert admin.patch(f"{API}/NT03", json={"display_name": None}).json()["display_name"] is None


# --- audit ---


def test_audit_never_contains_category(admin: TestClient, db: Session) -> None:
    _generate(admin)
    admin.post(f"{API}/NT01/check-in", json={"category": "ovz", "display_name": "Ann"})
    admin.post(f"{API}/NT01/check-in", json={"category": "general"})
    admin.patch(f"{API}/NT01", json={"display_name": "Bob"})
    admin.delete(f"{API}/NT01/check-in")
    rows = list(db.scalars(select(AuditLog)))
    actions = {row.action for row in rows}
    assert {"participant.check_in", "participant.undo_check_in", "participant.update"} <= actions
    dump = json.dumps(
        [
            [row.action, row.object_type, row.object_id, row.before, row.after, row.reason]
            for row in rows
        ]
    ).lower()
    assert "ovz" not in dump
    assert "general" not in dump
    check_in = db.scalars(select(AuditLog).where(AuditLog.action == "participant.check_in")).first()
    assert check_in is not None
    assert check_in.after == {"checked_in": True, "category_set": True, "display_name": "Ann"}


# --- atomicity ---


@pytest.fixture
def failing_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    real = write_audit

    def write_then_fail(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        raise RuntimeError("boom")

    monkeypatch.setattr("neurotlon_server.participants.write_audit", write_then_fail)


def test_generate_is_atomic(admin: TestClient, db: Session, failing_audit: None) -> None:
    with pytest.raises(RuntimeError):
        admin.post(f"{API}/generate", json={"count": 3})
    assert list(db.scalars(select(Participant))) == []
    assert list(db.scalars(select(AuditLog).where(AuditLog.action == "participant.generate"))) == []


def test_check_in_is_atomic(
    admin: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate(admin, 2)
    audit_rows = len(list(db.scalars(select(AuditLog))))
    real = write_audit

    def write_then_fail(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        raise RuntimeError("boom")

    monkeypatch.setattr("neurotlon_server.participants.write_audit", write_then_fail)
    with pytest.raises(RuntimeError):
        admin.post(f"{API}/NT01/check-in", json={"category": "general", "display_name": "Ann"})
    participant = db.scalars(select(Participant).where(Participant.code == "NT01")).one()
    assert participant.checked_in_at is None
    assert participant.category is None
    assert participant.display_name is None
    assert len(list(db.scalars(select(AuditLog)))) == audit_rows
