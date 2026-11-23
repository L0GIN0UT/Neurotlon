"""Заготовки для глубины картинки: градиенты, свечение, мягкие тени, скругление.

Всё строится из маленьких поверхностей, растянутых `smoothscale` (билинейная интерполяция
даёт градиент или размытие почти даром). Результаты кэшируются вызывающим кодом.
"""

from __future__ import annotations

import pygame

from . import theme
from .layout import Color


def gradient(size: tuple[int, int], tl: Color, tr: Color, bl: Color, br: Color) -> pygame.Surface:
    """Плавный градиент между четырьмя углами."""
    tiny = pygame.Surface((2, 2))
    tiny.set_at((0, 0), tl)
    tiny.set_at((1, 0), tr)
    tiny.set_at((0, 1), bl)
    tiny.set_at((1, 1), br)
    return pygame.transform.smoothscale(tiny, size)


def glow(radius: int, color: Color, strength: float) -> pygame.Surface:
    """Круглое свечение для сложения с фоном (`BLEND_RGB_ADD`): ярко в центре, плавно в ноль."""
    steps = 48
    tiny = pygame.Surface((steps * 2, steps * 2))
    for i in range(steps, 0, -1):
        level = (1 - i / steps) ** 2 * strength
        pygame.draw.circle(
            tiny,
            (round(color[0] * level), round(color[1] * level), round(color[2] * level)),
            (steps, steps),
            i,
        )
    return pygame.transform.smoothscale(tiny, (radius * 2, radius * 2))


def soft_shadow(size: tuple[int, int], inset: int, radius: int, alpha: int) -> pygame.Surface:
    """Размытая тень: скруглённый прямоугольник отступает от краёв `size` на `inset` пикселей."""
    scale = 12
    small = pygame.Surface((max(2, size[0] // scale), max(2, size[1] // scale)), pygame.SRCALPHA)
    margin = max(1, inset // scale)
    pygame.draw.rect(
        small,
        (0, 0, 0, alpha),
        (margin, margin, small.get_width() - 2 * margin, small.get_height() - 2 * margin),
        border_radius=max(1, radius // scale),
    )
    return pygame.transform.smoothscale(small, size)


def rounded(surface: pygame.Surface, radius: int) -> pygame.Surface:
    """Скруглить углы картинки (результат с альфа-каналом)."""
    result = surface.convert_alpha()
    mask = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    result.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return result


def backdrop(size: tuple[int, int], accent: Color) -> pygame.Surface:
    """Фон экрана: тёмный градиент с цветным свечением дисциплины."""
    width, height = size
    base = gradient(
        size,
        theme.mix(accent, theme.BG, 0.20),
        theme.mix(accent, theme.BG, 0.08),
        theme.mix(accent, theme.BG, 0.03),
        theme.mix(accent, theme.BG, 0.10),
    )
    top = glow(round(height * 0.75), accent, 0.50)
    base.blit(
        top,
        (round(width * 0.86) - top.get_width() // 2, -top.get_height() // 3),
        special_flags=pygame.BLEND_RGB_ADD,
    )
    low = glow(round(height * 0.55), accent, 0.22)
    base.blit(
        low,
        (-low.get_width() // 3, height - low.get_height() * 2 // 3),
        special_flags=pygame.BLEND_RGB_ADD,
    )
    return base


def banner(size: tuple[int, int], color: Color, radius: int) -> pygame.Surface:
    """Баннер участника: цвет команды слева плавно уходит в тёмное, низ затемнён под текст."""
    width, height = size
    base = gradient(
        size,
        theme.mix(color, theme.BG, 0.80),
        theme.mix(color, theme.BG, 0.22),
        theme.mix(color, theme.BG, 0.50),
        theme.mix(color, theme.BG, 0.10),
    )
    shade = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(0, height, 2):
        alpha = round(150 * (y / height) ** 2)
        pygame.draw.line(shade, (0, 0, 0, alpha), (0, y), (width, y), 2)
    base.blit(shade, (0, 0))
    return rounded(base, radius)
