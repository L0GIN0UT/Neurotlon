"""Шаблон игры: самая маленькая полная игра на `GameApp`. Отправная точка для настоящих игр.

Запуск без лаунчера (мост с эмулятором должен работать: `neurotlon-bridge --emulate`):

    python -m neurotlon_games.template --launch path/to/launch.json --windowed

Что делает: показывает шкалу(ы) сигнала; пока значение выше `THRESHOLD`, копятся очки
(одно очко за секунду на каждый сигнал). Дартс и футбол: один игрок, шкалы `eeg` и `emg`.
Понг: два игрока, шкалы `emg_left` и `emg_right`, побеждает набравший больше очков.

Что заменить в настоящей игре (всё остальное уже есть в `GameApp`):
1. `update` — игровая механика, читает `signals.value(...)`;
2. `draw` — картинка; таймер и подсказки рисует `GameApp`;
3. `result` — очки по методике и (в понге) победитель.
Окно, проверка калибровки (саму калибровку проводит лаунчер), отсчёт, таймер, Esc, потеря датчика
и запись result.json делает базовый класс.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

import pygame

from .sdk import GameApp, LaunchInfo, ResultEntry, Signals, completed, draw_bar, draw_text, run_game
from .sdk.app import ACCENT, MUTED

THRESHOLD = 0.6
POINTS_PER_SECOND = 1.0
MAX_POINTS = 1000.0  # потолок схемы result.json

SIGNAL_TITLES = {
    "eeg": "Расслабление",
    "emg": "Сила мышцы",
    "emg_left": "Левый игрок",
    "emg_right": "Правый игрок",
}


class TemplateGame(GameApp):
    title = "Нейротлон: шаблон игры"

    def __init__(self, launch: LaunchInfo, signals: Signals) -> None:
        super().__init__(launch, signals)
        self._levels: dict[str, float] = dict.fromkeys(launch.signals, 0.0)
        self._points: dict[str, float] = dict.fromkeys(launch.signals, 0.0)
        self._peaks: dict[str, float] = dict.fromkeys(launch.signals, 0.0)

    def update(self, dt: float, signals: Signals) -> None:
        for name in self.launch.signals:
            value = signals.value(name)  # None: артефакт или нет контакта — очков не даём
            self._levels[name] = 0.0 if value is None else value
            if value is None:
                continue
            self._peaks[name] = max(self._peaks[name], value)
            if value > THRESHOLD:
                self._points[name] += POINTS_PER_SECOND * dt

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        names = self.launch.signals
        slot = width // (len(names) + 1)
        for i, name in enumerate(names, start=1):
            x = slot * i
            color = ACCENT if self._levels[name] > THRESHOLD else MUTED
            draw_text(surface, SIGNAL_TITLES[name], 44, (x, height // 3), MUTED)
            draw_bar(surface, (x - 150, height // 2, 300, 36), self._levels[name], color)
            draw_text(surface, f"Очки: {int(self._points[name])}", 52, (x, height * 2 // 3))

    def result(self) -> Sequence[ResultEntry]:
        launch = self.launch
        if not launch.is_pong:
            player = launch.participants[0]
            total = sum(self._points.values())
            cap = float(launch.max_points or MAX_POINTS)  # секция: не больше лимита дисциплины
            return [completed(player.code, int(min(total, cap)))]
        scores = {p.code: self._points[launch.signal_of(p)] for p in launch.participants}
        peaks = {p.code: self._peaks[launch.signal_of(p)] for p in launch.participants}
        # при равенстве очков побеждает тот, у кого выше пик; потом левый (первый)
        winner = max(
            launch.participants, key=lambda p: (scores[p.code], peaks[p.code], p.side == "left")
        )
        return [
            completed(p.code, int(min(scores[p.code], MAX_POINTS)), int(p is winner))
            for p in launch.participants
        ]


def main(argv: Sequence[str] | None = None) -> int:
    return run_game(TemplateGame, argv)


if __name__ == "__main__":
    sys.exit(main())
