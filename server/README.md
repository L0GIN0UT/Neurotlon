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

## Проверки

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```
