"""Экраны лаунчера на pygame-ce: рисуют состояние машины и передают ей ввод.

Логики здесь нет: события клавиатуры, мыши и камеры превращаются в вызовы машины.
Внешний вид (цвета, размеры) — в `theme.py`, примитивы рисования — в `widgets.py`.
Модуль подключается только при запуске интерфейса (pygame тяжёлый).

Каждый экран строится по одной схеме: верхняя полоса (марка, дисциплина, связь), содержимое,
нижняя полоса (подсказка и очередь отправки). Кнопки не меньше 100 единиц высотой: ими
пользуются на сенсорном экране.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

import pygame

from . import texts, theme
from .layout import Button, Color, Rect, fit_rect, parse_hex_color
from .machine import (
    DONE_SECONDS,
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
from .status import StationStatus
from .widgets import Assets, Canvas

log = logging.getLogger(__name__)

FPS = 30
WINDOWED_SIZE = (1280, 720)
FADE_MS = 220
FLASH_MS = 140  # на сколько подсвечивается нажатая кнопка
TOP_BAR = 96
BOTTOM_BAR = 68
PAD = 56
KEYPAD = ("1", "2", "3", "4", "5", "6", "7", "8", "9")

StatusSource = Callable[[], StationStatus]


def _step_of(state: object) -> int | None:
    """Номер шага в полосе «Бейдж → Проверка → Игра → Результат»; `None` — полосы нет."""
    if isinstance(state, Idle | Checking):
        return 0
    if isinstance(state, Confirm):
        return 1
    if isinstance(state, Starting | Playing | TechnicalProblem):
        return 2
    if isinstance(state, Done):
        return 3
    return None


class Ui:
    def __init__(
        self,
        machine: StationMachine,
        scanner: CodeSource,
        status: StatusSource,
        *,
        windowed: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._monotonic = monotonic
        self._machine = machine
        self._scanner = scanner
        self._status_source = status
        self._windowed = windowed
        self._buttons: list[Button] = []
        self._canvas: Canvas
        self._status = StationStatus()
        self._status_at = -10_000
        self._flash: tuple[Rect, int] | None = None
        self._assets = Assets()
        self._shown: tuple[type, int] | None = None  # тип состояния и время появления

    # --- главный цикл -------------------------------------------------------------------

    def run(self) -> None:
        pygame.init()
        try:
            flags = 0 if self._windowed else pygame.FULLSCREEN
            size = WINDOWED_SIZE if self._windowed else (0, 0)
            screen = pygame.display.set_mode(size, flags)
            pygame.display.set_caption(texts.TITLE)
            pygame.mouse.set_visible(self._windowed)
            clock = pygame.time.Clock()
            running = True
            while running:
                for event in pygame.event.get():
                    running = self._handle(event) and running
                self._poll_scanner()
                self._machine.tick()
                self.draw(screen)
                pygame.display.flip()
                clock.tick(FPS)
        finally:
            pygame.quit()

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
            self._on_click(event.pos)
        return True

    def _on_click(self, pos: tuple[int, int]) -> None:
        for button in self._buttons:
            if button.hit(pos):
                self._flash = (button.rect, pygame.time.get_ticks() + FLASH_MS)
                button.action()
                break

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

    def draw(self, screen: pygame.Surface) -> None:
        """Нарисовать текущее состояние машины на `screen`."""
        canvas = Canvas(screen, self._assets)
        self._canvas = canvas
        self._buttons = []
        canvas.backdrop(self._accent, self._machine.discipline)
        state = self._machine.state
        content = self._content_rect()
        if isinstance(state, Idle):
            self._draw_idle(state, content)
        elif isinstance(state, Checking):
            self._draw_busy(content, texts.CHECKING, "", state.taken)
        elif isinstance(state, Confirm):
            self._draw_confirm(state, content)
        elif isinstance(state, Starting):
            self._draw_busy(content, texts.STARTING, texts.STARTING_HINT, state.players)
        elif isinstance(state, Playing):
            self._draw_playing(state, content)
        elif isinstance(state, Done):
            self._draw_done(state, content)
        elif isinstance(state, Blocked):
            self._draw_blocked(state, content)
        elif isinstance(state, RejectedList):
            self._draw_rejected(state, content)
        else:
            self._draw_problem(state, content)
        self._refresh_status()
        self._draw_top_bar(state)
        self._draw_bottom_bar(state)
        self._fade_in(type(state))

    @property
    def _accent(self) -> Color:
        return theme.accent_for(self._machine.discipline)

    def _fade_in(self, kind: type) -> None:
        """Плавное появление нового экрана: затемнение поверх быстро сходит на нет."""
        now = pygame.time.get_ticks()
        if self._shown is None or self._shown[0] is not kind:
            self._shown = (kind, now)
        alpha = round(255 * max(0.0, 1 - (now - self._shown[1]) / FADE_MS))
        if alpha <= 0:
            return
        size = self._canvas.screen.get_size()
        veil = self._assets.surfaces.get(("veil", size))
        if veil is None:
            veil = pygame.Surface(size)
            veil.fill(theme.BG)
            self._assets.surfaces[("veil", size)] = veil
        veil.set_alpha(alpha)
        self._canvas.screen.blit(veil, (0, 0))

    def _content_rect(self) -> Rect:
        c = self._canvas
        top, bottom, pad = c.px(TOP_BAR), c.px(BOTTOM_BAR), c.px(PAD)
        return (pad, top + c.px(8), c.width - 2 * pad, c.height - top - bottom - c.px(16))

    def _refresh_status(self) -> None:
        now = pygame.time.get_ticks()
        if now - self._status_at > 1000:
            self._status, self._status_at = self._status_source(), now

    def _button(
        self,
        rect: Rect,
        label: str,
        action: Callable[[], None],
        *,
        primary: bool = False,
        accent: Color | None = None,
        icon: str | None = None,
        size: float = 40,
        dim: bool = False,
    ) -> None:
        pressed = (
            self._flash is not None
            and self._flash[0] == rect
            and pygame.time.get_ticks() < self._flash[1]
        )
        button = self._canvas.button(
            rect,
            label,
            action,
            primary=primary,
            accent=accent or self._accent,
            icon=icon,
            size=size,
            pressed=pressed,
            dim=dim,
        )
        self._buttons.append(button)

    # --- общая рамка --------------------------------------------------------------------

    def _draw_top_bar(self, state: object) -> None:
        c = self._canvas
        h = c.px(TOP_BAR)
        bar = pygame.Surface((c.width, h), pygame.SRCALPHA)
        bar.fill((6, 9, 18, 200))
        c.screen.blit(bar, (0, 0))
        pad, mid = c.px(PAD), h // 2
        c.disc((pad + c.px(8), mid), 12, self._accent)
        c.text(texts.BRAND, 34, theme.TEXT, bold=True, midleft=(pad + c.px(40), mid - c.px(9)))
        c.text(texts.BRAND_SUB, 20, theme.MUTED, midleft=(pad + c.px(40), mid + c.px(21)))
        brand_right = pad + c.px(40) + c.measure(texts.BRAND, 34, bold=True)
        self._draw_link_chip(c.width - pad, mid)
        step = _step_of(state)
        if step is not None:
            self._draw_steps(step, brand_right + c.px(48), c.width - pad - c.px(230), mid)

    def _draw_steps(self, current: int, left: int, right: int, mid: int) -> None:
        """Полоса шагов: пройденные с галочкой, текущий окрашен цветом дисциплины."""
        c = self._canvas
        wide = c.width / c.height >= 1.6
        r = c.px(20)
        gap = c.px(26)
        widths = [
            2 * r + (c.px(12) + c.measure(label, 24, True) if wide or i == current else 0)
            for i, label in enumerate(texts.STEPS)
        ]
        total = sum(widths) + gap * (len(widths) - 1)
        if total > right - left:
            return
        x = left + (right - left - total) // 2
        for i, label in enumerate(texts.STEPS):
            done, active = i < current, i == current
            color = self._accent if active else theme.GREEN if done else theme.BORDER
            center = (x + r, mid)
            if active or done:
                c.disc(center, 20, color)
                if done:
                    c.icon("check", center, c.px(22), theme.BG)
                else:
                    c.text(str(i + 1), 24, theme.on_color(color), bold=True, center=center)
            else:
                c.ring(center, 20, color, 3)
                c.text(str(i + 1), 24, theme.MUTED, bold=True, center=center)
            if wide or active:
                c.text(
                    label,
                    24,
                    theme.TEXT if active else theme.MUTED,
                    bold=active,
                    midleft=(x + 2 * r + c.px(12), mid),
                )
            x += widths[i] + gap
            if i < len(widths) - 1:
                pygame.draw.line(
                    c.screen, theme.BORDER, (x - gap + c.px(12), mid), (x - c.px(12), mid), c.px(2)
                )

    def _draw_link_chip(self, right: int, mid: int) -> None:
        c = self._canvas
        online = self._status.online
        if online is True:
            label, color, icon = texts.ONLINE, theme.GREEN, "dot"
        elif online is False:
            label, color, icon = texts.OFFLINE, theme.YELLOW, "offline"
        else:
            label, color, icon = texts.LINK_UNKNOWN, theme.MUTED, "dot"
        c.chip(label, color, icon=icon, midright=(right, mid))

    def _draw_bottom_bar(self, state: object) -> None:
        c = self._canvas
        h = c.px(BOTTOM_BAR)
        y = c.height - h
        bar = pygame.Surface((c.width, h), pygame.SRCALPHA)
        bar.fill((6, 9, 18, 215))
        c.screen.blit(bar, (0, y))
        pad, mid = c.px(PAD), y + h // 2
        right = c.width - pad
        status = self._status
        if status.rejected and not isinstance(state, RejectedList):
            rect = c.chip(
                texts.REJECTED_LINE.format(n=status.rejected),
                theme.RED,
                icon="warning",
                midright=(right, mid),
            )
            if isinstance(state, Idle):  # плашка нажимается: список без клавиатуры
                tap = (rect[0], mid - c.px(50), rect[2], c.px(100))
                self._buttons.append(Button("rejected", tap, self._machine.show_rejected))
            right = rect[0] - c.px(16)
        if status.pending:
            rect = c.chip(
                texts.QUEUE_LINE.format(n=status.pending), theme.YELLOW, midright=(right, mid)
            )
            right = rect[0] - c.px(16)
        hints = {
            Idle: texts.HINTS_IDLE,
            Confirm: texts.HINTS_CONFIRM,
            TechnicalProblem: texts.HINTS_PROBLEM,
            RejectedList: texts.HINTS_REJECTED,
            Blocked: texts.HINTS_BLOCKED,
        }.get(type(state), ())
        if hints:
            c.hints(list(hints), (pad, mid), right - c.px(24))

    # --- ввод ID ------------------------------------------------------------------------

    def _draw_idle(self, state: Idle, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        gap = c.px(40)
        left_w = round(w * 0.5) - gap // 2
        right_x, right_w = x0 + left_w + gap, w - left_w - gap
        self._draw_camera(state, (x0, y0, left_w, h))

        y = y0 + c.px(4)
        need = self._machine.players_needed
        prompt = texts.SCAN_PROMPT_PONG[len(state.taken)] if need == 2 else texts.SCAN_PROMPT
        lines = c.wrap(prompt, 46, right_w, bold=True)[:2]
        for line in lines:
            c.text(line, 46, theme.TEXT, bold=True, topleft=(right_x, y))
            y += c.px(56)
        y += c.px(24)
        if need == 2:
            y = self._draw_pong_slots(state, right_x, y, right_w)
        c.text(texts.TYPE_HINT, 26, theme.MUTED, topleft=(right_x, y))
        y += c.px(40)

        field_h = c.px(104)
        field = (right_x, y, right_w, field_h)
        c.card(field, theme.SURFACE, border=self._accent if state.input else theme.BORDER)
        text_x, text_y = right_x + c.px(28), y + field_h // 2
        if state.input:
            rect = c.text(state.input, 64, theme.TEXT, bold=True, midleft=(text_x, text_y))
            if pygame.time.get_ticks() // 500 % 2 == 0:  # мигающий курсор линией, не символом
                cap = c.px(52)
                pygame.draw.rect(
                    c.screen,
                    self._accent,
                    (rect[0] + rect[2] + c.px(6), text_y - cap // 2, c.px(4), cap),
                )
        else:
            c.text(texts.ID_PLACEHOLDER, 64, theme.BORDER, bold=True, midleft=(text_x, text_y))
        y += field_h + c.px(12)

        notice_h = c.px(44)
        if state.notice:
            c.chip(
                state.notice,
                theme.RED,
                icon="warning",
                size=24,
                max_width=right_w,
                topleft=(right_x, y),
            )
        y += notice_h + c.px(16)

        self._draw_keypad((right_x, y, right_w, y0 + h - y), bool(state.input))

    def _draw_camera(self, state: Idle, area: Rect) -> None:
        """Карточка с видом камеры: высота по пропорциям кадра, по центру области."""
        c = self._canvas
        frame = self._scanner.frame()
        pad = c.px(28)
        aspect = 4 / 3
        if frame is not None:
            aspect = frame.shape[1] / max(1, frame.shape[0])
        card_h = min(area[3], round((area[2] - 2 * pad) / aspect) + 2 * pad)
        box = (area[0], area[1] + (area[3] - card_h) // 2, area[2], card_h)
        c.card(box, theme.SURFACE, border=theme.BORDER)
        inner = (box[0] + pad, box[1] + pad, box[2] - 2 * pad, box[3] - 2 * pad)
        if frame is None:
            cx, cy = box[0] + box[2] // 2, box[1] + box[3] // 2
            if self._scanner.available:
                c.spinner((cx, cy - c.px(30)), 46, pygame.time.get_ticks(), self._accent)
                c.text(texts.CAMERA_STARTING, 30, theme.MUTED, center=(cx, cy + c.px(60)))
            else:
                c.icon("warning", (cx, cy - c.px(60)), c.px(110), theme.YELLOW)
                c.text(texts.NO_CAMERA, 40, theme.YELLOW, bold=True, center=(cx, cy + c.px(30)))
                c.text(texts.NO_CAMERA_HINT, 28, theme.MUTED, center=(cx, cy + c.px(84)))
            return
        height, width = frame.shape[:2]
        surface = pygame.image.frombuffer(frame.tobytes(), (width, height), "BGR")
        x, y, out_w, out_h = fit_rect(width, height, inner)
        scaled = pygame.transform.smoothscale(surface, (out_w, out_h)).convert_alpha()
        mask = pygame.Surface((out_w, out_h), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, out_w, out_h), border_radius=c.px(18))
        scaled.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        c.screen.blit(scaled, (x, y))
        margin = c.px(14)
        c.corner_brackets(
            (x + margin, y + margin, out_w - 2 * margin, out_h - 2 * margin), self._accent
        )

    def _draw_pong_slots(self, state: Idle, x: int, y: int, width: int) -> int:
        c = self._canvas
        gap = c.px(20)
        slot_w, slot_h = (width - gap) // 2, c.px(92)
        for i in range(2):
            rect = (x + i * (slot_w + gap), y, slot_w, slot_h)
            taken = state.taken[i] if i < len(state.taken) else None
            active = i == len(state.taken)
            team = parse_hex_color(taken.team.color) if taken and taken.team else theme.MUTED
            c.card(
                rect,
                theme.SURFACE,
                border=self._accent if active else (team if taken else theme.BORDER),
            )
            c.text(
                f"{texts.PLAYER_SLOT[i]} · {texts.side_line(i).lower()}",
                22,
                theme.MUTED,
                midleft=(rect[0] + c.px(24), y + c.px(27)),
            )
            if taken:
                c.dot((rect[0] + c.px(34), y + c.px(64)), 8, team)
                label = c.fit(taken.display_name or taken.code, 30, slot_w - c.px(80), bold=True)
                c.text(label, 30, theme.TEXT, bold=True, midleft=(rect[0] + c.px(56), y + c.px(64)))
            else:
                waiting = texts.SLOT_WAITING
                c.text(
                    waiting,
                    28,
                    self._accent if active else theme.BORDER,
                    midleft=(rect[0] + c.px(24), y + c.px(64)),
                )
        return y + slot_h + c.px(28)

    def _draw_keypad(self, area: Rect, has_input: bool) -> None:
        c = self._canvas
        x, y, w, h = area
        gap = c.px(14)
        cols, rows = 3, 4
        key_h = max(c.px(100), min(c.px(124), (h - gap * (rows - 1)) // rows))
        key_w = (w - gap * (cols - 1)) // cols
        machine = self._machine

        def rect(row: int, col: int) -> Rect:
            return (x + col * (key_w + gap), y + row * (key_h + gap), key_w, key_h)

        for i, digit in enumerate(KEYPAD):
            self._button(rect(i // 3, i % 3), digit, partial(machine.type_char, digit), size=44)
        self._button(rect(3, 0), "", machine.backspace, icon="backspace", size=44)
        self._button(rect(3, 1), "0", partial(machine.type_char, "0"), size=44)
        self._button(
            rect(3, 2),
            texts.NEXT_BUTTON,
            machine.submit_input,
            primary=True,
            icon="arrow",
            size=34,
            dim=not has_input,
        )

    # --- подтверждение ------------------------------------------------------------------

    def _draw_confirm(self, state: Confirm, content: Rect) -> None:
        """Страница участника, как страница установленной игры в библиотеке Steam:
        баннер цвета команды, крупная кнопка «Играть» и строка сведений."""
        c = self._canvas
        x0, y0, w, h = content
        candidate = state.candidate
        warned = candidate.warned
        team_color = parse_hex_color(candidate.team.color) if candidate.team else theme.MUTED
        index = len(state.taken)
        two = self._machine.players_needed == 2
        warnings = self._warnings(candidate, state.notice)

        width = min(w, c.px(1500))
        x = x0 + (w - width) // 2
        banner_h = c.px(360)
        strip_h = c.px(140)
        warn_h = (c.px(64) * len(warnings) + c.px(12)) if warnings else 0
        gap = c.px(28)
        top = y0 + max(0, (h - banner_h - gap - strip_h - warn_h) // 2)

        # баннер
        banner = (x, top, width, banner_h)
        c.banner(banner, team_color)
        glyph = self._machine.discipline
        if glyph in theme.DISCIPLINE_GLYPHS:
            c.watermark(
                glyph,
                (x + width - c.px(250), top + banner_h // 2),
                c.px(300),
                theme.mix(theme.TEXT, team_color, 0.35),
                46,
            )
        center = (x + c.px(60 + 110), top + banner_h // 2)
        c.disc((center[0], center[1] + c.px(8)), 112, (0, 0, 0))
        c.disc(center, 110, theme.mix(team_color, theme.BG, 0.55))
        c.ring(center, 110, theme.TEXT, 5)
        c.text(
            theme.initials(candidate.display_name, candidate.code),
            110,
            theme.TEXT,
            bold=True,
            center=center,
        )
        tx = x + c.px(60 + 220 + 56)
        tw = x + width - c.px(60) - tx
        ty = top + c.px(70)
        if two:
            side = f"{texts.PLAYER_SLOT[index]} · {texts.side_line(index).lower()}"
            c.chip(side, theme.TEXT, size=24, topleft=(tx, top + c.px(40)))
            ty = top + c.px(112)
        name = c.fit(candidate.display_name or candidate.code, 92, tw, bold=True)
        c.text(name, 92, theme.TEXT, bold=True, topleft=(tx, ty))
        sub = (
            texts.team_line(candidate.team.number, candidate.team.name)
            if candidate.team
            else texts.TEAM_NONE
        )
        c.text(
            c.fit(sub, 40, tw, bold=True),
            40,
            theme.mix(theme.TEXT, team_color, 0.8),
            bold=True,
            topleft=(tx, ty + c.px(112)),
        )

        # строка с кнопкой «Играть» и сведениями
        sy = top + banner_h + gap
        strip = (x, sy, width, strip_h)
        c.card(strip, theme.mix(theme.SURFACE, theme.BG, 0.8), radius=30)
        last = len(state.taken) + 1 >= self._machine.players_needed
        play_color = theme.YELLOW if warned else theme.PLAY_GREEN
        play = (x + c.px(16), sy + c.px(14), c.px(470), strip_h - c.px(28))
        c.shadow(play, 26, 110)
        self._button(
            play,
            texts.PLAY_BUTTON if last else texts.PLAY_NEXT_BUTTON,
            self._machine.confirm,
            primary=True,
            accent=play_color,
            icon="play" if last else "arrow",
            size=50,
        )
        columns = (
            (texts.INFO_PARTICIPANT, candidate.code),
            (texts.INFO_TEAM, candidate.team.name if candidate.team else "—"),
            (texts.INFO_DISCIPLINE, texts.DISCIPLINE_NAMES.get(glyph, glyph)),
        )
        cancel_w = c.px(250)
        info_left = play[0] + play[2] + c.px(48)
        info_w = (x + width - c.px(24) - cancel_w - c.px(24) - info_left) // len(columns)
        for i, (label, value) in enumerate(columns):
            cx = info_left + i * info_w
            c.text(label, 20, theme.MUTED, bold=True, topleft=(cx, sy + c.px(34)))
            c.text(
                c.fit(value, 36, info_w - c.px(20), True),
                36,
                theme.TEXT,
                bold=True,
                topleft=(cx, sy + c.px(66)),
            )
        self._button(
            (x + width - c.px(24) - cancel_w, sy + c.px(20), cancel_w, strip_h - c.px(40)),
            texts.CANCEL_BUTTON,
            self._machine.cancel,
            size=30,
        )

        wy = sy + strip_h + c.px(12)
        for text, color, icon in warnings:
            c.chip(text, color, icon=icon, size=26, max_width=width, topleft=(x, wy))
            wy += c.px(64)

    @staticmethod
    def _warnings(candidate: Candidate, notice: str | None) -> list[tuple[str, Color, str]]:
        items: list[tuple[str, Color, str]] = []
        if candidate.offline:
            items.append((texts.OFFLINE_WARNING, theme.YELLOW, "offline"))
        items.extend(
            (texts.ISSUES.get(issue, issue), theme.YELLOW, "warning") for issue in candidate.issues
        )
        if notice:
            items.append((notice, theme.RED, "warning"))
        return items[:4]

    # --- ожидание, игра, итог -----------------------------------------------------------

    def _draw_players(self, players: tuple[Candidate, ...], center_x: int, y: int) -> None:
        c = self._canvas
        gap = c.px(24)
        limit = (c.width - 2 * c.px(PAD) - gap * (len(players) - 1)) // max(1, len(players))
        names = [c.fit(p.display_name or p.code, 30, limit - c.px(70), True) for p in players]
        widths = [c.measure(name, 30, bold=True) + c.px(70) for name in names]
        x = center_x - (sum(widths) + gap * (len(players) - 1)) // 2
        for player, name, width in zip(players, names, widths, strict=True):
            team = parse_hex_color(player.team.color) if player.team else theme.MUTED
            rect = (x, y, width, c.px(64))
            c.card(rect, theme.SURFACE, border=team, radius=32, border_width=2)
            c.dot((x + c.px(30), y + c.px(32)), 9, team)
            c.text(
                name,
                30,
                theme.TEXT,
                bold=True,
                midleft=(x + c.px(52), y + c.px(32)),
            )
            x += width + gap

    def _draw_busy(
        self, content: Rect, title: str, hint: str, players: tuple[Candidate, ...]
    ) -> None:
        c = self._canvas
        x0, y0, w, h = content
        cx, cy = x0 + w // 2, y0 + h // 2
        c.spinner((cx, cy - c.px(120)), 70, pygame.time.get_ticks(), self._accent)
        c.text(title, 64, theme.TEXT, bold=True, center=(cx, cy + c.px(10)))
        if hint:
            c.text(hint, 30, theme.MUTED, center=(cx, cy + c.px(76)))
        if players:
            self._draw_players(players, cx, cy + c.px(140))

    def _draw_playing(self, state: Playing, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        cx, cy = x0 + w // 2, y0 + h // 2 - c.px(30)
        pulse = 1 + 0.04 * ((pygame.time.get_ticks() // 40) % 20 / 20)
        glyph = self._machine.discipline
        c.disc((cx, cy - c.px(110)), 118 * pulse, theme.mix(theme.GREEN, theme.BG, 0.14))
        c.ring((cx, cy - c.px(110)), 118 * pulse, theme.GREEN, 5)
        if glyph in theme.DISCIPLINE_GLYPHS:
            c.icon(glyph, (cx, cy - c.px(110)), c.px(120), theme.GREEN)
        c.text(texts.PLAYING, 72, theme.TEXT, bold=True, center=(cx, cy + c.px(60)))
        c.text(texts.PLAYING_HINT, 30, theme.MUTED, center=(cx, cy + c.px(126)))
        self._draw_players(state.players, cx, cy + c.px(180))
        y = cy + c.px(280)
        if state.offline:
            c.chip(texts.PLAYING_OFFLINE, theme.YELLOW, icon="offline", midtop=(cx, y))
            y += c.px(66)
        if state.default_limit:
            c.chip(texts.LIMIT_DEFAULT, theme.YELLOW, icon="info", midtop=(cx, y))

    def _draw_done(self, state: Done, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        cx = x0 + w // 2
        rows = state.lines
        row_h = c.px(96)
        total = c.px(150) + c.px(40) + c.px(96) + c.px(30) + row_h * len(rows)
        top = y0 + max(0, (h - total) // 2)
        c.disc((cx, top + c.px(75)), 75, theme.GREEN)
        c.icon("check", (cx, top + c.px(75)), c.px(84), theme.BG)
        c.text(texts.DONE_TITLE, 80, theme.TEXT, bold=True, center=(cx, top + c.px(210)))
        card_w = min(w, c.px(900))
        y = top + c.px(280)
        card = (cx - card_w // 2, y, card_w, row_h * len(rows) + c.px(16))
        c.card(card, theme.SURFACE, border=theme.BORDER, radius=28)
        for i, line in enumerate(rows):
            label, _, value = line.partition(": ")
            ry = y + c.px(8) + i * row_h + row_h // 2
            if not value:
                label, value = line, ""
            c.text(label, 40, theme.MUTED, midleft=(card[0] + c.px(36), ry))
            if value:
                good = texts.DONE_POINTS in value
                c.text(
                    value,
                    46,
                    theme.GREEN if good else theme.YELLOW,
                    bold=True,
                    midright=(card[0] + card_w - c.px(36), ry),
                )
            if i:
                pygame.draw.line(
                    c.screen,
                    theme.BORDER,
                    (card[0] + c.px(24), ry - row_h // 2),
                    (card[0] + card_w - c.px(24), ry - row_h // 2),
                    c.px(1),
                )
        left = max(0.0, state.until - self._monotonic())
        bar = (cx - card_w // 2, card[1] + card[3] + c.px(36), card_w, c.px(10))
        c.progress(bar, left / DONE_SECONDS, theme.GREEN)

    def _draw_problem(self, state: TechnicalProblem, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        cx = x0 + w // 2
        buttons_h = c.px(124)
        card_w = min(w, c.px(1100))
        lines = c.lines(state.reason, 30, card_w - c.px(80), 4)
        card_h = c.px(56 + 40 * len(lines))
        block = c.px(310) + card_h + c.px(48) + buttons_h
        top = y0 + max(0, (h - block) // 2)
        c.disc((cx, top + c.px(70)), 70, theme.mix(theme.YELLOW, theme.BG, 0.2))
        c.icon("warning", (cx, top + c.px(70)), c.px(84), theme.YELLOW)
        c.text(texts.PROBLEM_TITLE, 72, theme.TEXT, bold=True, center=(cx, top + c.px(190)))
        c.text(texts.PROBLEM_HINT, 30, theme.MUTED, center=(cx, top + c.px(256)))
        card = (cx - card_w // 2, top + c.px(310), card_w, card_h)
        c.card(card, theme.SURFACE, border=theme.BORDER)
        for i, line in enumerate(lines):
            c.text(line, 30, theme.TEXT, topleft=(card[0] + c.px(40), card[1] + c.px(28 + i * 40)))
        by = card[1] + card_h + c.px(48)
        bw = (card_w - c.px(32)) // 2
        self._button(
            (cx - card_w // 2, by, bw, buttons_h),
            texts.RETRY_BUTTON,
            self._machine.retry,
            primary=True,
            accent=theme.YELLOW,
            size=42,
        )
        self._button(
            (cx - card_w // 2 + bw + c.px(32), by, bw, buttons_h),
            texts.GIVE_UP_BUTTON,
            self._machine.give_up,
            size=42,
        )

    def _draw_blocked(self, state: Blocked, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        cx = x0 + w // 2
        top = y0 + c.px(30)
        c.disc((cx, top + c.px(70)), 70, theme.mix(theme.RED, theme.BG, 0.2))
        c.icon("cross", (cx, top + c.px(70)), c.px(76), theme.RED)
        c.text(texts.BLOCKED_TITLE, 76, theme.TEXT, bold=True, center=(cx, top + c.px(200)))
        c.text(texts.BLOCKED_CALL, 34, theme.RED, bold=True, center=(cx, top + c.px(270)))
        card_w = min(w, c.px(1200))
        card = (cx - card_w // 2, top + c.px(330), card_w, c.px(260))
        c.card(card, theme.SURFACE, border=theme.RED)
        for i, line in enumerate(c.lines(state.message, 32, card_w - c.px(80), 5)):
            c.text(line, 32, theme.TEXT, topleft=(card[0] + c.px(40), card[1] + c.px(32 + i * 44)))
        c.text(texts.BLOCKED_HINT, 26, theme.MUTED, center=(cx, y0 + h - c.px(20)))

    def _draw_rejected(self, state: RejectedList, content: Rect) -> None:
        c = self._canvas
        x0, y0, w, h = content
        c.text(texts.REJECTED_TITLE, 52, theme.TEXT, bold=True, topleft=(x0, y0 + c.px(6)))
        c.text(texts.REJECTED_HINT, 26, theme.MUTED, topleft=(x0, y0 + c.px(70)))
        buttons_h = c.px(110)
        table = (x0, y0 + c.px(120), w, h - c.px(120) - buttons_h - c.px(30))
        c.card(table, theme.SURFACE, border=theme.BORDER)
        if not state.items:
            c.text(
                texts.REJECTED_EMPTY,
                36,
                theme.MUTED,
                center=(x0 + w // 2, table[1] + table[3] // 2),
            )
        cols = (x0 + c.px(40), x0 + round(w * 0.16), x0 + round(w * 0.40))
        header_y = table[1] + c.px(34)
        for label, cx in zip(texts.REJECTED_COLUMNS, cols, strict=True):
            c.text(label, 22, theme.MUTED, bold=True, midleft=(cx, header_y))
        row_h = c.px(56)
        for i, item in enumerate(state.items[:8]):
            ry = table[1] + c.px(86) + i * row_h
            pygame.draw.line(
                c.screen,
                theme.BORDER,
                (table[0] + c.px(20), ry - row_h // 2),
                (table[0] + w - c.px(20), ry - row_h // 2),
                c.px(1),
            )
            c.text(item.session_id[:8], 26, theme.TEXT, midleft=(cols[0], ry))
            c.text(
                c.fit(", ".join(item.codes), 26, cols[2] - cols[1] - c.px(20)),
                26,
                theme.TEXT,
                midleft=(cols[1], ry),
            )
            c.text(
                c.fit(item.error, 26, table[0] + w - cols[2] - c.px(40)),
                26,
                theme.YELLOW,
                midleft=(cols[2], ry),
            )
        by = y0 + h - buttons_h
        if state.exported_to:
            c.text(
                c.fit(texts.exported_to(state.exported_to), 24, w // 2),
                24,
                theme.GREEN,
                midleft=(x0, by + buttons_h // 2),
            )
        bw = c.px(420)
        self._button(
            (x0 + w - 2 * bw - c.px(24), by, bw, buttons_h),
            texts.EXPORT_BUTTON,
            self._machine.export_rejected,
            primary=True,
            accent=theme.GREEN,
            size=36,
        )
        self._button(
            (x0 + w - bw, by, bw, buttons_h),
            texts.BACK_BUTTON,
            self._machine.close_rejected,
            size=36,
        )
