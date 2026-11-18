# shared

Контракты между частями системы (этап M0):

- [`openapi.yaml`](openapi.yaml) — API «лаунчер / планшет → сервер»: проверка участника, начало сессии, результат, heartbeat;
- [`bridge-protocol.md`](bridge-protocol.md) и [`bridge-protocol.schema.json`](bridge-protocol.schema.json) — протокол «BCI-мост ↔ игра»: сигналы 0…1, состояние датчиков, калибровка;
- [`game-launch.md`](game-launch.md) и [`game-launch.schema.json`](game-launch.schema.json) — запуск игры лаунчером и результат игры; игра может быть на pygame-ce, Unity или другом движке;
- [`participant-code.md`](participant-code.md) — формат ID, содержимое QR, нормализация ручного ввода; проверочные примеры в [`participant-code.cases.json`](participant-code.cases.json).

Проверка: `uv run pytest shared` — схемы валидны, примеры из документов проходят их.
