import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from .conftest import login_as, make_user
from .station_helpers import API


@pytest.mark.parametrize(
    ("role", "discipline", "status"),
    [
        ("superuser", None, 200),
        ("admin", None, 200),
        ("judge", None, 200),
        ("volunteer", "pong", 403),
    ],
)
def test_disciplines_list_role_matrix(
    app: FastAPI, db: Session, role: str, discipline: str | None, status: int
) -> None:
    make_user(db, "staff", role=role, discipline=discipline)
    assert login_as(app, "staff").get(f"{API}/disciplines").status_code == status


def test_disciplines_list_shows_current_settings(app: FastAPI, db: Session) -> None:
    make_user(db, "adm", role="admin")
    admin = login_as(app, "adm")
    admin.patch(f"{API}/disciplines/pong", json={"win_points": 25})
    rows = {d["code"]: d for d in admin.get(f"{API}/disciplines").json()}
    assert list(rows) == ["darts", "football", "pong"]
    assert rows["pong"]["win_points"] == 25
    assert set(rows["darts"]) == {
        "code",
        "game_duration_s",
        "physical_duration_s",
        "win_points",
        "max_section_points",
    }
    assert rows["darts"]["max_section_points"] == 10


def test_disciplines_list_requires_login(client: TestClient) -> None:
    assert client.get(f"{API}/disciplines").status_code == 401
