"""Раскладка эмулятора: имя клавиши pygame -> логическая клавиша источника. Без pygame."""

from __future__ import annotations

_DARTS_FOOTBALL = {
    "w": "eeg_up",
    "s": "eeg_down",
    "a": "eeg_artifact",
    "space": "emg",
    "f": "calib_fail",
}
_PONG = {
    "left shift": "emg_left",
    "q": "emg_left",
    "right shift": "emg_right",
    "p": "emg_right",
    "f": "calib_fail",
}

KEY_MAPS: dict[str, dict[str, str]] = {
    "darts": _DARTS_FOOTBALL,
    "football": _DARTS_FOOTBALL,
    "pong": _PONG,
}

HINTS: dict[str, str] = {
    "eeg_up": "W: сосредоточение больше",
    "eeg_down": "S: сосредоточение меньше",
    "eeg_artifact": "A: артефакт ЭЭГ",
    "emg": "Пробел: сокращение мышцы",
    "emg_left": "Левый Shift / Q: левая мышца",
    "emg_right": "Правый Shift / P: правая мышца",
    "calib_fail": "F (держать): калибровка завершится сбоем",
}


def logical_keys(profile: str, pressed_names: set[str]) -> set[str]:
    mapping = KEY_MAPS[profile]
    return {mapping[n] for n in pressed_names if n in mapping}
