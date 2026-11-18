from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from neurotlon_server.admin import router as admin_router
from neurotlon_server.auth import LoginThrottle
from neurotlon_server.auth import router as auth_router
from neurotlon_server.config import Settings
from neurotlon_server.db import create_engine_from_settings, create_session_factory
from neurotlon_server.errors import PROBLEM_JSON, forbidden, install_error_handlers
from neurotlon_server.models import utcnow
from neurotlon_server.participants import router as participants_router

_UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def create_app(settings: Settings | None = None, clock: Callable[[], datetime] = utcnow) -> FastAPI:
    settings = settings or Settings()
    engine = create_engine_from_settings(settings)
    app = FastAPI(title="Neurotlon")
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = create_session_factory(engine)
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
        return await call_next(request)

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(participants_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
