import uuid

import pytest

from neurotlon_launcher import texts
from neurotlon_launcher.api import ApiProblem, Busy, Offline, Unauthorized, UnknownParticipant
from neurotlon_launcher.game import Aborted, Crashed, Finished, GameEntry
from neurotlon_launcher.machine import (
    DEFAULT_DURATION_S,
    DONE_SECONDS,
    Checking,
    Confirm,
    Done,
    Idle,
    Playing,
    Starting,
    State,
    StationMachine,
    TechnicalProblem,
)
from neurotlon_launcher.outbox import ActiveSession
from neurotlon_launcher.testing import FakeApi, FakeQueue, FakeRunner, Ids, Time, eligibility

DARTS_DONE = Finished((GameEntry("NT07", "completed", 42.5),))
PONG_DONE = Finished(
    (GameEntry("NT03", "completed", 11.0, 1), GameEntry("NT14", "completed", 7.0, 0))
)


class Rig:
    def __init__(self, discipline: str = "darts", *outcomes: Finished | Aborted | Crashed) -> None:
        self.api = FakeApi()
        self.queue = FakeQueue()
        self.runner = FakeRunner(*outcomes)
        self.time = Time()
        self.kicks = 0
        self.machine = StationMachine(
            discipline,
            self.api,
            self.queue,
            self.runner,
            clock=self.time.clock,
            monotonic=self.time.monotonic,
            new_session_id=Ids(),
            on_enqueue=self._kick,
        )

    def _kick(self) -> None:
        self.kicks += 1

    @property
    def state(self) -> State:
        return self.machine.state

    def snap(self) -> State:
        return self.machine.state

    def scan(self, raw: str) -> None:
        self.machine.enter_code(raw)
        self.machine.tick()

    def confirm_through(self, raw: str) -> None:
        """Ввод кода и «Это я» (для понга после первого игрока вернёмся в Idle)."""
        self.scan(raw)
        self.machine.confirm()


def test_happy_path_darts() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.api.people["NT07"] = eligibility("NT07", name="Аня")
    rig.machine.enter_code("7")
    assert rig.snap() == Checking("NT07", ())
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.display_name == "Аня"
    assert not rig.state.candidate.warned
    rig.machine.confirm()
    assert isinstance(rig.state, Starting)
    assert rig.state.session_id == uuid.UUID(int=1)
    rig.machine.tick()
    assert isinstance(rig.state, Playing)
    assert rig.api.started == [(uuid.UUID(int=1), "darts", ["NT07"])]
    request = rig.runner.requests[0]
    assert (request.duration_s, request.discipline) == (90, "darts")
    assert [(p.code, p.display_name) for p in request.players] == [("NT07", "Аня")]

    rig.time.wall = rig.time.wall.replace(minute=9)  # игра вышла в 11:09
    rig.machine.tick()
    assert isinstance(rig.state, Done)
    assert rig.queue.items == [
        {
            "session_id": str(uuid.UUID(int=1)),
            "discipline": "darts",
            "section": "bci",
            "finished_at": "2027-04-12T11:09:00+00:00",
            "entries": [{"participant_code": "NT07", "outcome": "completed", "points": 42.5}],
        }
    ]
    assert rig.kicks == 1

    rig.time.mono += DONE_SECONDS - 0.1
    rig.machine.tick()
    assert isinstance(rig.state, Done)
    rig.time.mono += 0.2
    rig.machine.tick()
    assert rig.snap() == Idle()


def test_pong_collects_two_distinct_participants() -> None:
    rig = Rig("pong", PONG_DONE)
    rig.confirm_through("NT03")
    assert isinstance(rig.state, Idle)
    assert [c.code for c in rig.state.taken] == ["NT03"]

    taken = rig.state.taken
    rig.machine.enter_code("nt-03")  # тот же участник
    assert rig.snap() == Idle("", texts.ALREADY_PICKED, taken)
    assert rig.api.eligibility_calls == ["NT03"]  # на сервер повторно не ходили

    rig.confirm_through("NT14")
    assert isinstance(rig.state, Starting)
    rig.machine.tick()
    request = rig.runner.requests[0]
    assert [p.code for p in request.players] == ["NT03", "NT14"]  # левый, правый
    assert rig.api.started[0][2] == ["NT03", "NT14"]

    rig.machine.tick()
    assert rig.queue.items[0]["entries"] == [
        {"participant_code": "NT03", "outcome": "completed", "points": 11.0, "wins": 1},
        {"participant_code": "NT14", "outcome": "completed", "points": 7.0, "wins": 0},
    ]


