"""Клиент API станции (`shared/openapi.yaml`): токен станции в заголовке Bearer."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx2

API_PREFIX = "/api/v1"
TIMEOUT_S = 3.0


class StationApiError(Exception):
    """Базовая ошибка обращения к серверу."""


class Offline(StationApiError):
    """Нет связи: сервер не ответил за таймаут или соединение не установлено."""


class ApiProblem(StationApiError):
    """Ответ сервера `application/problem+json` (или любой не-успешный ответ)."""

    def __init__(self, status: int, code: str, detail: str | None = None) -> None:
        super().__init__(f"{status} {code}" + (f": {detail}" if detail else ""))
        self.status = status
        self.code = code
        self.detail = detail


class Unauthorized(ApiProblem):
    """401: токен станции неверный или отозван."""


class UnknownParticipant(ApiProblem):
    """Нет участника с таким ID."""


class Busy(ApiProblem):
    """409 busy_on_other_station: участник играет на другом стенде."""


class SessionConflict(ApiProblem):
    """409 session_conflict: тот же session_id с другими данными."""


class InvalidRequest(ApiProblem):
    """422: тело запроса не принято (`invalid_request`, `invalid_entries`, ...)."""


_BY_CODE: dict[str, type[ApiProblem]] = {
    "unauthorized": Unauthorized,
    "unknown_participant": UnknownParticipant,
    "busy_on_other_station": Busy,
    "session_conflict": SessionConflict,
    "invalid_request": InvalidRequest,
    "invalid_entries": InvalidRequest,
}


def problem_from_response(response: httpx2.Response) -> ApiProblem:
    code = "unknown"
    detail: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        raw_code, raw_detail = body.get("code"), body.get("detail")
        code = raw_code if isinstance(raw_code, str) else code
        detail = raw_detail if isinstance(raw_detail, str) else None
    if response.status_code == 401:
        code = "unauthorized"
    kind = _BY_CODE.get(code, ApiProblem)
    return kind(response.status_code, code, detail)


@dataclass(frozen=True)
class DisciplineConfig:
    discipline: str
    section: str
    duration_s: int


@dataclass(frozen=True)
class Team:
    number: int
    name: str
    color: str


@dataclass(frozen=True)
class Eligibility:
    code: str
    display_name: str | None
    team: Team | None
    issues: tuple[str, ...]


class StationApi(Protocol):
    def get_config(self) -> DisciplineConfig: ...

    def eligibility(self, code: str, discipline: str, section: str) -> Eligibility: ...

    def start_session(
        self, session_id: uuid.UUID, discipline: str, participant_codes: list[str]
    ) -> None: ...

    def submit_result(self, payload: dict[str, Any]) -> None: ...

    def heartbeat(
        self,
        state: str,
        session_id: uuid.UUID | None,
        queue_length: int,
        sensors: dict[str, str],
    ) -> None: ...


class HttpStationApi:
    """HTTP-реализация `StationApi`; `get_config` кэширует ответ для старта без связи."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx2.Client | None = None,
        cache_path: Path | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_s)
        self._headers = {"Authorization": f"Bearer {token}"}
        self._cache_path = cache_path
        self._timeout_s = timeout_s

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx2.Response:
        try:
            response = self._client.request(
                method,
                API_PREFIX + path,
                params=params,
                json=json_body,
                headers=self._headers,
                timeout=self._timeout_s,
            )
        except httpx2.HTTPError as exc:
            raise Offline(str(exc) or type(exc).__name__) from exc
        if response.is_success:
            return response
        raise problem_from_response(response)

    def get_config(self) -> DisciplineConfig:
        try:
            data = self._request("GET", "/me/config").json()
        except Offline:
            cached = self._read_cache()
            if cached is None:
                raise
            return cached
        config = DisciplineConfig(data["discipline"], data["section"], int(data["duration_s"]))
        self._write_cache(data)
        return config

    def _read_cache(self) -> DisciplineConfig | None:
        if self._cache_path is None:
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return DisciplineConfig(data["discipline"], data["section"], int(data["duration_s"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, data: dict[str, Any]) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # кэш — удобство, а не обязанность

    def eligibility(self, code: str, discipline: str, section: str) -> Eligibility:
        data = self._request(
            "GET",
            f"/participants/{code}/eligibility",
            params={"discipline": discipline, "section": section},
        ).json()
        team = data.get("team")
        return Eligibility(
            code=data["code"],
            display_name=data.get("display_name"),
            team=Team(team["number"], team["name"], team["color"]) if team else None,
            issues=tuple(data.get("issues", [])),
        )

    def start_session(
        self, session_id: uuid.UUID, discipline: str, participant_codes: list[str]
    ) -> None:
        self._request(
            "POST",
            "/sessions",
            json_body={
                "session_id": str(session_id),
                "discipline": discipline,
                "participant_codes": participant_codes,
            },
        )

    def submit_result(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/results", json_body=payload)

    def heartbeat(
        self,
        state: str,
        session_id: uuid.UUID | None,
        queue_length: int,
        sensors: dict[str, str],
    ) -> None:
        body: dict[str, Any] = {"state": state, "queue_length": queue_length, "sensors": sensors}
        if session_id is not None:
            body["session_id"] = str(session_id)
        self._request("POST", "/stations/me/heartbeat", json_body=body)
