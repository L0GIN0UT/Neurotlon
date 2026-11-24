import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

from neurotlon_launcher import proc
from neurotlon_launcher.game import (
    Aborted,
    Crashed,
    Finished,
    GameEntry,
    GameOutcome,
    GameRequest,
    Player,
    SubprocessGameRunner,
    launch_document,
    parse_result,
)
from neurotlon_launcher.schema import launch_validator

STUB = [sys.executable, "-m", "neurotlon_games.stub"]


def request(discipline: str = "darts", codes: tuple[str, ...] = ("NT07",)) -> GameRequest:
    players = tuple(Player(c, f"Имя {c}" if i == 0 else None) for i, c in enumerate(codes))
    return GameRequest(uuid.uuid4(), discipline, 10, players)


def runner(tmp_path: Path, *extra: str, **kwargs: object) -> SubprocessGameRunner:
    return SubprocessGameRunner(
        (*STUB, "--seconds", "0", *extra),
        None,
        tmp_path,
        "127.0.0.1",
        8765,
        **kwargs,  # type: ignore[arg-type]
    )


def wait(game: SubprocessGameRunner, timeout: float = 30.0) -> GameOutcome:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        outcome = game.poll()
        if outcome is not None:
            return outcome
        time.sleep(0.02)
    raise AssertionError("game did not finish")


def test_darts_finished(tmp_path: Path) -> None:
    game = runner(tmp_path, "--seed", "3")
    req = request()
    game.start(req)
    outcome = wait(game)
    assert isinstance(outcome, Finished)
    assert [e.participant_code for e in outcome.entries] == ["NT07"]
    assert outcome.entries[0].outcome == "completed"
    assert outcome.entries[0].points is not None
    assert outcome.entries[0].wins is None
    folder = tmp_path / "sessions" / str(req.session_id)
    launch = json.loads((folder / "launch.json").read_text(encoding="utf-8"))
    launch_validator("Launch").validate(launch)
    assert launch["participants"] == [{"code": "NT07", "display_name": "Имя NT07"}]
    assert game.poll() is None  # результат отдаётся один раз


def test_pong_two_players_one_winner(tmp_path: Path) -> None:
    game = runner(tmp_path)
    req = request("pong", ("NT03", "NT14"))
    game.start(req)
    outcome = wait(game)
    assert isinstance(outcome, Finished)
    assert [e.participant_code for e in outcome.entries] == ["NT03", "NT14"]
    assert sorted(e.wins or 0 for e in outcome.entries) == [0, 1]
    launch = json.loads(
        (tmp_path / "sessions" / str(req.session_id) / "launch.json").read_text(encoding="utf-8")
    )
    assert [p["side"] for p in launch["participants"]] == ["left", "right"]


def test_aborted(tmp_path: Path) -> None:
    game = runner(tmp_path, "--abort")
    game.start(request())
    assert wait(game) == Aborted("stub: aborted")


