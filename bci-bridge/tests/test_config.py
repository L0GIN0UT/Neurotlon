from pathlib import Path

import pytest

from neurotlon_bridge.config import (
    BridgeConfig,
    ConfigError,
    default_config_path,
    load_config,
    parse_config,
    required_devices,
)

EXAMPLE = Path(__file__).parents[1] / "bridge.example.toml"


def test_example_file_parses_with_defaults() -> None:
    config = load_config(EXAMPLE)
    assert config.devices == {}  # серийные номера в примере пустые
    assert config.emg == BridgeConfig().emg
    assert config.eeg == BridgeConfig().eeg
    assert config.scan_s == 12.0


def test_devices_and_overrides() -> None:
    config = parse_config(
        {
            "devices": {"eeg": "BB1", "emg": 123456, "scan_s": 5},
            "emg": {"settle_s": 2, "band_high_hz": 400},
            "eeg": {"calibration_s": 10},
        }
    )
    assert config.devices == {"eeg": "BB1", "emg": "123456"}
    assert config.scan_s == 5.0
    assert config.emg.settle_s == 2.0
    assert config.emg.band_high_hz == 400.0
    assert config.eeg.calibration_s == 10


@pytest.mark.parametrize(
    "data",
    [
        {"unknown": {}},
        {"devices": {"emg_middle": "x"}},
        {"devices": {"emg": ["x"]}},
        {"devices": {"scan_s": -1}},
        {"emg": {"nope": 1}},
        {"emg": {"settle_s": "5"}},
        {"emg": {"settle_s": True}},
        {"eeg": {"calibration_s": 8.5}},
    ],
)
def test_invalid_config_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config(data)


def test_required_devices_per_profile() -> None:
    config = BridgeConfig(devices={"eeg": "A", "emg": "B", "emg_left": "L", "emg_right": "R"})
    assert required_devices("darts", config) == {"eeg": "A", "emg": "B"}
    assert required_devices("pong", config) == {"emg_left": "L", "emg_right": "R"}


def test_missing_file_explicit_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="не найден"):
        load_config(tmp_path / "none.toml")


def test_broken_toml(tmp_path: Path) -> None:
    path = tmp_path / "bridge.toml"
    path.write_text("[devices\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="разобрать"):
        load_config(path)


def test_default_path_prefers_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_config_path() is None
    with pytest.raises(ConfigError, match=r"bridge\.example\.toml"):
        load_config(None)
    (tmp_path / "bridge.toml").write_text('[devices]\nemg = "Z"\n', encoding="utf-8")
    assert default_config_path() == tmp_path / "bridge.toml"
    assert load_config(None).devices == {"emg": "Z"}
