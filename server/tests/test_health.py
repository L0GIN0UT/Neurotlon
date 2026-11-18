from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_database(app: FastAPI) -> None:
    def broken() -> Session:
        raise RuntimeError("database is gone")

    app.state.session_factory = broken
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error"}
