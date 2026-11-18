"""Проверка соответствия игры контракту: запуск тем же `SubprocessGameRunner`, что на стенде."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from neurotlon_contracts.contract import (
    RawEntry,
    entries_problem,
    pong_winner_problem,
    raw_entries_problem,
    schema_problem,
)
from neurotlon_launcher.game import (
    DETAIL_EXIT_CODE,
    DETAIL_START_FAILED,
    DETAIL_TIMEOUT,
    Aborted,
    Crashed,
    Finished,
    GameOutcome,
    GameRequest,
    Player,
    SubprocessGameRunner,
    session_dir,
)

from ..sdk.app import TIME_SCALE_ENV
from ..sdk.calibration import phases_for
from .harness import CheckBridge

Status = Literal["PASS", "FAIL", "WARN", "SKIP"]
POLL_S = 0.05
TEST_PLAYERS = (Player("NT03", "Тест Один"), Player("NT14", "Тест Два"))
LOST_ABORT_S = 30.0  # правило GameApp: через столько игра сама прерывается без датчика


@dataclass(frozen=True)
class Check:
    status: Status
    name: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    log_tail: str = ""

    def add(self, status: Status, name: str, detail: str) -> None:
        self.checks.append(Check(status, name, detail))

    @property
    def passed(self) -> bool:
        return not any(c.status == "FAIL" for c in self.checks)

    def format(self) -> str:
        lines = [f"{c.status:<5} {c.name}: {c.detail}" for c in self.checks]
        counts = ", ".join(
            f"{sum(c.status == s for c in self.checks)} {s}"
            for s in ("PASS", "FAIL", "WARN", "SKIP")
        )
        if self.log_tail:
            lines += ["", "Конец game.log:", self.log_tail]
        lines += ["", f"ИТОГ: {'PASS' if self.passed else 'FAIL'} ({counts})"]
        return "\n".join(lines)


@dataclass(frozen=True)
class Options:
    discipline: str
    command: tuple[str, ...]
    duration_s: int = 10
    grace_s: float = 120.0
    bridge_speed: float = 10.0
    time_scale: float = 1.0
    abort_test: bool = False
    abort_wait_s: float | None = None
    keep_dir: Path | None = None


def resolve_command(command: Sequence[str]) -> tuple[str, ...]:
    """`python` в команде — тот интерпретатор, в котором запущена проверка."""
    if command and command[0] in ("python", "python3"):
        return (sys.executable, *command[1:])
    return tuple(command)


def executable_exists(command: Sequence[str]) -> bool:
    if not command:
        return False
    first = command[0]
    return Path(first).exists() or shutil.which(first) is not None


@contextmanager
def _env(name: str, value: str | None) -> Iterator[None]:
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def run_check(opts: Options) -> Report:
    report = Report()
    command = resolve_command(opts.command)
    if not executable_exists(command):
        report.add("FAIL", "запуск", f"команда не найдена: {command[0] if command else '(пусто)'}")
        return report
    players = TEST_PLAYERS[: 2 if opts.discipline == "pong" else 1]
    request = GameRequest(uuid.uuid4(), opts.discipline, opts.duration_s, players)
    scale = None if opts.time_scale == 1.0 else f"{opts.time_scale:g}"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data_dir = opts.keep_dir or Path(tmp)
        with CheckBridge(opts.discipline, opts.bridge_speed) as bridge, _env(TIME_SCALE_ENV, scale):
            runner = SubprocessGameRunner(
                command,
                None,
                data_dir,
                bridge.host,
                bridge.port,
                fullscreen=False,
                grace_s=opts.grace_s,
            )
            started = time.monotonic()
            runner.start(request)
            outcome, abort_sent = _wait(runner, bridge, opts)
            elapsed = time.monotonic() - started
        folder = session_dir(data_dir, request.session_id)
        _evaluate(report, opts, request, bridge, outcome, abort_sent, elapsed, folder)
        log = folder / "game.log"
        if not report.passed and log.exists():
            report.log_tail = _tail(log)
        if opts.keep_dir:
            report.add("PASS", "файлы", f"сохранены в {folder}")
    return report


def _tail(path: Path, lines: int = 15) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return "\n".join(text.splitlines()[-lines:])


def _abort_due(bridge: CheckBridge, expected_steps: int, now: float) -> bool:
    """Когда обрывать мост в проверке потери датчиков: игра уже вошла в игру."""
    first = bridge.source.first_read_at
    if first is None or now - first < 1.5:
        return False
    steps = len(bridge.source.calibrations)
    last = bridge.source.last_calibration_at
    if steps == 0:
        return True
    return steps >= expected_steps and last is not None and now - last >= 1.5


def _wait(
    runner: SubprocessGameRunner, bridge: CheckBridge, opts: Options
) -> tuple[GameOutcome, bool]:
    expected = sum(len(p.signals) for p in phases_for(opts.discipline))
    abort_at: float | None = None
    abort_wait = opts.abort_wait_s or (LOST_ABORT_S / opts.time_scale + 15.0)
    try:
        while True:
            outcome = runner.poll()
            if outcome is not None:
                return outcome, abort_at is not None
            now = time.monotonic()
            if opts.abort_test and abort_at is None and _abort_due(bridge, expected, now):
                bridge.stop_serving()
                abort_at = now
            if abort_at is not None and now - abort_at > abort_wait:
                runner.stop()
                return Crashed(f"{DETAIL_TIMEOUT} после потери датчиков"), True
            time.sleep(POLL_S)
    except BaseException:
        runner.stop()
        raise


def _evaluate(
    report: Report,
    opts: Options,
    request: GameRequest,
    bridge: CheckBridge,
    outcome: GameOutcome,
    abort_sent: bool,
    elapsed: float,
    folder: Path,
) -> None:
    if isinstance(outcome, Crashed) and outcome.detail.startswith(DETAIL_START_FAILED):
        report.add("FAIL", "запуск", outcome.detail)
        return
    report.add("PASS", "запуск", "процесс запущен с --launch <launch.json>")
    _check_bridge(report, bridge)
    _check_calibration(report, opts, bridge)
    if opts.abort_test:
        _check_abort(report, outcome, abort_sent)
        return
    timed_out = isinstance(outcome, Crashed) and outcome.detail.startswith(DETAIL_TIMEOUT)
    if timed_out:
        report.add(
            "FAIL",
            "выход",
            f"игра не вышла за {opts.duration_s + opts.grace_s:g} с (duration_s + запас), убита",
        )
    elif isinstance(outcome, Crashed) and outcome.detail.startswith(DETAIL_EXIT_CODE):
        report.add("FAIL", "выход", outcome.detail)
    else:
        report.add("PASS", "выход", f"код 0 через {elapsed:.1f} с")
        _check_duration(report, opts, elapsed)
    _check_result(report, opts, request, folder / "result.json", timed_out)


def _check_bridge(report: Report, bridge: CheckBridge) -> None:
    if bridge.source.reads > 0:
        report.add("PASS", "мост", f"игра подключилась к {bridge.host}:{bridge.port}")
    else:
        report.add(
            "FAIL", "мост", f"игра не подключилась к {bridge.host}:{bridge.port} из launch.json"
        )


def _check_calibration(report: Report, opts: Options, bridge: CheckBridge) -> None:
    expected = [(s, p.step) for p in phases_for(opts.discipline) for s in p.signals]
    done = bridge.source.calibrations
    if not done:
        report.add("WARN", "калибровка", "игра не запускала калибровку (на стенде она нужна)")
    elif all(step in done for step in expected):
        report.add("PASS", "калибровка", "пройдены все шаги: " + _steps(expected))
    else:
        missing = [step for step in expected if step not in done]
        report.add("WARN", "калибровка", "не запущены шаги: " + _steps(missing))


def _steps(steps: Sequence[tuple[str, str]]) -> str:
    return ", ".join(f"{signal}/{step}" for signal, step in steps)


def _check_duration(report: Report, opts: Options, elapsed: float) -> None:
    if elapsed < opts.duration_s * 0.5 / opts.time_scale:
        report.add(
            "WARN",
            "время",
            f"игра закончилась за {elapsed:.1f} с при duration_s={opts.duration_s}: "
            "проверьте, что таймер берётся из launch.json",
        )


def _check_abort(report: Report, outcome: GameOutcome, abort_sent: bool) -> None:
    name = "потеря датчиков"
    if not abort_sent:
        report.add("SKIP", name, "игра не подключилась к мосту или вышла раньше: нечего проверять")
    elif isinstance(outcome, Aborted):
        report.add("PASS", name, f"игра записала aborted: {outcome.reason}")
    elif isinstance(outcome, Crashed) and outcome.detail.startswith(DETAIL_TIMEOUT):
        report.add("WARN", name, "игра не прервалась без датчиков (необязательно, но желательно)")
    else:
        report.add("WARN", name, f"игра вышла иначе, чем aborted: {_describe(outcome)}")


def _describe(outcome: GameOutcome) -> str:
    if isinstance(outcome, Crashed):
        return outcome.detail
    if isinstance(outcome, Finished):
        return "finished"
    return f"aborted: {outcome.reason}"


def _check_result(
    report: Report, opts: Options, request: GameRequest, path: Path, timed_out: bool
) -> None:
    if timed_out:
        report.add("SKIP", "result.json", "игра убита по таймауту")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report.add("FAIL", "result.json", "файла нет: игра вышла, не записав результат")
        return
    except (OSError, ValueError) as exc:
        report.add("FAIL", "result.json", f"не читается: {exc}")
        return
    problem = schema_problem("Result", data)
    if problem:
        report.add("FAIL", "result.json", f"не проходит схему: {problem}")
        return
    report.add("PASS", "result.json", "проходит схему Result")
    if data["session_id"] != str(request.session_id):
        report.add(
            "FAIL",
            "session_id",
            f"в результате {data['session_id']}, а запущена {request.session_id}",
        )
    else:
        report.add("PASS", "session_id", "совпадает с launch.json")
    if data["status"] == "aborted":
        report.add("FAIL", "статус", f"игра сама записала aborted: {data['reason']}")
        return
    report.add("PASS", "статус", "finished")
    _check_entries(report, opts, request, data["entries"])


def _check_entries(
    report: Report, opts: Options, request: GameRequest, raw: list[dict[str, Any]]
) -> None:
    entries = [RawEntry(e) for e in raw]
    problem = raw_entries_problem(raw, [p.code for p in request.players])
    if problem is None and opts.discipline != "pong":
        problem = entries_problem(opts.discipline, entries)
    if problem:
        report.add("FAIL", "записи", problem)
        return
    report.add("PASS", "записи", "участники те же, points и wins по правилам сервера")
    if opts.discipline == "pong":
        winner = pong_winner_problem(entries)
        if winner:
            report.add("FAIL", "победитель", winner)
        else:
            report.add("PASS", "победитель", "ровно один")
