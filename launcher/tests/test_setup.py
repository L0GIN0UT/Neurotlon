import json
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from neurotlon_launcher import setup as setup_mod
from neurotlon_launcher.__main__ import EXIT_RESTART, main
from neurotlon_launcher.api import DisciplineConfig, Offline, StationApiError, Unauthorized
from neurotlon_launcher.config import ConfigError, load_config
from neurotlon_launcher.setup import SetupForm, SetupService
from neurotlon_launcher.setup_station import SetupStation, form_from
from neurotlon_launcher.web_bridge import BridgeServer


def record(into: dict[str, Any], kwargs: dict[str, Any]) -> int:
    into.update(kwargs)
    return 0


TOKEN = "a-very-long-station-token-0123456789"


class FakeClient:
    def __init__(self, outcome: DisciplineConfig | Exception) -> None:
        self.outcome = outcome
        self.closed = False

    def get_config(self) -> DisciplineConfig:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        self.closed = True


class Factory:
    def __init__(self, outcome: DisciplineConfig | Exception) -> None:
        self.client = FakeClient(outcome)
        self.calls: list[tuple[str, str, Path | None]] = []

    def __call__(self, url: str, token: str, ca_file: Path | None) -> FakeClient:
        self.calls.append((url, token, ca_file))
        return self.client


@pytest.fixture
def game(tmp_path: Path) -> Path:
    exe = tmp_path / "games" / "Darts.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    return exe


def form(game: Path, **changes: str) -> SetupForm:
    values: dict[str, Any] = {
        "server_url": "https://192.168.1.10",
        "token": TOKEN,
        "game_path": str(game),
        "ca_file": "",
    }
    values.update(changes)
    return SetupForm(**values)


def service(tmp_path: Path, outcome: DisciplineConfig | Exception) -> tuple[SetupService, Factory]:
    factory = Factory(outcome)
    return SetupService(tmp_path / "cfg" / "launcher.toml", factory), factory


DARTS = DisciplineConfig("darts", "bci", 240, 10)


def test_check_returns_the_discipline_the_server_reports(tmp_path: Path, game: Path) -> None:
    svc, factory = service(tmp_path, DisciplineConfig("pong", "bci", 240))
    result = svc.check(form(game, server_url=" https://192.168.1.10/ "))
    assert (result.ok, result.discipline) == (True, "pong")
    assert factory.calls == [("https://192.168.1.10", TOKEN, None)]
    assert factory.client.closed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"server_url": ""}, setup_mod.URL_REQUIRED),
        ({"server_url": "http://192.168.1.10"}, setup_mod.URL_SCHEME),
        ({"server_url": "192.168.1.10"}, setup_mod.URL_SCHEME),
        ({"token": ""}, setup_mod.TOKEN_REQUIRED),
        ({"token": "short"}, setup_mod.TOKEN_SHORT),
        ({"game_path": ""}, setup_mod.GAME_REQUIRED),
        ({"game_path": "C:/nowhere/Game.exe"}, setup_mod.GAME_MISSING),
        ({"ca_file": "C:/nowhere/ca.crt"}, setup_mod.CERT_MISSING),
    ],
)
def test_check_rejects_bad_input_before_touching_the_network(
    tmp_path: Path, game: Path, changes: dict[str, str], message: str
) -> None:
    svc, factory = service(tmp_path, DARTS)
    assert svc.check(form(game, **changes)).error == message
    assert factory.calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (Unauthorized(401, "unauthorized"), setup_mod.UNAUTHORIZED),
        (Offline("connection refused"), setup_mod.OFFLINE),
        (Offline("[SSL: CERTIFICATE_VERIFY_FAILED] expired"), setup_mod.CERT_REJECTED),
    ],
)
def test_check_explains_what_went_wrong(
    tmp_path: Path, game: Path, outcome: Exception, message: str
) -> None:
    svc, factory = service(tmp_path, outcome)
    assert svc.check(form(game)).error == message
    assert factory.client.closed


def test_other_server_errors_are_reported(tmp_path: Path, game: Path) -> None:
    svc, _ = service(tmp_path, StationApiError("boom"))
    assert "boom" in (svc.check(form(game)).error or "")


