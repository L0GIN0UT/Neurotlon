"""Окно моста (pygame-ce): эмулятор с клавишами или живые значения датчиков.

pygame импортируется лениво.
"""

from __future__ import annotations

from .emulator import EmulatedSource
from .keymap import HINTS, KEY_MAPS, logical_keys
from .source import CalibrationProgress, SignalSource

FPS = 60
TITLE_EMULATOR = "Эмулятор датчиков"
TITLE_HARDWARE = "Датчики"
STATE_TEXT = {
    "connecting": "подключение",
    "connected": "на связи",
    "disconnected": "нет связи",
    "emulated": "эмуляция",
}
REASON_TEXT = {
    "artifact": "артефакт",
    "no_contact": "нет контакта",
    "not_calibrated": "нет калибровки",
    "stale": "нет данных",
    "disconnected": "датчик отключён",
}


def calibration_text(progress: CalibrationProgress | None) -> str:
    if progress is None:
        return ""
    if progress.status == "running":
        text = f"калибровка {progress.step}: {progress.progress * 100:.0f}%"
        if progress.phase is not None and progress.phase_left_s is not None:
            action = "напрячь" if progress.phase == "tense" else "расслабить"
            text += f", {action} ещё {progress.phase_left_s:.1f} с"
        return text
    if progress.status == "done":
        return f"калибровка {progress.step}: готово"
    return f"калибровка {progress.step}: сбой ({progress.reason})"


def run_window(source: SignalSource, profile: str, *, keyboard: bool = True) -> None:
    """Главный цикл окна. Возвращается при закрытии окна.

    `keyboard=True` — эмулятор: клавиши -> источник (нужен `EmulatedSource`).
    `keyboard=False` — датчики: окно только показывает значения.
    """
    import pygame

    emulator: EmulatedSource | None = None
    if keyboard:
        if not isinstance(source, EmulatedSource):
            raise TypeError("управление с клавиатуры возможно только для эмулятора")
        emulator = source
    title = TITLE_EMULATOR if keyboard else TITLE_HARDWARE
    pygame.init()
    try:
        names = source.signals()
        hints = [HINTS[k] for k in dict.fromkeys(KEY_MAPS[profile].values())] if keyboard else []
        row_h = 50 if keyboard else 70
        screen = pygame.display.set_mode((460, 120 + row_h * len(names) + 24 * len(hints)))
        pygame.display.set_caption(title)
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
                elif keyboard and event.type == pygame.KEYDOWN:
                    pressed.add(pygame.key.name(event.key))
                elif keyboard and event.type == pygame.KEYUP:
                    pressed.discard(pygame.key.name(event.key))
                elif event.type == pygame.WINDOWFOCUSLOST:
                    pressed.clear()
            if emulator is not None:
                emulator.set_keys(logical_keys(profile, pressed))
                emulator.tick(dt_s)
            readings = source.read(0)

            screen.fill((24, 26, 32))
            screen.blit(font.render(f"{title} ({profile})", True, (235, 235, 235)), (16, 12))
            y = 56
            for name in names:
                reading = readings[name]
                color = (90, 190, 120) if reading.valid else (210, 80, 80)
                label = f"{name}: {reading.value:.2f}"
                if not reading.valid:
                    label += f" ({REASON_TEXT.get(reading.reason or '', reading.reason)})"
                screen.blit(small.render(label, True, (220, 220, 220)), (16, y))
                pygame.draw.rect(screen, (60, 64, 74), (16, y + 20, 428, 18))
                pygame.draw.rect(screen, color, (16, y + 20, int(428 * reading.value), 18))
                if not keyboard:
                    detail = [STATE_TEXT.get(source.state(name), source.state(name))]
                    level = source.battery(name)
                    if level is not None:
                        detail.append(f"заряд {level}%")
                    calib = calibration_text(source.calibration_status(name))
                    if calib:
                        detail.append(calib)
                    screen.blit(
                        small.render(", ".join(detail), True, (160, 165, 175)), (16, y + 42)
                    )
                y += row_h
            y += 10
            for hint in hints:
                screen.blit(small.render(hint, True, (160, 165, 175)), (16, y))
                y += 24
            pygame.display.flip()
    finally:
        pygame.quit()
