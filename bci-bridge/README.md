# BCI-мост

Отдаёт играм сигналы датчиков по протоколу из `shared/bridge-protocol.md` (TCP `127.0.0.1:8765`, NDJSON).
Сейчас есть только эмулятор: значения задаются с клавиатуры. Реальные BrainBit и Callibri — следующий шаг M2.

## Запуск эмулятора

```
uv run neurotlon-bridge --emulate --profile darts
```

- `--profile darts|football|pong` — набор сигналов (по умолчанию `darts`);
- `--port 8765` — порт;
- `--headless` — без окна, значения не меняются (для проверки связи).

## Клавиши

| Профиль | Клавиша | Действие |
|---|---|---|
| darts, football | `W` / `S` | ЭЭГ: расслабление больше / меньше (0,5 в секунду) |
| darts, football | `A` (держать) | артефакт ЭЭГ |
| darts, football | Пробел (держать) | ЭМГ: сокращение |
| pong | левый `Shift` или `Q` | левая ЭМГ |
| pong | правый `Shift` или `P` | правая ЭМГ |

## Для игр

Игры импортируют только `neurotlon_bridge.client.BridgeClient`: `latest(signal)`, `calibrate(signal, step)`, `reset()`, `close()`.
Данные старше 500 мс приходят как `valid=False, reason="stale"`.
