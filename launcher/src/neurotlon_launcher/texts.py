"""Интерфейс лаунчера: все тексты по-русски в одном месте."""

from __future__ import annotations

TITLE = "Нейротлон"

# Ввод ID
SCAN_PROMPT = "Покажите QR-код бейджа камере"
SCAN_PROMPT_PONG = ("Игрок 1 (слева): покажите QR-код бейджа", "Игрок 2 (справа): покажите QR-код")
TYPE_HINT = "Или введите ID с клавиатуры и нажмите Enter"
INPUT_LABEL = "ID"
NO_CAMERA = "Камера недоступна: вводите ID с клавиатуры"
BAD_CODE = "Это не похоже на ID. Пример: NT07 или просто 7"
UNKNOWN_PARTICIPANT = "Участник с таким ID не найден"
ALREADY_PICKED = "Этот участник уже выбран, нужен другой игрок"
UNAUTHORIZED = "Станция не авторизована: проверьте токен станции"


def server_error(detail: str) -> str:
    return f"Ошибка сервера: {detail}"


# Проверка и подтверждение
CHECKING = "Проверяем ID…"
OFFLINE_WARNING = "Нет связи с сервером: проверка не выполнена, результат отправится позже"
CONFIRM_BUTTON = "Это я — начать"
CANCEL_BUTTON = "Отмена"
CONFIRM_HINT = "Enter — начать, Esc — отмена"
TEAM_NONE = "Команда ещё не назначена"
BUSY = "Участник сейчас играет на другом стенде"
ISSUES = {
    "not_checked_in": "Нет отметки о регистрации",
    "already_completed": "Эту дисциплину уже проходил(а)",
    "busy_on_other_station": "Играет на другом стенде",
    "no_pair_assigned": "Не назначена пара",
}
ISSUES_TITLE = "Проверьте перед началом"


def team_line(number: int, name: str) -> str:
    return f"Команда {number}: {name}"


def side_line(index: int) -> str:
    return ("Слева", "Справа")[index]


# Игра
STARTING = "Запускаем игру…"
PLAYING = "Идёт игра"
PLAYING_OFFLINE = "Нет связи с сервером: результат отправится позже"

# Итог
DONE_TITLE = "Готово!"
DONE_GIVE_UP = "Отмечено: не пройдено"


def points_line(code: str, points: float | None, outcome: str) -> str:
    if outcome != "completed" or points is None:
        return f"{code}: не пройдено"
    return f"{code}: {points:g} очк."


# Техническая проблема
PROBLEM_TITLE = "Техническая проблема"
RETRY_BUTTON = "Повторить"
GIVE_UP_BUTTON = "Не пройдено"
PROBLEM_HINT = "Enter — повторить, Esc — не пройдено"

# Подвал
QUEUE_LINE = "Не отправлено: {n}"
REJECTED_LINE = "Сервер не принял результатов: {n} (см. data/outbox.db)"
