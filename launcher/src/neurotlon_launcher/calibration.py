"""Калибровка датчиков на экране лаунчера: план шагов и оркестратор без ввода-вывода.

Оркестратор не знает сокета: он получает снимок связи с мостом (`LinkView`) и время, а в ответ
отдаёт команды (`Calibrate`, `Reset`), которые машина передаёт связи. Состояние шагов выводится
из того, что говорит мост: сигнал в `hello.calibrated` (или шаг завершился `done`) значит
«готов». Так перезапуск процесса моста не сбрасывает готовые шаги: после нового `hello` картина
перечитывается.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .bridge_link import LinkView, StepProgress

StepKind = Literal["cycle", "baseline"]
StepStatus = Literal["pending", "running", "done", "failed"]

# Ритм шагов по умолчанию (мост берёт его из настроек, лаунчер `segments` и `duration_s` не шлёт).
CYCLE_DURATION_S = 20.0
CYCLE_SEGMENTS = 4
BASELINE_DURATION_S = 12.0
TIMEOUT_FACTOR = 2.0
TIMEOUT_EXTRA_S = 5.0
TIMEOUT_MIN_S = 20.0
LINK_WAIT_S = 20.0  # мост не ответил ни разу за это время: шаг считается проваленным
SENSOR_WAIT_S = 30.0  # датчик не подключился за это время: шаг считается проваленным
READY_STATES = frozenset({"connected", "emulated"})  # в других состояниях шаг не запускаем

STEP_MUSCLE = "muscle"
STEP_BRAIN = "brain"

BRIDGE_SILENT = "Мост датчиков не отвечает"
LINK_DROPPED = "Связь с мостом прервалась"
STEP_FAILED = "Шаг не удался"
SENSOR_MISSING = "Датчик не подключён"

TEXT_WEAK = "Мышца напряглась слабо: напрягите сильнее"
TEXT_NO_SIGNAL = "Нет сигнала с датчика: проверьте, что он плотно прилегает"
# причины сбоя шага от моста, которые волонтёру понятнее в других словах
_REASON_TEXTS = {
    "сокращение слабое, нет отличия от покоя": TEXT_WEAK,
    "нет данных в покое": TEXT_NO_SIGNAL,
    "нет данных при напряжении": TEXT_NO_SIGNAL,
}


def reason_text(reason: str | None) -> str | None:
    """Причина сбоя шага для экрана: известные по-человечески, остальные как есть."""
    return None if reason is None else _REASON_TEXTS.get(reason, reason)


@dataclass(frozen=True)
class PlanStep:
    id: str
    kind: StepKind
    signals: tuple[str, ...]
    duration_s: float
    segments_total: int | None = None

    @property
    def timeout_s(self) -> float:
        """Сколько ждать завершения шага, прежде чем счесть мост молчащим."""
        return max(TIMEOUT_MIN_S, self.duration_s * TIMEOUT_FACTOR + TIMEOUT_EXTRA_S)


def plan_for(discipline: str) -> tuple[PlanStep, ...]:
    """Дартс и футбол: мышца, потом мозг; понг: обе мышцы одним шагом, одновременно."""
    if discipline == "pong":
        signals = ("emg_left", "emg_right")
        return (PlanStep(STEP_MUSCLE, "cycle", signals, CYCLE_DURATION_S, CYCLE_SEGMENTS),)
    return (
        PlanStep(STEP_MUSCLE, "cycle", ("emg",), CYCLE_DURATION_S, CYCLE_SEGMENTS),
        PlanStep(STEP_BRAIN, "baseline", ("eeg",), BASELINE_DURATION_S),
    )


@dataclass(frozen=True)
class Calibrate:
    signal: str
    step: StepKind


@dataclass(frozen=True)
class Reset:
    pass


Command = Calibrate | Reset


@dataclass(frozen=True)
class PartView:
    """Один сигнал шага (в понге у шага две части: левая и правая рука)."""

    signal: str
    status: StepStatus
    progress: float
    reason_text: str | None = None


@dataclass(frozen=True)
class StepView:
    id: str
    step: StepKind
    signals: tuple[str, ...]
    status: StepStatus
    progress: float
    segment: int | None
    segments_total: int | None
    phase: str | None
    phase_left_s: float | None
    reason_text: str | None
    parts: tuple[PartView, ...]


@dataclass(frozen=True)
class CalibrationView:
    steps: tuple[StepView, ...]
    current: str | None
    ready: bool


@dataclass
class _Sent:
    step: StepKind
    at: float  # последняя активность моста по шагу: тайм-аут считается от неё
    last: StepProgress | None = None


class CalibrationRun:
    """Ход калибровки одной сессии. Не потокобезопасен: вызывающий сериализует доступ."""

    def __init__(self, plan: tuple[PlanStep, ...], *, fresh: bool = True) -> None:
        self.plan = plan
        self.fresh = fresh  # новая сессия участника: прежняя калибровка стирается командой `reset`
        self._sent: dict[str, _Sent] = {}
        self._failed: dict[str, str] = {}
        self._reset_tried = False
        self._reset_gen: int | None = None  # поколение `hello`, для которого сброс отправлен
        self._done_here: set[str] = set()  # сигналы, откалиброванные в этом заходе
        self._seen_segments: dict[str, int] = {}
        self._sensor_wait: dict[str, float] = {}
        self._down_since: float | None = None
        self._silent = False

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(s for step in self.plan for s in step.signals)

    # --- шаг по времени ---

    def update(self, link: LinkView, now: float) -> list[Command]:
        """Принять состояние моста; вернуть команды, которые нужно отправить."""
        self._watch_link(link, now)
        if link.link != "live":
            return []
        commands: list[Command] = []
        calibrated = link.calibrated
        if self.fresh and self._reset_gen != link.generation:
            if self._needs_reset(link):
                self._reset_tried = True
                self._reset_gen = link.generation  # откатывается, если команда не ушла
                self._done_here.clear()
                commands.append(Reset())
                calibrated = frozenset()  # стёртое мостом ещё не видно в `link`
            else:
                self._reset_gen = link.generation  # новый `hello` показал чистое состояние
        self._collect(link, calibrated, now)
        for step in self.plan:
            parts = [self._part(s, link, calibrated) for s in step.signals]
            if all(p.status == "done" for p in parts):
                continue
            if any(p.status in ("running", "failed") for p in parts):
                break  # шаг идёт или ждёт повтора от волонтёра
            pending = tuple(p.signal for p in parts if p.status == "pending")
            commands += self._start_ready(step, pending, link, now)
            break
        return commands

    def _needs_reset(self, link: LinkView) -> bool:
        """Первый заход всегда сбрасывает; позже `reset` повторяется, если мост помнит чужое."""
        if not self._reset_tried:
            return True
        return bool((link.calibrated & set(self.signals)) - self._done_here)

    def _start_ready(
        self, step: PlanStep, pending: tuple[str, ...], link: LinkView, now: float
    ) -> list[Command]:
        """Запустить сигналы, чьи датчики на связи; ждущие датчика слишком долго проваливаются."""
        ready = tuple(s for s in pending if link.states.get(s) in READY_STATES)
        for signal in pending:
            if signal in ready:
                self._sensor_wait.pop(signal, None)
            elif now - self._sensor_wait.setdefault(signal, now) >= SENSOR_WAIT_S:
                self._failed[signal] = SENSOR_MISSING
        return self._start(step, ready, now)

    def command_failed(self, command: Command) -> None:
        """Команда не ушла (нет связи): считать её неотправленной."""
        if isinstance(command, Reset):
            self._reset_gen = None
        else:
            self._sent.pop(command.signal, None)

    def _watch_link(self, link: LinkView, now: float) -> None:
        if link.link == "live":
            self._down_since = None
            self._silent = False
            return
        if self._down_since is None:
            self._down_since = now
        if link.link == "lost":
            for signal in list(self._sent):  # шаг оборван вместе с мостом
                self._failed[signal] = LINK_DROPPED
                del self._sent[signal]
        elif now - self._down_since >= LINK_WAIT_S:
            self._silent = True

    def _collect(self, link: LinkView, calibrated: frozenset[str], now: float) -> None:
        """Завершение шага, провал от моста и тайм-аут молчащего моста."""
        for step in self.plan:
            for signal in step.signals:
                sent = self._sent.get(signal)
                if sent is None:
                    continue
                progress = link.progress.get(signal)
                if progress is not None and progress != sent.last:
                    sent.last, sent.at = progress, now  # мост жив: тайм-аут отсчитывается заново
                    if progress.segment is not None:
                        seen = self._seen_segments.get(signal, 0)
                        self._seen_segments[signal] = max(seen, progress.segment)
                if signal in calibrated:  # `calibrate` стёр сигнал из списка: он вернулся
                    self._done_here.add(signal)
                    del self._sent[signal]
                elif progress is not None and progress.status == "failed":
                    self._failed[signal] = progress.reason or STEP_FAILED
                    del self._sent[signal]
                elif now - sent.at > step.timeout_s:
                    self._failed[signal] = BRIDGE_SILENT
                    del self._sent[signal]

    def _part(self, signal: str, link: LinkView, calibrated: frozenset[str]) -> PartView:
        if signal in calibrated:  # и шаг, который мост только что завершил
            return PartView(signal, "done", 1.0)
        if signal in self._sent:
            progress = link.progress.get(signal)
            return PartView(signal, "running", progress.progress if progress else 0.0)
        if signal in self._failed:
            return PartView(signal, "failed", 0.0, reason_text(self._failed[signal]))
        if self._silent:
            return PartView(signal, "failed", 0.0, BRIDGE_SILENT)
        return PartView(signal, "pending", 0.0)

    def _start(self, step: PlanStep, signals: tuple[str, ...], now: float) -> list[Command]:
        commands: list[Command] = []
        for signal in signals:
            self._failed.pop(signal, None)
            self._sent[signal] = _Sent(step.kind, now)
            commands.append(Calibrate(signal, step.kind))
        return commands

    # --- действия волонтёра ---

    def restart(self, link: LinkView, now: float) -> list[Command]:
        """«Всё заново»: калибровка стирается, шаги идут с начала."""
        self._sent.clear()
        self._failed.clear()
        self._sensor_wait.clear()
        self._done_here.clear()
        self._reset_gen = link.generation
        if link.link != "live":
            return self._wait_again(now)
        first = self.plan[0]
        return [Reset(), *self._start(first, first.signals, now)]

    def retry(self, key: str, link: LinkView, now: float) -> list[Command]:
        """Повтор шага (по `id`) или одного сигнала; неизвестный ключ ничего не делает."""
        for step in self.plan:
            signals = step.signals if key == step.id else (key,) if key in step.signals else None
            if signals is None:
                continue
            if link.link != "live":
                return self._wait_again(now)
            self._sensor_wait.clear()
            return self._start(step, signals, now)
        return []

    def _wait_again(self, now: float) -> list[Command]:
        """Моста нет: «Повторить» даёт ему ещё одно окно ожидания."""
        self._silent = False
        self._sensor_wait.clear()
        if self._down_since is not None:
            self._down_since = now
        return []

    # --- вид для экрана ---

    def view(self, link: LinkView) -> CalibrationView:
        calibrated = (
            link.calibrated
        )  # при обрыве связи остаётся то, что мост сообщал в последний раз
        if self.fresh and self._reset_gen != link.generation:
            calibrated = frozenset()  # сброс не подтверждён: прежняя калибровка не показывается
        steps = tuple(self._step_view(step, link, calibrated) for step in self.plan)
        current = next((s.id for s in steps if s.status != "done"), None)
        return CalibrationView(steps, current, ready=link.link == "live" and current is None)

    def _segments_total(self, step: PlanStep) -> int | None:
        """Число сегментов: запасное значение, но не меньше номера, который уже присылал мост."""
        if step.segments_total is None:
            return None
        seen = max((self._seen_segments.get(s, 0) for s in step.signals), default=0)
        return max(step.segments_total, seen)

    def _step_view(self, step: PlanStep, link: LinkView, calibrated: frozenset[str]) -> StepView:
        parts = tuple(self._part(s, link, calibrated) for s in step.signals)
        statuses = {p.status for p in parts}
        status: StepStatus
        if "running" in statuses:
            status = "running"
        elif "failed" in statuses:
            status = "failed"
        elif statuses == {"done"}:
            status = "done"
        else:
            status = "pending"
        running = [
            link.progress[p.signal]
            for p in parts
            if p.status == "running" and p.signal in link.progress
        ]
        lead: StepProgress | None = running[0] if running else None
        return StepView(
            step.id,
            step.kind,
            step.signals,
            status,
            sum(p.progress for p in parts) / len(parts),
            lead.segment if lead else None,
            self._segments_total(step),
            lead.phase if lead else None,
            lead.phase_left_s if lead else None,
            next((p.reason_text for p in parts if p.status == "failed"), None),
            parts,
        )


def sensors_view(link: LinkView) -> list[dict[str, object]]:
    """Датчики для чипов экрана: сигнал, состояние, заряд."""
    return [
        {"signal": name, "state": state, "battery": link.batteries.get(name)}
        for name, state in link.states.items()
    ]
