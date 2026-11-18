# Neurotlon Kit для Unity

Готовые куски, чтобы в Unity-игре писать только геймплей: чтение `--launch`, клиент BCI-моста, калибровка, запись `result.json`. Без внешних пакетов, JSON — через `JsonUtility`. Контракт — [`shared/game-launch.md`](../../../shared/game-launch.md) и [`shared/bridge-protocol.md`](../../../shared/bridge-protocol.md); общая инструкция — [`games/README.md`](../../README.md).

Кит написан без возможности собрать C# в CI репозитория. Первая сборка в Unity — это и есть проверка: если что-то не компилируется, исправьте и сообщите команде.

| Файл | Что делает |
|---|---|
| `NeurotlonProtocol.cs` | Константы: сигналы, шаги калибровки, статусы. Сверяются со схемами тестом |
| `NeurotlonLaunch.cs` | Читает и проверяет `launch.json` из `--launch <путь>` |
| `NeurotlonBridge.cs` | Клиент моста: TCP в фоновом потоке, последнее значение сигнала, потеря связи, переподключение, команды `calibrate` / `reset` |
| `NeurotlonCalibration.cs` | Шаги калибровки по очереди, инструкции на русском, один повтор при сбое |
| `NeurotlonResult.cs` | Проверка правил и атомарная запись `result.json` (`finished` / `aborted`) |
| `NeurotlonGame.cs` | Пример `MonoBehaviour`: всё вместе плюс отсчёт, таймер, Esc, пауза при потере датчика |

## Подключение шаг за шагом

1. **Пакет.** Unity 2021.3 или новее. `Window → Package Manager → + → Add package from disk…` и выберите `games/unity/NeurotlonKit/package.json`. Либо скопируйте папку `NeurotlonKit` в `Packages/` проекта.
2. **Сцена.** Создайте пустой `GameObject`, добавьте компонент `NeurotlonGame` (или свой наследник). Камеру и графику делайте как обычно.
3. **Геймплей.** Наследуйтесь от `NeurotlonGame` и переопределите методы, остальное уже работает:

   ```csharp
   public class DartsGame : NeurotlonGame
   {
       protected override void OnGameStart() { /* игра началась после отсчёта */ }

       protected override void OnGameUpdate(float dt)
       {
           float? relax = Bridge.Value("eeg");   // null: сигнала сейчас нет, очков не давать
           float? force = Bridge.Value("emg");
           // ...ваша механика...
       }

       protected override IList<ResultEntryData> BuildResult()
       {
           return new List<ResultEntryData> { NeurotlonResult.Completed(Launch.Participants[0].code, points) };
       }
   }
   ```

   В понге игрок с `side == "left"` управляется сигналом `emg_left`, с `"right"` — `emg_right` (`Launch.SignalOf(participant)`). В `BuildResult` у обоих `wins`: 1 у победителя, 0 у проигравшего.
   В дартсе и футболе `points` не больше `Launch.MaxPoints` (лимит очков за секцию из `launch.json`, 0 — лимита нет): иначе `NeurotlonResult.WriteFinished` бросит `NeurotlonResultException`. В понге лимита нет. `points` — `int`: очки только целые.
4. **Настройки сборки** (`File → Build Settings`, `Player Settings`):
   - платформа **Windows**, Architecture x86_64, Mono или IL2CPP;
   - `Resolution and Presentation → Fullscreen Mode = Fullscreen Window`, `Run In Background` включён (кит включает его и из кода);
   - `Other Settings → Active Input Handling = Input Manager (Old)` или `Both`: кит читает Esc и Enter через `Input`;
   - `Resolution and Presentation → Display Resolution Dialog = Disabled`, иначе перед игрой появится окно выбора разрешения;
   - название `.exe` укажите в `launcher.toml` (`game.command`).
5. **Сборка.** `Build` в папку, например `games/darts/`. Рядом с `.exe` появятся `*_Data` и `UnityPlayer.dll`: копировать надо всю папку.

## Проверка с эмулятором

1. Запустите мост с эмулятором (откроется окно с подсказками клавиш): `uv run neurotlon-bridge --emulate --profile darts` (для понга `--profile pong`).
2. Создайте `launch.json`. Проще всего скопировать пример из `shared/game-launch.md` и поправить `result_path` на существующую папку.
3. Запустите игру: `Darts.exe --launch C:\путь\launch.json`. В редакторе аргументы не передать: задайте переменную окружения `NEUROTLON_LAUNCH=C:\путь\launch.json` до запуска Unity Hub / редактора.
4. Автоматическая проверка контракта, которую запускает и организатор перед событием:

   ```
   uv run neurotlon-game-check --discipline darts -- games\darts\Darts.exe
   ```

   Она поднимает эмулированный мост, запускает `.exe` так же, как лаунчер, и проверяет подключение, калибровку, выход вовремя и `result.json`.

## Правила, которые нельзя нарушать

- Время игры берите из `Launch.DurationSeconds`, не из своих констант. По истечении записывайте результат и выходите.
- Результат — только через `NeurotlonResult` (временный файл и переименование, правила как у сервера). Выход с кодом 0 (`Application.Quit(0)`).
- В игре не должно быть ФИО и любых данных, кроме `code` и `display_name`.
- Датчик потерян: пауза и ожидание, через 30 с `aborted`. Пример уже так делает.
- Мост читается в фоновом потоке, а разбирается в главном: вызывайте `Bridge.Pump()` каждый кадр (в `NeurotlonGame` это сделано).
