from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        extra: dict[str, int] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.extra = extra or {}

    def body(self) -> dict[str, str | int]:
        body: dict[str, str | int] = {
            **self.extra,
            "type": "about:blank",
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            body["detail"] = self.detail
        return body


def unauthorized() -> ProblemError:
    return ProblemError(401, "unauthorized", "Unauthorized")


def forbidden() -> ProblemError:
    return ProblemError(403, "forbidden", "Forbidden")


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not_found", "Not found", what)


def conflict(detail: str) -> ProblemError:
    return ProblemError(409, "conflict", "Conflict", detail)


def install_error_handlers(app: FastAPI) -> None:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ProblemError)
        return JSONResponse(exc.body(), status_code=exc.status, media_type=PROBLEM_JSON)

    async def handle_validation(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        # Drop `input` and `ctx`: they can echo submitted passwords back.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        body = {
            "type": "about:blank",
            "title": "Invalid request",
            "status": 422,
            "code": "invalid_request",
            "errors": errors,
        }
        return JSONResponse(body, status_code=422, media_type=PROBLEM_JSON)

    app.add_exception_handler(ProblemError, handle)
    app.add_exception_handler(RequestValidationError, handle_validation)