def test_crash_exit_code(tmp_path: Path) -> None:
    game = runner(tmp_path, "--crash")
    game.start(request())
    outcome = wait(game)
    assert isinstance(outcome, Crashed)
    assert "1" in outcome.detail


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def wait_child_pid(folder: Path, timeout: float = 20.0) -> int:
    end = time.monotonic() + timeout
    pid_file = folder / "child.pid"
    while time.monotonic() < end:
        if pid_file.exists() and pid_file.read_text(encoding="utf-8"):
            return int(pid_file.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError("child pid was not written")


def timeout_game(tmp_path: Path, now: list[float]) -> SubprocessGameRunner:
    return SubprocessGameRunner(
        (*STUB, "--seconds", "60", "--spawn-child"),
        None,
        tmp_path,
        "127.0.0.1",
        8765,
        monotonic=lambda: now[0],
    )


def test_timeout_kills_process_and_its_child(tmp_path: Path) -> None:
    now = [0.0]
    game = timeout_game(tmp_path, now)
    req = request()
    game.start(req)
    child = wait_child_pid(tmp_path / "sessions" / str(req.session_id))
    parent = game._proc
    assert parent is not None
    assert pid_alive(child)
    assert game.poll() is None
    now[0] = 10 + 420 + 1  # duration_s + 420
    outcome = game.poll()
    assert isinstance(outcome, Crashed)
    assert "вовремя" in outcome.detail
    assert game.poll() is None
    assert parent.poll() is not None
    assert wait_dead(parent.pid)
    assert wait_dead(child)


def test_taskkill_fallback_when_job_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform != "win32":
        pytest.skip("taskkill fallback is Windows-only")
    monkeypatch.setattr(proc, "create_kill_on_close_job", lambda process: None)
    now = [0.0]
    game = timeout_game(tmp_path, now)
    req = request()
    game.start(req)
    child = wait_child_pid(tmp_path / "sessions" / str(req.session_id))
    now[0] = 1000.0
    assert isinstance(game.poll(), Crashed)
    assert wait_dead(child)


def test_missing_executable(tmp_path: Path) -> None:
    game = SubprocessGameRunner(("definitely-not-a-binary-xyz",), None, tmp_path, "h", 1)
    game.start(request())
    outcome = game.poll()
    assert isinstance(outcome, Crashed)
    assert game.poll() is None


def test_stop_kills_running_game(tmp_path: Path) -> None:
    game = SubprocessGameRunner((*STUB, "--seconds", "60"), None, tmp_path, "127.0.0.1", 8765)
    game.start(request())
    game.stop()
    assert game.poll() is None


def test_long_display_name_is_truncated(tmp_path: Path) -> None:
    req = GameRequest(uuid.uuid4(), "darts", 10, (Player("NT01", "я" * 50),))
    doc = launch_document(req, tmp_path / "r.json", "h", 1)
    assert len(doc["participants"][0]["display_name"]) == 24
    launch_validator("Launch").validate(doc)


def write_result(tmp_path: Path, req: GameRequest, **fields: object) -> Path:
    body = {"protocol": 1, "session_id": str(req.session_id), **fields}
    path = tmp_path / "result.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_parse_missing_file(tmp_path: Path) -> None:
    assert isinstance(parse_result(tmp_path / "none.json", request()), Crashed)


def test_parse_garbage(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("{not json", encoding="utf-8")
    assert isinstance(parse_result(path, request()), Crashed)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "finished", "entries": []},  # finished без записей
        {"status": "aborted", "entries": []},  # aborted без причины
        {"status": "finished", "entries": [{"participant_code": "NT07", "outcome": "bad"}]},
        {"status": "finished", "entries": [{"participant_code": "NT7", "outcome": "completed"}]},
        {"status": "weird", "entries": []},
    ],
)
def test_parse_schema_violations(tmp_path: Path, fields: dict[str, object]) -> None:
    req = request()
    outcome = parse_result(write_result(tmp_path, req, **fields), req)
    assert isinstance(outcome, Crashed)
    assert "схем" in outcome.detail


def test_parse_wrong_session(tmp_path: Path) -> None:
    req = request()
    path = write_result(tmp_path, request(), status="aborted", entries=[], reason="x")
    assert isinstance(parse_result(path, req), Crashed)


def test_parse_wrong_participants(tmp_path: Path) -> None:
    req = request()
    entries = [{"participant_code": "NT08", "outcome": "completed", "points": 1}]
    assert isinstance(
        parse_result(write_result(tmp_path, req, status="finished", entries=entries), req),
        Crashed,
    )


def test_parse_completed_without_points(tmp_path: Path) -> None:
    req = request()
    entries = [{"participant_code": "NT07", "outcome": "completed"}]
    assert isinstance(
        parse_result(write_result(tmp_path, req, status="finished", entries=entries), req),
        Crashed,
    )


def test_parse_not_completed_gets_reason(tmp_path: Path) -> None:
    req = request()
    entries = [{"participant_code": "NT07", "outcome": "not_completed"}]
    outcome = parse_result(write_result(tmp_path, req, status="finished", entries=entries), req)
    assert outcome == Finished((GameEntry("NT07", "not_completed", None, None, "other"),))


def test_start_removes_stale_result_of_previous_attempt(tmp_path: Path) -> None:
    game = runner(tmp_path, "--crash")
    req = request()
    folder = tmp_path.resolve() / "sessions" / str(req.session_id)
    folder.mkdir(parents=True)
    stale = write_result(folder, req, status="aborted", entries=[], reason="old")
    game.start(req)
    outcome = wait(game)
    assert isinstance(outcome, Crashed)  # не Aborted("old")
    assert not stale.exists()


def completed(code: str, points: float, **extra: object) -> dict[str, object]:
    return {"participant_code": code, "outcome": "completed", "points": points, **extra}


