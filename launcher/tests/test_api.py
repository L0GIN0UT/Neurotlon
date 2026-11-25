import json
import ssl
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from neurotlon_launcher.api import (
    ApiProblem,
    Busy,
    DisciplineConfig,
    HttpStationApi,
    InvalidRequest,
    Offline,
    SessionConflict,
    Unauthorized,
    UnknownParticipant,
    build_verify,
)

SESSION = uuid.UUID("0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10")
Handler = Callable[[httpx2.Request], httpx2.Response]


def make_api(handler: Handler, cache: Path | None = None) -> HttpStationApi:
    client = httpx2.Client(base_url="http://srv", transport=httpx2.MockTransport(handler))
    return HttpStationApi("http://srv", "tok", client=client, cache_path=cache)


def problem(status: int, code: str, detail: str = "d") -> httpx2.Response:
    return httpx2.Response(
        status,
        json={
            "type": "about:blank",
            "title": "t",
            "status": status,
            "code": code,
            "detail": detail,
        },
        headers={"content-type": "application/problem+json"},
    )


def test_get_config_sends_bearer_and_parses() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json={"discipline": "darts", "section": "bci", "duration_s": 120}
        )

    assert make_api(handler).get_config() == DisciplineConfig("darts", "bci", 120)
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert seen[0].url.path == "/api/v1/me/config"


def test_get_config_reads_and_caches_max_points(tmp_path: Path) -> None:
    online = {"up": True}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if not online["up"]:
            raise httpx2.ConnectError("down")
        body = {"discipline": "darts", "section": "bci", "duration_s": 120, "max_points": 10}
        return httpx2.Response(200, json=body)

    api = make_api(handler, tmp_path / "config.json")
    assert api.get_config().max_points == 10
    online["up"] = False
    assert api.get_config().max_points == 10


def test_get_config_without_max_points_is_none() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = {"discipline": "pong", "section": "bci", "duration_s": 90, "max_points": None}
        return httpx2.Response(200, json=body)

    assert make_api(handler).get_config().max_points is None


def test_config_cached_for_offline_start(tmp_path: Path) -> None:
    online = {"up": True}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if not online["up"]:
            raise httpx2.ConnectError("down")
        return httpx2.Response(200, json={"discipline": "pong", "section": "bci", "duration_s": 90})

    api = make_api(handler, tmp_path / "cache" / "config.json")
    assert api.get_config().duration_s == 90
    online["up"] = False
    assert api.get_config() == DisciplineConfig("pong", "bci", 90)


def test_offline_without_cache_raises_offline(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow")

    with pytest.raises(Offline):
        make_api(handler, tmp_path / "c.json").get_config()


def test_corrupt_cache_is_ignored(tmp_path: Path) -> None:
    cache = tmp_path / "c.json"
    cache.write_text("{bad", encoding="utf-8")

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    with pytest.raises(Offline):
        make_api(handler, cache).get_config()


def test_eligibility_parses_team_and_issues() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/participants/NT07/eligibility"
        assert dict(request.url.params) == {"discipline": "darts", "section": "bci"}
        return httpx2.Response(
            200,
            json={
                "code": "NT07",
                "display_name": None,
                "team": {"number": 1, "name": "Alpha", "color": "#aa00bb"},
                "issues": ["no_pair_assigned"],
            },
        )

    result = make_api(handler).eligibility("NT07", "darts", "bci")
    assert result.team is not None
    assert (result.team.name, result.team.color) == ("Alpha", "#aa00bb")
    assert result.issues == ("no_pair_assigned",)
    assert result.display_name is None


def test_eligibility_without_team() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"code": "NT07", "team": None, "issues": []})

    assert make_api(handler).eligibility("NT07", "darts", "bci").team is None


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (problem(404, "unknown_participant"), UnknownParticipant),
        (problem(409, "busy_on_other_station"), Busy),
        (problem(409, "session_conflict"), SessionConflict),
        (problem(422, "invalid_entries"), InvalidRequest),
        (problem(422, "invalid_request"), InvalidRequest),
        (problem(403, "wrong_discipline"), ApiProblem),
        (httpx2.Response(401, text="nope"), Unauthorized),
        (httpx2.Response(500, text="boom"), ApiProblem),
    ],
)
def test_problem_mapping(response: httpx2.Response, kind: type[ApiProblem]) -> None:
    api = make_api(lambda request: response)
    with pytest.raises(kind) as info:
        api.submit_result({})
    assert info.value.status == response.status_code
    assert type(info.value) is kind


