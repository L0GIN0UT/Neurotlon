"""Экраны лаунчера на pygame-ce: рисуют состояние машины и передают ей ввод.

Логики здесь нет: события клавиатуры, мыши и камеры превращаются в вызовы машины.
Модуль подключается только при запуске интерфейса (pygame тяжёлый).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

import pygame

from . import texts
from .layout import (
    DARK,
    GRAY,
    GREEN,
    RED,
    WHITE,
    YELLOW,
    Button,
    Color,
    Rect,
    button_row,
    fit_rect,
    parse_hex_color,
    wrap_text,
)
from .machine import (
    Blocked,
    Candidate,
    Checking,
    Confirm,
    Done,
    Idle,
    Playing,
    RejectedList,
    Starting,
    StationMachine,
    TechnicalProblem,
)
from .qr import CodeSource

log = logging.getLogger(__name__)

FPS = 30
FONT_CANDIDATES = "segoeui,arial,dejavusans,liberationsans,freesans"
WINDOWED_SIZE = (1280, 720)
Footer = Callable[[], tuple[int, int]]  # (не отправлено, отклонено сервером)


class Ui:
    def __init__(
        self,
        machine: StationMachine,
        scanner: CodeSource,
        footer: Footer,
        *,
        windowed: bool = False,
    ) -> None:
        self._machine = machine
        self._scanner = scanner
        self._footer = footer
        self._windowed = windowed
        self._buttons: list[Button] = []
        self._fonts: dict[str, pygame.font.Font] = {}
        self._screen: pygame.Surface
        self._footer_cache = (0, 0)
        self._footer_at = -10_000

    # --- главный цикл -------------------------------------------------------------------

    def run(self) -> None:
        pygame.init()
        try:
            flags = 0 if self._windowed else pygame.FULLSCREEN
            size = WINDOWED_SIZE if self._windowed else (0, 0)
            self._screen = pygame.display.set_mode(size, flags)
            pygame.display.set_caption(texts.TITLE)
            pygame.mouse.set_visible(self._windowed)
            self._load_fonts(self._screen.get_height())
            clock = pygame.time.Clock()
            running = True
            while running:
                for event in pygame.event.get():
                    running = self._handle(event) and running
                self._poll_scanner()
                self._machine.tick()
                self._draw()
                pygame.display.flip()
                clock.tick(FPS)
        finally:
            pygame.quit()

    def _load_fonts(self, height: int) -> None:
        for name, divisor in (("big", 9), ("mid", 17), ("small", 30)):
            self._fonts[name] = pygame.font.SysFont(FONT_CANDIDATES, height // divisor)

    def _poll_scanner(self) -> None:
        code = self._scanner.poll()
        if code is not None:
            self._machine.enter_code(code)

    # --- ввод ---------------------------------------------------------------------------

    def _handle(self, event: pygame.event.Event) -> bool:
        """`False` — закрыть лаунчер."""
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q and event.mod & pygame.KMOD_CTRL:
                return False
            self._on_key(event)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for button in self._buttons:
                if button.hit(event.pos):
                    button.action()
                    break
        return True

    def _on_key(self, event: pygame.event.Event) -> None:
        machine, state = self._machine, self._machine.state
        enter = event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
        if isinstance(state, Idle):
            if event.key == pygame.K_F2:
                machine.show_rejected()
            elif enter:
                machine.submit_input()
            elif event.key == pygame.K_BACKSPACE:
                machine.backspace()
            elif event.key == pygame.K_ESCAPE:
                machine.cancel()
            elif event.unicode:
                machine.type_char(event.unicode)
        elif isinstance(state, Confirm):
            if enter:
                machine.confirm()
            elif event.key == pygame.K_ESCAPE:
                machine.cancel()
        elif isinstance(state, RejectedList):
            if event.key == pygame.K_ESCAPE:
                machine.close_rejected()
            elif event.key == pygame.K_e:
                machine.export_rejected()
        elif isinstance(state, TechnicalProblem) and enter:
            machine.retry()  # «Не пройдено» только кнопкой: случайное нажатие не должно её вызвать

    # --- рисование ----------------------------------------------------------------------

    def _draw(self) -> None:
        screen = self._screen
        screen.fill(DARK)
        self._buttons = []
        state = self._machine.state
        if isinstance(state, Idle):
            self._draw_idle(state)
        elif isinstance(state, Checking):
            self._center(texts.CHECKING, "big", WHITE, 0.45)
        elif isinstance(state, Confirm):
            self._draw_confirm(state)
        elif isinstance(state, Starting):
            self._center(texts.STARTING, "big", WHITE, 0.45)
        elif isinstance(state, Playing):
            self._center(texts.PLAYING, "big", GREEN, 0.4)
            if state.offline:
                self._center(texts.PLAYING_OFFLINE, "mid", YELLOW, 0.55)
            if state.default_limit:
                self._center(texts.LIMIT_DEFAULT, "mid", YELLOW, 0.65)
        elif isinstance(state, Done):
            self._draw_done(state)
        elif isinstance(state, Blocked):
            self._draw_blocked(state)
        elif isinstance(state, RejectedList):
            self._draw_rejected(state)
        else:
            self._draw_problem(state)
        self._draw_footer()

    def _draw_idle(self, state: Idle) -> None:
        w, h = self._screen.get_size()
        need = self._machine.players_needed
        prompt = texts.SCAN_PROMPT_PONG[len(state.taken)] if need == 2 else texts.SCAN_PROMPT
        self._center(prompt, "mid", WHITE, 0.07)
        preview: Rect = (w // 4, int(h * 0.12), w // 2, int(h * 0.5))
        self._draw_preview(preview)
        cursor = "_" if pygame.time.get_ticks() // 500 % 2 == 0 else " "
        self._center(f"{texts.INPUT_LABEL}: {state.input}{cursor}", "big", WHITE, 0.72)
        if state.notice:
            self._center(state.notice, "mid", RED, 0.82)
        else:
            self._center(texts.TYPE_HINT, "small", GRAY, 0.82)
        for i, taken in enumerate(state.taken):
            self._center(f"{texts.side_line(i)}: {taken.code}", "small", GREEN, 0.88 + i * 0.03)

    def _draw_preview(self, box: Rect) -> None:
        frame = self._scanner.frame()
        if frame is None:
            message = texts.NO_CAMERA if not self._scanner.available else ""
            if message:
                self._center(message, "small", YELLOW, 0.37)
            return
        height, width = frame.shape[:2]
        surface = pygame.image.frombuffer(frame.tobytes(), (width, height), "BGR")
        x, y, out_w, out_h = fit_rect(width, height, box)
        self._screen.blit(pygame.transform.smoothscale(surface, (out_w, out_h)), (x, y))

    def _draw_confirm(self, state: Confirm) -> None:
        w, h = self._screen.get_size()
        candidate = state.candidate
        accent = YELLOW if candidate.warned else GREEN
        index = len(state.taken)
        if self._machine.players_needed == 2:
            self._center(f"{texts.side_line(index)}", "mid", GRAY, 0.06)
        bar = parse_hex_color(candidate.team.color) if candidate.team else GRAY
        pygame.draw.rect(self._screen, bar, (w // 8, int(h * 0.1), w * 3 // 4, h // 40))
        pygame.draw.rect(
            self._screen, accent, (w // 8, int(h * 0.1), w * 3 // 4, int(h * 0.5)), width=4
        )
        self._center(candidate.display_name or candidate.code, "big", WHITE, 0.2)
        if candidate.display_name:
            self._center(candidate.code, "mid", GRAY, 0.3)
        team_text = (
            texts.team_line(candidate.team.number, candidate.team.name)
            if candidate.team
            else texts.TEAM_NONE
        )
        self._center(team_text, "mid", bar if candidate.team else GRAY, 0.38)
        self._draw_warnings(candidate, state.notice)
        confirm = Button(texts.CONFIRM_BUTTON, button_row(w, h, 2)[0], self._machine.confirm, True)
        cancel = Button(texts.CANCEL_BUTTON, button_row(w, h, 2)[1], self._machine.cancel)
        self._draw_buttons((confirm, cancel), YELLOW if candidate.warned else GREEN)

    def _draw_warnings(self, candidate: Candidate, notice: str | None) -> None:
        lines: list[str] = []
        if candidate.offline:
            lines.append(texts.OFFLINE_WARNING)
        lines.extend(texts.ISSUES.get(issue, issue) for issue in candidate.issues)
        if notice:
            lines.append(notice)
        if not lines:
            return
        self._center(texts.ISSUES_TITLE, "small", YELLOW, 0.46)
        for i, line in enumerate(lines[:4]):
            self._center(line, "small", RED if line == notice else YELLOW, 0.5 + i * 0.04)

    def _draw_done(self, state: Done) -> None:
        self._center(texts.DONE_TITLE, "big", GREEN, 0.3)
        for i, line in enumerate(state.lines):
            self._center(line, "mid", WHITE, 0.45 + i * 0.08)

    def _draw_problem(self, state: TechnicalProblem) -> None:
        w, h = self._screen.get_size()
        self._center(texts.PROBLEM_TITLE, "big", YELLOW, 0.2)
        font = self._fonts["small"]
        lines = wrap_text(state.reason, w * 3 // 4, lambda s: font.size(s)[0])
        for i, line in enumerate(lines[:4]):
            self._center(line, "small", GRAY, 0.35 + i * 0.05)
        retry = Button(texts.RETRY_BUTTON, button_row(w, h, 2)[0], self._machine.retry, True)
        give_up = Button(texts.GIVE_UP_BUTTON, button_row(w, h, 2)[1], self._machine.give_up)
        self._draw_buttons((retry, give_up), YELLOW)

    def _draw_blocked(self, state: Blocked) -> None:
        w, _ = self._screen.get_size()
        self._center(texts.BLOCKED_TITLE, "big", RED, 0.2)
        font = self._fonts["mid"]
        lines = wrap_text(state.message, w * 3 // 4, lambda s: font.size(s)[0])
        for i, line in enumerate(lines[:5]):
            self._center(line, "mid", WHITE, 0.4 + i * 0.07)
        self._center(texts.BLOCKED_HINT, "small", GRAY, 0.85)

    def _draw_rejected(self, state: RejectedList) -> None:
        w, h = self._screen.get_size()
        self._center(texts.REJECTED_TITLE, "mid", WHITE, 0.07)
        if not state.items:
            self._center(texts.REJECTED_EMPTY, "mid", GRAY, 0.4)
        font = self._fonts["small"]
        for i, item in enumerate(state.items[:8]):
            line = f"{item.session_id[:8]}  {', '.join(item.codes)}  {item.error}"
            while len(line) > 8 and font.size(line)[0] > w - 80:
                line = line[:-4] + "…"
            surface = font.render(line, True, YELLOW)
            self._screen.blit(surface, (40, int(h * 0.15) + i * surface.get_height() * 3 // 2))
        if state.exported_to:
            self._center(texts.exported_to(state.exported_to), "small", GREEN, 0.7)
        rects = button_row(w, h, 2)
        export = Button(texts.EXPORT_BUTTON, rects[0], self._machine.export_rejected, True)
        back = Button(texts.BACK_BUTTON, rects[1], self._machine.close_rejected)
        self._draw_buttons((export, back), GREEN)

    def _draw_buttons(self, buttons: Sequence[Button], accent: Color) -> None:
        font = self._fonts["mid"]
        for button in buttons:
            fill = accent if button.primary else (60, 63, 72)
            pygame.draw.rect(self._screen, fill, button.rect, border_radius=16)
            label = font.render(button.label, True, DARK if button.primary else WHITE)
            x, y, w, h = button.rect
            self._screen.blit(label, label.get_rect(center=(x + w // 2, y + h // 2)))
            self._buttons.append(button)

    def _draw_footer(self) -> None:
        now = pygame.time.get_ticks()
        if now - self._footer_at > 1000:
            self._footer_cache, self._footer_at = self._footer(), now
        pending, rejected = self._footer_cache
        parts: list[str] = []
        if pending:
            parts.append(texts.QUEUE_LINE.format(n=pending))
        if rejected:
            parts.append(f"{texts.REJECTED_LINE.format(n=rejected)} · {texts.REJECTED_HINT}")
        if parts:
            color = RED if rejected else YELLOW
            surface = self._fonts["small"].render("   ".join(parts), True, color)
            self._screen.blit(surface, (20, self._screen.get_height() - surface.get_height() - 10))

    def _center(self, text: str, size: str, color: Color, y_ratio: float) -> None:
        surface = self._fonts[size].render(text, True, color)
        w, h = self._screen.get_size()
        self._screen.blit(surface, surface.get_rect(center=(w // 2, int(h * y_ratio))))
