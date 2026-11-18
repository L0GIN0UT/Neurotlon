"""Сценарий «рук и головы» для проверки: эмулятор сам двигает сигналы, без клавиатуры."""

from __future__ import annotations

import threading
import time

from neurotlon_bridge.emulator import EmulatedSource

TICK_S = 0.02
EMG_PERIOD_S = 1.2  # половину периода мышца сжата
EEG_PERIOD_S = 6.0  # половину периода расслабление растёт, потом падает
PONG_PERIOD_S = 1.6


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
    if t % EMG_PERIOD_S < EMG_PERIOD_S / 2:
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
