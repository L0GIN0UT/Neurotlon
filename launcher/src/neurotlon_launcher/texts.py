"""Тексты, которые ядро само отдаёт окну: ошибки и строки результата.

Подписи экранов лежат в web/src/station/texts.ts.
"""

from __future__ import annotations

BAD_CODE = "Это не похоже на ID. Пример: NT07 или просто 7"
UNKNOWN_PARTICIPANT = "Участник с таким ID не найден"
ALREADY_PICKED = "Этот участник уже выбран, нужен другой игрок"
BUSY = "Участник сейчас играет на другом стенде"
UNAUTHORIZED = "Станция не авторизована: проверьте токен станции"
SETUP_FAILED = "Не удалось проверить подключение: смотрите launcher.log"
SETUP_CHECK_FIRST = "Сначала нажмите «Проверить подключение»: сохранять можно только проверенное"
DISCIPLINE_UNKNOWN = (
    "Нет связи с сервером, а дисциплина станции ещё неизвестна: "
    "подключитесь к сети зала и запустите заново"
)
SENSORS_BRIDGE_BUSY = "Мост датчиков уже запущен: остановите его, затем нажмите «Искать снова»"
SENSORS_DISCOVERY_LOST = "Поиск датчиков остановился: нажмите «Искать снова»"
LAUNCH_FAILED = "Не удалось запустить игру: смотрите launcher.log"
RESTARTED = "Лаунчер был перезапущен во время игры, результата нет"


def sensors_discovery_failed(reason: str) -> str:
    return f"Не удалось запустить поиск датчиков: {reason}"


def server_error(detail: str) -> str:
    return f"Ошибка сервера: {detail}"


def points_line(code: str, points: int | None, outcome: str) -> str:
    if outcome != "completed" or points is None:
        return f"{code}: не пройдено"
    return f"{code}: {points} очк."


def discipline_mismatch(configured: str, on_server: str) -> str:
    return (
        f"Дисциплина в launcher.toml ({configured}) не совпадает "
        f"с дисциплиной станции на сервере ({on_server})"
    )
