"""Цвета и размеры интерфейса лаунчера. Без pygame: проверяется юнит-тестами.

Палитра совпадает с табло (тёмный фон #0b0f1a), чтобы стенд и экран зала выглядели одним целым.
Размеры задаются в «единицах»: 1 единица = 1/1080 высоты экрана, поэтому на 1080p это пиксели,
а в окне 1280x720 всё пропорционально уменьшается.
"""

from __future__ import annotations

from .layout import Color

BG: Color = (11, 15, 26)
SURFACE: Color = (21, 27, 44)
SURFACE_HI: Color = (35, 44, 70)
BORDER: Color = (58, 69, 102)
TEXT: Color = (241, 245, 255)
MUTED: Color = (159, 176, 214)
ACCENT: Color = (91, 140, 255)
GREEN: Color = (52, 211, 153)
YELLOW: Color = (242, 183, 5)
RED: Color = (240, 82, 79)

BASE_HEIGHT = 1080  # высота экрана, для которой заданы размеры

DISCIPLINE_GLYPHS = ("darts", "football", "pong")
# Каждой дисциплине свой цвет: им окрашены фон, шаги и акценты.
DISCIPLINE_ACCENTS: dict[str, Color] = {
    "darts": (255, 112, 67),
    "football": (46, 204, 113),
    "pong": (56, 189, 248),
}
PLAY_GREEN: Color = (74, 222, 128)  # кнопка «Играть», как в библиотеке Steam


def accent_for(discipline: str) -> Color:
    return DISCIPLINE_ACCENTS.get(discipline, ACCENT)


def mix(front: Color, back: Color, amount: float) -> Color:
    """Смешать цвета: `amount` 0 — только `back`, 1 — только `front`."""
    a = min(1.0, max(0.0, amount))
    return (
        round(front[0] * a + back[0] * (1 - a)),
        round(front[1] * a + back[1] * (1 - a)),
        round(front[2] * a + back[2] * (1 - a)),
    )


def luminance(color: Color) -> float:
    """Относительная яркость по WCAG, 0…1."""

    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = color
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: Color, b: Color) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def on_color(fill: Color) -> Color:
    """Цвет текста для заливки `fill`: тёмный или светлый, где контраст выше."""
    return BG if contrast(BG, fill) >= contrast(TEXT, fill) else TEXT


def readable_on_dark(color: Color) -> Color:
    """Цвет команды для текста на тёмном фоне: слишком тёмные цвета подсвечиваются."""
    lifted = color
    for step in range(1, 11):
        if contrast(lifted, SURFACE) >= 4.5:
            break
        lifted = mix(TEXT, color, step / 10)
    return lifted


def scale(height: int) -> float:
    return height / BASE_HEIGHT


def initials(name: str | None, code: str) -> str:
    """Буквы для круга-аватара: инициал имени или цифры кода (`NT07` → `07`)."""
    if name and name.strip():
        return name.strip()[:1].upper()
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits or code[:2].upper()
