using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon
{
    // Пример игры: положите на пустой GameObject в сцене. Это отправная точка, как neurotlon_games.template.
    //
    // Что делает: шкала сигнала, очки копятся, пока значение больше Threshold (по секунде на сигнал).
    // Дартс и футбол: eeg + emg, один игрок. Понг: emg_left + emg_right, побеждает набравший больше.
    //
    // Что заменить в настоящей игре: OnGameStart / OnGameUpdate (механика, читайте Bridge.Value(...)),
    // BuildResult (очки и победитель). Подключение к мосту, проверку калибровки, обучение, проверку, отсчёт, таймер, Esc,
    // потерю датчика и запись result.json делает этот класс.
    //
    // Калибровку датчиков проводит лаунчер до запуска игры; игра её не проводит, а проверяет готовность
    // (NeurotlonReadiness) и без неё сразу пишет aborted.
    //
    // Порядок: подключение и проверка готовности → обучение (TutorialSteps) → демо-проверка (HasCheck, OnCheckUpdate, PassCheck) →
    // отсчёт → игра. Очки обучения и проверки в результат не попадают: игра сама заводит для проверки отдельное состояние.
    public class NeurotlonGame : MonoBehaviour
    {
        public enum Stage { Connecting, Tutorial, Check, Countdown, Playing, SensorLost, ConfirmAbort, Finished }

        public const float ConnectTimeoutSeconds = 15f;
        public const float CountdownSeconds = 3f;
        public const float LostAbortSeconds = 30f;
        public const float FinishShowSeconds = 2f;
        public const float Threshold = 0.6f;
        public const float TutorialStepSeconds = NeurotlonTutorial.StepSeconds;     // на одну попытку шага обучения
        public const float CheckHelpSeconds = 90f;                 // проверка не пройдена за это время: «Позовите волонтёра»
        public const int CheckHelpFailures = 3;                    // или столько неудачных попыток
        public const float PrepLimitSeconds = 360f;                // обучение, проверка и отсчёт вместе: не больше 6 минут
        public const float HardLimitAfterDurationSeconds = 405f;   // лаунчер убивает игру через duration_s + 420 с: уходим раньше

        public NeurotlonLaunch Launch { get; private set; }
        public NeurotlonBridge Bridge { get; private set; }
        public Stage CurrentStage { get; private set; }
        public float TimeLeft { get; private set; }

        readonly Dictionary<string, float> levels = new Dictionary<string, float>();
        readonly Dictionary<string, float> points = new Dictionary<string, float>();
        readonly Dictionary<string, float> peaks = new Dictionary<string, float>();
        Stage resumeStage = Stage.Playing;
        float waited;
        float countdownLeft;
        float lostFor;
        float finishedFor;
        float startedAt;                // Time.realtimeSinceStartup при запуске: от него считаются предохранители
        bool prepDone;                  // зачётная часть уже началась: лимит подготовки больше не действует
        string[] tutorialTexts = new string[0];
        NeurotlonTutorial tutorial;
        float checkElapsed;
        int checkFailures;
        bool checkPassed;
        bool aborted;
        string startupError;
        readonly NeurotlonCalibrationWatch calibrationWatch = new NeurotlonCalibrationWatch();
        List<string> lostNames = new List<string>();
        GUIStyle big, medium, small, tutorialStyle;

        void Start()
        {
            Application.runInBackground = true; // иначе при потере фокуса игра встанет и мост оборвёт связь
            Application.targetFrameRate = 60;
            try
            {
                Launch = NeurotlonLaunch.FromCommandLine();
            }
            catch (NeurotlonLaunchException e)
            {
                // без launch.json писать результат некуда: ошибка в лог и код выхода 2
                startupError = e.Message;
                Debug.LogError("Нейротлон: " + e.Message);
                Application.Quit(2);
                return;
            }
            Screen.fullScreen = Launch.Fullscreen;
            Bridge = new NeurotlonBridge(Launch.BridgeHost, Launch.BridgePort);
            Bridge.Start();
            TimeLeft = Launch.DurationSeconds;
            startedAt = Time.realtimeSinceStartup;
            countdownLeft = CountdownSeconds;
            foreach (var signal in Launch.Signals)
            {
                levels[signal] = 0f;
                points[signal] = 0f;
                peaks[signal] = 0f;
            }
            CurrentStage = Stage.Connecting;
        }

        void OnDestroy()
        {
            if (Bridge != null) Bridge.Dispose();
        }

        void Update()
        {
            if (Launch == null) return;
            Bridge.Pump();
            float dt = Time.unscaledDeltaTime;
            if (Input.GetKeyDown(KeyCode.Escape)) ToggleConfirm();
            else if (CurrentStage == Stage.ConfirmAbort && Input.GetKeyDown(KeyCode.Return))
            {
                bool failedTest = resumeStage == Stage.Check || (resumeStage == Stage.Tutorial && tutorial != null && !tutorial.CanSkipNow);
                Abort(failedTest ? "демо-проверка не пройдена" : "игра прервана оператором");
            }
            CheckFuses();
            WatchCalibration(dt);
            switch (CurrentStage)
            {
                case Stage.Connecting: TickConnecting(dt); break;
                case Stage.Tutorial: TickTutorial(dt); break;
                case Stage.Check: TickCheck(dt); break;
                case Stage.Countdown: TickCountdown(dt); break;
                case Stage.Playing: TickPlaying(dt); break;
                case Stage.SensorLost: TickLost(dt); break;
                case Stage.Finished: TickFinished(dt); break;
            }
        }

        // --- что реализует игра ---

        protected virtual void OnGameStart() { }

        // Механика: dt в секундах, значения сигналов — Bridge.Value(имя) (null, пока значение недействительно).
        protected virtual void OnGameUpdate(float dt)
        {
            foreach (var signal in Launch.Signals)
            {
                float? value = Bridge.Value(signal);
                levels[signal] = value ?? 0f;
                if (value == null) continue;
                peaks[signal] = Mathf.Max(peaks[signal], value.Value);
                if (value.Value > Threshold) points[signal] += dt;
            }
        }

        // --- обучение и проверка ---

        // Подсказки обучения: по одной на механику (1-2 строки), игрок пробует механики по очереди. Пустой список: обучения нет.
        // Общие формулировки (напрячь, расслабить) берите из NeurotlonTexts.
        protected virtual string[] TutorialSteps() { return new string[0]; }

        // Шаг обучения начался (первый раз или заново после неудачи за TutorialStepSeconds): заведите песочницу под механику
        // шага. Очки песочницы в результат не идут.
        protected virtual void OnTutorialStepStart(int index) { }

        // Каждый кадр обучения, в том числе пока подсказку читают и пока показано «Готово» (картинка и камера живут всегда):
        // двигайте песочницу и верните true, когда механика шага сработала. Результат учитывается только в попытке
        // (TutorialInPlay); пока читают, подавайте в правила emg = null, чтобы игрок не успел «сделать» шаг заранее.
        protected virtual bool OnTutorialUpdate(int index, float dt) { return false; }

        // Началась попытка шага (чтение закончилось или повтор): сбросьте счётчики условия шага.
        protected virtual void OnTutorialTryStart(int index) { }

        // Можно ли пропустить шаг клавишей Enter. Шаги-проверки («попади сам») нельзя: при неудаче «Позовите волонтёра»,
        // волонтёр может только завершить игру (Esc, Enter).
        protected virtual bool TutorialStepSkippable(int index) { return true; }

        // Секунд на одну попытку шага (не получилось: шаг начинается заново).
        protected virtual float TutorialStepTimeout(int index) { return NeurotlonTutorial.StepSeconds; }

        // Идёт попытка шага (не чтение подсказки): механика засчитывается.
        protected bool TutorialInPlay { get { return tutorial != null && tutorial.InPlay; } }

        // Нарисовать игровые элементы шага (шкалы и т. п.) под подсказкой. Фон не затемняется: сцена остаётся видна.
        protected virtual void DrawTutorial(int index) { }

        // Обучение закончилось: уберите песочницу.
        protected virtual void OnTutorialEnd() { }

        // Шаг, который сейчас идёт (для игр, которым нужно знать, что показано).
        protected int TutorialIndex { get { return tutorial != null ? tutorial.Index : 0; } }

        // Есть ли демо-проверка перед игрой: игрок сам выполняет минимальное действие, и только потом начинается зачёт.
        protected virtual bool HasCheck { get { return false; } }

        // Проверка началась: заведите отдельное состояние (не то, что пойдёт в результат).
        protected virtual void OnCheckStart() { }

        // Каждый кадр проверки: читайте сигналы, двигайте картинку и вызовите PassCheck(), когда игрок справился.
        protected virtual void OnCheckUpdate(float dt) { }

        // Нарисовать экран проверки (инструкция и ход). Фон не затемняется: сцена остаётся видна.
        protected virtual void DrawCheck() { }

        // Игрок справился: проверка закончена, дальше отсчёт и игра.
        protected void PassCheck() { checkPassed = true; }

        // Неудачная попытка в проверке (бросок мимо и т. п.): после нескольких появится «Позовите волонтёра».
        protected void ReportCheckFailure() { checkFailures++; }

        // Показан ли призыв волонтёра: время проверки вышло или неудач слишком много.
        public bool CheckNeedsHelp { get { return checkElapsed >= CheckHelpSeconds || checkFailures >= CheckHelpFailures; } }

        // Время вышло, а игра ещё не закончена (например, золотой мяч в понге): верните true и завершите
        // игру сами через FinishGame(). По умолчанию игра заканчивается вместе с таймером.
        protected virtual bool ExtendBeyondTime() { return false; }

        // Закончить игру сейчас: записать результат из BuildResult и выйти. Работает только во время игры.
        protected void FinishGame()
        {
            if (CurrentStage == Stage.Playing) Finish();
        }

        // Надпись на экране после окончания игры.
        protected virtual string FinishedMessage() { return "Игра окончена"; }

        // Очки по методике. Зовётся один раз, когда время вышло.
        protected virtual IList<ResultEntryData> BuildResult()
        {
            if (!Launch.IsPong)
            {
                float total = 0f;
                foreach (var pair in points) total += pair.Value;
                return new List<ResultEntryData>
                {
                    NeurotlonResult.Completed(Launch.Participants[0].code, Round(total)),
                };
            }
            var left = Launch.BySide(NeurotlonProtocol.SideLeft);
            var right = Launch.BySide(NeurotlonProtocol.SideRight);
            float l = points[Launch.SignalOf(left)], r = points[Launch.SignalOf(right)];
            float lp = peaks[Launch.SignalOf(left)], rp = peaks[Launch.SignalOf(right)];
            // при равенстве очков побеждает тот, у кого выше пик; потом левый
            bool leftWins = l > r || (l == r && lp >= rp);
            return new List<ResultEntryData>
            {
                NeurotlonResult.Completed(left.code, Round(l), leftWins ? 1 : 0),
                NeurotlonResult.Completed(right.code, Round(r), leftWins ? 0 : 1),
            };
        }

        protected virtual void DrawGame()
        {
            int i = 0;
            foreach (var signal in Launch.Signals)
            {
                i++;
                float x = Screen.width * i / (Launch.Signals.Length + 1f);
                GUI.Label(new Rect(x - 200, Screen.height * 0.25f, 400, 50), signal, medium);
                GUI.Box(new Rect(x - 150, Screen.height * 0.45f, 300, 36), GUIContent.none);
                GUI.Box(new Rect(x - 150, Screen.height * 0.45f, 300 * levels[signal], 36), GUIContent.none);
                GUI.Label(new Rect(x - 200, Screen.height * 0.6f, 400, 60),
                    "Очки: " + Mathf.FloorToInt(points[signal]), medium);
            }
        }

        // --- ход игры ---

        void TickConnecting(float dt)
        {
            if (Bridge.IsReady(Launch.Signals))
            {
                // калибровку провёл лаунчер: нет её на реальных датчиках, играть нельзя
                if (NeurotlonReadiness.Uncalibrated(Bridge, Launch.Signals).Count > 0)
                {
                    Abort(NeurotlonReadiness.NotCalibratedReason);
                    return;
                }
                BeginTutorial();
                return;
            }
            waited += dt;
            if (waited >= ConnectTimeoutSeconds) Abort("нет связи с BCI-мостом");
        }

        // Мост перезапустился и калибровку не вернул: not_calibrated в sample дольше двух секунд. Обрыв связи и stale
        // сюда не входят: это потеря датчика (SensorLost, 30 с).
        void WatchCalibration(float dt)
        {
            bool watching = CurrentStage == Stage.Tutorial || CurrentStage == Stage.Check || CurrentStage == Stage.Countdown
                || CurrentStage == Stage.Playing || CurrentStage == Stage.SensorLost;
            if (!watching)
            {
                calibrationWatch.Reset();
                return;
            }
            if (calibrationWatch.Update(dt, NeurotlonReadiness.CalibrationLost(Bridge, Launch.Signals)))
            {
                Abort(NeurotlonReadiness.CalibrationResetReason);
            }
        }

        void BeginTutorial()
        {
            tutorialTexts = TutorialSteps() ?? new string[0];
            tutorial = new NeurotlonTutorial(tutorialTexts.Length, TutorialStepSkippable, TutorialStepTimeout);
            if (tutorialTexts.Length == 0)
            {
                BeginCheck();
                return;
            }
            tutorial.MinTrySeconds = ReadFloatArg("--tutorial-min");     // служебный параметр показа: успеть прочитать подсказку
            tutorial.StepStarted += OnTutorialStepStart;
            tutorial.TryStarted += OnTutorialTryStart;
            CurrentStage = Stage.Tutorial;
            tutorial.Begin();
        }

        static float ReadFloatArg(string name)
        {
            string[] args = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                float value;
                if (args[i] == name && float.TryParse(args[i + 1], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value)) return Mathf.Max(0f, value);
            }
            return 0f;
        }

        // Enter у волонтёра пропускает шаг; не сработала механика за 20 с, шаг начинается заново, после двух неудач просим волонтёра.
        void TickTutorial(float dt)
        {
            if (EnterLostIfNeeded(Stage.Tutorial)) return;
            if (Input.GetKeyDown(KeyCode.Return)) tutorial.Skip();
            if (tutorial.State != NeurotlonTutorial.Phase.Finished)
            {
                // картинка живёт и при чтении подсказки, но механика засчитывается только в попытке
                bool worked = OnTutorialUpdate(tutorial.Index, dt);
                tutorial.Update(dt, worked && tutorial.State == NeurotlonTutorial.Phase.Trying);
            }
            if (tutorial.State == NeurotlonTutorial.Phase.Finished)
            {
                OnTutorialEnd();
                BeginCheck();
            }
        }

        void BeginCheck()
        {
            checkElapsed = 0f;
            checkFailures = 0;
            checkPassed = false;
            if (!HasCheck)
            {
                CurrentStage = Stage.Countdown;
                return;
            }
            OnCheckStart();
            CurrentStage = Stage.Check;
        }

        void TickCheck(float dt)
        {
            if (EnterLostIfNeeded(Stage.Check)) return;
            checkElapsed += dt;
            OnCheckUpdate(dt);
            if (checkPassed) CurrentStage = Stage.Countdown;
        }

        // Предохранители. Подготовка (обучение, проверка, отсчёт): не дольше PrepLimitSeconds, иначе игра
        // уйдёт с aborted. Вся игра: не дольше duration_s + HardLimitAfterDurationSeconds. Лаунчер убивает процесс на 420 с,
        // мы выходим раньше и пишем результат (в зачётной части) или aborted (в подготовке).
        void CheckFuses()
        {
            if (CurrentStage == Stage.Finished) return;
            float real = Time.realtimeSinceStartup - startedAt;
            bool preparing = !prepDone;
            if (preparing && real > PrepLimitSeconds)
            {
                Abort("подготовка заняла больше 6 минут");
                return;
            }
            if (real > Launch.DurationSeconds + HardLimitAfterDurationSeconds)
            {
                if (preparing) Abort("игра не началась за отведённое время");
                else Finish();
            }
        }

        void TickCountdown(float dt)
        {
            if (EnterLostIfNeeded(Stage.Countdown)) return;
            countdownLeft -= dt;
            if (countdownLeft > 0f) return;
            OnGameStart();
            prepDone = true;
            CurrentStage = Stage.Playing;
        }

        void TickPlaying(float dt)
        {
            if (EnterLostIfNeeded(Stage.Playing)) return;
            TimeLeft = Mathf.Max(0f, TimeLeft - dt);
            OnGameUpdate(dt);
            if (TimeLeft <= 0f && !ExtendBeyondTime()) Finish();
        }

        bool EnterLostIfNeeded(Stage cameFrom)
        {
            lostNames = Bridge.LostSignals(Launch.Signals);
            if (lostNames.Count == 0) return false;
            lostFor = 0f;
            resumeStage = cameFrom;
            CurrentStage = Stage.SensorLost;
            return true;
        }

        void TickLost(float dt)
        {
            lostNames = Bridge.LostSignals(Launch.Signals);
            if (lostNames.Count == 0)
            {
                CurrentStage = resumeStage;
                return;
            }
            lostFor += dt;
            if (lostFor >= LostAbortSeconds)
            {
                Abort("датчик не вернулся за 30 с: " + string.Join(", ", lostNames.ToArray()));
            }
        }

        void TickFinished(float dt)
        {
            finishedFor += dt;
            if (aborted || finishedFor >= FinishShowSeconds) Application.Quit(0);
        }

        void ToggleConfirm()
        {
            if (CurrentStage == Stage.Finished) return;
            if (CurrentStage == Stage.ConfirmAbort)
            {
                CurrentStage = resumeStage;
                return;
            }
            resumeStage = CurrentStage;
            CurrentStage = Stage.ConfirmAbort;
        }

        void Finish()
        {
            try
            {
                NeurotlonResult.WriteFinished(Launch, BuildResult());
                CurrentStage = Stage.Finished;
            }
            catch (NeurotlonResultException e)
            {
                Debug.LogError("Нейротлон: недопустимый результат игры: " + e.Message);
                Abort("недопустимый результат игры: " + e.Message);
            }
        }

        protected void Abort(string reason)
        {
            if (CurrentStage == Stage.Finished) return;
            NeurotlonResult.WriteAborted(Launch, reason);
            aborted = true;
            CurrentStage = Stage.Finished;
        }

        static int Round(float value)
        {
            return Mathf.Min(NeurotlonProtocol.ResultPointsMax, Mathf.FloorToInt(value));
        }

        // --- экран (IMGUI: без пакетов и шрифтов) ---

        void OnGUI()
        {
            if (Launch == null)
            {
                EnsureStyles();
                GUI.Label(new Rect(0, 0, Screen.width, Screen.height), "Нет launch.json: " + startupError, medium);
                return;
            }
            EnsureStyles();
            float cx = Screen.width / 2f, cy = Screen.height / 2f;
            if (CurrentStage != Stage.Playing && CurrentStage != Stage.Check && CurrentStage != Stage.Tutorial)          // служебные экраны читаются поверх любой картинки
            {
                GUI.color = new Color(0f, 0f, 0f, 0.62f);
                GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Screen.height), Texture2D.whiteTexture);
                GUI.color = Color.white;
            }
            switch (CurrentStage)
            {
                case Stage.Connecting:
                    Label(cx, cy, "Подключение к датчикам…", big);
                    break;
                case Stage.Tutorial:
                    DrawTutorial(tutorial.Index);
                    DrawTutorialBanner();
                    break;
                case Stage.Check:
                    DrawCheck();
                    if (CheckNeedsHelp) DrawNotice(NeurotlonTexts.CallVolunteer, VolunteerCallHeight);
                    break;
                case Stage.Countdown:
                    Label(cx, cy - 120, "Приготовьтесь", medium);
                    Label(cx, cy, Mathf.Max(1, Mathf.CeilToInt(countdownLeft)).ToString(), big);
                    break;
                case Stage.Playing:
                    DrawGame();
                    if (!DrawsOwnTimer) Label(cx, 40, TimerText(), big);
                    break;
                case Stage.SensorLost:
                    Label(cx, cy - 60, "Датчик потерян", big);
                    Label(cx, cy + 10, "Игра на паузе, проверьте датчик", medium);
                    Label(cx, cy + 60, "Если связь не вернётся, игра прервётся через "
                        + Mathf.Max(0, Mathf.CeilToInt(LostAbortSeconds - lostFor)) + " с", small);
                    break;
                case Stage.ConfirmAbort:
                    Label(cx, cy - 40, "Прервать игру?", big);
                    Label(cx, cy + 40, "Enter: прервать    Esc: продолжить", medium);
                    break;
                case Stage.Finished:
                    Label(cx, cy, aborted ? "Игра прервана" : FinishedMessage(), big);
                    break;
            }
        }

        // Где во время попытки стоит компактная подсказка: x, y и ширина (высота по тексту). По умолчанию сверху по центру;
        // игра может увести её в свободную часть экрана, чтобы не закрывать цель.
        protected virtual Rect TutorialHintArea
        {
            get { return new Rect(Screen.width * 0.14f, Screen.height * 0.17f, Screen.width * 0.72f, 0f); }
        }

        // Где стоит призыв волонтёра: доля высоты экрана, выше нижних плашек со шкалами.
        const float VolunteerCallHeight = 0.70f;

        // Крупная надпись на тёмной полосе по всей ширине: читается на любой картинке и не лежит на шкалах.
        // centerHeight: доля высоты экрана, где центр надписи.
        protected void DrawNotice(string text, float centerHeight)
        {
            EnsureStyles();
            float height = big.fontSize * 1.5f;
            var band = new Rect(0f, Screen.height * centerHeight - height * 0.5f, Screen.width, height);
            GUI.color = new Color(0f, 0f, 0f, 0.72f);
            GUI.DrawTexture(band, Texture2D.whiteTexture);
            GUI.color = Color.white;
            Label(Screen.width * 0.5f, band.center.y, text, big);
        }

        // Заголовок шага: «Обучение: n из m», а у шага-проверки (его нельзя пропустить) «ПРОВЕРКА», чтобы тренировку и зачёт было видно.
        string TutorialTitle()
        {
            return tutorial.CanSkipNow ? NeurotlonTexts.TutorialCounter(tutorial.Index + 1, tutorial.Count) : NeurotlonTexts.TestTitle;
        }

        // Сначала новая подсказка крупно по центру на лёгком затемнении (прочитать), потом компактная панель без затемнения.
        // Счётчик шагов, «Готово», при неудачах призыв волонтёра.
        void DrawTutorialBanner()
        {
            if (tutorial.Index >= tutorialTexts.Length) return;
            float scale = Mathf.Clamp(Screen.height / 1080f, 0.5f, 2.5f);
            float cx = Screen.width * 0.5f;
            if (tutorial.State == NeurotlonTutorial.Phase.Reading)
            {
                GUI.color = new Color(0f, 0f, 0f, 0.5f);
                GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Screen.height), Texture2D.whiteTexture);
                GUI.color = Color.white;
                Label(cx, Screen.height * 0.30f, TutorialTitle(), medium);
                Label(cx, Screen.height * 0.5f, tutorialTexts[tutorial.Index], big);
                return;
            }
            bool done = tutorial.State == NeurotlonTutorial.Phase.Done;
            string text = done ? NeurotlonTexts.TutorialDone : tutorialTexts[tutorial.Index];
            Rect area = TutorialHintArea;
            float height = tutorialStyle.CalcHeight(new GUIContent(text), area.width);
            var box = new Rect(area.x, area.y, area.width, height + 16f * scale);
            GUI.color = new Color(0f, 0f, 0f, 0.62f);
            GUI.DrawTexture(box, Texture2D.whiteTexture);
            GUI.color = Color.white;
            Color keep = tutorialStyle.normal.textColor;
            tutorialStyle.normal.textColor = done ? new Color(0.55f, 0.95f, 0.55f) : Color.white;
            OutlinedLabel(new Rect(box.x, box.y + 8f * scale, box.width, height), text, tutorialStyle);
            tutorialStyle.normal.textColor = keep;
            Label(box.center.x, box.y - 22f * scale, TutorialTitle(), small);
            if (tutorial.NeedsHelp) DrawNotice(NeurotlonTexts.CallVolunteer, VolunteerCallHeight);
        }

        // Игра рисует таймер сама (в своей плашке), текст берёт из TimerText(); тогда кит свой таймер не рисует.
        protected virtual bool DrawsOwnTimer { get { return false; } }

        protected virtual string TimerText()
        {
            int seconds = Mathf.CeilToInt(TimeLeft);
            return (seconds / 60) + ":" + (seconds % 60).ToString("00");
        }

        // Надпись по центру (cx, cy): ширина 90 % экрана, высота по тексту, длинные фразы переносятся и не обрезаются.
        void Label(float cx, float cy, string text, GUIStyle style)
        {
            float width = Screen.width * 0.9f;
            float height = Mathf.Max(style.fontSize * 1.6f, style.CalcHeight(new GUIContent(text), width));
            OutlinedLabel(new Rect(cx - width / 2f, cy - height / 2f, width, height), text, style);
        }

        // Надпись с тёмной обводкой: читается на светлом и пёстром фоне. Цвет берётся из стиля.
        protected static void OutlinedLabel(Rect rect, string text, GUIStyle style)
        {
            Color fill = style.normal.textColor;
            float o = Mathf.Max(1.5f, style.fontSize / 18f);
            style.normal.textColor = new Color(0f, 0f, 0f, 0.92f * fill.a);       // обводка гаснет вместе с надписью
            for (int i = 0; i < 8; i++)
            {
                float a = i * Mathf.PI / 4f;
                GUI.Label(new Rect(rect.x + Mathf.Cos(a) * o, rect.y + Mathf.Sin(a) * o, rect.width, rect.height), text, style);
            }
            style.normal.textColor = fill;
            GUI.Label(rect, text, style);
        }

        void EnsureStyles()
        {
            if (big == null)
            {
                big = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter, wordWrap = true };
                medium = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter, wordWrap = true };
                small = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter, wordWrap = true };
                tutorialStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter, wordWrap = true };
                big.normal.textColor = medium.normal.textColor = small.normal.textColor = tutorialStyle.normal.textColor = Color.white;
            }
            float scale = Mathf.Clamp(Screen.height / 1080f, 0.5f, 2.5f);          // размер шрифта следует за размером окна
            big.fontSize = Mathf.RoundToInt(72f * scale);
            medium.fontSize = Mathf.RoundToInt(40f * scale);
            small.fontSize = Mathf.RoundToInt(28f * scale);
            tutorialStyle.fontSize = Mathf.RoundToInt(40f * scale);
        }
    }
}
