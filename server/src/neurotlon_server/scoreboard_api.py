"""Public live scoreboard: JSON snapshot and SSE stream. No category, no internal ids."""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from neurotlon_server.models import Discipline, Participant, SectionResult, Team
from neurotlon_server.scoring import (
    DisciplineIn,
    ParticipantIn,
    ResultIn,
    SectionScoring,
    TeamIn,
    duel_score,
    score_teams,
    top_players,
)

router = APIRouter(prefix="/api/v1/scoreboard", tags=["scoreboard"])

DISCIPLINE_ORDER = ("darts", "football", "pong")
PUSH_INTERVAL_S = 2.0
POLL_INTERVAL_S = 0.5  # how often a stream checks the shared cache (in memory)
PING_INTERVAL_S = 15.0


class TopOut(BaseModel):
    rank: int | None
    number: int
    label: str
    points: float
    pending: bool


class TeamRowOut(BaseModel):
    rank: int
    number: int
    name: str
    color: str
    total: float
    duel_score: int
    by_discipline: dict[str, float]
    sections_passed: int
    finished: bool
    top: dict[str, list[TopOut]]


class ScoreboardOut(BaseModel):
    teams: list[TeamRowOut]


def load_inputs(
    db: Session,
) -> tuple[list[ResultIn], list[ParticipantIn], list[TeamIn], list[DisciplineIn]]:
    results = [
        ResultIn(
            r.id,
            r.participant_id,
            r.discipline,
            r.section,
            r.outcome,
            r.points,
            r.wins,
            r.status,
            r.voided_at is not None,
            r.session_id,
        )
        for r in db.scalars(select(SectionResult))
    ]
    people = [
        ParticipantIn(p.id, p.code, p.display_name, p.team_id, p.number_in_team)
        for p in db.scalars(select(Participant).where(Participant.team_id.is_not(None)))
    ]
    teams = [TeamIn(t.id, t.number, t.name, t.color) for t in db.scalars(select(Team))]
    disciplines = [DisciplineIn(d.code, d.win_points) for d in db.scalars(select(Discipline))]
    return results, people, teams, disciplines


def build_scoreboard(db: Session, scoring: SectionScoring) -> ScoreboardOut:
    results, people, teams, disciplines = load_inputs(db)
    labels = {p.id: p.display_name or p.code for p in people}
    numbers = {p.id: p.number_in_team or 0 for p in people}
    duel = duel_score(results, people)
    rows = [
        TeamRowOut(
            rank=score.rank,
            number=team.number,
            name=team.name,
            color=team.color,
            total=score.total,
            duel_score=duel.get(team.id, 0),
            by_discipline=score.by_discipline,
            sections_passed=score.sections_passed,
            finished=score.finished,
            top={
                d.code: [
                    TopOut(
                        rank=e.rank,
                        number=e.number,
                        label=labels[e.participant_id],
                        points=e.points,
                        pending=e.pending,
                    )
                    for e in top_players(score.members, numbers, d.code)
                ]
                for d in sorted(disciplines, key=lambda d: DISCIPLINE_ORDER.index(d.code))
            },
        )
        for team, score in score_teams(results, people, teams, disciplines, scoring)
    ]
    return ScoreboardOut(teams=rows)


def _event(payload: str) -> str:
    return f"event: scoreboard\ndata: {payload}\n\n"


class ScoreboardCache:
    """One shared snapshot for all clients: built once per change or tick, not per request."""

    def __init__(self, factory: sessionmaker[Session], scoring: SectionScoring) -> None:
        self._factory = factory
        self._scoring = scoring
        self._lock = threading.Lock()
        self._payload: str | None = None
        self._version = 0
        self._dirty = True

    def mark_dirty(self) -> None:
        self._dirty = True

    def _build(self) -> str:
        with self._factory() as db:
            return build_scoreboard(db, self._scoring).model_dump_json()

    def _rebuild(self) -> tuple[int, str]:
        self._dirty = False  # a write during the build marks it dirty again
        payload = self._build()
        if payload != self._payload:
            self._payload = payload
            self._version += 1
        return self._version, payload

    def refresh(self) -> tuple[int, str]:
        with self._lock:
            return self._rebuild()

    def current(self) -> tuple[int, str]:
        """Cached snapshot; rebuilt first when a write happened since the last build."""
        with self._lock:
            if self._dirty or self._payload is None:
                return self._rebuild()
            return self._version, self._payload

    async def run(
        self,
        interval: float = PUSH_INTERVAL_S,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        """Background task: rebuild every `interval` seconds (picks up out-of-band writes)."""
        while True:
            try:
                await asyncio.to_thread(self.refresh)
            except Exception:
                logging.getLogger(__name__).exception("scoreboard refresh failed")
            await sleep(interval)


async def scoreboard_events(
    snapshot: Callable[[], tuple[int, str]],
    *,
    interval: float = POLL_INTERVAL_S,
    ping_every: float = PING_INTERVAL_S,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """First event right away, then one whenever the version changed; `: ping` while idle."""
    last, payload = await asyncio.to_thread(snapshot)
    yield _event(payload)
    idle = 0.0
    while True:
        await sleep(interval)
        if is_disconnected is not None and await is_disconnected():
            return
        version, payload = await asyncio.to_thread(snapshot)
        if version != last:
            last, idle = version, 0.0
            yield _event(payload)
            continue
        idle += interval
        if idle >= ping_every:
            idle = 0.0
            yield ": ping\n\n"


@router.get("", response_model=ScoreboardOut)
def get_scoreboard(request: Request) -> Response:
    cache: ScoreboardCache = request.app.state.scoreboard
    _, payload = cache.current()
    return Response(payload, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/stream")
async def stream_scoreboard(request: Request) -> StreamingResponse:
    cache: ScoreboardCache = request.app.state.scoreboard
    ping: float = getattr(request.app.state, "scoreboard_ping", PING_INTERVAL_S)
    return StreamingResponse(
        scoreboard_events(cache.current, ping_every=ping, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
