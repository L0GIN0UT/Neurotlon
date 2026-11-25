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
    points_limit_problem,
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
from .harness import CheckBridge, CheckBridgeError

Status = Literal["PASS", "FAIL", "WARN", "SKIP"]
POLL_S = 0.05
TEST_PLAYERS = (Player("NT03", "Тест Один"), Player("NT14", "Тест Два"))
BURST_DISCIPLINES = frozenset({"darts", "football"})  # игры, где бросок и удар запускает burst
BURST_SETTLE_S = 3.5  # запас от первого чтения игрой: отсчёт «3-2-1» и начало игры
PLAY_TAIL_S = 3.0  # после конца зачётной части: экран «Игра окончена» и выход
ABORT_SETTLE_S = 3.0  # потерю датчиков имитируем, когда игра уже читала мост столько секунд
LOST_ABORT_S = 30.0  # правило GameApp: через столько игра сама прерывается без датчика
UNCALIBRATED_WAIT_S = 40.0  # игре без калибровки на то, чтобы запуститься и выйти с aborted


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
    max_points: int | None = None
    grace_s: float = 420.0
    bridge_speed: float = 10.0
    time_scale: float = 1.0
    abort_test: bool = False
    abort_wait_s: float | None = None
    keep_dir: Path | None = None
    uncalibrated_test: bool = True
    uncalibrated_wait_s: float = UNCALIBRATED_WAIT_S


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
    request = GameRequest(uuid.uuid4(), opts.discipline, opts.duration_s, players, opts.max_points)
    scale = None if opts.time_scale == 1.0 else f"{opts.time_scale:g}"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data_dir = opts.keep_dir or Path(tmp)
        try:
            # мост сам калибрует сигналы до запуска игры, как лаунчер на стенде
            with (
                CheckBridge(opts.discipline, opts.bridge_speed) as bridge,
                _env(TIME_SCALE_ENV, scale),
            ):
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
                finished = time.monotonic()
                elapsed = finished - started
                bursts = _bursts_in_play(bridge, finished, opts)
        except CheckBridgeError as exc:
            report.add("FAIL", "мост", f"мост проверки не откалибровал сигналы: {exc}")
            return report
        folder = session_dir(data_dir, request.session_id)
        _evaluate(report, opts, request, bridge, bursts, outcome, abort_sent, elapsed, folder)
        log = folder / "game.log"
        if not report.passed and log.exists():
            report.log_tail = _tail(log)
        launched = any(c.name == "запуск" and c.status == "PASS" for c in report.checks)
        if opts.uncalibrated_test and not opts.abort_test and launched:
            _check_uncalibrated(report, opts, command, data_dir, scale)
        if opts.keep_dir:
            report.add("PASS", "файлы", f"сохранены в {folder}")
    return report


def _tail(path: Path, lines: int = 15) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return "\n".join(text.splitlines()[-lines:])


def _bursts_in_play(bridge: CheckBridge, end: float, opts: Options) -> int:
    """События `burst`, отданные игре в зачётной части.

    Начало игры мост не видит (после первого чтения идут обучение и отсчёт, у Unity до минуты),
    поэтому окно считаем от конца: зачётная часть длится `duration_s` и заканчивается за
    `PLAY_TAIL_S` до выхода. Раньше первого чтения с запасом на отсчёт окно не начинается."""
    first = bridge.source.first_read_at
    if first is None:
        return 0  # игра не читала мост: момент начала игры неизвестен
    play_from = end - opts.duration_s / opts.time_scale - PLAY_TAIL_S
    return bridge.source.bursts_between(max(first + BURST_SETTLE_S, play_from), end)


def _abort_due(bridge: CheckBridge, now: float) -> bool:
    """Когда обрывать мост в проверке потери датчиков: игра уже читает сигналы."""
    first = bridge.source.first_read_at
    return first is not None and now - first >= ABORT_SETTLE_S


def _wait(
    runner: SubprocessGameRunner, bridge: CheckBridge, opts: Options
) -> tuple[GameOutcome, bool]:
    abort_at: float | None = None
    abort_wait = opts.abort_wait_s or (LOST_ABORT_S / opts.time_scale + 15.0)
    try:
        while True:
            outcome = runner.poll()
            if outcome is not None:
                return outcome, abort_at is not None
            now = time.monotonic()
            if opts.abort_test and abort_at is None and _abort_due(bridge, now):
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
    bursts: int,
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
    _check_calibration(report, bridge)
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
    _check_result(report, opts, request, bursts, folder / "result.json", timed_out)


def _check_bridge(report: Report, bridge: CheckBridge) -> None:
    if bridge.source.reads > 0:
        report.add("PASS", "мост", f"игра подключилась к {bridge.host}:{bridge.port}")
    else:
        report.add(
            "FAIL", "мост", f"игра не подключилась к {bridge.host}:{bridge.port} из launch.json"
        )


