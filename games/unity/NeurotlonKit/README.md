# Neurotlon Kit для Unity

Готовые куски, чтобы в Unity-игре писать только геймплей: чтение `--launch`, клиент BCI-моста, калибровка, запись `result.json`. Без внешних пакетов, JSON — через `JsonUtility`. Контракт — [`shared/game-launch.md`](../../../shared/game-launch.md) и [`shared/bridge-protocol.md`](../../../shared/bridge-protocol.md); общая инструкция — [`games/README.md`](../../README.md).

Кит проверен в Unity 6000.6.9f1: компилируется без ошибок, собранный пример проходит `neurotlon-game-check` для дартса и понга. В CI Unity нет, поэтому после правок C# соберите пример и прогоните проверку вручную.

Unity-проект каждой игры лежит в `games/unity/<игра>/` и подключает кит как `"ru.neurotlon.kit": "file:../../NeurotlonKit"` в `Packages/manifest.json`. Файлы `.meta` кита хранятся в git: без них пакет по `file:` не подключится.

| Файл | Что делает |
|---|---|
| `NeurotlonProtocol.cs` | Константы: сигналы, шаги калибровки, статусы. Сверяются со схемами тестом |
| `NeurotlonLaunch.cs` | Читает и проверяет `launch.json` из `--launch <путь>` |
| `NeurotlonBridge.cs` | Клиент моста: TCP в фоновом потоке, последнее значение сигнала, события `burst`, возможности моста (`hello.features`), потеря связи, переподключение, команды `calibrate` / `reset` |
| `NeurotlonCalibration.cs` | Шаги калибровки по очереди (`cycle` или `rest` + `contract`, `baseline`), инструкции на русском, причина сбоя на экране, один повтор |
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

   Если игра может идти дольше таймера (золотой мяч в понге), переопределите `ExtendBeyondTime()` (вернуть `true`, пока игра не закончена) и завершите её сами через `FinishGame()`. Надпись после окончания — `FinishedMessage()`, текст таймера — `TimerText()`; если игра рисует таймер сама (в своей плашке), переопределите `DrawsOwnTimer` и верните `true`, тогда кит свой таймер не рисует.

   Обучение (порядок: калибровка, обучение, отсчёт, игра):
   - `TutorialSteps()` возвращает подсказки: по одной на механику (1-2 строки), игрок пробует механики по очереди. Каждая подсказка сначала 3 с крупно по центру (`NeurotlonTutorial.ReadSeconds`, механика не считается), потом компактная панель (`TutorialHintArea`: игра может увести её в свободное место) без затемнения.
   - `OnTutorialStepStart(i)` готовит песочницу шага (отдельные правила, очки не идут в результат); `OnTutorialTryStart(i)` зовётся, когда чтение закончилось и при каждом повторе: сбрасывайте счётчики условия; `OnTutorialUpdate(i, dt)` зовётся каждый кадр (картинка и камера живут и при чтении) и возвращает `true`, когда механика сработала (учитывается только пока `TutorialInPlay`); `DrawTutorial(i)` рисует игровые элементы под подсказкой; `OnTutorialEnd()` убирает песочницу.
   - Шаг: 20 с на попытку (`TutorialStepTimeout`), не получилось: шаг начинается заново, после двух неудач «Позовите волонтёра». Enter у волонтёра пропускает шаг (`TutorialStepSkippable`). Шаги-проверки («попади сам») возвращают `false`: их пропустить нельзя, заголовок «ПРОВЕРКА», при неудаче волонтёр может только завершить игру (Esc, Enter, причина `aborted`: «демо-проверка не пройдена»). Логика хода обучения без Unity: `NeurotlonTutorial`.
   - Общие формулировки (напрячь, расслабить, «мышца с датчиком») лежат в `NeurotlonTexts`; не пишите «рука», «кулак» и названия части тела в играх. Подпись счёта и поля под числа: `NeurotlonHud` (число растёт влево, без переноса).
   - Служебные параметры для показа: `--tutorial-min N` (шаг не засчитывается раньше N с).
   - Предохранители: подготовка (калибровка, обучение, отсчёт) не дольше `PrepLimitSeconds` (360 с), иначе `aborted`; вся игра не дольше `duration_s + HardLimitAfterDurationSeconds` (405 с), иначе результат пишется сразу. Лаунчер убивает игру на `duration_s + 420` с.

   Для своих надписей поверх картинки используйте `OutlinedLabel(rect, text, style)`: она рисует тёмную обводку, и текст читается на любом фоне (обводка гаснет вместе с надписью). Служебные экраны кита (калибровка, отсчёт, пауза, окончание) идут на затемнении экрана.

   Если бросок или удар идёт в точку прицела, возьмите `AimWobble` (`Runtime/NeurotlonAim.cs`, чистый C# без Unity): прицел гуляет по кругу, размах которого сужается с ростом сосредоточения. `new AimWobble(wobbleMax, wobbleMin, gamma, eegSmoothSeconds, random01)`, затем `Step(dt, eeg)` каждый кадр (`eeg` — `null`, если сигнала нет: размах не меняется) и чтение `X`, `Z`, `Amplitude`, `Concentration`. Её используют дартс и футбол.
   **Резкое сокращение (`burst`).** Дартс и футбол запускают бросок и удар по событию, а не по порогу уровня:

   ```csharp
   if (!Bridge.BurstSupported) { /* старый мост: запасной путь по уровню emg */ }
   if (!ReadyToThrow) Bridge.DiscardBursts("emg");        // каждый кадр, пока игра не готова: события не копятся
   else if (Bridge.TryTakeBurst("emg")) { /* бросок */ }  // забирает одно свежее событие
   ```

   - `bool TryTakeBurst(string signal)` — `true`, если есть свежее необработанное событие; забирает ровно одно. Событие старше `StaleSeconds` (0,5 с по времени получения) считается устаревшим и выбрасывается.
   - `void DiscardBursts(string signal)` — выбросить накопленные события; зовите каждый кадр, пока игра не готова к броску или удару.
   - `bool BurstSupported` — мост объявил `burst` в последнем `hello`. `bool Supports(string feature)` проверяет любую функцию (`NeurotlonProtocol.FeatureBurst`, `FeatureEmgCycle`, `FeatureBaselineDuration`); `string EegMethod` — метод ЭЭГ из `hello.eeg_method`, только для отладки.
   - Принимается только `seq` больше последнего для сигнала и `t_ms` не меньше последнего: дубль и старое событие отбрасываются. При новом `hello` и при потере связи `seq` и очередь сбрасываются. В очереди не больше `MaxBursts` (8) событий на сигнал.
   - Для проверки без сокета: `new NeurotlonBridge(host, port, () => секунды)` и `ApplyLine(json)` подают строки моста прямо в разбор; тесты кита лежат в `Darts/Assets/Tests/EditMode` (`NeurotlonBridgeBurstTests`, `NeurotlonCalibrationCycleTests`).

   **Калибровка.** Если мост объявил `emg_cycle`, мышца калибруется одним шагом `cycle` (20 с, ритм по умолчанию 5/5/5/5, `NeurotlonCalibration.CycleSeconds`) вместо `rest` и `contract`; `calibrate` уходит без своих `segments` и `duration_s`. Экран показывает «Напрягите / Расслабьте мышцу с датчиком» по фазе из сообщения `calibration` и секунды до конца фазы (`CyclePhase`, `CycleSegment`, `PhaseLeftSeconds`; те же поля в `CalibrationProgress`). Сбой `cycle` (слабое сокращение, нет данных): причина человеческим текстом (`RetryReason`) и один повтор. У старого моста без `emg_cycle` идут прежние `rest` и `contract`. Понг калибрует `emg_left` и `emg_right` одновременно тем же шагом. `baseline` длится 12 с (`BaselineSeconds`), глаза открыты: надпись «Расслабьтесь и смотрите на точку на экране» и белая точка по центру; `duration_s` кит не передаёт, мост берёт 12 с сам.
4. **Настройки сборки** (`File → Build Settings`, `Player Settings`):
   - платформа **Windows**, Architecture x86_64, Mono или IL2CPP;
   - `Resolution and Presentation → Fullscreen Mode = Fullscreen Window`, `Run In Background` включён (кит включает его и из кода);
   - `Other Settings → Active Input Handling = Input Manager (Old)` или `Both`: кит читает Esc и Enter через `Input`. В новом проекте Unity 6 по умолчанию стоит только Input System Package, это надо переключить;
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

   Она поднимает эмулированный мост, запускает `.exe` так же, как лаунчер, и проверяет подключение, калибровку, выход вовремя и `result.json`. Для дартса и футбола требуется реакция на `burst`: мост эмулятора присылает события во время игры, а игра, которая не набрала ни одного очка, получает FAIL.

## Правила, которые нельзя нарушать

- Время игры берите из `Launch.DurationSeconds`, не из своих констант. По истечении записывайте результат и выходите.
- Результат — только через `NeurotlonResult` (временный файл и переименование, правила как у сервера). Выход с кодом 0 (`Application.Quit(0)`).
- В игре не должно быть ФИО и любых данных, кроме `code` и `display_name`.
- Датчик потерян: пауза и ожидание, через 30 с `aborted`. Пример уже так делает.
- Мост читается в фоновом потоке, а разбирается в главном: вызывайте `Bridge.Pump()` каждый кадр (в `NeurotlonGame` это сделано).
