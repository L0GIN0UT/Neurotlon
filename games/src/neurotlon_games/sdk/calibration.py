"""Калибровка датчиков по протоколу моста (`shared/bridge-protocol.md`).

Мост считает шаги сам, игра только запускает их по очереди и показывает инструкцию:
- ЭМГ: если мост объявил `emg_cycle`, один шаг `cycle` (20 с, ритм по умолчанию 5/5/5/5
  «напрячь / расслабить», фазу сообщает мост); иначе `rest` 5 с покоя и `contract` 12 с
  = 3 x (3 с напрячь + 1 с пауза);
- ЭЭГ: `baseline` 12 с, глаза открыты, взгляд на точку.
В понге оба датчика (`emg_left`, `emg_right`) калибруются одновременно.
Сбой шага: один повтор, потом состояние `failed` с причиной — игра сообщает `aborted`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from neurotlon_bridge.source import CalibrationProgress, CalibrationStep
from neurotlon_bridge.source import Phase as CyclePhase

from .launch import LaunchInfo
from .signals import Signals

STEP_DURATION_S: dict[CalibrationStep, float] = {
    "rest": 5.0,
    "contract": 12.0,
    "cycle": 20.0,
    "baseline": 12.0,
}
SQUEEZE_S = 3.0
PAUSE_S = 1.0
RETRIES = 1
TIMEOUT_FACTOR = 2.0
TIMEOUT_EXTRA_S = 5.0

TEXT_REST = "Расслабьте мышцу с датчиком"
TEXT_SQUEEZE = "Напрягите мышцу с датчиком"
TEXT_RELEASE = "Расслабьте"
TEXT_BASELINE = "Расслабьтесь и смотрите на точку на экране"
TEXT_RETRY = "Не получилось, повторяем шаг"
TEXT_WEAK = "Мышца напряглась слабо: напрягите сильнее"
TEXT_NO_SIGNAL = "Нет сигнала с датчика: проверьте, что он плотно прилегает"

# причины сбоя шага от моста, которые игроку понятнее в других словах
_REASON_TEXTS = {
    "сокращение слабое, нет отличия от покоя": TEXT_WEAK,
    "нет данных в покое": TEXT_NO_SIGNAL,
    "нет данных при напряжении": TEXT_NO_SIGNAL,
}

State = Literal["idle", "running", "done", "failed"]


@dataclass(frozen=True)
class Phase:
    step: CalibrationStep
    signals: tuple[str, ...]


def phases_for(discipline: str, *, emg_cycle: bool = False) -> tuple[Phase, ...]:
    """Шаги калибровки; `emg_cycle` — мост объявил `emg_cycle`, ЭМГ идёт одним шагом `cycle`."""
    pong = discipline == "pong"
    emg = ("emg_left", "emg_right") if pong else ("emg",)
    steps: list[Phase] = [Phase("cycle", emg)] if emg_cycle else [Phase("rest", emg)]
    if not emg_cycle:
        steps.append(Phase("contract", emg))
    if not pong:
        steps.append(Phase("baseline", ("eeg",)))
    return tuple(steps)


def reason_text(reason: str) -> str:
    """Причина сбоя шага для экрана: известные по-человечески, остальные как есть."""
    return _REASON_TEXTS.get(reason, reason)


def instruction(
    step: CalibrationStep, progress: float, cycle_phase: CyclePhase | None = None
) -> str:
    """Текст для игрока; у `cycle` фазу сообщает мост, у `contract` ритм выводится из прогресса."""
    if step == "baseline":
        return TEXT_BASELINE
    if step == "rest":
        return TEXT_REST
    if step == "cycle":
        return TEXT_REST if cycle_phase == "relax" else TEXT_SQUEEZE
    position = (progress * STEP_DURATION_S["contract"]) % (SQUEEZE_S + PAUSE_S)
    return TEXT_SQUEEZE if position < SQUEEZE_S else TEXT_RELEASE


class Calibration:
    def __init__(
        self,
        signals: Signals,
        phases: Sequence[Phase] | Callable[[], Sequence[Phase]],
        retries: int = RETRIES,
    ) -> None:
        self._signals = signals
        # функция нужна, когда шаги зависят от моста: его возможности известны только после `hello`
        self._phases_source = phases
        self._phases = tuple(phases() if callable(phases) else phases)
        self._retries = retries
        self._state: State = "idle"
        self._index = 0
        self._attempt = 0
        self._sent = False
        self._elapsed_s = 0.0
        self._progress = 0.0
        self._stale: dict[str, CalibrationProgress | None] = {}
        self._fresh: set[str] = set()
        self._failure: str | None = None
        self._retry_reason: str | None = None
        self._cycle: CalibrationProgress | None = None

    @classmethod
    def for_launch(cls, signals: Signals, launch: LaunchInfo) -> Calibration:
        discipline = launch.discipline
        return cls(signals, lambda: phases_for(discipline, emg_cycle=signals.supports("emg_cycle")))

    # --- состояние ---

    @property
    def state(self) -> State:
        return self._state

    @property
    def finished(self) -> bool:
        return self._state in ("done", "failed")

    @property
    def failure_reason(self) -> str | None:
        return self._failure

    @property
    def phase(self) -> Phase | None:
        if self._state != "running":
            return None
        return self._phases[self._index]

    @property
    def phase_count(self) -> int:
        return len(self._phases)

    @property
    def phase_number(self) -> int:
        """Номер текущего шага с единицы."""
        return min(self._index + 1, len(self._phases))

    @property
    def progress(self) -> float:
        """Прогресс текущего шага 0…1."""
        return self._progress

    @property
    def total_progress(self) -> float:
        if not self._phases:
            return 1.0
        done = self._index + (1.0 if self._state == "done" else self._progress)
        return min(1.0, done / len(self._phases))

    @property
    def retrying(self) -> bool:
        return self._state == "running" and self._attempt > 0

    @property
    def cycle_phase(self) -> CyclePhase | None:
        """Фаза шага `cycle` по последнему сообщению моста; вне `cycle` `None`."""
        return None if self._cycle is None else self._cycle.phase

    @property
    def phase_left_s(self) -> float | None:
        """Сколько секунд осталось фазе `cycle`; вне `cycle` `None`."""
        return None if self._cycle is None else self._cycle.phase_left_s

    @property
    def shows_dot(self) -> bool:
        """Во время `baseline` на экране рисуется точка, на которую надо смотреть."""
        phase = self.phase
        return phase is not None and phase.step == "baseline"

    @property
    def retry_reason(self) -> str | None:
        """Причина последнего сбоя шага человеческим текстом, пока идёт повтор."""
        return self._retry_reason if self.retrying else None

    @property
    def text(self) -> str:
        """Инструкция сейчас; пусто, если калибровка не идёт."""
        phase = self.phase
        return "" if phase is None else instruction(phase.step, self._progress, self.cycle_phase)

    # --- ход ---

    def start(self) -> None:
        if callable(self._phases_source):
            self._phases = tuple(self._phases_source())
        self._index = 0
        self._failure = None
        self._retry_reason = None
        self._state = "running" if self._phases else "done"
        self._begin_phase()

    def update(self, dt: float) -> None:
        if self._state != "running":
            return
        self._elapsed_s += dt
        phase = self._phases[self._index]
        if not self._sent:
            self._sent = self._send(phase)
            if not self._sent:
                self._check_timeout(phase)
                return
        failure = self._poll(phase)
        if failure is not None:
            self._on_failure(failure)
        elif self._progress >= 1.0:
            self._next_phase()
        else:
            self._check_timeout(phase)

    # --- внутреннее ---

    def _begin_phase(self) -> None:
        self._attempt = 0
        self._restart_phase()

    def _restart_phase(self) -> None:
        self._sent = False
        self._elapsed_s = 0.0
        self._progress = 0.0
        self._cycle = None

    def _send(self, phase: Phase) -> bool:
        # прогресс, который мост уже держит от прошлого запуска, за новый не считаем
        stale = {s: self._signals.calibration(s) for s in phase.signals}
        if not all(self._signals.calibrate(s, phase.step) for s in phase.signals):
            return False
        self._stale = stale
        self._fresh.clear()
        return True

    def _poll(self, phase: Phase) -> str | None:
        """Причина сбоя или `None`; обновляет `_progress`."""
        progresses: list[float] = []
        for name in phase.signals:
            current = self._signals.calibration(name)
            if current is not None and current != self._stale.get(name):
                self._fresh.add(name)  # мост ответил на новый запуск: дальше верим всему
            if current is None or current.step != phase.step or name not in self._fresh:
                progresses.append(0.0)
            elif current.status == "failed":
                return current.reason or f"{name}: калибровка не удалась"
            elif current.status == "done":
                progresses.append(1.0)
            else:
                progresses.append(min(1.0, max(0.0, current.progress)))
                if phase.step == "cycle" and name == phase.signals[0]:
                    self._cycle = current  # у понга оба датчика в одном ритме: берём первый
        self._progress = min(progresses)
        return None

    def _check_timeout(self, phase: Phase) -> None:
        limit = STEP_DURATION_S[phase.step] * TIMEOUT_FACTOR + TIMEOUT_EXTRA_S
        if self._elapsed_s > limit:
            self._on_failure("мост не отвечает на калибровку")

    def _on_failure(self, reason: str) -> None:
        if self._attempt < self._retries:
            self._attempt += 1
            self._retry_reason = reason_text(reason)
            self._restart_phase()
            return
        self._failure = reason
        self._state = "failed"

    def _next_phase(self) -> None:
        if self._index + 1 >= len(self._phases):
            self._progress = 1.0
            self._state = "done"
            return
        self._index += 1
        self._retry_reason = None
        self._begin_phase()
