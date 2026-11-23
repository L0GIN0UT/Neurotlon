"""Интерфейс лаунчера: все тексты по-русски в одном месте."""

from __future__ import annotations

TITLE = "Нейротлон"
BRAND = "НЕЙРОТЛОН"
BRAND_SUB = "BCI Samara-2027"
DISCIPLINE_NAMES = {"darts": "Дартс", "football": "Футбол", "pong": "Понг"}

# Связь
ONLINE = "Связь есть"
OFFLINE = "Нет связи"
LINK_UNKNOWN = "Проверяем связь"

# Ввод ID
SCAN_PROMPT = "Покажите QR-код бейджа камере"
SCAN_PROMPT_PONG = ("Игрок 1: покажите QR-код бейджа", "Игрок 2: покажите QR-код бейджа")
TYPE_HINT = "или введите номер бейджа"
INPUT_LABEL = "ID"
NO_CAMERA = "Камера недоступна"
NO_CAMERA_HINT = "Введите номер бейджа справа"
CAMERA_STARTING = "Запускаем камеру…"
ID_PLACEHOLDER = "NT07"
NEXT_BUTTON = "Далее"
BAD_CODE = "Это не похоже на ID. Пример: NT07 или просто 7"
UNKNOWN_PARTICIPANT = "Участник с таким ID не найден"
ALREADY_PICKED = "Этот участник уже выбран, нужен другой игрок"
UNAUTHORIZED = "Станция не авторизована: проверьте токен станции"


def server_error(detail: str) -> str:
    return f"Ошибка сервера: {detail}"


# Проверка и подтверждение
CHECKING = "Проверяем участника…"
OFFLINE_WARNING = "Нет связи с сервером: проверка не выполнена, результат отправится позже"
CONFIRM_BUTTON = "Это я — начать"
CONFIRM_NEXT_BUTTON = "Это я — дальше"
CANCEL_BUTTON = "Это не я"
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


SLOT_WAITING = "ждём бейдж"
PLAYER_SLOT = ("Игрок 1", "Игрок 2")


# Игра
STARTING = "Запускаем игру…"
STARTING_HINT = "Подключаем датчики, это займёт несколько секунд"
PLAYING = "Идёт игра"
PLAYING_HINT = "Следуйте подсказкам на экране игры"
PLAYING_OFFLINE = "Нет связи с сервером: результат отправится позже"
LIMIT_DEFAULT = "Лимит очков не получен с сервера, используется 10"

# Итог
DONE_TITLE = "Готово!"
DONE_HINT = "Результат сохранён"
DONE_POINTS = "очк."
DONE_GIVE_UP = "Отмечено: не пройдено"


def points_line(code: str, points: int | None, outcome: str) -> str:
    if outcome != "completed" or points is None:
        return f"{code}: не пройдено"
    return f"{code}: {points} очк."


# Техническая проблема
PROBLEM_TITLE = "Техническая проблема"
PROBLEM_HINT = "Позовите волонтёра. Можно повторить игру или отметить «не пройдено»."
RETRY_BUTTON = "Повторить"
GIVE_UP_BUTTON = "Не пройдено"

# Подвал
QUEUE_LINE = "Ждут отправки: {n}"
REJECTED_LINE = "Не принято сервером: {n}"

# Восстановление
RESTARTED = "Лаунчер был перезапущен во время игры, результата нет"

# Блокировка и отклонённые результаты
BLOCKED_TITLE = "Стенд остановлен"
BLOCKED_HINT = "Исправьте launcher.toml или станцию в админке и перезапустите лаунчер (Ctrl+Q)"
BLOCKED_CALL = "Позовите организатора"


def discipline_mismatch(configured: str, on_server: str) -> str:
    return (
        f"Дисциплина в launcher.toml ({configured}) не совпадает "
        f"с дисциплиной станции на сервере ({on_server})"
    )


REJECTED_TITLE = "Отклонённые результаты"
REJECTED_EMPTY = "Отклонённых результатов нет"
REJECTED_HINT = "Покажите волонтёру или нажмите F2"
REJECTED_COLUMNS = ("Сессия", "Участники", "Причина")
EXPORT_BUTTON = "Экспорт в файл"
BACK_BUTTON = "Назад"


def exported_to(path: str) -> str:
    return f"Сохранено: {path}"


# Подсказки внизу экрана
HINT_IDLE = "Esc — стереть ввод   ·   F2 — отклонённые результаты   ·   Ctrl+Q — выход"
HINT_CONFIRM = "Enter — подтвердить   ·   Esc — отмена"
