# Игры

Дартс, футбол и понг. Механика игр ещё не придумана, поэтому здесь лежит всё, кроме геймплея: запуск, датчики, калибровка, таймер и отправка результата уже сделаны. Игру можно писать на pygame-ce (Python) или на Unity, одной командой проверяется, что она встанет на стенд.

## Как подключить игру

### Контракт простыми словами

Игра — любой исполняемый файл. Лаунчер запускает его как `<команда> --launch <путь к launch.json>` и ждёт `result.json`. Полное описание: [`shared/game-launch.md`](../shared/game-launch.md), схемы лежат рядом.

1. **Читает `launch.json`**: `session_id`, `discipline`, `duration_s`, участники (в понге у каждого `side`: `left` или `right`), адрес моста, `result_path`; необязательное `max_points` — лимит очков за секцию (дартс, футбол): `ResultWriter` не запишет `points` больше, у понга поля нет. `points` — целое число (решение 28): `completed()` и `ResultWriter` отклоняют дробное, проверка даёт FAIL.
2. **Подключается к BCI-мосту** ([`shared/bridge-protocol.md`](../shared/bridge-protocol.md)) и берёт значения сигналов 0…1. Значение может быть недействительным (артефакт, нет контакта): тогда очков не давать.
3. **Калибрует датчики**: ЭМГ 5 с покоя и 12 с «сжать / отпустить» (3 раза по 3 с с паузой 1 с), ЭЭГ 8 с с закрытыми глазами. Показывает игроку инструкцию. Сбой шага — один повтор, потом `aborted`.
4. **Играет `duration_s` секунд** и по истечении завершается с текущими очками.
5. **Пишет `result.json`** во временный файл и переименовывает его: `finished` с записью на каждого участника или `aborted` с причиной. В понге ровно один победитель (`wins`: 1 и 0).
6. **Выходит с кодом 0.**

Также: Esc — прервать с подтверждением; датчик пропал — пауза, через 30 с `aborted`; в игре нет ФИО и других данных, кроме `code` и `display_name`.

### Путь Python (pygame-ce)

Пакет `neurotlon_games.sdk` берёт на себя пункты 1–6 и всё из «также». Игровой код — три метода:

```python
from collections.abc import Sequence

import pygame
from neurotlon_games.sdk import GameApp, LaunchInfo, ResultEntry, Signals, completed, run_game


class MyDarts(GameApp):
    def update(self, dt: float, signals: Signals) -> None:
        force = signals.value("emg")  # float 0..1 или None, если сигнала сейчас нет
        relax = signals.value("eeg")
        # здесь механика

    def draw(self, surface: pygame.Surface) -> None:
        # картинка; таймер и подсказки рисует GameApp
        surface.fill((0, 0, 0))

    def result(self) -> Sequence[ResultEntry]:
        return [completed(self.launch.participants[0].code, points)]


if __name__ == "__main__":
    raise SystemExit(run_game(MyDarts))
```

Начните с готового шаблона [`neurotlon_games/template.py`](src/neurotlon_games/template.py): шкала сигнала, очки копятся при значении выше 0,6; работает для дартса, футбола и понга. Скопируйте его, замените `update`, `draw` и `result`.

- Запуск без лаунчера: `uv run python -m neurotlon_games.template --launch путь\к\launch.json --windowed`.
- Понг: сторона игрока — `participant.side`, его сигнал — `launch.signal_of(participant)` (`emg_left` / `emg_right`).
- Очки — число от 0 до 1000. `wins` только в понге.
- Юнит-тесты игры без моста: `neurotlon_games.sdk.testing` (`FakeBridge`, `make_launch`, `make_signals`).

### Путь Unity

Папка [`unity/NeurotlonKit/`](unity/NeurotlonKit/README.md): локальный UPM-пакет без внешних зависимостей. Пошаговая инструкция (пакет, сцена, настройки сборки Windows, запуск с эмулятором) — в [README кита](unity/NeurotlonKit/README.md). Компонент `NeurotlonGame` делает то же, что `GameApp`, геймплей переопределяется в трёх методах.

