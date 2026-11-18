from pathlib import Path
from typing import Any

import pytest

from neurotlon_launcher.config import ConfigError, load_config, parse_config

VALID: dict[str, Any] = {
    "server_url": "http://10.0.0.5:8000/",
    "token_file": "station.token",
    "discipline": "pong",
    "game": {"command": ["python", "-m", "game"], "workdir": "games"},
}


def test_parse_defaults_and_relative_paths(tmp_path: Path) -> None:
    config = parse_config(VALID, tmp_path)
    assert config.server_url == "http://10.0.0.5:8000"
    assert config.token_file == tmp_path / "station.token"
    assert config.game_workdir == tmp_path / "games"
    assert config.data_dir == tmp_path / "data"
    assert (config.bridge_host, config.bridge_port, config.camera_index) == ("127.0.0.1", 8765, 0)


def test_load_from_toml_and_read_token(tmp_path: Path) -> None:
    (tmp_path / "station.token").write_text("  secret-token\n", encoding="utf-8")
    (tmp_path / "launcher.toml").write_text(
        'server_url = "http://x"\ntoken_file = "station.token"\ndiscipline = "darts"\n'
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
