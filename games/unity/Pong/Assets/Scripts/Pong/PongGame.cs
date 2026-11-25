using System;
using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon.Games.Pong
{
    // Понг для двух игроков на стенде. Каждый управляет ракеткой силой своего ЭМГ-сигнала (0…1 = от края до края).
    // Запуск, мост, калибровку, отсчёт, таймер, Esc, паузу и запись результата делает NeurotlonGame;
    // здесь — правила (PongRules), картинка, звук и табло.
    public sealed class PongGame : NeurotlonGame
    {
        const float FollowSmoothSeconds = 0.11f; // за сколько примерно ракетка догоняет сигнал; больше — плавнее и ленивее
        const float MaxPaddleSpeed = 5f;         // м/с, предел скорости ракетки
        const float PaddleCenterHeight = 0.16f; // центр ракетки над столом
        const float BallArcHeight = 0.16f;      // высота дуги мяча над столом (выше сетки)
        const float FloorBallHeight = 0.03f;
        const float ServeTossHeight = 0.20f;     // высота подброса мяча на подаче
        const float EndDelaySeconds = 1.8f;     // пауза после последнего очка, потом результат
        const float HitPulseSeconds = 0.45f;    // длительность удара ракетки при отбитии
        const int TutorialTargetScore = 99;     // в песочнице обучения розыгрыш не заканчивается
        const string HighLine = NeurotlonTexts.Tense + " сильно и держите";
        const string LowLine = NeurotlonTexts.Relax + " полностью и держите";

        [Header("Объекты сцены")]
        [SerializeField] Transform ball;
        [SerializeField] Transform paddleLeft;
        [SerializeField] Transform paddleRight;
        [SerializeField] Transform paddleLeftFpv;     // копии ракеток для камер игроков (вид от первого лица)
        [SerializeField] Transform paddleRightFpv;
        [SerializeField] PongScoreboard scoreboard;
        [SerializeField] PongSounds sounds;
        [SerializeField] PongDisplays displays;
        [SerializeField] float tableTop = 0.76f;

        readonly PongTuning tuning = new PongTuning();
        readonly PongTutorial tutorialState = new PongTutorial();   // условия шагов обучения у обоих игроков
        PongRules rules;                         // в обучении здесь песочница (null на шаге «Ракетка»); настоящие правила создаёт OnGameStart
        bool hasDebugScore;                      // --debug-score: на экране вместо настоящего счёта, в результат не попадает
        int debugScoreLeft;
        int debugScoreRight;
        LaunchParticipant playerLeft;
        LaunchParticipant playerRight;
        string signalLeft;
        string signalRight;
        float targetLeft = 0.5f;
        float targetRight = 0.5f;
        float zLeft;
        float zRight;
        float zLeftVelocity;
        float zRightVelocity;
        float pulseLeft;
        float pulseRight;
        readonly PaddleAnimator animLeft = new PaddleAnimator(Side.Left, PaddleView.Audience);
        readonly PaddleAnimator animRight = new PaddleAnimator(Side.Right, PaddleView.Audience);
        readonly PaddleAnimator animLeftFpv = new PaddleAnimator(Side.Left, PaddleView.FirstPerson);
        readonly PaddleAnimator animRightFpv = new PaddleAnimator(Side.Right, PaddleView.FirstPerson);
        float ballY;
        float previousArcSign = 1f;
        float endTimer;
        bool timeExpiredHandled;
        PongCheck checkLeft;                     // демо-проверка перед матчем: у каждого игрока своя, идут одновременно
        PongCheck checkRight;
        GUIStyle hudName, hudScore, checkStyle, tensionStyle, introStyle;
        const float MatchIntroSeconds = 3f;
        float matchIntroLeft;
        const string TensionLabel = "МЫШЦА";

        void Awake()
        {
            ballY = tableTop + BallRadius() + BallArcHeight;
            hasDebugScore = PongScoreLayout.TryParseDebugScore(Environment.GetCommandLineArgs(), out debugScoreLeft, out debugScoreRight);
            PlaceObjects();
        }

        void LateUpdate()
        {
            if (Launch == null) return;
            if (playerLeft == null) ResolvePlayers();
            if (scoreboard != null) scoreboard.Show(NameOf(playerLeft), NameOf(playerRight), ShownScoreLeft, ShownScoreRight, Caption(), Hint());
        }

        // --- что реализует игра ---

        protected override void OnGameStart()
        {
            if (playerLeft == null) ResolvePlayers();
            rules = CreateRules(tuning);
            rules.Raised += OnRulesEvent;
            pulseLeft = 0f;
            pulseRight = 0f;
            zLeft = 0f;
            zRight = 0f;
            targetLeft = 0.5f;
            targetRight = 0.5f;
            matchIntroLeft = MatchIntroSeconds;                 // «официальное» начало: карточка матча, розыгрыш ещё не идёт
        }

        // Обучение: механики понга по очереди, у обоих игроков одновременно. Шаг засчитан, когда механика сработала у обоих.
        protected override string[] TutorialSteps()
        {
            return PongTutorial.Texts(tuning.TargetScore);
        }

        // Песочница: на шаге «Ракетка» мяча нет, на остальных идёт розыгрыш на отдельных правилах (очки в результат не идут).
        protected override void OnTutorialStepStart(int index)
        {
            if (playerLeft == null) ResolvePlayers();
            tutorialState.Reset();
            pulseLeft = 0f;
            pulseRight = 0f;
            if (index == PongTutorial.PaddleStep)
            {
                rules = null;
                return;
            }
            PongTuning sandbox = tuning.Clone();
            sandbox.TargetScore = TutorialTargetScore;
            rules = CreateRules(sandbox);
            rules.Raised += OnTutorialRulesEvent;
            tutorialState.OnRulesEvent(PongEventKind.Serve, rules.Server);     // первую подачу конструктор поднял до подписки
        }

        protected override bool OnTutorialUpdate(int index, float dt)
        {
            float? l = Bridge.Value(signalLeft);
            float? r = Bridge.Value(signalRight);
            FollowSignals(l, r, dt);
            tutorialState.StepSignals(l, r);
            if (rules != null) rules.Step(dt, zLeft, zRight);
            pulseLeft = Mathf.Max(0f, pulseLeft - dt);
            pulseRight = Mathf.Max(0f, pulseRight - dt);
            PlaceObjects(dt);
            return tutorialState.IsDone(index);
        }

        protected override void DrawTutorial(int index)
        {
            DrawScoreHeader();
            DrawTensionBars(false);
        }

        protected override void OnTutorialEnd()
        {
            rules = null;
            pulseLeft = 0f;
            pulseRight = 0f;
        }

        PongRules CreateRules(PongTuning settings)
        {
            var random = new System.Random();
            return new PongRules(settings, () => (float)random.NextDouble(), Side.Left);
        }

        void OnTutorialRulesEvent(PongEvent e)
        {
            OnRulesEvent(e);
            tutorialState.OnRulesEvent(e.Kind, e.Side);
        }

        protected override bool HasCheck { get { return true; } }

        // Проверка идёт у обоих игроков одновременно; матч начинается, когда справились оба.
        protected override void OnCheckStart()
        {
            if (playerLeft == null) ResolvePlayers();
            checkLeft = new PongCheck();
            checkRight = new PongCheck();
            zLeft = 0f;
            zRight = 0f;
            targetLeft = 0.5f;
            targetRight = 0.5f;
        }

        protected override void OnCheckUpdate(float dt)
        {
            float? l = Bridge.Value(signalLeft);
            float? r = Bridge.Value(signalRight);
            FollowSignals(l, r, dt);
            checkLeft.Step(dt, l);
            checkRight.Step(dt, r);
            PlaceObjects(dt);
            if (checkLeft.Passed && checkRight.Passed) PassCheck();
        }

        // Ракетки идут за сигналом: в проверке и в матче одинаково.
        void FollowSignals(float? l, float? r, float dt)
        {
            if (l.HasValue) targetLeft = Mathf.Clamp01(l.Value);      // сигнала нет: ракетка стоит на месте
            if (r.HasValue) targetRight = Mathf.Clamp01(r.Value);
            // критическое затухание: плавно и без дрожи даже при шумном сигнале
            zLeft = Mathf.SmoothDamp(zLeft, ZFor(targetLeft), ref zLeftVelocity, FollowSmoothSeconds, MaxPaddleSpeed, dt);
            zRight = Mathf.SmoothDamp(zRight, ZFor(targetRight), ref zRightVelocity, FollowSmoothSeconds, MaxPaddleSpeed, dt);
        }

        protected override void OnGameUpdate(float dt)
        {
            FollowSignals(Bridge.Value(signalLeft), Bridge.Value(signalRight), dt);
            if (matchIntroLeft > 0f)
            {
                matchIntroLeft -= dt;                           // ракетки уже двигаются, а мяч и счёт ждут конца карточки
                PlaceObjects(dt);
                return;
            }

            if (TimeLeft <= 0f && !timeExpiredHandled)
            {
                timeExpiredHandled = true;
                rules.TimeExpired();
            }
            rules.Step(dt, zLeft, zRight);
            if (rules.Phase == PongPhase.Over)
            {
                endTimer += dt;
                if (endTimer >= EndDelaySeconds) FinishGame();
            }
            pulseLeft = Mathf.Max(0f, pulseLeft - dt);
            pulseRight = Mathf.Max(0f, pulseRight - dt);
            PlaceObjects(dt);
        }

        // Время вышло: при равном счёте играется золотой мяч, игра заканчивается сама.
        protected override bool ExtendBeyondTime()
        {
            return rules != null;
        }

        protected override IList<ResultEntryData> BuildResult()
        {
            Side winner;
            if (rules.Winner.HasValue) winner = rules.Winner.Value;
            else winner = rules.ScoreLeft >= rules.ScoreRight ? Side.Left : Side.Right;
            int winsLeft = winner == Side.Left ? 1 : 0;
            return new List<ResultEntryData>
            {
                NeurotlonResult.Completed(playerLeft.code, rules.ScoreLeft, winsLeft),
                NeurotlonResult.Completed(playerRight.code, rules.ScoreRight, 1 - winsLeft),
            };
        }

        // Время на экране не показываем: матч идёт до 11 очков. Время из launch.json — страховка для лаунчера.
        protected override string TimerText()
        {
            return rules != null && rules.Overtime ? "ЗОЛОТОЙ МЯЧ" : "";
        }

        protected override string FinishedMessage()
        {
            if (rules == null || !rules.Winner.HasValue) return base.FinishedMessage();
            return "Победитель: " + NameOf(rules.Winner.Value == Side.Left ? playerLeft : playerRight);
        }

        // Счёт на экране игроков: сверху по центру, между двумя половинами. Для зрителей — табло на стене.
        protected override void DrawGame()
        {
            DrawScoreHeader();
            DrawTensionBars(false);
            DrawMatchIntro();
        }

        // Карточка начала матча: «МАТЧ», до скольки очков, кто с кем играет и кто подаёт первым. Держится MatchIntroSeconds.
        void DrawMatchIntro()
        {
            if (matchIntroLeft <= 0f || rules == null) return;
            if (displays != null && !displays.ShowsPlayers) return;
            if (introStyle == null)
                introStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter, wordWrap = false, clipping = TextClipping.Overflow };
            Rect area = displays != null ? displays.PlayerViewArea : new Rect(0f, 0f, Screen.width, Screen.height);
            float s = Mathf.Clamp(area.height / 1080f, 0.5f, 2.5f);
            float alpha = Mathf.Clamp01(matchIntroLeft / 0.4f);                  // в конце карточка гаснет
            var band = new Rect(area.x, area.y + area.height * 0.30f, area.width, area.height * 0.34f);
            GUI.color = new Color(0f, 0f, 0f, 0.62f * alpha);
            GUI.DrawTexture(band, Texture2D.whiteTexture);
            GUI.color = Color.white;
            float cx = band.center.x;
            DrawIntroLine(new Rect(area.x, band.y + band.height * 0.04f, area.width, 120f * s), "МАТЧ", Mathf.RoundToInt(100f * s), Color.white, alpha);
            DrawIntroLine(new Rect(area.x, band.y + band.height * 0.36f, area.width, 56f * s), "До " + tuning.TargetScore + " очков", Mathf.RoundToInt(44f * s), Color.white, alpha);
            DrawIntroLine(new Rect(area.x, band.y + band.height * 0.56f, area.width, 56f * s), NameOf(playerLeft) + "  против  " + NameOf(playerRight), Mathf.RoundToInt(44f * s), new Color(1f, 0.95f, 0.7f), alpha);
            string server = NameOf(rules.Server == Side.Left ? playerLeft : playerRight);
            DrawIntroLine(new Rect(area.x, band.y + band.height * 0.76f, area.width, 50f * s), "Первая подача: " + server, Mathf.RoundToInt(36f * s), new Color(0.75f, 0.9f, 1f), alpha);
        }

        void DrawIntroLine(Rect rect, string text, int fontSize, Color color, float alpha)
        {
            introStyle.fontSize = fontSize;
            color.a = alpha;
            introStyle.normal.textColor = color;
            OutlinedLabel(rect, text, introStyle);
        }

        // Верх экрана игроков: разделитель половин, цветные метки, имена и счёт. Общий для матча и обучения.
        const string PracticeLabel = "Тренировка";
        const float PracticeFontSize = 44f;

        void DrawScoreHeader()
        {
            bool practice = CurrentStage == Stage.Tutorial;     // в обучении очки не считаются: вместо счёта подпись
            if (displays != null && !displays.ShowsPlayers) return;     // в виде «только зрители» подсказок игроков нет
            if (hudName == null)
            {
                hudName = new GUIStyle(GUI.skin.label) { fontSize = 30, fontStyle = FontStyle.Bold, wordWrap = false, clipping = TextClipping.Clip };
                hudScore = new GUIStyle(GUI.skin.label) { fontSize = Mathf.RoundToInt(PongScoreLayout.FontSize), fontStyle = FontStyle.Bold, alignment = TextAnchor.UpperCenter };
                NeurotlonHud.SingleLine(hudScore);
            }
            Rect area = displays != null ? displays.PlayerViewArea : new Rect(0f, 0f, Screen.width, Screen.height);
            float cx = area.x + area.width * 0.5f;
            // разделитель двух половин и цветные метки игроков (красный слева, синий справа)
            GUI.color = new Color(0.02f, 0.03f, 0.06f, 1f);
            GUI.DrawTexture(new Rect(cx - 3f, area.y, 6f, area.height), Texture2D.whiteTexture);
            GUI.color = new Color(0.85f, 0.10f, 0.10f, 1f);
            GUI.DrawTexture(new Rect(area.x, area.y, area.width * 0.5f - 3f, 8f), Texture2D.whiteTexture);
            GUI.color = new Color(0.12f, 0.38f, 0.90f, 1f);
            GUI.DrawTexture(new Rect(cx + 3f, area.y, area.width * 0.5f - 3f, 8f), Texture2D.whiteTexture);
            GUI.color = Color.white;
            hudName.normal.textColor = Color.white;
            hudScore.normal.textColor = Color.white;
            // счёт по ширине текста строго по центру; имена отодвинуты на половину его ширины и запас
            string score = practice ? PracticeLabel : PongScoreLayout.Text(ShownScoreLeft, ShownScoreRight);
            float scoreWidth = practice ? NeurotlonHud.TextWidth(score, PracticeFontSize) : PongScoreLayout.Width(score);
            float offset = PongScoreLayout.NameOffset(score);
            float nameWidth = Mathf.Min(Mathf.Max(160f, area.width * 0.2f), area.width * 0.5f - offset - 8f);
            hudName.alignment = TextAnchor.UpperRight;
            GUI.Label(new Rect(cx - offset - nameWidth, area.y + 26f, nameWidth, 44f), NameOf(playerLeft), hudName);
            hudName.alignment = TextAnchor.UpperLeft;
            GUI.Label(new Rect(cx + offset, area.y + 26f, nameWidth, 44f), NameOf(playerRight), hudName);
            int scoreFont = hudScore.fontSize;
            if (practice) hudScore.fontSize = Mathf.RoundToInt(PracticeFontSize);
            GUI.Label(new Rect(cx - scoreWidth * 0.5f, area.y + (practice ? 36f : 10f), scoreWidth, 110f), score, hudScore);
            hudScore.fontSize = scoreFont;
        }

        // Экран проверки: у каждого игрока своя половина, два пункта и отметка «готово». Значений сигнала и шкал нет.
        protected override void DrawCheck()
        {
            if (displays != null && !displays.ShowsPlayers) return;
            if (checkLeft == null || checkRight == null) return;
            if (checkStyle == null)
                checkStyle = new GUIStyle(GUI.skin.label) { fontSize = 34, fontStyle = FontStyle.Bold, wordWrap = true, alignment = TextAnchor.UpperCenter };
            Rect area = displays != null ? displays.PlayerViewArea : new Rect(0f, 0f, Screen.width, Screen.height);
            DrawCheckHalf(new Rect(area.x, area.y, area.width * 0.5f, area.height), playerLeft, checkLeft, checkRight.Passed);
            DrawCheckHalf(new Rect(area.x + area.width * 0.5f, area.y, area.width * 0.5f, area.height), playerRight, checkRight, checkLeft.Passed);
            DrawTensionBars(true);
        }

        // Шкалы напряжения в верхних внешних углах на уровне имён: у левого игрока слева (красная), у правого справа
        // (синяя), обе заполняются к центру. Игрок сам решает, смотреть ли на шкалу. В проверке на шкале отмечены границы
        // «слабо» и «сильно».
        void DrawTensionBars(bool showCheckMarks)
        {
            if (displays != null && !displays.ShowsPlayers) return;
            Rect area = displays != null ? displays.PlayerViewArea : new Rect(0f, 0f, Screen.width, Screen.height);
            const float barH = 30f, margin = 24f, nameTop = 26f, nameHeight = 44f;           // по высоте строки имён (DrawScoreHeader)
            float barW = Mathf.Clamp(area.width * 0.18f, 160f, 420f);
            float top = area.y + nameTop + (nameHeight - barH) * 0.5f;
            DrawTensionBar(new Rect(area.x + margin, top, barW, barH), targetLeft, new Color(0.85f, 0.10f, 0.10f), false, showCheckMarks);
            DrawTensionBar(new Rect(area.xMax - margin - barW, top, barW, barH), targetRight, new Color(0.12f, 0.38f, 0.90f), true, showCheckMarks);
        }

        // fromRight: шкала растёт справа налево (у правого игрока), иначе слева направо.
        void DrawTensionBar(Rect bar, float value, Color fill, bool fromRight, bool marks)
        {
            if (tensionStyle == null)
                tensionStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.UpperCenter, wordWrap = false, clipping = TextClipping.Overflow };
            tensionStyle.fontSize = 18;
            tensionStyle.normal.textColor = Color.white;
            const float edge = 3f;
            GUI.color = new Color(0f, 0f, 0f, 0.65f);
            GUI.DrawTexture(new Rect(bar.x - edge, bar.y - edge, bar.width + 2f * edge, bar.height + 2f * edge), Texture2D.whiteTexture);
            GUI.color = new Color(0.12f, 0.14f, 0.20f, 1f);
            GUI.DrawTexture(bar, Texture2D.whiteTexture);
            float filled = bar.width * Mathf.Clamp01(value);
            GUI.color = fill;
            GUI.DrawTexture(new Rect(fromRight ? bar.xMax - filled : bar.x, bar.y, filled, bar.height), Texture2D.whiteTexture);
            if (marks)
            {
                GUI.color = Color.white;
                foreach (float mark in new[] { PongCheck.LowThreshold, PongCheck.HighThreshold })
                {
                    float x = fromRight ? bar.xMax - bar.width * mark : bar.x + bar.width * mark;
                    GUI.DrawTexture(new Rect(x - 1.5f, bar.y - 6f, 3f, bar.height + 12f), Texture2D.whiteTexture);
                }
            }
            GUI.color = Color.white;
            OutlinedLabel(new Rect(bar.x, bar.yMax + 4f, bar.width, 24f), TensionLabel, tensionStyle);
        }

        void DrawCheckHalf(Rect half, LaunchParticipant player, PongCheck check, bool otherPassed)
        {
            float scale = Mathf.Clamp(Screen.height / 1080f, 0.5f, 2.5f);
            checkStyle.fontSize = Mathf.RoundToInt(34f * scale);
            float pad = half.width * 0.06f, gap = 8f * scale;
            float width = half.width - 2f * pad;
            // сначала собираем строки и считаем их высоту (перенос по словам), потом рисуем подложку по размеру текста
            var lines = new List<KeyValuePair<string, Color>>();
            Color green = new Color(0.55f, 0.95f, 0.55f);
            lines.Add(new KeyValuePair<string, Color>("ПРОВЕРКА: " + NameOf(player), Color.white));
            lines.Add(new KeyValuePair<string, Color>(check.HighDone ? HighLine + ": готово" : HighLine, check.HighDone ? green : Color.white));
            lines.Add(new KeyValuePair<string, Color>(check.LowDone ? LowLine + ": готово" : LowLine, check.LowDone ? green : Color.white));
            if (check.Passed && !otherPassed) lines.Add(new KeyValuePair<string, Color>("Ждём второго игрока", green));
            float total = gap;
            foreach (var line in lines) total += checkStyle.CalcHeight(new GUIContent(line.Key), width) + gap;
            var box = new Rect(half.x + pad * 0.5f, half.y + half.height * 0.10f, half.width - pad, total + gap);
            GUI.color = new Color(0f, 0f, 0f, 0.55f);
            GUI.DrawTexture(box, Texture2D.whiteTexture);
            GUI.color = Color.white;
            float y = box.y + gap;
            foreach (var line in lines)
            {
                float height = checkStyle.CalcHeight(new GUIContent(line.Key), width);
                checkStyle.normal.textColor = line.Value;
                OutlinedLabel(new Rect(half.x + pad, y, width, height), line.Key, checkStyle);
                y += height + gap;
            }
        }

        // --- внутреннее ---

        // Счёт для показа: --debug-score подменяет только экран, в BuildResult идут настоящие очки правил.
        int ShownScoreLeft { get { return hasDebugScore ? debugScoreLeft : rules != null && CurrentStage != Stage.Tutorial ? rules.ScoreLeft : 0; } }
        int ShownScoreRight { get { return hasDebugScore ? debugScoreRight : rules != null && CurrentStage != Stage.Tutorial ? rules.ScoreRight : 0; } }

        void ResolvePlayers()
        {
            playerLeft = Launch.BySide(NeurotlonProtocol.SideLeft);
            playerRight = Launch.BySide(NeurotlonProtocol.SideRight);
            signalLeft = Launch.SignalOf(playerLeft);
            signalRight = Launch.SignalOf(playerRight);
        }

        static string NameOf(LaunchParticipant p)
        {
            if (p == null) return "";
            return string.IsNullOrEmpty(p.display_name) ? p.code : p.display_name;
        }

        float ZFor(float signal)
        {
            return (signal - 0.5f) * 2f * tuning.PaddleRange;
        }

        float BallRadius()
        {
            return tuning.BallRadius;
        }

        string Caption()
        {
            switch (CurrentStage)
            {
                case Stage.Connecting: return "ПОДКЛЮЧЕНИЕ";
                case Stage.Tutorial: return "ОБУЧЕНИЕ";
                case Stage.Check: return "ПРОВЕРКА";
                case Stage.Countdown: return "ПРИГОТОВЬТЕСЬ";
                case Stage.SensorLost: return "ПАУЗА";
                case Stage.ConfirmAbort: return "ПАУЗА";
                case Stage.Finished: return "ИГРА ОКОНЧЕНА";
            }
            if (rules == null) return "";
            if (matchIntroLeft > 0f) return "МАТЧ";
            if (rules.Phase == PongPhase.Over) return "ПОБЕДА";
            if (rules.Overtime) return "ЗОЛОТОЙ МЯЧ";
            return "ДО " + tuning.TargetScore;
        }

        string Hint()
        {
            if (rules == null || CurrentStage != Stage.Playing) return "";
            if (rules.Phase == PongPhase.Over) return NameOf(rules.Winner == Side.Left ? playerLeft : playerRight);
            if (rules.Phase == PongPhase.Serving) return "подача: " + NameOf(rules.Server == Side.Left ? playerLeft : playerRight);
            return "";
        }

        // Насколько ракетка отводится в замах: чем ближе летящий к ней мяч, тем сильнее (0…1). Это реакция на игру, не на ЭМГ.
        float Anticipation(Side side)
        {
            if (rules == null) return 0f;
            if (rules.Phase == PongPhase.Serving)
            {
                // подающий готовится: к удару ракетка понемногу отводится в замах
                if (rules.Server != side) return 0f;
                return Mathf.Clamp01(0.3f + 0.7f * (1f - rules.ServeTimeLeft / tuning.ServeDelay));
            }
            if (rules.Phase != PongPhase.Rally) return 0f;
            bool incoming = side == Side.Left ? rules.VelX < 0f : rules.VelX > 0f;
            if (!incoming) return 0f;
            float plane = tuning.PaddleX - tuning.PaddleFaceInset;
            return Mathf.Clamp01(1f - (plane - Mathf.Abs(rules.BallX)) / 0.55f);
        }

        // Где мяч пересечёт линию ракетки относительно неё: +1 справа от игрока (форхенд), -1 слева (бэкхенд).
        // Игрок слева смотрит вдоль +X, «вправо» для него — это -Z; игрок справа смотрит вдоль -X, «вправо» — +Z.
        float Lateral(Side side, float paddleZ)
        {
            if (rules == null || rules.Phase != PongPhase.Rally) return 0f;
            bool incoming = side == Side.Left ? rules.VelX < 0f : rules.VelX > 0f;
            if (!incoming) return 0f;
            float plane = tuning.PaddleX - tuning.PaddleFaceInset;
            float secondsToPlane = Mathf.Max(0f, plane - Mathf.Abs(rules.BallX)) / Mathf.Max(0.1f, Mathf.Abs(rules.VelX));
            float arrivalZ = Mathf.Clamp(rules.BallZ + rules.VelZ * secondsToPlane, -tuning.HalfWidth, tuning.HalfWidth);
            float right = side == Side.Left ? -1f : 1f;
            return Mathf.Clamp((arrivalZ - paddleZ) * right / (tuning.HitHalfHeight * 1.6f), -1f, 1f);
        }

        // Ход удара ракетки от 0 до 1. Контакт с мячом приходится ровно на отбитие: ракетка начинает бить за
        // ContactFraction * HitPulseSeconds секунд до него, а после отбития доигрывает выход вперёд и возврат.
        float Swing(Side side, float pulseRemaining)
        {
            if (pulseRemaining > 0f) return 1f - pulseRemaining / HitPulseSeconds;
            if (rules == null) return 0f;
            float preSeconds = PaddleAnimator.ContactFraction * HitPulseSeconds;
            float secondsToContact = -1f;
            if (rules.Phase == PongPhase.Serving && rules.Server == side)
            {
                secondsToContact = rules.ServeTimeLeft;
            }
            else if (rules.Phase == PongPhase.Rally && (side == Side.Left ? rules.VelX < 0f : rules.VelX > 0f))
            {
                float plane = tuning.PaddleX - tuning.PaddleFaceInset;
                secondsToContact = Mathf.Max(0f, plane - Mathf.Abs(rules.BallX)) / Mathf.Max(0.1f, Mathf.Abs(rules.VelX));
            }
            if (secondsToContact >= 0f && secondsToContact < preSeconds)
                return PaddleAnimator.ContactFraction * (1f - secondsToContact / preSeconds);
            return 0f;
        }

        void OnRulesEvent(PongEvent e)
        {
            if (sounds != null) sounds.Play(e.Kind);
            if (e.Kind == PongEventKind.PaddleHit)
            {
                // удар уже идёт с момента контакта (ContactFraction), поэтому остаток длительности короче
                float remaining = HitPulseSeconds * (1f - PaddleAnimator.ContactFraction);
                if (e.Side == Side.Left) pulseLeft = remaining; else pulseRight = remaining;
            }
        }

        void PlaceObjects(float dt = 0f)
        {
            float paddleY = tableTop + PaddleCenterHeight;
            float now = Time.unscaledTime;
            var leftPosition = new Vector3(-tuning.PaddleX, paddleY, zLeft);
            var rightPosition = new Vector3(tuning.PaddleX, paddleY, zRight);
            float anticipationLeft = Anticipation(Side.Left), anticipationRight = Anticipation(Side.Right);
            float lateralLeft = Lateral(Side.Left, zLeft), lateralRight = Lateral(Side.Right, zRight);
            float swingLeft = Swing(Side.Left, pulseLeft), swingRight = Swing(Side.Right, pulseRight);
            animLeft.Apply(paddleLeft, leftPosition, anticipationLeft, lateralLeft, swingLeft, now, dt);
            animRight.Apply(paddleRight, rightPosition, anticipationRight, lateralRight, swingRight, now, dt);
            // у каждой камеры своя копия ракетки: поза и анимация подобраны под её ракурс
            if (paddleLeftFpv != null) animLeftFpv.Apply(paddleLeftFpv, leftPosition, anticipationLeft, lateralLeft, swingLeft, now, dt);
            if (paddleRightFpv != null) animRightFpv.Apply(paddleRightFpv, rightPosition, anticipationRight, lateralRight, swingRight, now, dt);
            if (rules == null)
            {
                ball.position = new Vector3(-(tuning.PaddleX - tuning.PaddleFaceInset - 0.02f), ballY, zLeft);
                return;
            }
            float x = rules.BallX;
            float baseY = tableTop + tuning.BallRadius + BallArcHeight;       // на высоте ракеток
            bool flyingPast = (rules.Phase == PongPhase.PointPause || rules.Phase == PongPhase.Over) && Mathf.Abs(x) > tuning.HalfLength;
            if (rules.Phase == PongPhase.Serving)
            {
                // подача: мяч подбрасывается над ракеткой и к моменту удара возвращается на её высоту
                float p = Mathf.Clamp01(1f - rules.ServeTimeLeft / tuning.ServeDelay);
                ballY = baseY + ServeTossHeight * Mathf.Sin(p * Mathf.PI);
            }
            else if (!flyingPast)
            {
                // дуга с отскоками от стола; у краёв стола мяч на высоте ракеток, а не падает
                float t = Mathf.Clamp01((x + tuning.HalfLength) / (2f * tuning.HalfLength));
                float arc = Mathf.Cos(2f * Mathf.PI * t);
                ballY = tableTop + tuning.BallRadius + BallArcHeight * Mathf.Abs(arc);
                if (rules.Phase == PongPhase.Rally && Mathf.Abs(x) <= tuning.HalfLength && arc * previousArcSign < 0f && sounds != null) sounds.PlayTableBounce();
                previousArcSign = arc >= 0f ? 1f : -1f;
            }
            else
            {
                ballY = Mathf.MoveTowards(ballY, FloorBallHeight, 2.5f * dt);     // мяч пролетел мимо и падает
            }
            ball.position = new Vector3(x, ballY, rules.BallZ);
        }
    }
}
