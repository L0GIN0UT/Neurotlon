import asyncio
import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.requests import Request

from neurotlon_server.models import AuditLog, Discipline, Participant, SectionResult, Team
from neurotlon_server.scoreboard_api import (
    ScoreboardCache,
    scoreboard_events,
    stream_scoreboard,
)

from .conftest import login_as, make_user
from .station_helpers import API, SESSION_B, darts_body, make_station, pong_body, seed_people

SESSION_C = "5d2f6a10-9b3c-4e1d-a7c8-0e4b1f2a3c6d"


def two_darts(client: TestClient, db: Session) -> dict[str, str]:
    """NT01 gets two different darts BCI results: a conflict."""
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    assert client.post(f"{API}/results", json=darts_body(), headers=headers).status_code == 201
    second = darts_body(SESSION_B, points=10)
    assert client.post(f"{API}/results", json=second, headers=headers).status_code == 201
    return headers


def alpha(client: TestClient) -> dict[str, Any]:
    team: dict[str, Any] = client.get(f"{API}/scoreboard").json()["teams"][0]
    assert team["name"] == "Alpha"
    return team


def result_ids(db: Session) -> list[int]:
    db.expire_all()
    return [r.id for r in db.scalars(select(SectionResult).order_by(SectionResult.id))]


def test_scoreboard_is_public_and_has_no_category(client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    response = client.get(f"{API}/scoreboard")
    assert response.status_code == 200
    body = response.json()
    assert [t["number"] for t in body["teams"]] == [1, 2]
    first = body["teams"][0]
    assert (first["rank"], first["total"], first["sections_passed"]) == (1, 4.5, 1)
    assert first["by_discipline"] == {"darts": 4.5, "football": 0, "pong": 0}
    assert first["finished"] is False
    assert first["duel_score"] == 0
    assert first["top"]["darts"] == [
        {"rank": 1, "number": 1, "label": "Name 1", "points": 4.5, "pending": False}
    ]
    assert first["top"]["football"] == first["top"]["pong"] == []
    assert list(first["top"]) == ["darts", "football", "pong"]
    assert "members" not in first
    text = response.text.lower()
    assert "ovz" not in text
    assert "general" not in text
    assert "NT05" not in response.text  # reserve is not shown


def test_conflict_appears_and_counts_nothing(app: FastAPI, client: TestClient, db: Session) -> None:
    two_darts(client, db)
    team = alpha(client)
    assert team["total"] == 0
    assert team["top"]["darts"][0]["pending"] is True
    make_user(db, "boss", role="admin")
    listing = login_as(app, "boss").get(f"{API}/conflicts")
    assert listing.status_code == 200
    (item,) = listing.json()
    assert (item["participant_code"], item["discipline"], item["section"]) == (
        "NT01",
        "darts",
        "bci",
    )
    assert [r["points"] for r in item["results"]] == [4.5, 10]
    assert set(item["results"][0]) == {
        "id",
        "points",
        "wins",
        "outcome",
        "reason",
        "source",
        "finished_at",
        "created_at",
    }


def test_conflicts_require_login(client: TestClient) -> None:
    assert client.get(f"{API}/conflicts").status_code == 401
    assert client.post(f"{API}/conflicts/resolve", json={}).status_code == 401


def test_judge_resolves_and_scoreboard_counts_kept(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    two_darts(client, db)
    make_user(db, "judge", role="judge")
    judge = login_as(app, "judge")
    first, second = result_ids(db)
    response = judge.post(
        f"{API}/conflicts/resolve", json={"keep_result_id": second, "reason": "station glitch"}
    )
    assert response.status_code == 200
    assert response.json() == {"voided": [first]}
    assert alpha(client)["total"] == 10
    assert alpha(client)["top"]["darts"][0]["pending"] is False
    assert judge.get(f"{API}/conflicts").json() == []
    db.expire_all()
    voided = db.get(SectionResult, first)
    assert voided is not None
    assert voided.voided_at is not None
    assert voided.void_reason == "station glitch"
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "result.resolve")).one()
    assert audit.after == {"kept": second, "voided": [first]}
    assert audit.reason == "station glitch"
    again = judge.post(f"{API}/conflicts/resolve", json={"keep_result_id": second, "reason": "x"})
    assert again.status_code == 409