def _check_calibration(report: Report, bridge: CheckBridge) -> None:
    """Калибровку проводит лаунчер: игра её не запускает (`calibrate` от игры нежелателен)."""
    sent = bridge.source.calibrations
    if not sent:
        report.add("PASS", "калибровка", "датчики откалиброваны до игры, игра их не калибрует")
    else:
        steps = ", ".join(f"{signal}/{step}" for signal, step in sent)
        report.add(
            "WARN",
            "калибровка",
            f"игра запускала калибровку ({steps}): её проводит лаунчер, игре калибровать нечего",
        )


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
    report: Report,
    opts: Options,
    request: GameRequest,
    bursts: int,
    path: Path,
    timed_out: bool,
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
    _check_burst(report, opts, bursts, data["entries"])


def _check_entries(
    report: Report, opts: Options, request: GameRequest, raw: list[dict[str, Any]]
) -> None:
    entries = [RawEntry(e) for e in raw]
    problem = raw_entries_problem(raw, [p.code for p in request.players])
    if problem is None and opts.discipline != "pong":
        problem = entries_problem(opts.discipline, entries)
    if problem is None:
        problem = points_limit_problem(
            opts.discipline,
            [(e["participant_code"], e["points"]) for e in raw if e["outcome"] == "completed"],
            request.max_points,
        )
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


def _check_burst(report: Report, opts: Options, bursts: int, raw: list[dict[str, Any]]) -> None:
    """Дартс и футбол запускают бросок и удар по `burst`: во время игры мост присылает события,
    а игра, которая на них не реагирует, не наберёт ни одного очка. Это косвенный признак: игра
    ничего не отвечает мосту, виден только результат."""
    if opts.discipline not in BURST_DISCIPLINES:
        return
    name = "burst"
    if bursts == 0:
        report.add("SKIP", name, "за время игры мост не прислал ни одного события burst")
        return
    points = sum(e["points"] for e in raw if e["outcome"] == "completed")
    if points > 0:
        report.add("PASS", name, f"мост прислал {bursts} событий, игра набрала очки ({points})")
    else:
        report.add(
            "FAIL",
            name,
            f"мост прислал {bursts} событий burst, а игра не набрала очков: "
            "нет реакции на резкое сокращение мышцы",
        )


def _check_uncalibrated(
    report: Report,
    opts: Options,
    command: tuple[str, ...],
    data_dir: Path,
    scale: str | None,
) -> None:
    """Игра на реальных датчиках без калибровки не должна играть: `aborted` с понятной причиной."""
    name = "без калибровки"
    request = GameRequest(
        uuid.uuid4(),
        opts.discipline,
        opts.duration_s,
        TEST_PLAYERS[: 2 if opts.discipline == "pong" else 1],
        opts.max_points,
    )
    with (
        CheckBridge(opts.discipline, opts.bridge_speed, calibrate=False) as bridge,
        _env(TIME_SCALE_ENV, scale),
    ):
        runner = SubprocessGameRunner(
            command,
            None,
            data_dir,
            bridge.host,
            bridge.port,
            fullscreen=False,
            grace_s=opts.grace_s,
        )
        runner.start(request)
        outcome = _wait_for_exit(runner, opts.uncalibrated_wait_s)
    if isinstance(outcome, Aborted):
        if "калибр" in outcome.reason.lower():
            report.add("PASS", name, f"игра вышла с aborted: {outcome.reason}")
        else:
            report.add(
                "WARN",
                name,
                f"игра вышла с aborted, но причина не про калибровку: {outcome.reason}",
            )
    elif isinstance(outcome, Crashed) and outcome.detail.startswith(DETAIL_TIMEOUT):
        report.add(
            "FAIL",
            name,
            f"игра не вышла за {opts.uncalibrated_wait_s:g} с без калибровки: "
            "должна сразу записать aborted",
        )
    elif isinstance(outcome, Crashed):
        report.add("FAIL", name, f"игра без калибровки упала: {outcome.detail}")
    else:
        report.add(
            "FAIL",
            name,
            "игра без калибровки дошла до конца: на реальных датчиках она должна "
            "записать aborted (датчики не откалиброваны)",
        )


def _wait_for_exit(runner: SubprocessGameRunner, wait_s: float) -> GameOutcome:
    deadline = time.monotonic() + wait_s
    try:
        while True:
            outcome = runner.poll()
            if outcome is not None:
                return outcome
            if time.monotonic() > deadline:
                runner.stop()
                return Crashed(f"{DETAIL_TIMEOUT} без калибровки")
            time.sleep(POLL_S)
    except BaseException:
        runner.stop()
        raise
