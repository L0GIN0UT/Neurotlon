"""Окно «Эмулятор датчиков» (pygame-ce). pygame импортируется лениво."""

from __future__ import annotations

from .emulator import EmulatedSource
from .keymap import HINTS, KEY_MAPS, logical_keys

FPS = 60
TITLE = "Эмулятор датчиков"


def run_window(source: EmulatedSource, profile: str) -> None:
    """Главный цикл окна: клавиши -> источник. Возвращается при закрытии окна."""
    import pygame

    pygame.init()
    try:
        names = source.signals()
        hints = [HINTS[k] for k in dict.fromkeys(KEY_MAPS[profile].values())]
        screen = pygame.display.set_mode((460, 120 + 50 * len(names) + 24 * len(hints)))
        pygame.display.set_caption(TITLE)
        font = pygame.font.Font(None, 28)
        small = pygame.font.Font(None, 22)
        clock = pygame.time.Clock()
        pressed: set[str] = set()
        running = True
        while running:
            dt_s = clock.tick(FPS) / 1000
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    pressed.add(pygame.key.name(event.key))
                elif event.type == pygame.KEYUP:
                    pressed.discard(pygame.key.name(event.key))
                elif event.type == pygame.WINDOWFOCUSLOST:
                    pressed.clear()
            source.set_keys(logical_keys(profile, pressed))
            source.tick(dt_s)
            readings = source.read(0)

            screen.fill((24, 26, 32))
            screen.blit(font.render(f"{TITLE} ({profile})", True, (235, 235, 235)), (16, 12))
            y = 56
            for name in names:
                reading = readings[name]
                color = (90, 190, 120) if reading.valid else (210, 80, 80)
                label = f"{name}: {reading.value:.2f}"
                if not reading.valid:
                    label += f" ({reading.reason})"
                screen.blit(small.render(label, True, (220, 220, 220)), (16, y))
                pygame.draw.rect(screen, (60, 64, 74), (16, y + 20, 428, 18))
                pygame.draw.rect(screen, color, (16, y + 20, int(428 * reading.value), 18))
                y += 50
            y += 10
            for hint in hints:
                screen.blit(small.render(hint, True, (160, 165, 175)), (16, y))
                y += 24
            pygame.display.flip()
    finally:
        pygame.quit()