def test_pong_cancel_steps_back() -> None:
    rig = Rig("pong")
    rig.confirm_through("NT03")
    rig.scan("NT14")
    assert isinstance(rig.state, Confirm)
    rig.machine.cancel()  # из подтверждения второго — к вводу второго
    assert isinstance(rig.state, Idle)
    assert len(rig.state.taken) == 1
    rig.machine.cancel()  # Esc ещё раз — убрать первого
    assert rig.snap() == Idle()


def test_issues_make_confirm_yellow_but_allow_start() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.api.people["NT07"] = eligibility("NT07", "not_checked_in", "no_pair_assigned")
    rig.scan("NT07")
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.warned
    assert rig.state.candidate.issues == ("not_checked_in", "no_pair_assigned")
    rig.machine.confirm()
    assert isinstance(rig.state, Starting)


def test_offline_everywhere_still_plays_and_queues() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.api.people["NT07"] = Offline("down")
    rig.api.config = Offline("down")
    rig.api.start_error = Offline("down")
    rig.scan("NT07")
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.offline
    assert rig.state.candidate.warned
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Playing)
    assert rig.state.offline
    assert rig.runner.requests[0].duration_s == DEFAULT_DURATION_S == 240
    rig.machine.tick()
    assert isinstance(rig.state, Done)
    assert len(rig.queue.items) == 1


def test_busy_returns_to_confirm_with_message() -> None:
    rig = Rig("darts")
    rig.api.start_error = Busy(409, "busy_on_other_station")
    rig.scan("NT07")
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.state.notice == texts.BUSY
    assert rig.state.candidate.code == "NT07"
    assert rig.runner.requests == []
    rig.machine.cancel()
    assert rig.snap() == Idle()


def test_busy_in_pong_returns_to_second_player_confirm() -> None:
    rig = Rig("pong")
    rig.confirm_through("NT03")
    rig.api.start_error = Busy(409, "busy_on_other_station")
    rig.confirm_through("NT14")
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.state.candidate.code == "NT14"
    assert [c.code for c in rig.state.taken] == ["NT03"]


@pytest.mark.parametrize(
    ("error", "notice"),
    [
        (UnknownParticipant(404, "unknown_participant"), texts.UNKNOWN_PARTICIPANT),
        (Unauthorized(401, "unauthorized"), texts.UNAUTHORIZED),
        (ApiProblem(500, "server_error"), texts.server_error("server_error")),
    ],
)
def test_eligibility_errors_return_to_idle(error: ApiProblem, notice: str) -> None:
    rig = Rig("darts")
    rig.api.people["NT07"] = error
    rig.scan("NT07")
    assert rig.state == Idle("", notice, ())


@pytest.mark.parametrize("raw", ["", "abc", "NT00", "https://x/NT07"])
def test_bad_code_keeps_idle_with_notice(raw: str) -> None:
    rig = Rig("darts")
    rig.machine.enter_code(raw)
    assert rig.state == Idle("", texts.BAD_CODE, ())


def test_start_errors_other_than_busy_return_to_confirm() -> None:
    rig = Rig("darts")
    rig.api.start_error = ApiProblem(403, "wrong_discipline")
    rig.scan("NT07")
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.state.notice == texts.server_error("wrong_discipline")
    rig.api.start_error = Unauthorized(401, "unauthorized")
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.state.notice == texts.UNAUTHORIZED


def test_config_error_returns_to_confirm() -> None:
    rig = Rig("darts")
    rig.api.config = ApiProblem(500, "server_error")
    rig.scan("NT07")
    rig.machine.confirm()
    rig.machine.tick()
    assert isinstance(rig.state, Confirm)
    assert rig.api.started == []


def test_technical_problem_retry_reuses_session_and_people() -> None:
    rig = Rig("darts", Crashed("код выхода 1"), DARTS_DONE)
    rig.scan("NT07")
    rig.machine.confirm()
    rig.machine.tick()
    rig.machine.tick()
    assert isinstance(rig.state, TechnicalProblem)
    assert rig.state.reason == "код выхода 1"
    assert rig.queue.items == []
    first = rig.state.session_id

    rig.machine.retry()
    assert isinstance(rig.state, Starting)
    assert rig.state.session_id == first
    rig.machine.tick()
    rig.machine.tick()
    assert isinstance(rig.state, Done)
    assert [r.session_id for r in rig.runner.requests] == [first, first]
    first_try, second_try = rig.runner.requests
    assert first_try.players == second_try.players
    assert rig.queue.items[0]["session_id"] == str(first)
    assert rig.queue.items[0]["entries"][0]["outcome"] == "completed"


