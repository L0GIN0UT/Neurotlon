from pathlib import Path

import pytest

from neurotlon_launcher.__main__ import EXIT_CONFIG, build_parser, main


def test_missing_config_exits_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "nope.toml")]) == EXIT_CONFIG
    assert "Ошибка настроек" in capsys.readouterr().err


def test_missing_token_file_exits_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "launcher.toml"
    config.write_text(
        'server_url = "https://x"\ntoken_file = "none.token"\ndiscipline = "darts"\n'
        '[game]\ncommand = ["g"]\n',
        encoding="utf-8",
    )
    assert main(["--config", str(config)]) == EXIT_CONFIG
    assert "токен" in capsys.readouterr().err


def test_parser_flags() -> None:
    args = build_parser().parse_args(["--no-camera", "--windowed", "--config", "x.toml"])
    assert (args.no_camera, args.windowed, args.config) == (True, True, Path("x.toml"))
    assert build_parser().parse_args([]).config == Path("launcher.toml")