@pytest.mark.parametrize(
    ("discipline", "codes", "entries"),
    [
        ("darts", ("NT01",), [completed("NT01", 5, wins=1)]),  # wins вне понга
        ("pong", ("NT03", "NT04"), [completed("NT03", 5), completed("NT04", 6)]),  # нет wins
        ("pong", ("NT03", "NT04"), [completed("NT03", 5, wins=1), completed("NT04", 6, wins=1)]),
        ("pong", ("NT03", "NT04"), [completed("NT03", 5, wins=0), completed("NT04", 6, wins=0)]),
        (
            "pong",
            ("NT03", "NT04"),
            [
                completed("NT03", 5, wins=1),
                {
                    "participant_code": "NT04",
                    "outcome": "not_completed",
                    "points": 3,
                    "reason": "health",
                },
            ],
        ),
        ("pong", ("NT03", "NT04"), [completed("NT03", 5, wins=1)]),  # не хватает игрока
        ("darts", ("NT01",), [completed("NT01", 4.5)]),  # дробные очки (решение 28)
    ],
)
def test_locally_invalid_results_are_crashes(
    tmp_path: Path, discipline: str, codes: tuple[str, ...], entries: list[dict[str, object]]
) -> None:
    req = request(discipline, codes)
    path = write_result(tmp_path, req, status="finished", entries=entries)
    assert isinstance(parse_result(path, req), Crashed)


def test_locally_valid_pong_variants(tmp_path: Path) -> None:
    req = request("pong", ("NT03", "NT04"))
    ok_both = [completed("NT03", 5, wins=1), completed("NT04", 6, wins=0)]
    one_left = [
        completed("NT03", 5, wins=1),
        {"participant_code": "NT04", "outcome": "not_completed", "reason": "health"},
    ]
    for entries in (ok_both, one_left):
        path = write_result(tmp_path, req, status="finished", entries=entries)
        assert isinstance(parse_result(path, req), Finished)


def test_launch_json_carries_max_points_except_for_pong(tmp_path: Path) -> None:
    from neurotlon_launcher.game import launch_document

    def launch_for(discipline: str, codes: tuple[str, ...], max_points: int | None) -> dict:  # type: ignore[type-arg]
        players = tuple(Player(c) for c in codes)
        req = GameRequest(uuid.uuid4(), discipline, 10, players, max_points)
        data = launch_document(req, tmp_path / "r.json", "127.0.0.1", 8765)
        launch_validator("Launch").validate(data)
        return data

    assert launch_for("darts", ("NT07",), 10)["max_points"] == 10
    assert "max_points" not in launch_for("darts", ("NT07",), None)
    assert "max_points" not in launch_for("pong", ("NT03", "NT04"), 10)


def test_result_above_max_points_is_a_crash(tmp_path: Path) -> None:
    players = (Player("NT01"),)
    req = GameRequest(uuid.uuid4(), "darts", 10, players, 10)
    over = write_result(tmp_path, req, status="finished", entries=[completed("NT01", 11)])
    assert isinstance(parse_result(over, req), Crashed)
    ok = write_result(tmp_path, req, status="finished", entries=[completed("NT01", 10)])
    assert isinstance(parse_result(ok, req), Finished)


def test_whole_float_points_are_stored_as_int(tmp_path: Path) -> None:
    req = request()
    path = write_result(tmp_path, req, status="finished", entries=[completed("NT07", 7.0)])
    outcome = parse_result(path, req)
    assert isinstance(outcome, Finished)
    assert outcome.entries[0].points == 7
    assert isinstance(outcome.entries[0].points, int)


def test_game_waits_for_the_bridge_and_starts_when_it_answers(tmp_path: Path) -> None:
    now = [0.0]
    ready = [False]
    game = SubprocessGameRunner(
        tuple(STUB),
        None,
        tmp_path,
        "127.0.0.1",
        8765,
        monotonic=lambda: now[0],
        bridge_ready=lambda: ready[0],
        bridge_wait_s=20.0,
    )
    req = request()
    game.start(req)
    assert game._proc is None  # моста нет: игру не запускаем
    now[0] = 10.0
    assert game.poll() is None
    assert game._proc is None
    ready[0] = True
    game.poll()
    assert game._proc is not None  # мост ответил: игра пошла
    game.stop()


def test_game_is_not_started_when_the_bridge_never_answers(tmp_path: Path) -> None:
    now = [0.0]
    game = SubprocessGameRunner(
        tuple(STUB),
        None,
        tmp_path,
        "127.0.0.1",
        8765,
        monotonic=lambda: now[0],
        bridge_ready=lambda: False,
        bridge_wait_s=20.0,
    )
    game.start(request())
    now[0] = 21.0
    outcome = game.poll()
    assert game._proc is None  # без моста игра только зря покажет ошибку
    assert isinstance(outcome, Crashed)
    assert "мост" in outcome.detail


def test_bridge_answers_probe(tmp_path: Path) -> None:
    import socket

    from neurotlon_launcher.game import bridge_answers

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert bridge_answers("127.0.0.1", port)
    assert not bridge_answers("127.0.0.1", port)
