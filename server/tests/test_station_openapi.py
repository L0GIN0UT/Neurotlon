from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from .conftest import login_as, make_user
from .station_helpers import API, darts_body, make_station, pong_body, seed_people

SPEC_PATH = Path(__file__).resolve().parents[2] / "shared" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return data


def validate(spec: dict[str, Any], name: str, instance: object) -> None:
    schema = {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
    Draft202012Validator(schema).validate(instance)


def test_config_matches_schema(spec: dict[str, Any], client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    validate(spec, "DisciplineConfig", client.get(f"{API}/me/config", headers=headers).json())


def test_volunteer_config_matches_schema(spec: dict[str, Any], app: FastAPI, db: Session) -> None:
    make_user(db, "vol", role="volunteer", discipline="pong")
    validate(spec, "DisciplineConfig", login_as(app, "vol").get(f"{API}/me/config").json())


def test_eligibility_matches_schema(spec: dict[str, Any], client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    for code in ("NT01", "NT02", "NT06"):
        response = client.get(
            f"{API}/participants/{code}/eligibility?discipline=darts&section=bci", headers=headers
        )
        validate(spec, "Eligibility", response.json())


def test_receipts_match_schema(spec: dict[str, Any], client: TestClient, db: Session) -> None:
    seed_people(db)
    _, darts = make_station(db, "d1", "darts")
    _, pong = make_station(db, "p1", "pong")
    first = client.post(f"{API}/results", json=darts_body(code="NT05"), headers=darts)
    second = client.post(f"{API}/results", json=pong_body(), headers=pong)
    assert first.json()["warnings"]  # the schema is checked with a warning present
    validate(spec, "ResultReceipt", first.json())
    validate(spec, "ResultReceipt", second.json())


def test_problem_matches_schema(spec: dict[str, Any], client: TestClient, db: Session) -> None:
    _, headers = make_station(db, "d1", "darts")
    response = client.get(
        f"{API}/participants/NT77/eligibility?discipline=darts&section=bci", headers=headers
    )
    assert response.status_code == 404
    validate(spec, "Problem", response.json())


def test_staff_endpoints_match_schema(
    spec: dict[str, Any], app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    make_user(db, "root", role="superuser")
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    root = login_as(app, "root")
    for row in root.get(f"{API}/stations").json():
        validate(spec, "StationInfo", row)
    for row in root.get(f"{API}/users").json():
        validate(spec, "UserInfo", row)
    found = root.get(f"{API}/results").json()["items"]
    assert found
    for row in found:
        validate(spec, "StoredResult", row)
    patch = {"points": 4, "change_reason": "recount"}
    validate(spec, "ResultPatch", patch)
    validate(spec, "StoredResult", root.patch(f"{API}/results/{found[0]['id']}", json=patch).json())