### Запуск с эмулятором

Датчики для разработки не нужны. Мост с эмулятором открывает окно, значения задаются клавишами (подсказки в окне):

```
uv run neurotlon-bridge --emulate --profile darts     # дартс и футбол: eeg + emg
uv run neurotlon-bridge --emulate --profile pong      # понг: emg_left + emg_right
```

Затем игра с `launch.json` (пример — в `shared/game-launch.md`; порт моста по умолчанию 8765).

### Проверка: `neurotlon-game-check`

Одна команда говорит, годится ли игра для стенда. Она поднимает эмулированный мост, сама двигает сигналы, запускает игру тем же кодом, что лаунчер (тот же таймаут `duration_s + 120 с` и завершение всего дерева процессов), и проверяет результат теми же правилами, что лаунчер и сервер:

```
uv run neurotlon-game-check --discipline pong -- python -m neurotlon_games.template
uv run neurotlon-game-check --discipline darts -- games\darts\Darts.exe
```

Команда игры идёт после `--`; `--launch <путь>` добавит проверка. Вывод: строка на проверку и итог.

| Проверка | Что значит |
|---|---|
| запуск | процесс стартовал |
| мост | игра подключилась к мосту |
| калибровка | пройдены все шаги (WARN, если пропущены: на стенде калибровка обязательна) |
| выход | вышла с кодом 0 за `duration_s` + запас |
| result.json | файл есть и проходит схему |
| session_id | совпадает с `launch.json` |
| статус, записи | `finished`, участники те же, целые `points` и `wins` по правилам сервера |
| победитель | только понг: ровно один |

Код выхода 0 только если нет ни одного `FAIL`; `WARN` не мешает. При `duration_s` = 10 проверка идёт около 20 секунд.

Полезные флаги: `--duration-s N` (от 10), `--max-points N` (положить `max_points` в `launch.json`; очки выше N дадут FAIL в проверке «записи»), `--keep ПАПКА` (оставить `launch.json`, `result.json`, `game.log`), `--abort-test` (оборвать мост и посмотреть, прервётся ли игра; необязательно, итог только `WARN` или `PASS`). Остальные: `neurotlon-game-check --help`. Для игр на `GameApp` флаг `--time-scale 5` ускоряет таймеры (переменная `NEUROTLON_TIME_SCALE`, только для проверок).

### Подключение к стенду

В `launcher.toml` на стенде (см. [`launcher/README.md`](../launcher/README.md)):

```toml
[game]
command = ["python", "-m", "neurotlon_games.darts"]   # pygame-ce
# command = ["games/darts/Darts.exe"]                  # Unity
# workdir = "games/darts"
```

Лаунчер допишет `--launch <путь>`. Мост на стенде запускается отдельно (`start-bridge.cmd`), игре нужен только его адрес из `launch.json`.

### Чек-лист перед мероприятием

- [ ] `neurotlon-game-check` проходит без `FAIL` для каждой дисциплины на том ПК, где будет стенд.
- [ ] Нет `WARN` про калибровку: игра проходит все шаги.
- [ ] Игра запущена с настоящими датчиками из лаунчера: значения двигаются, калибровка проходит.
- [ ] Выдернуть датчик в игре: пауза, через 30 с `aborted`; вернуть датчик в течение 30 с: игра продолжается.
- [ ] Esc во время игры спрашивает подтверждение; после подтверждения лаунчер показывает «Техническая проблема».
- [ ] Полный круг со стендом: скан QR, игра, результат на табло.
- [ ] Очки считаются по утверждённой методике (до её появления в игре стоят настройки по умолчанию).
- [ ] Игра запускается без интернета и без установки чего-либо поверх (шрифты и ресурсы внутри сборки).
- [ ] `.exe` или команда прописаны в `launcher.toml`, рабочая папка верная.
- [ ] Для понга проверены оба игрока: левый и правый датчик не перепутаны.
