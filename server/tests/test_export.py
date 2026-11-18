from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.models import Participant

from .conftest import login_as, make_user
from .station_helpers import API, SESSION_B, darts_body, make_station, seed_people


def sheets(response_content: bytes) -> dict[str, list[list[object]]]:
    book = load_workbook(BytesIO(response_content))
    return {ws.title: [list(row) for row in ws.iter_rows(values_only=True)] for ws in book}


@pytest.fixture
def played(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert client.post(f"{API}/results", json=darts_body(), headers=headers).status_code == 201


@pytest.mark.parametrize(
    ("role", "status"),
    [("superuser", 200), ("admin", 200), ("judge", 200), ("volunteer", 403)],
)
def test_export_role_matrix(app: FastAPI, db: Session, role: str, status: int) -> None:
    make_user(db, "u", role=role, discipline="darts" if role == "volunteer" else None)
    response = login_as(app, "u").get(f"{API}/export.xlsx")
    assert response.status_code == status


def test_export_requires_login(client: TestClient) -> None:
    assert client.get(f"{API}/export.xlsx").status_code == 401


def test_export_headers_and_sheets(app: FastAPI, db: Session, played: None) -> None:
    make_user(db, "adm", role="admin")
    response = login_as(app, "adm").get(f"{API}/export.xlsx")
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in response.headers["content-disposition"]
    book = sheets(response.content)
    assert list(book) == ["Итоги", "Участники"]
    assert book["Итоги"][0] == [
        "Место",
        "Команда",
        "Итого",
        "Дартс",
        "Футбол",
        "Понг",
        "Секций пройдено",
    ]
    assert book["Участники"][0] == [
        "Команда",
        "Участник",
        "Дартс · BCI",
        "Дартс · физическая",
        "Футбол · BCI",
        "Футбол · физическая",
        "Понг · BCI",
        "Понг · физическая",
        "Итого",
        "Секций пройдено",
        "Нужно решение",
    ]


def test_export_matches_the_scoreboard(
    app: FastAPI, client: TestClient, db: Session, played: None
) -> None:
    make_user(db, "adm", role="admin")
    book = sheets(login_as(app, "adm").get(f"{API}/export.xlsx").content)
    board = client.get(f"{API}/scoreboard").json()["teams"]
    summary = book["Итоги"][1:]
    assert len(summary) == len(board) == 2
    for row, team in zip(summary, board, strict=True):
        assert row[:3] == [team["rank"], team["name"], team["total"]]
        assert row[3:6] == [team["by_discipline"][d] for d in ("darts", "football", "pong")]
        assert row[6] == team["sections_passed"]
    assert summary[0][:3] == [1, "Alpha", 42.5]
    member = book["Участники"][1]
    assert member[:3] == ["Alpha", "Name 1", 42.5]  # label and darts BCI points
    assert member[3:8] == [None, None, None, None, None]  # nothing entered there
    assert member[8:10] == [42.5, 1]
    assert member[10] is None


def test_export_has_no_category(app: FastAPI, db: Session, played: None) -> None:
    make_user(db, "adm", role="admin")
    book = sheets(login_as(app, "adm").get(f"{API}/export.xlsx").content)
    text = repr(book).lower()
    for word in ("ovz", "general", "овз", "категор", "reserve", "резерв"):
        assert word not in text
    assert "NT05" not in repr(book)  # reserve participants are not exported


def test_conflict_is_marked_and_counts_nothing(
    app: FastAPI, client: TestClient, db: Session, played: None
) -> None:
    make_user(db, "adm", role="admin")
    _, headers = make_station(db, "d2", "darts")
    second = darts_body(SESSION_B, points=10)
    assert client.post(f"{API}/results", json=second, headers=headers).status_code == 201
    book = sheets(login_as(app, "adm").get(f"{API}/export.xlsx").content)
    member = book["Участники"][1]
    assert member[2] is None
    assert member[8:11] == [0, 0, "да"]


def test_export_without_draw_has_only_headers(app: FastAPI, db: Session) -> None:
    make_user(db, "adm", role="admin")
    book = sheets(login_as(app, "adm").get(f"{API}/export.xlsx").content)
    assert len(book["Итоги"]) == 1
    assert len(book["Участники"]) == 1


def test_display_name_cannot_become_a_formula(app: FastAPI, db: Session, played: None) -> None:
    make_user(db, "adm", role="admin")
    person = db.scalars(select(Participant).where(Participant.code == "NT01")).one()
    person.display_name = "=1+1"
    db.commit()
    response = login_as(app, "adm").get(f"{API}/export.xlsx")
    book = load_workbook(BytesIO(response.content))
    cell = book["Участники"]["B2"]
    assert cell.value == "=1+1"
    assert cell.data_type == "s"
