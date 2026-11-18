import pytest

from neurotlon_bridge.__main__ import main


def test_without_emulate_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "следующий шаг M2" in capsys.readouterr().out


def test_unknown_profile_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["--emulate", "--profile", "chess"])
