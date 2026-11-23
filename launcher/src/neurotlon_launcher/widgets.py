"""Рисование элементов интерфейса на pygame: карточки, кнопки, чипы, значки, индикаторы.

Здесь нет логики стенда, только внешний вид. Все размеры задаются в единицах `Canvas.px`
(1/1080 высоты экрана), значки рисуются линиями без картинок: офлайн и без лицензий.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pygame

from . import theme
from .layout import Button, Color, Rect

FONT_CANDIDATES = "segoeui,arial,dejavusans,liberationsans,freesans"


class Canvas:
    """Поверхность с набором примитивов в единой теме."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.width, self.height = screen.get_size()
        self._unit = theme.scale(self.height)
        self._fonts: dict[tuple[int, bool], pygame.font.Font] = {}

    def px(self, value: float) -> int:
        return max(1, round(value * self._unit))

    def font(self, size: float, bold: bool = False) -> pygame.font.Font:
        key = (self.px(size), bold)
        if key not in self._fonts:
            self._fonts[key] = pygame.font.SysFont(FONT_CANDIDATES, key[0], bold=bold)
        return self._fonts[key]

    # --- текст --------------------------------------------------------------------------

    def text(
        self,
        value: str,
        size: float,
        color: Color = theme.TEXT,
        *,
        bold: bool = False,
        **anchor: tuple[int, int],
    ) -> Rect:
        """Нарисовать строку; `anchor` — например `center=(x, y)` или `topleft=(x, y)`."""
        surface = self.font(size, bold).render(value, True, color)
        rect = surface.get_rect(**anchor)
        self.screen.blit(surface, rect)
        return rect.x, rect.y, rect.w, rect.h

    def measure(self, value: str, size: float, bold: bool = False) -> int:
        return self.font(size, bold).size(value)[0]

    def fit(self, value: str, size: float, max_width: int, bold: bool = False) -> str:
        """Обрезать строку многоточием, если она шире `max_width`."""
        font = self.font(size, bold)
        if font.size(value)[0] <= max_width:
            return value
        while len(value) > 1 and font.size(value + "…")[0] > max_width:
            value = value[:-1]
        return value + "…"

    def wrap(self, value: str, size: float, max_width: int, bold: bool = False) -> list[str]:
        from .layout import wrap_text

        font = self.font(size, bold)
        return wrap_text(value, max_width, lambda s: font.size(s)[0])

    # --- плашки -------------------------------------------------------------------------

    def card(
        self,
        rect: Rect,
        fill: Color = theme.SURFACE,
        *,
        border: Color | None = None,
        radius: float = 28,
        border_width: float = 3,
    ) -> None:
        pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(radius))
        if border is not None:
            pygame.draw.rect(
                self.screen,
                border,
                rect,
                width=self.px(border_width),
                border_radius=self.px(radius),
            )

    def chip(
        self,
        label: str,
        color: Color,
        *,
        icon: str | None = None,
        size: float = 26,
        **anchor: tuple[int, int],
    ) -> Rect:
        """Плашка-метка: полупрозрачная заливка цвета и текст этого цвета."""
        pad, gap = self.px(18), self.px(10)
        icon_w = self.px(size) if icon else 0
        text_w = self.measure(label, size, bold=True)
        width = pad * 2 + icon_w + (gap if icon else 0) + text_w
        height = self.px(size * 1.9)
        rect = pygame.Rect(0, 0, width, height)
        setattr(rect, next(iter(anchor)), next(iter(anchor.values())))
        pygame.draw.rect(
            self.screen,
            theme.mix(color, theme.SURFACE, 0.18),
            rect,
            border_radius=height // 2,
        )
        x = rect.x + pad
        if icon:
            self.icon(icon, (x + icon_w // 2, rect.centery), icon_w, color)
            x += icon_w + gap
        self.text(label, size, color, bold=True, midleft=(x, rect.centery))
        return rect.x, rect.y, rect.w, rect.h

    def dot(self, center: tuple[int, int], radius: float, color: Color) -> None:
        pygame.draw.circle(self.screen, color, center, self.px(radius))

    # --- кнопки -------------------------------------------------------------------------

    def button(
        self,
        rect: Rect,
        label: str,
        action: Callable[[], None],
        *,
        primary: bool = False,
        accent: Color = theme.ACCENT,
        icon: str | None = None,
        size: float = 40,
        pressed: bool = False,
        dim: bool = False,
    ) -> Button:
        fill = accent if primary else theme.SURFACE_HI
        text_color = theme.on_color(fill)
        if dim:
            fill, text_color = theme.SURFACE, theme.BORDER
        elif pressed:
            fill = theme.mix(theme.TEXT, fill, 0.22)
        radius = self.px(24)
        pygame.draw.rect(self.screen, fill, rect, border_radius=radius)
        if not primary and not dim:
            pygame.draw.rect(
                self.screen, theme.BORDER, rect, width=self.px(2), border_radius=radius
            )
        x, y, w, h = rect
        center_y = y + h // 2
        if icon and label:
            icon_size = self.px(size)
            label_w = self.measure(label, size, bold=True)
            total = icon_size + self.px(14) + label_w
            left = x + (w - total) // 2
            self.icon(icon, (left + icon_size // 2, center_y), icon_size, text_color)
            self.text(
                label,
                size,
                text_color,
                bold=True,
                midleft=(left + icon_size + self.px(14), center_y),
            )
        elif icon:
            self.icon(icon, (x + w // 2, center_y), self.px(size), text_color)
        else:
            self.text(label, size, text_color, bold=True, center=(x + w // 2, center_y))
        return Button(label or (icon or ""), rect, action, primary)

    # --- индикаторы ---------------------------------------------------------------------

    def spinner(self, center: tuple[int, int], radius: float, now_ms: int, color: Color) -> None:
        """Кольцо из точек, яркая «голова» бежит по кругу."""
        count = 12
        head = (now_ms // 90) % count
        r = self.px(radius)
        for i in range(count):
            age = (head - i) % count
            angle = 2 * math.pi * i / count - math.pi / 2
            fade = 1 - age / count
            point = (round(center[0] + r * math.cos(angle)), round(center[1] + r * math.sin(angle)))
            pygame.draw.circle(
                self.screen,
                theme.mix(color, theme.BG, 0.15 + 0.85 * fade),
                point,
                self.px(radius / 7),
            )

    def progress(self, rect: Rect, fraction: float, color: Color) -> None:
        radius = rect[3] // 2
        pygame.draw.rect(self.screen, theme.SURFACE_HI, rect, border_radius=radius)
        width = round(rect[2] * min(1.0, max(0.0, fraction)))
        if width > 0:
            pygame.draw.rect(
                self.screen,
                color,
                (rect[0], rect[1], max(width, rect[3]), rect[3]),
                border_radius=radius,
            )

    def corner_brackets(
        self, rect: Rect, color: Color, length: float = 70, width: float = 9
    ) -> None:
        """Уголки видоискателя вокруг области сканирования."""
        x, y, w, h = rect
        n, t = self.px(length), self.px(width)
        for cx, dx in ((x, 1), (x + w, -1)):
            for cy, dy in ((y, 1), (y + h, -1)):
                pygame.draw.line(self.screen, color, (cx, cy), (cx + dx * n, cy), t)
                pygame.draw.line(self.screen, color, (cx, cy), (cx, cy + dy * n), t)

    # --- значки -------------------------------------------------------------------------

    def icon(self, name: str, center: tuple[int, int], size: int, color: Color) -> None:
        """Значок в квадрате `size` пикселей вокруг `center`."""
        cx, cy = center
        s = size / 2
        w = max(2, size // 9)
        draw = pygame.draw
        surf = self.screen

        def p(x: float, y: float) -> tuple[int, int]:
            return (round(cx + x * s), round(cy + y * s))

        if name == "check":
            draw.lines(surf, color, False, [p(-0.6, 0.0), p(-0.2, 0.45), p(0.65, -0.45)], w)
        elif name == "cross":
            draw.line(surf, color, p(-0.5, -0.5), p(0.5, 0.5), w)
            draw.line(surf, color, p(0.5, -0.5), p(-0.5, 0.5), w)
        elif name == "warning":
            draw.polygon(surf, color, [p(0, -0.9), p(0.95, 0.75), p(-0.95, 0.75)], w)
            draw.line(surf, color, p(0, -0.25), p(0, 0.22), w)
            draw.circle(surf, color, p(0, 0.5), max(2, w // 2 + 1))
        elif name == "info":
            draw.circle(surf, color, center, round(s * 0.9), w)
            draw.line(surf, color, p(0, -0.05), p(0, 0.45), w)
            draw.circle(surf, color, p(0, -0.42), max(2, w // 2 + 1))
        elif name == "offline":
            for box in (0.9, 0.6, 0.3):
                rect = pygame.Rect(0, 0, round(2 * s * box), round(2 * s * box))
                rect.center = p(0, 0.45)
                draw.arc(surf, color, rect, math.radians(40), math.radians(140), w)
            draw.circle(surf, color, p(0, 0.45), max(2, w // 2 + 1))
            draw.line(surf, color, p(-0.8, -0.8), p(0.8, 0.9), w)
        elif name == "dot":
            draw.circle(surf, color, center, round(s * 0.5))
        elif name == "backspace":
            draw.polygon(
                surf,
                color,
                [p(-0.95, 0), p(-0.45, -0.7), p(0.95, -0.7), p(0.95, 0.7), p(-0.45, 0.7)],
                w,
            )
            draw.line(surf, color, p(-0.1, -0.28), p(0.5, 0.28), w)
            draw.line(surf, color, p(0.5, -0.28), p(-0.1, 0.28), w)
        elif name == "arrow":
            draw.line(surf, color, p(-0.8, 0), p(0.8, 0), w)
            draw.lines(surf, color, False, [p(0.2, -0.6), p(0.8, 0), p(0.2, 0.6)], w)
        elif name == "darts":
            for factor in (0.95, 0.6, 0.25):
                draw.circle(surf, color, center, round(s * factor), w if factor > 0.3 else 0)
        elif name == "football":
            draw.circle(surf, color, center, round(s * 0.95), w)
            pentagon = [
                p(0.38 * math.sin(i * 2 * math.pi / 5), -0.38 * math.cos(i * 2 * math.pi / 5))
                for i in range(5)
            ]
            draw.polygon(surf, color, pentagon)
        elif name == "pong":
            draw.rect(
                surf, color, (*p(-0.95, -0.6), max(3, w), round(s * 1.2)), border_radius=w // 2
            )
            draw.rect(
                surf, color, (*p(0.95, -0.6), max(3, w), round(s * 1.2)), border_radius=w // 2
            )
            draw.rect(surf, color, (*p(-0.12, -0.12), round(s * 0.28), round(s * 0.28)))
        else:
            raise ValueError(f"unknown icon: {name}")

    def disc(self, center: tuple[int, int], radius: float, fill: Color) -> None:
        pygame.draw.circle(self.screen, fill, center, self.px(radius))

    def ring(self, center: tuple[int, int], radius: float, color: Color, width: float = 6) -> None:
        pygame.draw.circle(self.screen, color, center, self.px(radius), self.px(width))
