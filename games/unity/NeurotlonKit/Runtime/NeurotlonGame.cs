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
    // BuildResult (очки и победитель). Подключение к мосту, калибровку, отсчёт, таймер, Esc,
    // потерю датчика и запись result.json делает этот класс.
    public class NeurotlonGame : MonoBehaviour
    {
        public enum Stage { Connecting, Calibrating, Countdown, Playing, SensorLost, ConfirmAbort, Finished }

        public const float ConnectTimeoutSeconds = 15f;
        public const float CountdownSeconds = 3f;
        public const float LostAbortSeconds = 30f;
        public const float FinishShowSeconds = 2f;
        public const float Threshold = 0.6f;

        public NeurotlonLaunch Launch { get; private set; }
        public NeurotlonBridge Bridge { get; private set; }
        public NeurotlonCalibration Calibration { get; private set; }
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
        bool aborted;
        string startupError;
        List<string> lostNames = new List<string>();
        GUIStyle big, medium, small;

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
            Calibration = new NeurotlonCalibration(Bridge, Launch.Discipline);
            TimeLeft = Launch.DurationSeconds;
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
                Abort("игра прервана оператором");
            }
            switch (CurrentStage)
            {
                case Stage.Connecting: TickConnecting(dt); break;
                case Stage.Calibrating: TickCalibrating(dt); break;
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
                Calibration.Start();
                CurrentStage = Stage.Calibrating;
                return;
            }
            waited += dt;
            if (waited >= ConnectTimeoutSeconds) Abort("нет связи с BCI-мостом");
        }

        void TickCalibrating(float dt)
        {
            Calibration.Update(dt);
            if (Calibration.State == NeurotlonCalibration.CalibrationState.Failed)
            {
                Abort("калибровка не удалась: " + Calibration.FailureReason);
            }
            else if (Calibration.State == NeurotlonCalibration.CalibrationState.Done)
            {
                CurrentStage = Stage.Countdown;
            }
        }

        void TickCountdown(float dt)
        {
            if (EnterLostIfNeeded(Stage.Countdown)) return;
            countdownLeft -= dt;
            if (countdownLeft > 0f) return;
            OnGameStart();
            CurrentStage = Stage.Playing;
        }

        void TickPlaying(float dt)
        {
            if (EnterLostIfNeeded(Stage.Playing)) return;
            TimeLeft = Mathf.Max(0f, TimeLeft - dt);
            OnGameUpdate(dt);
            if (TimeLeft <= 0f) Finish();
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
            switch (CurrentStage)
            {
                case Stage.Connecting:
                    Label(cx, cy, "Подключение к датчикам…", big);
                    break;
                case Stage.Calibrating:
                    Label(cx, Screen.height * 0.25f,
                        "Калибровка: шаг " + Calibration.PhaseNumber + " из " + Calibration.PhaseCount, medium);
                    Label(cx, cy, Calibration.Text, big);
                    GUI.Box(new Rect(cx - Screen.width / 4f, Screen.height * 0.66f, Screen.width / 2f * Calibration.Progress, 24),
                        GUIContent.none);
                    if (Calibration.Retrying) Label(cx, Screen.height * 0.75f, NeurotlonCalibration.TextRetry, small);
                    break;
                case Stage.Countdown:
                    Label(cx, cy - 120, "Приготовьтесь", medium);
                    Label(cx, cy, Mathf.Max(1, Mathf.CeilToInt(countdownLeft)).ToString(), big);
                    break;
                case Stage.Playing:
                    DrawGame();
                    Label(cx, 40, TimerText(), big);
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
                    Label(cx, cy, aborted ? "Игра прервана" : "Игра окончена", big);
                    break;
            }
        }

        string TimerText()
        {
            int seconds = Mathf.CeilToInt(TimeLeft);
            return (seconds / 60) + ":" + (seconds % 60).ToString("00");
        }

        void Label(float cx, float cy, string text, GUIStyle style)
        {
            GUI.Label(new Rect(cx - Screen.width / 2f, cy - 60, Screen.width, 120), text, style);
        }

        void EnsureStyles()
        {
            if (big != null) return;
            big = new GUIStyle(GUI.skin.label) { fontSize = 72, alignment = TextAnchor.MiddleCenter };
            medium = new GUIStyle(GUI.skin.label) { fontSize = 40, alignment = TextAnchor.MiddleCenter };
            small = new GUIStyle(GUI.skin.label) { fontSize = 28, alignment = TextAnchor.MiddleCenter };
        }
    }
}
