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
        PongRules rules;
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
        GUIStyle hudName, hudScore;

        void Awake()
        {
            ballY = tableTop + BallRadius() + BallArcHeight;
            PlaceObjects();
        }

        void LateUpdate()
        {
            if (Launch == null) return;
            if (playerLeft == null) ResolvePlayers();
            if (scoreboard != null) scoreboard.Show(NameOf(playerLeft), NameOf(playerRight), ScoreLeft, ScoreRight, Caption(), Hint());
        }

        // --- что реализует игра ---

        protected override void OnGameStart()
        {
            if (playerLeft == null) ResolvePlayers();
            var random = new System.Random();
            rules = new PongRules(tuning, () => (float)random.NextDouble(), Side.Left);
            rules.Raised += OnRulesEvent;
            zLeft = 0f;
            zRight = 0f;
            targetLeft = 0.5f;
            targetRight = 0.5f;
        }

        protected override void OnGameUpdate(float dt)
        {
            float? l = Bridge.Value(signalLeft);
            float? r = Bridge.Value(signalRight);
            if (l.HasValue) targetLeft = Mathf.Clamp01(l.Value);      // сигнала нет: ракетка стоит на месте
            if (r.HasValue) targetRight = Mathf.Clamp01(r.Value);
            // критическое затухание: плавно и без дрожи даже при шумном сигнале
            zLeft = Mathf.SmoothDamp(zLeft, ZFor(targetLeft), ref zLeftVelocity, FollowSmoothSeconds, MaxPaddleSpeed, dt);
            zRight = Mathf.SmoothDamp(zRight, ZFor(targetRight), ref zRightVelocity, FollowSmoothSeconds, MaxPaddleSpeed, dt);

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
            if (displays != null && !displays.ShowsPlayers) return;     // в виде «только зрители» подсказок игроков нет
            if (hudName == null)
            {
                hudName = new GUIStyle(GUI.skin.label) { fontSize = 30, fontStyle = FontStyle.Bold, wordWrap = false, clipping = TextClipping.Clip };
                hudScore = new GUIStyle(GUI.skin.label) { fontSize = 84, fontStyle = FontStyle.Bold, wordWrap = false, alignment = TextAnchor.UpperCenter };
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
            float nameWidth = Mathf.Max(160f, area.width * 0.2f);
            hudName.alignment = TextAnchor.UpperRight;
            GUI.Label(new Rect(cx - 90f - nameWidth, area.y + 26f, nameWidth, 44f), NameOf(playerLeft), hudName);
            hudName.alignment = TextAnchor.UpperLeft;
            GUI.Label(new Rect(cx + 90f, area.y + 26f, nameWidth, 44f), NameOf(playerRight), hudName);
            GUI.Label(new Rect(cx - 85f, area.y + 10f, 170f, 110f), ScoreLeft + ":" + ScoreRight, hudScore);
        }

        // --- внутреннее ---

        int ScoreLeft { get { return rules != null ? rules.ScoreLeft : 0; } }
        int ScoreRight { get { return rules != null ? rules.ScoreRight : 0; } }

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
                case Stage.Calibrating: return "КАЛИБРОВКА";
                case Stage.Countdown: return "ПРИГОТОВЬТЕСЬ";
                case Stage.SensorLost: return "ПАУЗА";
                case Stage.ConfirmAbort: return "ПАУЗА";
                case Stage.Finished: return "ИГРА ОКОНЧЕНА";
            }
            if (rules == null) return "";
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
        // Игрок слева смотрит вдоль +X, его правая рука — это -Z; игрок справа смотрит вдоль -X, правая рука — +Z.
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
