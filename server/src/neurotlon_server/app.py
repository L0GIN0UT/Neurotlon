import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from neurotlon_server.admin import router as admin_router
from neurotlon_server.auth import LoginThrottle
from neurotlon_server.auth import router as auth_router
from neurotlon_server.config import Settings
from neurotlon_server.conflicts_api import router as conflicts_router
from neurotlon_server.corrections_api import router as corrections_router
from neurotlon_server.db import create_engine_from_settings, create_session_factory
from neurotlon_server.disciplines_api import router as disciplines_router
from neurotlon_server.draw_api import router as draw_router
from neurotlon_server.errors import PROBLEM_JSON, forbidden, install_error_handlers
from neurotlon_server.models import utcnow
from neurotlon_server.participants import router as participants_router
from neurotlon_server.scoreboard_api import PUSH_INTERVAL_S, ScoreboardCache
from neurotlon_server.scoreboard_api import router as scoreboard_router
from neurotlon_server.scoring import PlaceholderScoring
from neurotlon_server.station_api import router as station_router

_UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] = utcnow,
    scoreboard_interval: float = PUSH_INTERVAL_S,
) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine_from_settings(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_app.state.scoreboard.run(scoreboard_interval))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Neurotlon", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = create_session_factory(engine)
    app.state.scoring = PlaceholderScoring()  # the only place the scoring rule is chosen
    app.state.scoreboard = ScoreboardCache(app.state.session_factory, app.state.scoring)
    app.state.throttle = LoginThrottle(clock)
    install_error_handlers(app)

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Cookie-authenticated unsafe requests must come from our own origin.
        # Station requests (Bearer) are not browser-driven and are exempt.
        site = request.headers.get("sec-fetch-site")
        is_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        if (
            request.method in _UNSAFE_METHODS
            and not is_bearer
            and site is not None
            and site not in ("same-origin", "none")
        ):
            return JSONResponse(forbidden().body(), status_code=403, media_type=PROBLEM_JSON)
        response = await call_next(request)
        if request.method in _UNSAFE_METHODS and response.status_code < 500:
            app.state.scoreboard.mark_dirty()  # any write may change the scoreboard
        return response

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(participants_router)
    app.include_router(draw_router)
    app.include_router(station_router)
    app.include_router(scoreboard_router)
    app.include_router(conflicts_router)
    app.include_router(corrections_router)
    app.include_router(disciplines_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