def test_problem_carries_code_and_detail() -> None:
    api = make_api(lambda request: problem(409, "busy_on_other_station", "elsewhere"))
    with pytest.raises(Busy) as info:
        api.start_session(SESSION, "darts", ["NT01"])
    assert (info.value.code, info.value.detail) == ("busy_on_other_station", "elsewhere")


def test_start_session_body() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(201)

    make_api(handler).start_session(SESSION, "pong", ["NT03", "NT04"])
    assert bodies == [
        {"session_id": str(SESSION), "discipline": "pong", "participant_codes": ["NT03", "NT04"]}
    ]


@pytest.mark.parametrize("status", [200, 201])
def test_submit_result_success(status: int) -> None:
    api = make_api(lambda request: httpx2.Response(status, json={"results": []}))
    api.submit_result({"session_id": str(SESSION)})


def test_heartbeat_body_and_204() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(204)

    api = make_api(handler)
    api.heartbeat("idle", None, 2, {})
    api.heartbeat("playing", SESSION, 0, {})
    assert bodies[0] == {"state": "idle", "queue_length": 2, "sensors": {}}
    assert bodies[1]["session_id"] == str(SESSION)


def test_network_error_is_offline() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route")

    with pytest.raises(Offline):
        make_api(handler).heartbeat("idle", None, 0, {})


def test_build_verify_without_ca_uses_system_store() -> None:
    assert build_verify(None) is True


def test_build_verify_loads_hall_ca() -> None:
    context = build_verify(Path(__file__).parent / "data" / "test-ca.crt")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_build_verify_rejects_missing_or_broken_ca(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        build_verify(tmp_path / "none.crt")
    broken = tmp_path / "broken.crt"
    broken.write_text("not a certificate", encoding="utf-8")
    with pytest.raises(ssl.SSLError):
        build_verify(broken)


def test_default_client_gets_hall_ca() -> None:
    api = HttpStationApi(
        "https://srv", "tok", ca_file=Path(__file__).parent / "data" / "test-ca.crt"
    )
    api.close()


JPEG_TYPE = {"content-type": "image/jpeg"}
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"x" * 100 + b"\xff\xd9"


def test_eligibility_sends_opponent_and_reads_photo_fields() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "code": "NT04",
                "display_name": None,
                "team": None,
                "issues": ["not_opponents"],
                "has_photo": True,
                "photo_version": 1700,
            },
        )

    result = make_api(handler).eligibility("NT04", "pong", "bci", "NT03")
    assert seen[0].url.params["with"] == "NT03"
    assert result.issues == ("not_opponents",)
    assert (result.has_photo, result.photo_version) == (True, 1700)


def test_eligibility_without_opponent_has_no_with_parameter() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"code": "NT01", "team": None, "issues": []})

    result = make_api(handler).eligibility("NT01", "darts", "bci")
    assert "with" not in seen[0].url.params
    assert (result.has_photo, result.photo_version) == (False, None)


def test_start_session_not_opponents_is_its_own_error() -> None:
    from neurotlon_launcher.api import NotOpponents

    api = make_api(lambda request: problem(409, "not_opponents"))
    with pytest.raises(NotOpponents):
        api.start_session(SESSION, "pong", ["NT01", "NT03"])


def test_photo_returns_jpeg_from_station_endpoint() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})

    assert make_api(handler).photo("NT01") == JPEG_BYTES
    assert seen[0].url.path == "/api/v1/station/participants/NT01/photo"
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, content=b"<html>not a jpeg</html>"),
        httpx2.Response(200, content=b""),
        httpx2.Response(200, content=b"\xff\xd8\xff" + b"x" * (400 * 1024)),
        httpx2.Response(404, json={"code": "no_photo"}),
        httpx2.Response(401, json={"code": "unauthorized"}),
        httpx2.Response(500, content=b"boom"),
    ],
)
def test_photo_rejects_bad_answers(response: httpx2.Response) -> None:
    assert make_api(lambda request: response).photo("NT01") is None


def test_photo_offline_is_none() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    assert make_api(handler).photo("NT01") is None


def test_photo_limit_boundary_is_accepted() -> None:
    body = b"\xff\xd8\xff" + b"x" * (400 * 1024 - 3)
    assert (
        make_api(lambda r: httpx2.Response(200, content=body, headers=JPEG_TYPE)).photo("NT01")
        == body
    )
