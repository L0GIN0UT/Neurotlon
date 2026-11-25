"""Сценарий «рук и головы»: эмулятор сам двигает сигналы, без клавиатуры.

Нужен для `neurotlon-game-check` и для режима `neurotlon-bridge --emulate --auto`: стенд без
датчиков проходит калибровку, обучение и игру сам.
"""

from __future__ import annotations

import threading
import time

from neurotlon_bridge.emulator import EmulatedSource

TICK_S = 0.02
# Импульсы (броски, удары): мышца напряжена 0,6 с, потом отдыхает 1 с. Эмулированный уровень
# спадает с постоянной 0,25 с, детектору резких сокращений нужно около 0,9 с спокойного
# уровня между событиями; в начале фазы так же 1 с отдыха.
PULSE_ON_S = 0.6
PULSE_PERIOD_S = 1.6
# Ровное напряжение около 0,3 (им останавливают мяч в зоне): ключ эмулятора включён
# на короткую долю каждых 0,1 с, после сглаживания среднее около 0,29.
STEADY_EMG_PERIOD_S = 0.1
STEADY_EMG_ON_S = 0.02
PULSE_PHASE_S = 12.0  # сначала импульсы (броски, удары), потом ровное напряжение (торможение)
STEADY_PHASE_S = 12.0
# Медленный подъём от нуля до максимума (растущая скважность): резкости нет, событий быть не должно.
RAMP_PHASE_S = 6.0
RAMP_PWM_PERIOD_S = 0.1
CYCLE_S = PULSE_PHASE_S + STEADY_PHASE_S + RAMP_PHASE_S
EEG_PERIOD_S = 6.0  # половину периода расслабление растёт, потом падает
PONG_PERIOD_S = 1.6


def emg_held(t: float) -> bool:
    """Нажат ли «ключ» мышцы в момент `t`: импульсы, ровное напряжение, медленный подъём."""
    u = t % CYCLE_S
    if u < PULSE_PHASE_S:
        return u % PULSE_PERIOD_S >= PULSE_PERIOD_S - PULSE_ON_S
    u -= PULSE_PHASE_S
    if u < STEADY_PHASE_S:
        return u % STEADY_EMG_PERIOD_S < STEADY_EMG_ON_S
    u -= STEADY_PHASE_S
    return u % RAMP_PWM_PERIOD_S < (u / RAMP_PHASE_S) * RAMP_PWM_PERIOD_S


def keys_at(profile: str, t: float) -> set[str]:
    """Логические клавиши эмулятора в момент `t` секунд: значения гуляют вверх и вниз."""
    if profile == "pong":
        keys = set()
        if t % PONG_PERIOD_S < PONG_PERIOD_S / 2:
            keys.add("emg_left")
        if (t + PONG_PERIOD_S / 2) % PONG_PERIOD_S < PONG_PERIOD_S / 2:
            keys.add("emg_right")
        return keys
    keys = set()
    if emg_held(t):
        keys.add("emg")
    keys.add("eeg_up" if t % EEG_PERIOD_S < EEG_PERIOD_S / 2 else "eeg_down")
    return keys


class ScriptedInput:
    """Поток, который по сценарию нажимает «клавиши» эмулятора и двигает его время."""

    def __init__(self, source: EmulatedSource, profile: str) -> None:
        self._source = source
        self._profile = profile
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scripted-input", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        t0 = time.monotonic()
        last = t0
        while not self._stop.wait(TICK_S):
            now = time.monotonic()
            self._source.set_keys(keys_at(self._profile, now - t0))
            self._source.tick(now - last)
            last = now
