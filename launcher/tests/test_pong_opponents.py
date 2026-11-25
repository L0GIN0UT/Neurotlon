"""Понг: второй игрок должен быть соперником из той же пары сетки."""

from neurotlon_launcher import texts
from neurotlon_launcher.api import NotOpponents, Offline
from neurotlon_launcher.machine import Confirm, Idle, Starting

from .test_machine import Rig


def test_second_player_is_checked_against_the_first() -> None:
    rig = Rig("pong")
    rig.confirm_through("3")
    rig.scan("4")
    assert rig.api.opponents == [None, "NT03"]
    assert isinstance(rig.state, Confirm)


def test_darts_never_sends_an_opponent() -> None:
    rig = Rig("darts")
    rig.scan("3")
    assert rig.api.opponents == [None]


def test_not_opponents_keeps_the_first_player_and_asks_for_another() -> None:
    from neurotlon_launcher.testing import eligibility

    rig = Rig("pong")
    rig.api.people["NT07"] = eligibility("NT07", "not_opponents")
    rig.confirm_through("3")
    rig.scan("7")
    assert isinstance(rig.state, Idle)
    assert rig.state.notice == texts.NOT_OPPONENTS
    assert [c.code for c in rig.state.taken] == ["NT03"]
    assert "не играют друг против друга" in texts.NOT_OPPONENTS
    assert "соперник из той же пары" in texts.NOT_OPPONENTS
    assert rig.runner.requests == []
    # a right opponent is accepted afterwards
    rig.scan("4")
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.code == "NT04"


def test_server_refusal_on_session_start_returns_to_second_player() -> None:
    rig = Rig("pong")
    rig.confirm_through("3")
    rig.scan("4")
    rig.api.start_error = NotOpponents(409, "not_opponents")
    rig.machine.confirm()
    assert isinstance(rig.state, Starting)
    rig.machine.tick()
    assert isinstance(rig.state, Idle)
    assert rig.state.notice == texts.NOT_OPPONENTS
    assert [c.code for c in rig.state.taken] == ["NT03"]
    assert rig.runner.requests == []


def test_offline_keeps_the_old_behaviour_and_logs_a_warning(caplog) -> None:  # type: ignore[no-untyped-def]
    rig = Rig("pong")
    rig.confirm_through("3")
    rig.api.people["NT04"] = Offline("down")
    with caplog.at_level("WARNING"):
        rig.scan("4")
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.offline
    assert "pair is not verified" in caplog.text
    assert "NT04" not in caplog.text and "NT03" not in caplog.text  # no IDs in the log