def test_save_writes_a_loadable_config_and_a_private_token(tmp_path: Path, game: Path) -> None:
    svc, _ = service(tmp_path, DARTS)
    ca = tmp_path / "hall-ca.crt"
    ca.write_text("x", encoding="utf-8")
    svc.save(form(game, ca_file=str(ca)))
    config = load_config(tmp_path / "cfg" / "launcher.toml")
    assert config.server_url == "https://192.168.1.10"
    assert config.discipline is None  # дисциплину сообщает сервер
    assert config.game_command == (str(game),)
    assert config.game_workdir == game.parent
    assert config.ca_file == ca
    assert config.read_token() == TOKEN
    assert not list((tmp_path / "cfg").glob("*.tmp"))


def test_save_handles_spaces_and_cyrillic_in_paths(tmp_path: Path) -> None:
    exe = tmp_path / "мои игры (v2)" / "Darts.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    svc, _ = service(tmp_path, DARTS)
    svc.save(form(exe))
    assert load_config(tmp_path / "cfg" / "launcher.toml").game_command == (str(exe),)


def test_toml_strings_survive_quotes_and_backslashes() -> None:
    import tomllib

    for value in (r"C:\Games\Darts.exe", 'say "hi"', "tab	here", "юникод"):
        assert tomllib.loads(f"v = {setup_mod._toml(value)}")["v"] == value


def test_camera_is_saved_loaded_and_offered_back_as_a_default(tmp_path: Path, game: Path) -> None:
    svc, _ = service(tmp_path, DARTS)
    svc.save(form(game, camera='Logitech "C920" HD Pro'))
    config = load_config(tmp_path / "cfg" / "launcher.toml")
    assert config.camera_name == 'Logitech "C920" HD Pro'
    assert svc.defaults()["camera"] == 'Logitech "C920" HD Pro'
    svc.save(form(game))
    assert load_config(tmp_path / "cfg" / "launcher.toml").camera_name is None


def test_save_refuses_invalid_input(tmp_path: Path, game: Path) -> None:
    svc, _ = service(tmp_path, DARTS)
    with pytest.raises(ConfigError):
        svc.save(form(game, server_url="http://x"))
    assert not (tmp_path / "cfg").exists()


def test_saved_token_is_reused_and_never_returned(tmp_path: Path, game: Path) -> None:
    svc, factory = service(tmp_path, DARTS)
    svc.save(form(game))
    assert svc.check(form(game, token="")).ok
    assert factory.calls[-1][1] == TOKEN
    defaults = svc.defaults()
    assert defaults["has_token"] is True
    assert TOKEN not in json.dumps(defaults)
    assert defaults["server_url"] == "https://192.168.1.10"
    assert defaults["game_path"] == str(game)


def test_defaults_are_empty_without_config(tmp_path: Path) -> None:
    svc, _ = service(tmp_path, DARTS)
    assert svc.defaults() == {
        "server_url": "",
        "game_path": "",
        "ca_file": "",
        "camera": "",
        "sensors": "",
        "devices": {},
        "has_token": False,
    }


def test_form_from_accepts_only_string_fields() -> None:
    assert form_from({"server_url": "https://x", "token": "t"}) == SetupForm("https://x", "t")
    assert form_from({"camera": "Cam"}) == SetupForm(camera="Cam")
    assert form_from({"camera": 3}) is None
    assert form_from("text") is None
    assert form_from({"token": 5}) is None
    assert form_from({"token": "x" * 5000}) is None


# --- станция настройки и мост ---------------------------------------------------------------


@pytest.fixture
def setup_rig(tmp_path: Path, game: Path) -> Iterator[tuple[SetupStation, BridgeServer, Factory]]:
    svc, factory = service(tmp_path, DisciplineConfig("pong", "bci", 240))
    station = SetupStation(svc)
    server = BridgeServer(station, "t" * 32)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield station, server, factory
    server.close()


def post(server: BridgeServer, body: dict[str, Any]) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/command",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"X-Station-Token": "t" * 32, "Content-Type": "application/json"},
    )
    status: int = urllib.request.urlopen(request, timeout=5).status
    return status


def state_of(server: BridgeServer) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/state", headers={"X-Station-Token": "t" * 32}
    )
    data: dict[str, Any] = json.loads(urllib.request.urlopen(request, timeout=5).read())
    state: dict[str, Any] = data["state"]
    return state


