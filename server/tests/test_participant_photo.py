import zipfile
from collections.abc import Iterator
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from neurotlon_server.models import AuditLog

from .conftest import FakeClock, login_as, make_user
from .station_helpers import API as ROOT
from .station_helpers import darts_body, make_station, seed_people

API = "/api/v1/participants"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"PHOTO-BYTES" * 10 + b"\xff\xd9"
JPEG_2 = b"\xff\xd8\xff\xe1" + b"OTHER" * 10 + b"\xff\xd9"
JPEG_HEADERS = {"Content-Type": "image/jpeg"}


@pytest.fixture
def admin(app: FastAPI, db: Session) -> TestClient:
    make_user(db, "boss", role="admin")
    client = login_as(app, "boss")
    assert client.post(f"{API}/generate", json={"count": 3}).status_code == 200
    return client


def put(client: TestClient, content: bytes, code: str = "NT01") -> int:
    return client.put(f"{API}/{code}/photo", content=content, headers=JPEG_HEADERS).status_code


def listed(client: TestClient, code: str = "NT01") -> dict[str, object]:
    rows = client.get(API).json()
    return next(row for row in rows if row["code"] == code)


def test_upload_read_replace_delete(admin: TestClient, clock: FakeClock) -> None:
    assert put(admin, JPEG) == 204
    response = admin.get(f"{API}/nt01/photo")
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    clock.advance(seconds=1)
    assert put(admin, JPEG_2) == 204
    assert admin.get(f"{API}/NT01/photo").content == JPEG_2

    assert admin.delete(f"{API}/NT01/photo").status_code == 204
    assert admin.get(f"{API}/NT01/photo").status_code == 404
    assert admin.delete(f"{API}/NT01/photo").status_code == 404


def test_unknown_participant_is_404(admin: TestClient) -> None:
    assert put(admin, JPEG, code="NT09") == 404
    assert put(admin, JPEG, code="bad") == 404
    assert admin.get(f"{API}/NT09/photo").status_code == 404
    assert admin.delete(f"{API}/NT09/photo").status_code == 404


def test_get_without_photo_is_404(admin: TestClient) -> None:
    assert admin.get(f"{API}/NT02/photo").status_code == 404


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"GIF89a" + b"x" * 40 + b"\xff\xd9",
        b"\x89PNG\r\n\x1a\n" + b"x" * 40,
        b"\xff\xd8\xff\xe0" + b"x" * 40,  # truncated: no end marker
        b"\xff\xd8\xe0" + b"x" * 40 + b"\xff\xd9",  # bad start
    ],
)
def test_not_a_complete_jpeg_is_422(admin: TestClient, content: bytes) -> None:
    assert put(admin, content) == 422
    assert admin.get(f"{API}/NT01/photo").status_code == 404


def test_too_large_is_413_and_limit_is_accepted(admin: TestClient) -> None:
    limit = 400 * 1024
    exact = b"\xff\xd8\xff" + b"x" * (limit - 5) + b"\xff\xd9"
    assert len(exact) == limit
    assert put(admin, exact) == 204
    response = admin.put(f"{API}/NT02/photo", content=exact + b"x", headers=JPEG_HEADERS)
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert admin.get(f"{API}/NT02/photo").status_code == 404