def test_volunteer_resolves_only_own_discipline(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    two_darts(client, db)
    make_user(db, "vd", role="volunteer", discipline="darts")
    make_user(db, "vf", role="volunteer", discipline="football")
    first, _second = result_ids(db)
    body = {"keep_result_id": first, "reason": "ok"}
    other = login_as(app, "vf")
    assert other.get(f"{API}/conflicts").json() == []
    assert other.post(f"{API}/conflicts/resolve", json=body).status_code == 403
    own = login_as(app, "vd")
    assert len(own.get(f"{API}/conflicts").json()) == 1
    assert own.post(f"{API}/conflicts/resolve", json=body).status_code == 200
    assert alpha(client)["total"] == 4.5


def test_resolve_validation(app: FastAPI, client: TestClient, db: Session) -> None:
    seed_people(db)
    _, headers = make_station(db, "d1", "darts")
    client.post(f"{API}/results", json=darts_body(), headers=headers)
    make_user(db, "judge", role="judge")
    judge = login_as(app, "judge")
    (only,) = result_ids(db)
    url = f"{API}/conflicts/resolve"
    assert judge.post(url, json={"keep_result_id": only, "reason": "x"}).status_code == 409
    assert judge.post(url, json={"keep_result_id": 999, "reason": "x"}).status_code == 404
    assert judge.post(url, json={"keep_result_id": only, "reason": ""}).status_code == 422
    assert judge.post(url, json={"keep_result_id": only, "reason": "x" * 201}).status_code == 422


def test_station_cannot_use_conflicts(client: TestClient, db: Session) -> None:
    headers = two_darts(client, db)
    assert client.get(f"{API}/conflicts", headers=headers).status_code == 401


def test_pong_win_points_come_from_discipline(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    seed_people(db)
    _, headers = make_station(db, "p1", "pong")
    body = {
        "session_id": SESSION_C,
        "discipline": "pong",
        "section": "bci",
        "finished_at": darts_body()["finished_at"],
        "entries": [
            {"participant_code": "NT01", "outcome": "completed", "points": 11, "wins": 1},
            {"participant_code": "NT02", "outcome": "completed", "points": 3, "wins": 0},
        ],
    }
    assert client.post(f"{API}/results", json=body, headers=headers).status_code == 201
    assert alpha(client)["total"] == 10
    make_user(db, "judge", role="judge")
    patch = login_as(app, "judge").patch(f"{API}/disciplines/pong", json={"win_points": 25})
    assert patch.status_code == 200
    assert alpha(client)["total"] == 25


def test_discipline_patch_roles_bounds_and_audit(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    for login, role, discipline in (
        ("boss", "admin", None),
        ("judge", "judge", None),
        ("vol", "volunteer", "darts"),
    ):
        make_user(db, login, role=role, discipline=discipline)
    url = f"{API}/disciplines/darts"
    assert client.patch(url, json={"win_points": 1}).status_code == 401
    assert login_as(app, "vol").patch(url, json={"win_points": 1}).status_code == 403
    admin = login_as(app, "boss")
    response = admin.patch(url, json={"game_duration_s": 90, "physical_duration_s": 200})
    assert response.status_code == 200
    assert response.json() == {
        "code": "darts",
        "game_duration_s": 90,
        "physical_duration_s": 200,
        "win_points": 10,
        "max_section_points": 10,
    }
    assert login_as(app, "judge").patch(url, json={"win_points": 0}).status_code == 200
    for bad in (
        {"game_duration_s": 9},
        {"physical_duration_s": 3601},
        {"win_points": -1},
        {"win_points": 1001},
        {"max_section_points": 0},
        {"max_section_points": 1001},
        {"unknown": 1},
        {},
    ):
        assert admin.patch(url, json=bad).status_code == 422, bad
    assert admin.patch(f"{API}/disciplines/nope", json={"win_points": 1}).status_code == 404
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "discipline.update")).all()
    assert audit[0].before == {"game_duration_s": 120, "physical_duration_s": 300}
    assert audit[0].after == {"game_duration_s": 90, "physical_duration_s": 200}
    db.expire_all()
    darts = db.get(Discipline, "darts")
    assert darts is not None
    assert (darts.game_duration_s, darts.win_points) == (90, 0)


def collect(snapshots: list[tuple[int, str]], ping_every: float, count: int) -> list[str]:
    async def run() -> list[str]:
        feed = iter(snapshots)
        last = snapshots[-1]

        def snapshot() -> tuple[int, str]:
            return next(feed, last)

        async def no_sleep(_seconds: float) -> None:
            return None

        events: list[str] = []
        async for chunk in scoreboard_events(
            snapshot, interval=5, ping_every=ping_every, sleep=no_sleep
        ):
            events.append(chunk)
            if len(events) == count:
                break
        return events

    return asyncio.run(run())


def test_stream_sends_first_event_then_only_changes() -> None:
    feed = [(1, '{"a":1}'), (1, '{"a":1}'), (2, '{"a":2}')]
    assert collect(feed, ping_every=15, count=2) == [
        'event: scoreboard\ndata: {"a":1}\n\n',
        'event: scoreboard\ndata: {"a":2}\n\n',
    ]


def test_stream_sends_ping_while_idle() -> None:
    events = collect([(1, '{"a":1}')], ping_every=10, count=3)
    assert events[1:] == [": ping\n\n", ": ping\n\n"]


def test_stream_stops_when_client_disconnects() -> None:
    async def run() -> list[str]:
        async def no_sleep(_seconds: float) -> None:
            return None

        async def gone() -> bool:
            return True

        return [
            chunk
            async for chunk in scoreboard_events(
                lambda: (1, "{}"), sleep=no_sleep, is_disconnected=gone
            )
        ]

    assert asyncio.run(run()) == ["event: scoreboard\ndata: {}\n\n"]


class CountingCache(ScoreboardCache):
    builds = 0

    def _build(self) -> str:
        self.builds += 1
        return super()._build()


def test_streams_share_one_snapshot_per_change(app: FastAPI, db: Session) -> None:
    seed_people(db)
    cache = CountingCache(app.state.session_factory, app.state.scoring)

    async def run() -> list[list[str]]:
        ticks = 0

        async def sleep(_seconds: float) -> None:
            nonlocal ticks
            ticks += 1
            await asyncio.sleep(0)

        async def read(n: int) -> list[str]:
            out: list[str] = []
            async for chunk in scoreboard_events(cache.current, sleep=sleep, ping_every=0.5):
                out.append(chunk)
                if len(out) == n:
                    return out
            return out

        return list(await asyncio.gather(read(3), read(3)))

    first, second = asyncio.run(run())
    assert first[0] == second[0]
    assert first[1:] == [": ping\n\n"] * 2
    assert cache.builds == 1  # two clients, several ticks, one DB snapshot
    cache.mark_dirty()
    assert cache.current()[0] == 1  # unchanged data: same version, rebuilt once
    assert cache.builds == 2


def test_cache_background_task_refreshes_each_tick(app: FastAPI, db: Session) -> None:
    seed_people(db)
    cache = CountingCache(app.state.session_factory, app.state.scoring)

    async def run() -> None:
        ticks = 0

        async def sleep(_seconds: float) -> None:
            nonlocal ticks
            ticks += 1
            if ticks == 3:
                raise asyncio.CancelledError

        with contextlib.suppress(asyncio.CancelledError):
            await cache.run(2, sleep=sleep)

    asyncio.run(run())
    assert cache.builds == 3


def test_stream_endpoint_is_public_sse(app: FastAPI, db: Session) -> None:
    seed_people(db)

    async def run() -> tuple[str, str, str]:
        async def receive() -> dict[str, str]:
            return {"type": "http.request"}

        request = Request({"type": "http", "app": app, "headers": []}, receive)
        response = await stream_scoreboard(request)
        iterator = response.body_iterator.__aiter__()
        chunk = await iterator.__anext__()
        text = chunk if isinstance(chunk, str) else bytes(chunk).decode()
        await iterator.aclose()  # type: ignore[attr-defined]
        return response.media_type or "", response.headers["cache-control"], text

    media_type, cache, chunk = asyncio.run(run())
    assert media_type == "text/event-stream"
    assert cache == "no-store"
    assert chunk.startswith("event: scoreboard\ndata: ")
    payload = json.loads(chunk.split("data: ", 1)[1])
    assert payload["teams"][0]["name"] == "Alpha"


def test_voided_and_entered_rows_are_excluded(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    two_darts(client, db)
    first, second = result_ids(db)
    db.get(SectionResult, first).voided_at = datetime(2027, 1, 1, tzinfo=UTC)  # type: ignore[union-attr]
    assert alpha(client)["total"] == 0  # still cached: no write through the API yet
    app.state.scoreboard.mark_dirty()
    assert alpha(client)["total"] == 0  # uncommitted change is not visible
    db.commit()
    app.state.scoreboard.mark_dirty()
    assert alpha(client)["total"] == 10
    db.get(SectionResult, second).status = "entered"  # type: ignore[union-attr]
    db.commit()
    app.state.scoreboard.mark_dirty()
    team = alpha(client)
    assert (team["total"], team["sections_passed"]) == (0, 0)
    assert team["top"]["darts"] == []


def test_locked_and_confirmed_in_same_section_conflict(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    two_darts(client, db)
    first, _second = result_ids(db)
    db.get(SectionResult, first).status = "locked"  # type: ignore[union-attr]
    db.commit()
    app.state.scoreboard.mark_dirty()
    assert alpha(client)["top"]["darts"][0]["pending"] is True
    make_user(db, "judge", role="judge")
    assert len(login_as(app, "judge").get(f"{API}/conflicts").json()) == 1


def test_resolve_database_error_is_409(
    app: FastAPI, client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_darts(client, db)
    make_user(db, "judge", role="judge")
    judge = login_as(app, "judge")
    first, _second = result_ids(db)

    def locked(_self: Session) -> None:
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(Session, "commit", locked)
    response = judge.post(f"{API}/conflicts/resolve", json={"keep_result_id": first, "reason": "x"})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


SPEC_PATH = Path(__file__).resolve().parents[2] / "shared" / "openapi.yaml"


def place_pong_players(db: Session) -> None:
    """NT03 plays for Alpha, NT04 for Beta (seed_people only places NT01)."""
    teams = {t.number: t.id for t in db.scalars(select(Team))}
    for code, number, slot in (("NT03", 1, 2), ("NT04", 2, 1)):
        person = db.scalars(select(Participant).where(Participant.code == code)).one()
        person.team_id, person.number_in_team = teams[number], slot
    db.commit()


def test_duel_score_and_discipline_tops_and_schema(client: TestClient, db: Session) -> None:
    seed_people(db)
    place_pong_players(db)
    _, darts = make_station(db, "d1", "darts")
    _, pong = make_station(db, "p1", "pong")
    client.post(f"{API}/results", json=darts_body(), headers=darts)
    assert client.post(f"{API}/results", json=pong_body(), headers=pong).status_code == 201

    body = client.get(f"{API}/scoreboard").json()
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    schema = {"$ref": "#/components/schemas/Scoreboard", "components": spec["components"]}
    Draft202012Validator(schema).validate(body)

    alpha_row, beta_row = body["teams"]
    assert (alpha_row["duel_score"], beta_row["duel_score"]) == (1, 0)  # NT03 won the match
    assert alpha_row["by_discipline"]["pong"] == 10  # placeholder: wins * win_points
    assert alpha_row["top"]["pong"] == [
        {"rank": 1, "number": 2, "label": "Name 3", "points": 10, "pending": False}
    ]
    assert [e["label"] for e in alpha_row["top"]["darts"]] == ["Name 1"]
    assert beta_row["top"]["pong"] == [
        {"rank": 1, "number": 1, "label": "Name 4", "points": 0, "pending": False}
    ]


def test_conflicted_pong_match_is_not_counted_in_duel(client: TestClient, db: Session) -> None:
    seed_people(db)
    place_pong_players(db)
    _, pong = make_station(db, "p1", "pong")
    client.post(f"{API}/results", json=pong_body(), headers=pong)
    client.post(f"{API}/results", json=pong_body(SESSION_C), headers=pong)  # same players again
    first, second = client.get(f"{API}/scoreboard").json()["teams"]
    assert (first["duel_score"], second["duel_score"]) == (0, 0)
    assert first["top"]["pong"][0]["pending"] is True
    assert first["top"]["pong"][0]["rank"] is None