def wait_for(server: BridgeServer, phase: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = state_of(server)
        if state["phase"] == phase:
            return state
        time.sleep(0.02)
    raise AssertionError(f"phase {phase} not reached: {state_of(server)}")


def fields(game: Path, **changes: str) -> dict[str, str]:
    base = {"server_url": "https://h", "token": TOKEN, "game_path": str(game), "ca_file": ""}
    return base | changes


def test_check_then_save_flow(
    setup_rig: tuple[SetupStation, BridgeServer, Factory], game: Path, tmp_path: Path
) -> None:
    station, server, _ = setup_rig
    first = state_of(server)
    assert (first["kind"], first["phase"], first["has_token"]) == ("setup", "form", False)

    assert post(server, {"action": "setup_check", "value": fields(game)}) == 204
    ok = wait_for(server, "ok")
    assert (ok["discipline"], ok["players_needed"], ok["error"]) == ("pong", 2, None)

    assert post(server, {"action": "setup_save", "value": fields(game)}) == 204
    assert state_of(server)["phase"] == "saved"
    assert station.saved.is_set()
    assert (tmp_path / "cfg" / "launcher.toml").is_file()


def test_save_without_a_matching_check_is_refused(
    setup_rig: tuple[SetupStation, BridgeServer, Factory], game: Path, tmp_path: Path
) -> None:
    station, server, _ = setup_rig
    post(server, {"action": "setup_save", "value": fields(game)})
    assert "Сначала нажмите" in state_of(server)["error"]
    assert not station.saved.is_set()

    post(server, {"action": "setup_check", "value": fields(game)})
    wait_for(server, "ok")
    post(server, {"action": "setup_save", "value": fields(game, server_url="https://other")})
    assert not station.saved.is_set()
    assert not (tmp_path / "cfg" / "launcher.toml").exists()


def test_failed_check_returns_to_the_form_with_the_reason(tmp_path: Path, game: Path) -> None:
    svc, _ = service(tmp_path, Unauthorized(401, "unauthorized"))
    station = SetupStation(svc)
    server = BridgeServer(station, "t" * 32)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        post(server, {"action": "setup_check", "value": fields(game)})
        state = wait_for(server, "form")
        assert state["error"] == setup_mod.UNAUTHORIZED
        assert state["discipline"] is None
    finally:
        server.close()


def test_setup_station_ignores_unknown_actions_and_bad_payloads(
    setup_rig: tuple[SetupStation, BridgeServer, Factory],
) -> None:
    station, _, _ = setup_rig
    assert not station.command("confirm", None)
    assert not station.command("setup_check", "nope")
    assert not station.command("setup_save", {"token": 1})


# --- выбор режима при запуске ---------------------------------------------------------------


def test_web_mode_without_config_starts_setup_and_exits_for_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    def fake_setup(config_path: Path, **kwargs: Any) -> int:
        seen.update(path=config_path, **kwargs)
        return EXIT_RESTART

    monkeypatch.setattr("neurotlon_launcher.__main__.run_setup", fake_setup)
    code = main(["--config", str(tmp_path / "launcher.toml"), "--ui-token", "t" * 32])
    assert code == EXIT_RESTART
    assert seen["error"] is None  # файла нет — это первая настройка, а не ошибка
    assert capsys.readouterr().err == ""


def test_web_mode_with_a_broken_config_shows_the_reason_in_the_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "launcher.toml").write_text("это не toml ===", encoding="utf-8")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "neurotlon_launcher.__main__.run_setup",
        lambda config_path, **kwargs: record(seen, kwargs),
    )
    main(["--config", str(tmp_path / "launcher.toml"), "--ui-token", "t" * 32])
    assert "не удалось разобрать" in seen["error"]


def test_setup_flag_forces_the_form_even_with_a_valid_config(
    tmp_path: Path, game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _ = service(tmp_path, DARTS)
    svc.save(form(game))
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "neurotlon_launcher.__main__.run_setup",
        lambda config_path, **kwargs: record(seen, kwargs),
    )
    main(
        [
            "--config",
            str(tmp_path / "cfg" / "launcher.toml"),
            "--setup",
            "--ui-token",
            "t" * 32,
        ]
    )
    assert seen["error"] is None


def test_web_mode_requires_a_launch_token(tmp_path: Path) -> None:
    assert main(["--config", str(tmp_path / "x.toml")]) == 2


def test_bundled_game_is_offered_by_default_but_never_overrides_a_working_choice(
    tmp_path: Path, game: Path
) -> None:
    bundled = tmp_path / "resources" / "game" / "Pong.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"MZ")
    factory = Factory(DARTS)
    svc = SetupService(tmp_path / "cfg" / "launcher.toml", factory, default_game=str(bundled))
    assert svc.defaults()["game_path"] == str(bundled)  # настроек ещё нет
    svc.save(form(game))
    assert svc.defaults()["game_path"] == str(game)  # рабочий выбор админа не трогаем
    game.unlink()
    assert svc.defaults()["game_path"] == str(bundled)  # выбранной игры уже нет
