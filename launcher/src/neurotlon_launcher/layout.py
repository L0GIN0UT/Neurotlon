"""Чистые помощники раскладки экрана: без pygame, проверяются юнит-тестами."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

Rect = tuple[int, int, int, int]  # x, y, ширина, высота
Color = tuple[int, int, int]

GRAY: Color = (150, 150, 150)
WHITE: Color = (245, 245, 245)
DARK: Color = (24, 26, 32)
RED: Color = (235, 90, 90)
YELLOW: Color = (240, 200, 60)
GREEN: Color = (70, 170, 110)
DEFAULT_TEAM_COLOR: Color = (110, 110, 120)


def wrap_text(text: str, max_width: int, measure: Callable[[str], int]) -> list[str]:
    """Разбить по словам так, чтобы каждая строка влезала в `max_width`.

    Слово шире строки остаётся на отдельной строке целиком.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and measure(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def fit_rect(src_w: int, src_h: int, box: Rect) -> Rect:
    """Вписать картинку `src_w` на `src_h` в `box`, сохранив пропорции, по центру."""
    x, y, w, h = box
    if src_w <= 0 or src_h <= 0:
        return (x, y, 0, 0)
    scale = min(w / src_w, h / src_h)
    out_w, out_h = int(src_w * scale), int(src_h * scale)
    return (x + (w - out_w) // 2, y + (h - out_h) // 2, out_w, out_h)


def parse_hex_color(value: str | None) -> Color:
    """`#rrggbb` → (r, g, b); пусто или мусор — нейтральный серый."""
    if value and len(value) == 7 and value[0] == "#":
        try:
            return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
        except ValueError:
            pass
    return DEFAULT_TEAM_COLOR


def contains(rect: Rect, point: tuple[int, int]) -> bool:
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


@dataclass(frozen=True)
class Button:
    label: str
    rect: Rect
    action: Callable[[], None]
    primary: bool = False

    def hit(self, point: tuple[int, int]) -> bool:
        return contains(self.rect, point)


def button_row(screen_w: int, screen_h: int, count: int) -> list[Rect]:
    """Ряд из `count` равных кнопок внизу экрана."""
    gap = screen_w // 40
    width = min(screen_w // 3, (screen_w - gap * (count + 1)) // max(count, 1))
    height = screen_h // 9
    total = width * count + gap * (count - 1)
    left = (screen_w - total) // 2
    top = screen_h - height - screen_h // 8
    return [(left + i * (width + gap), top, width, height) for i in range(count)]
