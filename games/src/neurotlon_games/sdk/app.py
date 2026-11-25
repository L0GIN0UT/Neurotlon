"""Основа игры на pygame-ce: игровой код пишет только `update`, `draw` и `result`.

Базовый класс сам: открывает окно, ждёт мост, проводит калибровку, отсчитывает «3-2-1»,
ведёт таймер и показывает его, обрабатывает Esc (прервать с подтверждением) и потерю датчика
(пауза, через 30 с — `aborted`), в конце пишет `result.json` и выходит.

`pygame` импортируется внутри методов, чтобы `neurotlon_games.sdk` можно было
импортировать и тестировать без окна.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .calibration import TEXT_RETRY, Calibration
from .launch import LaunchError, LaunchInfo
from .result import ResultEntry, ResultError, ResultWriter
from .signals import Signals
from .timer import Timer

if TYPE_CHECKING:
    import pygame

log = logging.getLogger(__name__)

TIME_SCALE_ENV = "NEUROTLON_TIME_SCALE"
WINDOW_SIZE = (1280, 720)

BACKGROUND = (18, 20, 28)
TEXT = (235, 238, 245)
MUTED = (150, 156, 170)
ACCENT = (80, 200, 140)
WARN = (240, 180, 60)
DANGER = (230, 90, 90)


class Phase(Enum):
    CONNECTING = "connecting"
    CALIBRATING = "calibrating"
    COUNTDOWN = "countdown"
    PLAYING = "playing"
    SENSOR_LOST = "sensor_lost"
    CONFIRM_ABORT = "confirm_abort"
    FINISHED = "finished"


def draw_text(
    surface: pygame.Surface,
    text: str,
    size: int,
    center: tuple[int, int],
    color: tuple[int, int, int] = TEXT,
) -> None:
    """Текст шрифтом pygame по умолчанию (кириллица есть), по центру точки."""
    import pygame

    font = pygame.font.Font(None, size)
    image = font.render(text, True, color)
    surface.blit(image, image.get_rect(center=center))


def draw_bar(
    surface: pygame.Surface,
    rect: tuple[int, int, int, int],
    value: float,
    color: tuple[int, int, int] = ACCENT,
) -> None:
    """Горизонтальная шкала 0…1."""
    import pygame

    x, y, w, h = rect
    pygame.draw.rect(surface, (50, 54, 66), rect, border_radius=6)
    filled = int(w * min(1.0, max(0.0, value)))
    if filled > 0:
        pygame.draw.rect(surface, color, (x, y, filled, h), border_radius=6)


def time_scale_from_env() -> float:
    """Только для проверок и разработки: `NEUROTLON_TIME_SCALE=5` ускоряет таймеры в 5 раз."""
    try:
        value = float(os.environ.get(TIME_SCALE_ENV, "1"))
    except ValueError:
        return 1.0
    return value if math.isfinite(value) and value > 0 else 1.0


class GameApp:
    """Наследник реализует `update`, `draw`, `result`; остальное — на базовом классе."""

    title = "Нейротлон"
    connect_timeout_s = 15.0
    countdown_s = 3
    lost_abort_s = 30.0
    finish_show_s = 2.0

    def __init__(
        self, launch: LaunchInfo, signals: Signals, *, time_scale: float | None = None
    ) -> None:
        self.launch = launch
        self.signals = signals
        self.timer = Timer(launch.duration_s)
        self.calibration = Calibration.for_launch(signals, launch)
        self._writer = ResultWriter(launch)
        self._scale = time_scale if time_scale is not None else time_scale_from_env()
        self._phase = Phase.CONNECTING
        self._resume_phase = Phase.PLAYING
        self._started = False
        self._waited_s = 0.0
        self._countdown_left = float(self.countdown_s)
        self._lost_s = 0.0
        self._lost_names: list[str] = []
        self._finished_s = 0.0
        self._aborted = False
        self._written_reason: str | None = None

    # --- что реализует игра ---

    def start(self) -> None:
        """Вызывается один раз, когда отсчёт закончился и игра начинается."""

    def update(self, dt: float, signals: Signals) -> None:
        raise NotImplementedError

    def draw(self, surface: pygame.Surface) -> None:
        raise NotImplementedError

    def result(self) -> Sequence[ResultEntry]:
        """Записи по участникам `launch.participants`; зовётся один раз, когда время вышло."""
        raise NotImplementedError

    # --- состояние ---

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def done(self) -> bool:
        """Результат записан и можно закрывать окно."""
        if self._phase is not Phase.FINISHED:
            return False
        return self._aborted or self._finished_s >= self.finish_show_s

    @property
    def aborted_reason(self) -> str | None:
        return self._written_reason if self._aborted else None

    @property
    def countdown_number(self) -> int:
        return max(1, math.ceil(self._countdown_left))

    # --- шаг ---

    def tick(self, dt: float, events: Sequence[Any] = ()) -> None:
        """Один кадр логики; `dt` в секундах реального времени."""
        self._handle_events(events)
        match self._phase:
            case Phase.CONNECTING:
                self._tick_connecting(dt)
            case Phase.CALIBRATING:
                self._tick_calibrating(dt)
            case Phase.COUNTDOWN:
                self._tick_countdown(dt * self._scale)
            case Phase.PLAYING:
                self._tick_playing(dt * self._scale)
            case Phase.SENSOR_LOST:
                self._tick_lost(dt * self._scale)
            case Phase.FINISHED:
                self._finished_s += dt * self._scale
            case Phase.CONFIRM_ABORT:
                pass

    def abort(self, reason: str) -> None:
        """Записать `aborted` и закончить."""
        if self._phase is Phase.FINISHED:
            return
        self._writer.write_aborted(reason)
        self._written_reason = reason
        self._aborted = True
        self._phase = Phase.FINISHED

    def _handle_events(self, events: Sequence[Any]) -> None:
        import pygame

        for event in events:
            if self._phase is Phase.FINISHED:
                return
            if event.type == pygame.QUIT:
                self.abort("окно игры закрыто")
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._toggle_confirm()
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and (
                    self._phase is Phase.CONFIRM_ABORT
                ):
                    self.abort("игра прервана оператором")

    def _toggle_confirm(self) -> None:
        if self._phase is Phase.CONFIRM_ABORT:
            self._phase = self._resume_phase
        else:
            self._resume_phase = self._phase
            self._phase = Phase.CONFIRM_ABORT

    def _tick_connecting(self, dt: float) -> None:
        if self.signals.connected and all(
            self.signals.sensor_state(n) is not None for n in self.signals.names
        ):
            self.calibration.start()
            self._phase = Phase.CALIBRATING
            return
        self._waited_s += dt
        if self._waited_s >= self.connect_timeout_s:
            self.abort("нет связи с BCI-мостом")

    def _tick_calibrating(self, dt: float) -> None:
        self.calibration.update(dt)
        if self.calibration.state == "failed":
            self.abort(f"калибровка не удалась: {self.calibration.failure_reason}")
        elif self.calibration.state == "done":
            self._phase = Phase.COUNTDOWN

    def _tick_countdown(self, dt: float) -> None:
        if self._enter_lost_if_needed(Phase.COUNTDOWN):
            return
        self._countdown_left -= dt
        if self._countdown_left <= 0:
            self._started = True
            self.start()
            self._phase = Phase.PLAYING

    def _tick_playing(self, dt: float) -> None:
        if self._enter_lost_if_needed(Phase.PLAYING):
            return
        self.timer.tick(dt)
        self.update(dt, self.signals)
        if self.timer.expired:
            self._finish()

    def _enter_lost_if_needed(self, came_from: Phase) -> bool:
        lost = self.signals.lost_signals()
        if not lost:
            return False
        self._lost_names = lost
        self._lost_s = 0.0
        self._resume_phase = came_from
        self._phase = Phase.SENSOR_LOST
        return True

    def _tick_lost(self, dt: float) -> None:
        lost = self.signals.lost_signals()
        if not lost:
            self._phase = self._resume_phase
            return
        self._lost_names = lost
        self._lost_s += dt
        if self._lost_s >= self.lost_abort_s:
            self.abort(f"датчик не вернулся за {self.lost_abort_s:g} с: {', '.join(lost)}")

    def _finish(self) -> None:
        try:
            self._writer.write_finished(self.result())
        except ResultError as exc:
            log.error("игра вернула недопустимый результат: %s", exc)
            self.abort(f"недопустимый результат игры: {exc}")
            return
        self._phase = Phase.FINISHED

    # --- отрисовка ---

    def render(self, surface: pygame.Surface) -> None:
        import pygame

        surface.fill(BACKGROUND)
        width, height = surface.get_size()
        mid = (width // 2, height // 2)
        match self._phase:
            case Phase.CONNECTING:
                draw_text(surface, "Подключение к датчикам…", 56, mid)
            case Phase.CALIBRATING:
                self._render_calibration(surface, width, height)
            case Phase.COUNTDOWN:
                draw_text(surface, "Приготовьтесь", 56, (mid[0], mid[1] - 120), MUTED)
                draw_text(surface, str(self.countdown_number), 280, mid, ACCENT)
            case Phase.PLAYING:
                self.draw(surface)
                self._render_hud(surface, width)
            case Phase.SENSOR_LOST | Phase.CONFIRM_ABORT:
                if self._started:
                    self.draw(surface)
                    self._render_hud(surface, width)
                veil = pygame.Surface((width, height), pygame.SRCALPHA)
                veil.fill((0, 0, 0, 190))
                surface.blit(veil, (0, 0))
                if self._phase is Phase.SENSOR_LOST:
                    self._render_lost(surface, mid)
                else:
                    draw_text(surface, "Прервать игру?", 80, (mid[0], mid[1] - 40), WARN)
                    draw_text(
                        surface, "Enter: прервать    Esc: продолжить", 44, (mid[0], mid[1] + 40)
                    )
            case Phase.FINISHED:
                text = "Игра прервана" if self._aborted else "Игра окончена"
                draw_text(surface, text, 96, mid, DANGER if self._aborted else ACCENT)

    def _render_calibration(self, surface: pygame.Surface, width: int, height: int) -> None:
        import pygame

        calibration = self.calibration
        mid_x = width // 2
        title = f"Калибровка: шаг {calibration.phase_number} из {calibration.phase_count}"
        draw_text(surface, title, 48, (mid_x, height // 4), MUTED)
        if calibration.shows_dot:
            draw_text(surface, calibration.text, 72, (mid_x, height * 2 // 5), ACCENT)
            pygame.draw.circle(surface, TEXT, (mid_x, height // 2), max(12, height // 50))
        else:
            draw_text(surface, calibration.text, 110, (mid_x, height // 2), ACCENT)
            left = calibration.phase_left_s
            if left is not None:
                draw_text(surface, str(math.ceil(left)), 64, (mid_x, height // 2 + 90), MUTED)
        bar_w = width // 2
        draw_bar(surface, (mid_x - bar_w // 2, height * 2 // 3, bar_w, 24), calibration.progress)
        if calibration.retrying:
            draw_text(surface, TEXT_RETRY, 40, (mid_x, height * 3 // 4), WARN)
            if calibration.retry_reason:
                draw_text(surface, calibration.retry_reason, 40, (mid_x, height * 4 // 5), WARN)

    def _render_hud(self, surface: pygame.Surface, width: int) -> None:
        draw_text(surface, self.timer.label(), 72, (width // 2, 40))

    def _render_lost(self, surface: pygame.Surface, mid: tuple[int, int]) -> None:
        left = max(0, math.ceil(self.lost_abort_s - self._lost_s))
        draw_text(surface, "Датчик потерян", 90, (mid[0], mid[1] - 60), DANGER)
        draw_text(surface, "Игра на паузе, проверьте датчик", 44, mid)
        draw_text(
            surface,
            f"Если связь не вернётся, игра прервётся через {left} с",
            36,
            (mid[0], mid[1] + 60),
            MUTED,
        )

    # --- запуск ---

    def run(self, *, windowed: bool = False) -> int:
        """Окно и цикл до конца игры; возвращает код выхода процесса."""
        import pygame

        pygame.init()
        try:
            fullscreen = self.launch.fullscreen and not windowed
            if fullscreen:
                screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                pygame.mouse.set_visible(False)
            else:
                screen = pygame.display.set_mode(WINDOW_SIZE)
            pygame.display.set_caption(self.title)
            clock = pygame.time.Clock()
            while not self.done:
                dt = clock.tick(60) / 1000.0
                self.tick(dt, pygame.event.get())
                self.render(screen)
                pygame.display.flip()
        finally:
            pygame.quit()
        return 0


def run_game(
    factory: Callable[[LaunchInfo, Signals], GameApp], argv: Sequence[str] | None = None
) -> int:
    """Точка входа игры: `--launch` -> мост -> игра -> код выхода."""
    parser = argparse.ArgumentParser(description="Игра Нейротлона")
    parser.add_argument("--launch", required=True, help="путь к launch.json")
    parser.add_argument("--windowed", action="store_true", help="в окне (разработка)")
    args = parser.parse_args(argv)
    try:
        launch = LaunchInfo.from_file(Path(args.launch))
    except LaunchError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    signals = Signals.connect(launch)
    try:
        return factory(launch, signals).run(windowed=args.windowed)
    finally:
        signals.close()
