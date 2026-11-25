"""Калибровка датчиков на экране лаунчера: план шагов и оркестратор без ввода-вывода.

Оркестратор не знает сокета: он получает снимок связи с мостом (`LinkView`) и время, а в ответ
отдаёт команды (`Calibrate`, `Reset`), которые машина передаёт связи. Состояние шагов выводится
из того, что говорит мост: сигнал в `hello.calibrated` (или шаг завершился `done`) значит
«готов». Так перезапуск процесса моста не сбрасывает готовые шаги: после нового `hello` картина
перечитывается.

Сценарий экрана: «Подключаем датчики…» (калибровка стартует, только когда все нужные датчики на
связи), затем для каждого шага отсчёт «Приготовьтесь» 5…1 и только потом команда `calibrate`
в мост. Окно ЭЭГ отмеряет сам лаунчер по времени после старта шага.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .bridge_link import LinkView, StepProgress

StepKind = Literal["cycle", "baseline"]
StepStatus = Literal["pending", "running", "done", "failed"]

# Ритм шагов по умолчанию (мост берёт его из настроек, лаунчер `segments` и `duration_s` не шлёт).
CYCLE_DURATION_S = 20.0
CYCLE_SEGMENTS = 4
BASELINE_DURATION_S = 20.0
TIMEOUT_FACTOR = 2.0
TIMEOUT_EXTRA_S = 5.0
TIMEOUT_MIN_S = 20.0
LINK_WAIT_S = 20.0  # мост не ответил ни разу за это время: шаг считается проваленным
SENSOR_WAIT_S = 30.0  # датчик не подключился за это время: шаг считается проваленным
READY_STATES = frozenset({"connected", "emulated"})  # в других состояниях шаг не запускаем
COUNTDOWN_S = 5  # «Приготовьтесь»: шаг уходит в мост только после отсчёта 5…1
CONNECT_WAIT_S = 30.0  # датчики не подключились за это время: понятная ошибка и «Повторить»
MISSING_AFTER_S = 8.0  # отключённый датчик столько «подключается», потом «не найден»
EEG_NO_DATA_S = 5.0  # мост не прислал ни одного `calibration` по ЭЭГ за это время после старта
EEG_GRACE_S = 8.0  # запас сверх окна ЭЭГ, потом шаг считается неудачным

STEP_EMG = "emg"
STEP_EEG = "eeg"
TITLE_EMG = "Калибровка ЭМГ"
TITLE_EEG = "Калибровка ЭЭГ"
# прежние имена шагов: команда `calibration_retry` их ещё понимает
STEP_ALIASES = {"muscle": STEP_EMG, "brain": STEP_EEG}
SENSOR_TITLES = {
    "eeg": "ЭЭГ",
    "emg": "ЭМГ",
    "emg_left": "ЭМГ игрока 1 (слева)",
    "emg_right": "ЭМГ игрока 2 (справа)",
}

BRIDGE_SILENT = "Мост датчиков не отвечает"
LINK_DROPPED = "Связь с мостом прервалась"
STEP_FAILED = "Шаг не удался"
SENSOR_MISSING = "Датчик не подключён"
CONNECT_TIMEOUT = (
    "Датчики не подключились за 30 секунд: включите их, поднесите к компьютеру "
    "и нажмите «Повторить»"
)
NO_EEG_DATA = "Нет данных от датчика ЭЭГ: повторите"
EEG_FAILED = "ЭЭГ не откалибровалась: смотрите на точку, дышите спокойно, повторите"

TEXT_WEAK = "Мышца с датчиком напряглась слабо: напрягите сильнее"
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
    title: str = ""

    @property
    def timeout_s(self) -> float:
        """Сколько ждать завершения шага, прежде чем счесть мост молчащим."""
        return max(TIMEOUT_MIN_S, self.duration_s * TIMEOUT_FACTOR + TIMEOUT_EXTRA_S)


def plan_for(discipline: str) -> tuple[PlanStep, ...]:
    """Дартс и футбол: ЭМГ, потом ЭЭГ; понг: ЭМГ обоих игроков одним шагом, одновременно."""
    if discipline == "pong":
        signals = ("emg_left", "emg_right")
        return (PlanStep(STEP_EMG, "cycle", signals, CYCLE_DURATION_S, CYCLE_SEGMENTS, TITLE_EMG),)
    return (
        PlanStep(STEP_EMG, "cycle", ("emg",), CYCLE_DURATION_S, CYCLE_SEGMENTS, TITLE_EMG),
        PlanStep(STEP_EEG, "baseline", ("eeg",), BASELINE_DURATION_S, None, TITLE_EEG),
    )


@dataclass(frozen=True)
class Calibrate:
    signal: str
    step: StepKind
    duration_s: float | None = None  # длина окна ЭЭГ, если мост умеет её принимать


@dataclass(frozen=True)
class Reset:
    pass


Command = Calibrate | Reset


@dataclass(frozen=True)
class PartView:
    """Один сигнал шага (в понге у шага две части: датчики левого и правого игрока)."""

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
    phase: str | None  # фаза моста (tense | relax); на отсчёте `countdown`, в ожидании `waiting`
    phase_left_s: float | None
    reason_text: str | None
    parts: tuple[PartView, ...]
    title: str = ""
    stage: str = "waiting"  # waiting | countdown | running | done | failed
    countdown_s: int | None = None  # целых секунд до старта шага (5…1), пока идёт отсчёт


@dataclass(frozen=True)
class SensorStatus:
    """Подключение одного нужного датчика на стадии «Подключаем датчики…»."""

    signal: str
    title: str
    status: str  # connected | connecting | missing
    state: str  # состояние моста; пока моста нет — `connecting`
    battery: int | None


@dataclass(frozen=True)
class CalibrationView:
    steps: tuple[StepView, ...]
    current: str | None
    ready: bool
    stage: str = "connecting"  # connecting | countdown | running | review
    sensors: tuple[SensorStatus, ...] = ()
    connect_error: str | None = None


@dataclass
class _Sent:
    step: StepKind
    at: float  # последняя активность моста по шагу: тайм-аут считается от неё
    last: StepProgress | None = None
    started: float = 0.0  # когда шаг ушёл в мост: окно ЭЭГ отмеряется от этого момента


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
        self._connected = False  # все нужные датчики на связи: сценарий может начинаться
        self._connect_since: float | None = None
        self._connect_failed = False
        self._countdown: dict[str, float] = {}  # шаг -> начало отсчёта «Приготовьтесь»
        self._redo: set[str] = set()  # сигналы на повтор: прежняя калибровка шага не в счёт
        self._now = 0.0  # время последнего `update`: по нему вид считает отсчёт

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(s for step in self.plan for s in step.signals)

    # --- шаг по времени ---

    def update(self, link: LinkView, now: float) -> list[Command]:
        """Принять состояние моста; вернуть команды, которые нужно отправить."""
        self._now = now
        self._watch_link(link, now)
        if link.link != "live":
            self._countdown.clear()  # мост пропал: отсчёт после возвращения идёт заново
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
        if not self._check_connected(link, calibrated, now):
            return commands  # «Подключаем датчики…»: ни отсчёта, ни калибровки
        for step in self.plan:
            parts = [self._part(s, link, calibrated) for s in step.signals]
            if all(p.status == "done" for p in parts):
                continue
            if any(p.status in ("running", "failed") for p in parts):
                break  # шаг идёт или ждёт повтора от волонтёра
            pending = tuple(p.signal for p in parts if p.status == "pending")
            commands += self._advance(step, pending, link, now)
            break
        return commands

    def _check_connected(self, link: LinkView, calibrated: frozenset[str], now: float) -> bool:
        """Стадия подключения: сценарий начинается, когда все нужные датчики на связи."""
        if self._connected:
            return True
        if self._connect_since is None:
            self._connect_since = now
        needed = [s for s in self.signals if s in self._redo or s not in calibrated]
        if all(link.states.get(s) in READY_STATES for s in needed):
            self._connected = True
            self._connect_failed = False
            return True
        if now - self._connect_since >= CONNECT_WAIT_S:
            self._connect_failed = True
        return False

    def _needs_reset(self, link: LinkView) -> bool:
        """Первый заход всегда сбрасывает; позже `reset` повторяется, если мост помнит чужое."""
        if not self._reset_tried:
            return True
        return bool((link.calibrated & set(self.signals)) - self._done_here)

    def _advance(
        self, step: PlanStep, pending: tuple[str, ...], link: LinkView, now: float
    ) -> list[Command]:
        """Отсчёт идёт, только пока все датчики шага на связи; шаг уходит в мост после отсчёта.

        Пропал датчик: отсчёт сбрасывается и после возвращения идёт заново с 5; ждущий датчика
        слишком долго проваливает шаг.
        """
        waiting = [s for s in pending if link.states.get(s) not in READY_STATES]
        for signal in pending:
            if signal not in waiting:
                self._sensor_wait.pop(signal, None)
        if waiting:
            self._countdown.pop(step.id, None)
            for signal in waiting:
                if now - self._sensor_wait.setdefault(signal, now) >= SENSOR_WAIT_S:
                    self._failed[signal] = SENSOR_MISSING
            return []
        began = self._countdown.setdefault(step.id, now)
        if now - began < COUNTDOWN_S:
            return []
        features = link.hello.features if link.hello else ()
        duration = step.duration_s if "baseline_duration" in features else None
        return self._start(step, pending, now, duration)

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
                problem = self._eeg_problem(step, sent, progress, now)
                if signal in calibrated:  # `calibrate` стёр сигнал из списка: он вернулся
                    self._done_here.add(signal)
                    del self._sent[signal]
                elif progress is not None and progress.status == "failed":
                    bad = progress.reason or (EEG_FAILED if step.kind == "baseline" else None)
                    self._failed[signal] = bad or STEP_FAILED
                    del self._sent[signal]
                elif problem is not None:
                    self._failed[signal] = problem
                    del self._sent[signal]
                elif now - sent.at > step.timeout_s:
                    self._failed[signal] = BRIDGE_SILENT
                    del self._sent[signal]

    @staticmethod
    def _eeg_problem(
        step: PlanStep, sent: _Sent, progress: StepProgress | None, now: float
    ) -> str | None:
        """ЭЭГ: окно отмеряет лаунчер. Нет данных или шаг не уложился в окно: причина по-русски."""
        if step.kind != "baseline":
            return None
        elapsed = now - sent.started
        if progress is None and elapsed > EEG_NO_DATA_S:
            return NO_EEG_DATA
        if elapsed > step.duration_s + EEG_GRACE_S:
            return EEG_FAILED
        return None

    def _part(self, signal: str, link: LinkView, calibrated: frozenset[str]) -> PartView:
        if signal in self._redo and signal not in self._sent:
            if signal in self._failed:  # повтор не дошёл до старта: сбой датчика на ожидании
                return self._failed_part(signal)
            return PartView(signal, "pending", 0.0)  # прежняя калибровка не в счёт
        if signal in calibrated:  # и шаг, который мост только что завершил
            return PartView(signal, "done", 1.0)
        if signal in self._sent:
            progress = link.progress.get(signal)
            return PartView(signal, "running", progress.progress if progress else 0.0)
        if signal in self._failed:
            return self._failed_part(signal)
        if self._silent:
            return PartView(signal, "failed", 0.0, BRIDGE_SILENT)
        return PartView(signal, "pending", 0.0)

    def _failed_part(self, signal: str) -> PartView:
        return PartView(signal, "failed", 0.0, reason_text(self._failed[signal]))

    def _start(
        self, step: PlanStep, signals: tuple[str, ...], now: float, duration: float | None = None
    ) -> list[Command]:
        commands: list[Command] = []
        if signals:
            self._countdown.pop(step.id, None)
        for signal in signals:
            self._failed.pop(signal, None)
            self._sent[signal] = _Sent(step.kind, now, started=now)
            self._redo.discard(signal)
            commands.append(
                Calibrate(signal, step.kind, duration if step.kind == "baseline" else None)
            )
        return commands

    # --- действия волонтёра ---

    def restart(self, link: LinkView, now: float) -> list[Command]:
        """«Всё заново»: калибровка стирается, подключение и шаги идут с начала."""
        self._now = now
        self._sent.clear()
        self._failed.clear()
        self._sensor_wait.clear()
        self._done_here.clear()
        self._redo.clear()
        self._countdown.clear()
        self._connected = False
        self._connect_since = None
        self._connect_failed = False
        self._reset_gen = link.generation
        if link.link != "live":
            return self._wait_again(now)
        return [Reset()]

    def retry(self, key: str, link: LinkView, now: float) -> list[Command]:
        """Повтор шага (по `id`, в том числе прежним `muscle`/`brain`) или одного сигнала.

        На стадии подключения любой ключ даёт датчикам ещё одно окно ожидания.
        Повторённый шаг идёт заново и с отсчётом: `calibrate` уходит в мост после него.
        """
        self._now = now
        if not self._connected:
            self._connect_since, self._connect_failed = now, False
            return self._wait_again(now)
        key = STEP_ALIASES.get(key, key)
        for step in self.plan:
            signals = step.signals if key == step.id else (key,) if key in step.signals else None
            if signals is None:
                continue
            if link.link != "live":
                return self._wait_again(now)
            self._sensor_wait.clear()
            for signal in signals:
                if signal in self._sent:
                    continue  # шаг уже идёт: повтор не нужен
                self._failed.pop(signal, None)
                self._redo.add(signal)
            self._countdown.pop(step.id, None)  # отсчёт, если он шёл, начнётся заново
            return []
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
        current = next((s for s in steps if s.status != "done"), None)
        stage = "review"
        if current is not None:
            if not self._connected:
                stage = "connecting"
            else:
                stage = "countdown" if current.stage == "countdown" else "running"
        return CalibrationView(
            steps,
            current.id if current else None,
            ready=link.link == "live" and current is None,
            stage=stage,
            sensors=self._sensors(link),
            connect_error=CONNECT_TIMEOUT if self._connect_failed and not self._connected else None,
        )

    def _sensors(self, link: LinkView) -> tuple[SensorStatus, ...]:
        """Нужные датчики: подключён / подключается / не найден (после недолгого ожидания)."""
        waited = self._now - self._connect_since if self._connect_since is not None else 0.0
        items: list[SensorStatus] = []
        for signal in self.signals:
            state = link.states.get(signal, "connecting")
            if state in READY_STATES:
                status = "connected"
            elif self._connect_failed or (state == "disconnected" and waited >= MISSING_AFTER_S):
                status = "missing"
            else:
                status = "connecting"
            title = SENSOR_TITLES.get(signal, signal)
            items.append(SensorStatus(signal, title, status, state, link.batteries.get(signal)))
        return tuple(items)

    def _segments_total(self, step: PlanStep) -> int | None:
        """Число сегментов: запасное значение, но не меньше номера, который уже присылал мост."""
        if step.segments_total is None:
            return None
        seen = max((self._seen_segments.get(s, 0) for s in step.signals), default=0)
        return max(step.segments_total, seen)

    def _countdown_s(self, step: PlanStep) -> int | None:
        began = self._countdown.get(step.id)
        if began is None or not self._connected:
            return None
        left = COUNTDOWN_S - (self._now - began)
        return None if left <= 0 else min(COUNTDOWN_S, max(1, math.ceil(left)))

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
        progress = sum(p.progress for p in parts) / len(parts)
        phase_left = lead.phase_left_s if lead else None
        countdown_s = self._countdown_s(step) if status == "pending" else None
        stage: str = status if status != "pending" else "waiting"
        if countdown_s is not None:
            stage = "countdown"
        phase = lead.phase if lead else (stage if stage in ("countdown", "waiting") else None)
        if status == "running" and step.kind == "baseline":
            progress, phase_left = self._window(step, parts, progress, phase_left)
        return StepView(
            step.id,
            step.kind,
            step.signals,
            status,
            progress,
            lead.segment if lead else None,
            self._segments_total(step),
            phase,
            phase_left,
            next((p.reason_text for p in parts if p.status == "failed"), None),
            parts,
            step.title,
            stage,
            countdown_s,
        )

    def _window(
        self, step: PlanStep, parts: tuple[PartView, ...], progress: float, phase_left: float | None
    ) -> tuple[float, float | None]:
        """Окно ЭЭГ идёт по часам лаунчера, не по ходу моста: отсчёт не зависит от подключений."""
        started = [
            self._sent[p.signal].started
            for p in parts
            if p.status == "running" and p.signal in self._sent
        ]
        if not started:
            return progress, phase_left
        elapsed = max(0.0, self._now - min(started))
        shown = min(0.99, elapsed / step.duration_s)
        left = phase_left if phase_left is not None else max(0.0, step.duration_s - elapsed)
        return max(progress, shown), left
