"""Клиент API станции (`shared/openapi.yaml`): токен станции в заголовке Bearer."""

from __future__ import annotations

import json
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx2

API_PREFIX = "/api/v1"
TIMEOUT_S = 3.0
PHOTO_MAX_BYTES = 400 * 1024
JPEG_MAGIC = b"\xff\xd8\xff"


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


class NotOpponents(ApiProblem):
    """409 not_opponents: в понге двое игроков не стоят в одной паре сетки."""


class SessionConflict(ApiProblem):
    """409 session_conflict: тот же session_id с другими данными."""


class InvalidRequest(ApiProblem):
    """422: тело запроса не принято (`invalid_request`, `invalid_entries`, ...)."""


_BY_CODE: dict[str, type[ApiProblem]] = {
    "unauthorized": Unauthorized,
    "unknown_participant": UnknownParticipant,
    "busy_on_other_station": Busy,
    "not_opponents": NotOpponents,
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
    max_points: int | None = None


def _config_from(data: dict[str, Any]) -> DisciplineConfig:
    raw = data.get("max_points")
    return DisciplineConfig(
        data["discipline"],
        data["section"],
        int(data["duration_s"]),
        int(raw) if raw is not None else None,
    )


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
    has_photo: bool = False
    photo_version: int | None = None


class StationApi(Protocol):
    def get_config(self) -> DisciplineConfig: ...

    def eligibility(
        self, code: str, discipline: str, section: str, opponent: str | None = None
    ) -> Eligibility: ...

    def photo(self, code: str) -> bytes | None:
        """JPEG участника; `None`, если фото нет, сервер недоступен или ответ не годится."""
        ...

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


def is_station_photo(data: bytes) -> bool:
    """Годится ли тело как фото: не больше 400 КБ и настоящий JPEG (по сигнатуре)."""
    return 0 < len(data) <= PHOTO_MAX_BYTES and data.startswith(JPEG_MAGIC)


def _photo_headers_ok(response: httpx2.Response) -> bool:
    """Тип и размер по заголовкам, до чтения тела."""
    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "image/jpeg":
        return False
    length = response.headers.get("content-length")
    return length is None or (length.isdigit() and int(length) <= PHOTO_MAX_BYTES)


def build_verify(ca_file: Path | None) -> ssl.SSLContext | bool:
    """Проверка сертификата сервера: свой корневой сертификат зала или системные."""
    if ca_file is None:
        return True
    return ssl.create_default_context(cafile=str(ca_file))


class HttpStationApi:
    """HTTP-реализация `StationApi`; `get_config` кэширует ответ для старта без связи."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx2.Client | None = None,
        cache_path: Path | None = None,
        ca_file: Path | None = None,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._client = client or httpx2.Client(
            base_url=base_url, timeout=timeout_s, verify=build_verify(ca_file)
        )
        self._headers = {"Authorization": f"Bearer {token}"}
        self._cache_path = cache_path

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
        config = _config_from(data)
        self._write_cache(data)
        return config

    def _read_cache(self) -> DisciplineConfig | None:
        if self._cache_path is None:
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return _config_from(data)
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

    def eligibility(
        self, code: str, discipline: str, section: str, opponent: str | None = None
    ) -> Eligibility:
        params = {"discipline": discipline, "section": section}
        if opponent is not None:
            params["with"] = opponent
        data = self._request("GET", f"/participants/{code}/eligibility", params=params).json()
        version = data.get("photo_version")
        team = data.get("team")
        return Eligibility(
            code=data["code"],
            display_name=data.get("display_name"),
            team=Team(team["number"], team["name"], team["color"]) if team else None,
            issues=tuple(data.get("issues", [])),
            has_photo=data.get("has_photo") is True,
            photo_version=version if isinstance(version, int) else None,
        )

    def photo(self, code: str) -> bytes | None:
        """Фото только в памяти: на диск и в журнал оно не попадает."""
        try:
            with self._client.stream(
                "GET", f"{API_PREFIX}/station/participants/{code}/photo", headers=self._headers
            ) as response:
                if not response.is_success or not _photo_headers_ok(response):
                    return None
                data = response.read()
        except httpx2.HTTPError:
            return None  # нет связи: экран остаётся с буквой
        return data if is_station_photo(data) else None

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