def test_technical_problem_give_up_enqueues_not_completed_for_each() -> None:
    rig = Rig("pong", Aborted("датчик отвалился"))
    rig.confirm_through("NT03")
    rig.confirm_through("NT14")
    rig.machine.tick()
    rig.machine.tick()
    assert isinstance(rig.state, TechnicalProblem)
    assert rig.state.reason == "датчик отвалился"
    failed = rig.state.session_id
    rig.machine.give_up()
    assert isinstance(rig.state, Done)
    assert rig.queue.items == [
        {
            "session_id": str(failed),
            "discipline": "pong",
            "section": "bci",
            "finished_at": "2027-04-12T11:05:00+00:00",
            "entries": [
                {"participant_code": "NT03", "outcome": "not_completed", "reason": "equipment"},
                {"participant_code": "NT14", "outcome": "not_completed", "reason": "equipment"},
            ],
        }
    ]
    assert rig.kicks == 1


def test_keyboard_entry() -> None:
    rig = Rig("darts")
    for char in "n-t":  # "-" не буква и не цифра — игнорируется
        rig.machine.type_char(char)
    rig.machine.type_char("1")
    rig.machine.type_char("2")
    rig.machine.backspace()
    assert isinstance(rig.state, Idle)
    assert rig.state.input == "nt1"
    rig.machine.cancel()  # Esc стирает ввод
    assert rig.snap() == Idle()
    rig.machine.submit_input()  # пустой ввод — ничего
    assert rig.snap() == Idle()
    for char in "07":
        rig.machine.type_char(char)
    rig.machine.submit_input()
    assert rig.snap() == Checking("NT07", ())


def test_events_in_wrong_state_are_ignored() -> None:
    rig = Rig("darts")
    rig.machine.confirm()
    rig.machine.retry()
    rig.machine.give_up()
    rig.machine.cancel()
    rig.machine.tick()
    assert rig.snap() == Idle()
    rig.machine.enter_code("NT07")
    rig.machine.enter_code("NT08")  # уже Checking
    rig.machine.type_char("1")
    assert rig.snap() == Checking("NT07", ())


def test_heartbeat_view_per_state() -> None:
    rig = Rig("darts", DARTS_DONE)
    assert rig.machine.heartbeat_view() == ("idle", None)
    rig.scan("NT07")
    assert rig.machine.heartbeat_view() == ("confirming", None)
    rig.machine.confirm()
    assert rig.machine.heartbeat_view() == ("calibrating", uuid.UUID(int=1))
    rig.machine.tick()
    assert rig.machine.heartbeat_view() == ("playing", uuid.UUID(int=1))
    rig.machine.tick()
    assert rig.machine.heartbeat_view() == ("sending", None)


def test_close_stops_runner() -> None:
    rig = Rig("darts")
    rig.machine.close()
    assert rig.runner.stopped


def test_active_session_is_stored_before_game_and_cleared_on_result() -> None:
    rig = Rig("darts", DARTS_DONE)
    rig.api.people["NT07"] = eligibility("NT07", name="Аня")
    rig.scan("NT07")
    rig.machine.confirm()
    assert rig.queue.active is None
    rig.machine.tick()  # старт игры
    active = rig.queue.active
    assert active is not None
    assert (active.session_id, active.discipline, active.duration_s) == (
        str(uuid.UUID(int=1)),
        "darts",
        90,
    )
    assert active.players == (("NT07", "Аня"),)
    rig.machine.tick()  # игра вышла
    assert rig.queue.active is None


def test_recover_finished_enqueues_result() -> None:
    rig = Rig("darts")
    active = ActiveSession(str(uuid.UUID(int=5)), "darts", 90, (("NT07", None),))
    rig.machine.recover(active, DARTS_DONE)
    assert isinstance(rig.state, Done)
    assert rig.queue.items[0]["session_id"] == str(uuid.UUID(int=5))


def test_recover_without_result_shows_technical_problem() -> None:
    rig = Rig("pong")
    active = ActiveSession(str(uuid.UUID(int=5)), "pong", 90, (("NT03", "Аня"), ("NT14", None)))
    rig.machine.recover(active, Crashed("нет результата"))
    assert isinstance(rig.state, TechnicalProblem)
    assert [p.code for p in rig.state.players] == ["NT03", "NT14"]
    assert rig.state.reason == "нет результата"
    rig.machine.retry()
    rig.machine.tick()
    assert rig.runner.requests[0].session_id == uuid.UUID(int=5)


def test_fallback_duration_is_configurable() -> None:
    rig = Rig("darts")
    rig.machine = StationMachine(
        "darts", rig.api, rig.queue, rig.runner, fallback_duration_s=150, new_session_id=Ids()
    )
    rig.api.config = Offline("down")
    rig.scan("NT07")
    rig.machine.confirm()
    rig.machine.tick()
    assert rig.runner.requests[0].duration_s == 150
