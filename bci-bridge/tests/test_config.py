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
    assert config.alpha == BridgeConfig().alpha
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


def test_alpha_section_overrides_numbers() -> None:
    config = parse_config({"alpha": {"window_s": 3, "artifact_ptp_uv": 120, "calib_min_values": 8}})
    assert config.alpha.window_s == 3.0
    assert config.alpha.artifact_ptp_uv == 120.0
    assert config.alpha.calib_min_values == 8
    assert config.alpha.step_s == 0.2


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
        {"alpha": {"window_s": "2"}},
        {"alpha": {"calib_min_values": 9.5}},
        {"alpha": {"method": "alpha"}},
        {"alpha": {"window_s": 0}},
        {"alpha": {"step_s": -0.2}},
        {"alpha": {"window_s": 1.0, "step_s": 2.0}},
        {"alpha": {"band_low_hz": 40, "band_high_hz": 30}},
        {"alpha": {"band_high_hz": 130}},
        {"alpha": {"calib_low_pct": 60}},
        {"alpha": {"calib_high_pct": 101}},
        {"alpha": {"calib_low_pct": -1}},
        {"alpha": {"gap_ms": -1}},
        {"alpha": {"calib_min_values": 0}},
        {"alpha": {"alpha_low_hz": 14}},
        {"eeg": {"sampling_rate": 80}},
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


def test_burst_defaults_and_overrides() -> None:
    assert BridgeConfig().burst.arm_window_ms == 400.0
    config = parse_config({"burst": {"min_rise": 0.5, "confirm_points": 4, "release_ms": 100}})
    assert config.burst.min_rise == 0.5
    assert config.burst.confirm_points == 4
    assert config.burst.release_ms == 100.0
    assert config.burst.fire_level == 0.5  # остальное по умолчанию


def test_example_file_burst_section_matches_defaults() -> None:
    assert load_config(EXAMPLE).burst == BridgeConfig().burst


@pytest.mark.parametrize(
    "section",
    [
        {"nope": 1},
        {"min_rise": "0.4"},
        {"min_rise": True},
        {"confirm_points": 2.5},
        {"confirm_points": 0},
        {"arm_window_ms": 0},
        {"fire_level": 2},
        {"min_interval_ms": -5},
    ],
)
def test_burst_section_rejects_bad_values(section: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"burst": section})


def test_emg_cycle_keys() -> None:
    defaults = BridgeConfig().emg
    assert (defaults.cycle_tense_s, defaults.cycle_relax_s, defaults.cycle_repeats) == (5.0, 5.0, 2)
    assert defaults.transition_s == 1.5
    config = parse_config(
        {"emg": {"cycle_tense_s": 4, "cycle_repeats": 3, "transition_s": 1, "calib_min_ratio": 2}}
    )
    assert config.emg.cycle_tense_s == 4.0
    assert config.emg.cycle_repeats == 3
    assert config.emg.transition_s == 1.0
    assert config.emg.calib_min_ratio == 2.0


@pytest.mark.parametrize(
    "emg",
    [{"cycle_repeats": 0}, {"cycle_repeats": 1.5}, {"cycle_tense_s": 0}, {"transition_s": -1}],
)
def test_emg_cycle_keys_reject_bad_values(emg: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        parse_config({"emg": emg})


def test_baseline_default_is_twelve_seconds() -> None:
    assert BridgeConfig().eeg.calibration_s == 12
