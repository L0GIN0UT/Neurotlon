from pathlib import Path

import pytest

from neurotlon_launcher.__main__ import EXIT_CONFIG, build_parser, main


def test_launch_token_is_required(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(tmp_path / "launcher.toml")]) == EXIT_CONFIG
    assert "--ui-token" in capsys.readouterr().err


def test_parser_flags() -> None:
    args = build_parser().parse_args(
        ["--config", "x.toml", "--ui-token", "t" * 16, "--ui-port", "9000", "--setup"]
    )
    assert (args.config, args.ui_token, args.ui_port, args.setup) == (
        Path("x.toml"),
        "t" * 16,
        9000,
        True,
    )
    defaults = build_parser().parse_args([])
    assert (defaults.config, defaults.ui_port, defaults.setup) == (Path("launcher.toml"), 0, False)
