from pathlib import Path

from neurotlon_launcher import texts
from neurotlon_launcher.api import ApiProblem, DisciplineConfig, Offline, Unauthorized
from neurotlon_launcher.machine import Blocked, Idle, RejectedEntry, RejectedList, StationMachine
from neurotlon_launcher.outbox import OutboxItem
from neurotlon_launcher.startup import check_discipline
from neurotlon_launcher.testing import FakeApi, FakeQueue, FakeRunner


class ConfigOnly:
    def __init__(self, result: DisciplineConfig | Exception) -> None:
        self.result = result

    def get_config(self) -> DisciplineConfig:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_matching_discipline_is_fine() -> None:
    assert check_discipline(ConfigOnly(DisciplineConfig("darts", "bci", 120)), "darts") is None


def test_mismatch_blocks_with_both_names() -> None:
    message = check_discipline(ConfigOnly(DisciplineConfig("pong", "bci", 120)), "darts")
    assert message == texts.discipline_mismatch("darts", "pong")
    assert message is not None
    assert "darts" in message
    assert "pong" in message


def test_offline_and_server_errors_do_not_block_but_bad_token_does() -> None:
    assert check_discipline(ConfigOnly(Offline("down")), "darts") is None
    assert check_discipline(ConfigOnly(ApiProblem(500, "server_error")), "darts") is None
    assert check_discipline(ConfigOnly(Unauthorized(401, "unauthorized")), "darts") == (
        texts.UNAUTHORIZED
    )


def make_machine(queue: FakeQueue) -> StationMachine:
    return StationMachine("darts", FakeApi(), queue, FakeRunner())


def test_blocked_state_ignores_every_event() -> None:
    machine = make_machine(FakeQueue())
    machine.block("нельзя")
    blocked = machine.state
    assert isinstance(blocked, Blocked)
    machine.enter_code("7")
    machine.type_char("1")
    machine.confirm()
    machine.cancel()
    machine.show_rejected()
    machine.tick()
    assert machine.state == blocked
    assert machine.heartbeat_view() == ("idle", None)


def rejected_item(n: int) -> OutboxItem:
    payload = {
        "session_id": f"s{n}",
        "entries": [{"participant_code": "NT03"}, {"participant_code": "NT14"}],
    }
    return OutboxItem(f"s{n}", payload, 1, f"409 session_conflict {n}", "rejected")


def test_rejected_screen_lists_items_and_exports() -> None:
    queue = FakeQueue()
    queue.rejected_items = [rejected_item(1), rejected_item(2)]
    machine = make_machine(queue)
    machine.show_rejected()
    state = machine.state
    assert isinstance(state, RejectedList)
    assert state.items[0] == RejectedEntry("s1", ("NT03", "NT14"), "409 session_conflict 1")
    assert len(state.items) == 2

    machine.export_rejected()
    exported = machine.state
    assert isinstance(exported, RejectedList)
    assert exported.exported_to == str(Path("rejected.json"))
    assert queue.exports == 1

    machine.close_rejected()
    assert machine.state == Idle()


def test_rejected_screen_only_from_clean_idle() -> None:
    machine = make_machine(FakeQueue())
    machine.type_char("1")
    machine.show_rejected()
    assert isinstance(machine.state, Idle)
    machine.export_rejected()  # вне экрана — ничего
    assert isinstance(machine.state, Idle)
