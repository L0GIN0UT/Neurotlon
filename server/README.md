# Сервер Нейротлона

API, база данных, расчёт очков, поток табло. Python 3.12, FastAPI, SQLAlchemy + Alembic, SQLite (WAL).

## База данных

Адрес базы — переменная `NEUROTLON_DATABASE_URL` (по умолчанию `sqlite:///./neurotlon.db`).

Применить миграции (из корня репозитория):

```bash
uv run alembic -c server/alembic.ini upgrade head
```

Откатить всё: `uv run alembic -c server/alembic.ini downgrade base`.

Первая миграция создаёт таблицы, триггеры «журнал аудита только на добавление» и три дисциплины
(длительности 120 и 300 с — временные значения, меняются в админке).

## Первый суперпользователь

После миграций (из корня репозитория):

```bash
uv run neurotlon-server create-superuser --login root
```

Пароль (не короче 8 символов) запрашивается интерактивно, в аргументах командной строки его нет.
Остальные аккаунты (админ, судья, волонтёры) и станции создаёт суперпользователь через API
(`POST /api/v1/users`, `POST /api/v1/stations`). Сессия входа живёт 24 часа
(`NEUROTLON_SESSION_TTL_SECONDS`); cookie `Secure`, поэтому вход работает только по HTTPS.
После 5 неудачных входов логин блокируется на 5 минут (так задумано для локальной сети).

## Проверки

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```
