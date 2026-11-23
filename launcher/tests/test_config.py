import logging
import os
from pathlib import Path
from typing import Any

import pytest

from neurotlon_launcher.config import (
    ConfigError,
    load_config,
    parse_config,
    warn_if_token_is_shared,
)

VALID: dict[str, Any] = {
    "server_url": "https://10.0.0.5:8443/",
    "token_file": "station.token",
    "discipline": "pong",
    "game": {"command": ["python", "-m", "game"], "workdir": "games"},
}


def test_parse_defaults_and_relative_paths(tmp_path: Path) -> None:
    config = parse_config(VALID, tmp_path)
    assert config.server_url == "https://10.0.0.5:8443"
    assert config.token_file == tmp_path / "station.token"
    assert config.game_workdir == tmp_path / "games"
    assert config.data_dir == tmp_path / "data"
    assert (config.bridge_host, config.bridge_port, config.camera_index) == ("127.0.0.1", 8765, 0)


def test_load_from_toml_and_read_token(tmp_path: Path) -> None:
    (tmp_path / "station.token").write_text("  secret-token\n", encoding="utf-8")
    (tmp_path / "launcher.toml").write_text(
        'server_url = "https://x"\ntoken_file = "station.token"\ndiscipline = "darts"\n'
        'camera_index = 2\n[game]\ncommand = ["a.exe"]\n[bridge]\nport = 9000\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path / "launcher.toml")
    assert config.read_token() == "secret-token"
    assert (config.bridge_port, config.camera_index, config.game_workdir) == (9000, 2, None)


def test_missing_and_empty_token_file(tmp_path: Path) -> None:
    config = parse_config(VALID, tmp_path)
    with pytest.raises(ConfigError):
        config.read_token()
    (tmp_path / "station.token").write_text("\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.read_token()


@pytest.mark.parametrize(
    "patch",
    [
        {"discipline": "chess"},
        {"server_url": None},
        {"game": {"command": []}},
        {"game": {"command": "python"}},
        {"bridge": {"port": 70000}},
        {"bridge": {"port": True}},
        {"camera_index": -1},
        {"camera_name": ""},
        {"camera_name": 5},
        {"server_url": "http://10.0.0.5:8000"},
        {"server_url": "ftp://x"},
        {"allow_insecure_http": "yes"},
        {"ca_file": 5},
        {"fallback_duration_s": 5},
        {"fallback_duration_s": True},
        {"token_file": 5},
    ],
)
def test_invalid_config(tmp_path: Path, patch: dict[str, Any]) -> None:
    data = {**VALID, **patch}
    if data.get("server_url") is None:
        del data["server_url"]
    with pytest.raises(ConfigError):
        parse_config(data, tmp_path)


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")
    (tmp_path / "bad.toml").write_text("= not toml", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "bad.toml")


def test_tls_and_fallback_defaults(tmp_path: Path) -> None:
    config = parse_config(VALID, tmp_path)
    assert config.ca_file is None
    assert config.allow_insecure_http is False
    assert config.fallback_duration_s == 240


def test_ca_file_and_fallback_from_config(tmp_path: Path) -> None:
    config = parse_config({**VALID, "ca_file": "hall.crt", "fallback_duration_s": 150}, tmp_path)
    assert config.ca_file == tmp_path / "hall.crt"
    assert config.fallback_duration_s == 150


def test_plain_http_needs_explicit_opt_in_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = {**VALID, "server_url": "http://10.0.0.5:8000"}
    with pytest.raises(ConfigError, match="https"):
        parse_config(data, tmp_path)
    with caplog.at_level(logging.WARNING):
        config = parse_config({**data, "allow_insecure_http": True}, tmp_path)
    assert config.allow_insecure_http
    assert "unencrypted" in caplog.text


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_warns_when_token_file_is_world_readable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    token = tmp_path / "station.token"
    token.write_text("secret", encoding="utf-8")
    config = parse_config(VALID, tmp_path)
    token.chmod(0o600)
    with caplog.at_level(logging.WARNING):
        config.read_token()
    assert "readable by other users" not in caplog.text
    token.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        config.read_token()
    assert "readable by other users" in caplog.text
    assert "secret" not in caplog.text


def test_warn_helper_is_quiet_on_missing_file(tmp_path: Path) -> None:
    warn_if_token_is_shared(tmp_path / "none.token")


def test_camera_name_is_optional_and_trimmed() -> None:
    assert parse_config(VALID, Path("/x")).camera_name is None
    assert (
        parse_config(VALID | {"camera_name": "  USB Camera "}, Path("/x")).camera_name
        == "USB Camera"
    )