def test_too_large_without_content_length_is_413(admin: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(5):
            yield b"x" * (100 * 1024)

    response = admin.put(f"{API}/NT02/photo", content=chunks(), headers=JPEG_HEADERS)
    assert response.status_code == 413


def test_roles(app: FastAPI, db: Session, admin: TestClient, client: TestClient) -> None:
    assert put(admin, JPEG) == 204
    make_user(db, "vol", role="volunteer", discipline="darts")
    make_user(db, "root", role="superuser")
    volunteer = login_as(app, "vol")
    assert put(volunteer, JPEG) == 403
    assert volunteer.get(f"{API}/NT01/photo").status_code == 403
    assert volunteer.delete(f"{API}/NT01/photo").status_code == 403
    assert put(login_as(app, "root"), JPEG_2) == 204

    assert put(client, JPEG) == 401
    assert client.get(f"{API}/NT01/photo").status_code == 401
    assert client.delete(f"{API}/NT01/photo").status_code == 401


def test_station_token_is_401(admin: TestClient, db: Session, client: TestClient) -> None:
    assert put(admin, JPEG) == 204
    _, headers = make_station(db, "d1", "darts")
    assert client.put(f"{API}/NT01/photo", content=JPEG, headers=headers).status_code == 401
    assert client.get(f"{API}/NT01/photo", headers=headers).status_code == 401
    assert client.delete(f"{API}/NT01/photo", headers=headers).status_code == 401


def test_audit_has_size_not_content(admin: TestClient, db: Session) -> None:
    assert put(admin, JPEG) == 204
    assert admin.delete(f"{API}/NT01/photo").status_code == 204
    rows = db.scalars(select(AuditLog).where(AuditLog.action.like("participant.photo_%"))).all()
    assert [row.action for row in rows] == ["participant.photo_set", "participant.photo_clear"]
    assert rows[0].after == {"code": "NT01", "size": len(JPEG)}
    assert rows[1].after == {"code": "NT01"}
    assert all(b"PHOTO-BYTES" not in repr(row.after).encode() for row in rows)


def test_list_has_photo_and_version(admin: TestClient, clock: FakeClock) -> None:
    before = listed(admin)
    assert before["has_photo"] is False
    assert before["photo_version"] is None

    assert put(admin, JPEG) == 204
    first = listed(admin)
    assert first["has_photo"] is True
    assert isinstance(first["photo_version"], int)
    assert listed(admin, "NT02")["has_photo"] is False

    clock.advance(seconds=1)
    assert put(admin, JPEG_2) == 204
    assert listed(admin)["photo_version"] != first["photo_version"]

    assert admin.delete(f"{API}/NT01/photo").status_code == 204
    assert listed(admin)["has_photo"] is False


def test_check_in_response_has_photo_fields(admin: TestClient) -> None:
    assert put(admin, JPEG) == 204
    body = admin.post(f"{API}/NT01/check-in", json={"category": "general"}).json()
    assert body["has_photo"] is True
    assert isinstance(body["photo_version"], int)


def test_list_does_not_query_per_participant(app: FastAPI, admin: TestClient) -> None:
    from sqlalchemy import event

    assert put(admin, JPEG) == 204
    assert put(admin, JPEG_2, code="NT02") == 204
    statements: list[str] = []
    engine = app.state.session_factory.kw["bind"]

    def record(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert admin.get(API).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    photo_queries = [s for s in statements if "participant_photo" in s]
    assert len(photo_queries) == 1
    assert "content" not in photo_queries[0]


def test_photo_absent_from_public_and_station_outputs(
    app: FastAPI, db: Session, client: TestClient
) -> None:
    seed_people(db)
    make_user(db, "boss", role="admin")
    admin = login_as(app, "boss")
    assert put(admin, JPEG, code="NT01") == 204
    assert put(admin, JPEG_2, code="NT03") == 204
    _, headers = make_station(db, "d1", "darts")
    assert client.post(f"{ROOT}/results", json=darts_body(), headers=headers).status_code == 201

    marker = b"PHOTO-BYTES"
    outputs = [
        client.get(f"{ROOT}/scoreboard"),
        client.get(f"{ROOT}/me/config", headers=headers),
        client.get(
            f"{ROOT}/participants/NT01/eligibility?discipline=darts&section=bci", headers=headers
        ),
    ]
    for response in outputs:
        assert response.status_code == 200
        assert marker not in response.content
        assert b"photo" not in response.content.lower()

    teams = admin.get(f"{ROOT}/teams")
    assert b"photo" not in teams.content.lower()

    export = admin.get(f"{ROOT}/export.xlsx")
    assert export.status_code == 200
    with zipfile.ZipFile(BytesIO(export.content)) as book:
        names = book.namelist()
        assert not [n for n in names if "media" in n or "drawing" in n or n.endswith(".jpeg")]
        assert all(b"photo" not in book.read(n).lower() for n in names)
        assert all(marker not in book.read(n) for n in names)
