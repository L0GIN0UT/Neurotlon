import json
import uuid
from pathlib import Path

from neurotlon_launcher import texts
from neurotlon_launcher.game import session_dir
from neurotlon_launcher.machine import Done, Idle, StationMachine, TechnicalProblem
from neurotlon_launcher.outbox import ActiveSession, Outbox
from neurotlon_launcher.recovery import recover_active
from neurotlon_launcher.testing import FakeApi, FakeRunner, Time

SID = uuid.UUID(int=9)


def machine_for(outbox: Outbox, discipline: str = "darts") -> StationMachine:
    clock = Time()
    return StationMachine(
        discipline, FakeApi(), outbox, FakeRunner(), clock=clock.clock, monotonic=clock.monotonic
    )


def write_result(data_dir: Path, **fields: object) -> None:
    folder = session_dir(data_dir, SID)
    folder.mkdir(parents=True)
    body = {"protocol": 1, "session_id": str(SID), **fields}
    (folder / "result.json").write_text(json.dumps(body), encoding="utf-8")


def active() -> ActiveSession:
    return ActiveSession(str(SID), "darts", 90, (("NT07", "Аня"),))


def test_active_session_survives_restart(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    assert box.get_active() is None
    box.set_active(active())
    box.close()
    assert Outbox(tmp_path / "o.db").get_active() == active()


def test_valid_result_after_restart_goes_to_outbox(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    box.set_active(active())
    write_result(
        tmp_path,
        status="finished",
        entries=[{"participant_code": "NT07", "outcome": "completed", "points": 12}],
    )
    machine = machine_for(box)
    recover_active(machine, box, tmp_path)
    assert isinstance(machine.state, Done)
    assert [i.session_id for i in box.pending()] == [str(SID)]
    assert box.get_active() is None


def test_missing_result_after_restart_shows_problem(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    box.set_active(active())
    machine = machine_for(box)
    recover_active(machine, box, tmp_path)
    assert isinstance(machine.state, TechnicalProblem)
    assert machine.state.reason == texts.RESTARTED
    assert box.pending() == []


def test_invalid_result_after_restart_shows_problem(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    box.set_active(active())
    write_result(tmp_path, status="finished", entries=[])
    machine = machine_for(box)
    recover_active(machine, box, tmp_path)
    assert isinstance(machine.state, TechnicalProblem)


def test_already_queued_or_foreign_discipline_is_just_cleared(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    box.set_active(active())
    box.add({"session_id": str(SID)})
    machine = machine_for(box)
    recover_active(machine, box, tmp_path)
    assert machine.state == Idle()
    assert box.get_active() is None
    box.set_active(active())
    recover_active(machine_for(box, "pong"), box, tmp_path)
    assert box.get_active() is None


def test_nothing_to_recover(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    machine = machine_for(box)
    recover_active(machine, box, tmp_path)
    assert machine.state == Idle()


def test_max_points_survives_restart(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db")
    limited = ActiveSession(str(SID), "darts", 90, (("NT07", "Аня"),), 10)
    box.set_active(limited)
    box.close()
    assert Outbox(tmp_path / "o.db").get_active() == limited
