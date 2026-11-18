"""XLSX export of the summary table. Same scoring code as the scoreboard; no category."""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from neurotlon_server.auth import Db, require_role
from neurotlon_server.models import User
from neurotlon_server.scoreboard_api import load_inputs
from neurotlon_server.scoring import SECTIONS, SectionScoring, score_teams

router = APIRouter(prefix="/api/v1", tags=["export"])

Exporter = Annotated[User, Depends(require_role("superuser", "admin", "judge"))]

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DISCIPLINE_TITLES = {"darts": "Дартс", "football": "Футбол", "pong": "Понг"}
SECTION_TITLES = {"bci": "BCI", "physical": "физическая"}


def _write(sheet: Worksheet, row: list[str | float | int | None], bold: bool = False) -> None:
    sheet.append(row)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"  # a name like "=1+1" must stay text, not become a formula
        if bold:
            cell.font = Font(bold=True)


def build_workbook(db: Session, scoring: SectionScoring) -> Workbook:
    results, people, teams, disciplines = load_inputs(db)
    labels = {p.id: p.display_name or p.code for p in people}
    codes = [
        d.code for d in sorted(disciplines, key=lambda d: list(DISCIPLINE_TITLES).index(d.code))
    ]
    ranked = score_teams(results, people, teams, disciplines, scoring)

    workbook = Workbook()
    summary = workbook.active
    assert summary is not None
    summary.title = "Итоги"
    _write(
        summary,
        ["Место", "Команда", "Итого", *[DISCIPLINE_TITLES[c] for c in codes], "Секций пройдено"],
        bold=True,
    )
    for team, score in ranked:
        _write(
            summary,
            [
                score.rank,
                team.name,
                score.total,
                *[score.by_discipline.get(c, 0.0) for c in codes],
                score.sections_passed,
            ],
        )

    members = workbook.create_sheet("Участники")
    section_columns = [(c, s) for c in codes for s in SECTIONS]
    _write(
        members,
        [
            "Команда",
            "Участник",
            *[f"{DISCIPLINE_TITLES[c]} · {SECTION_TITLES[s]}" for c, s in section_columns],
            "Итого",
            "Секций пройдено",
            "Нужно решение",
        ],
        bold=True,
    )
    for team, score in ranked:
        for member in score.members:
            _write(
                members,
                [
                    team.name,
                    labels[member.participant_id],
                    *[member.by_section.get(column) for column in section_columns],
                    member.total,
                    member.sections_passed,
                    "да" if member.conflicts else None,
                ],
            )
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for index, column in enumerate(sheet.columns, start=1):
            width = max(len(str(cell.value or "")) for cell in column)
            sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 40)
    return workbook


@router.get("/export.xlsx")
def export_xlsx(request: Request, db: Db, user: Exporter) -> Response:
    workbook = build_workbook(db, request.app.state.scoring)
    buffer = BytesIO()
    workbook.save(buffer)
    return Response(
        buffer.getvalue(),
        media_type=XLSX_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="neurotlon.xlsx"',
            "Cache-Control": "no-store",
        },
    )
