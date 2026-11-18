# Нейротлон

Система проведения мероприятия «Нейротлон BCI Samara-2027» в зале: участники, жеребьёвка, пары, приём результатов со стендов и планшетов, расчёт очков и табло. Работает в локальной сети без интернета.

## Начало работы

Нужны [uv](https://docs.astral.sh/uv/) и Node.js 24.

```
git config core.hooksPath .githooks
uv sync
cd web && npm ci
```

Проверки (то же, что в CI):

```
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd web && npm run lint && npm run typecheck && npm test
```

Хук `commit-msg` запрещает коммиты с соавторством Claude / Anthropic. Правила для разработки и для Claude Code — в [CLAUDE.md](CLAUDE.md).

## Документация

- [Архитектура](docs/architecture.md) — схемы зала, сервисов, стенда, процессов, модели данных, статусов и расчёта очков
- [Принятые решения](docs/decisions.md) — отличия от ТЗ и открытые вопросы
- [Роадмап](docs/roadmap.md) — этапы работ
- [Как подключить игру](games/README.md) — SDK для pygame-ce, кит для Unity, проверка `neurotlon-game-check`
