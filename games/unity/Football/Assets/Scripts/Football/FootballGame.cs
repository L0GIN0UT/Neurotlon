using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Футбольная полоса: четыре элемента по очереди на одном поле. Камера всегда сзади мяча. Управление: напряжение мышцы
    // с датчиком (ЭМГ, сигнал `emg`) и сосредоточение (ЭЭГ, сигнал `eeg`). Запуск, мост, калибровку, отсчёт, паузу и результат делает
    // NeurotlonGame; здесь правила (FootballRules), картинка, звук и экран игрока.
    public sealed class FootballGame : NeurotlonGame
    {
        enum Phase { Intro, Playing, Result }

        const float IntroSeconds = 1.8f;
        const float SandboxPhaseSeconds = 0.8f;     // в песочнице обучения заставка и итог элемента короткие
        const float ResultSeconds = 1.8f;
        const float RetryShowSeconds = 1.0f;
        const float EndDelaySeconds = 1.2f;
        const float CameraHeight = 1.6f;
        const float CameraBack = 2.3f;
        const float CameraBackAimed = 1.7f;               // у цели камера стоит ближе к мячу: мишень и ворота крупнее
        const float CameraSmoothSeconds = 0.55f;
        const int RingSegments = 64;

        [Header("Объекты сцены")]
        [SerializeField] Transform ball;
        [SerializeField] Transform[] cones;
        [SerializeField] Camera viewCamera;
        [SerializeField] FootballSounds sounds;
        [SerializeField] FootballNet goalNet;           // сетка ворот (прогибается от мяча)
        [SerializeField] FootballNet stopNet;           // сетка-занавес за зоной остановки (прогибается от мяча)
        [SerializeField] FootballTarp tarp;             // мягкий чехол ворот (прогибается от мяча)
        [SerializeField] Material reticleMaterial;      // прозрачный материал без освещения для колец прицела

        static readonly Color Ink = new Color(0.02f, 0.03f, 0.07f, 0.92f);
        static readonly Color Cyan = new Color(0.25f, 0.92f, 1f, 1f);
        static readonly Color Good = new Color(0.15f, 1f, 0.40f, 1f);
        static readonly Color Okay = new Color(1f, 0.56f, 0.04f, 1f);
        static readonly Color Bad = new Color(0.95f, 0.35f, 0.35f, 1f);
        static readonly Color PlaqueFill = new Color(0.03f, 0.06f, 0.13f, 0.90f);
        static readonly Color PlaqueEdge = new Color(0.30f, 0.88f, 1f, 1f);
        static readonly Color Cream = new Color(0.94f, 0.97f, 1f, 1f);
        static readonly Color Gold = new Color(1f, 0.80f, 0.10f, 1f);

        readonly FootballTuning tuning = new FootballTuning();
        readonly System.Random random = new System.Random();
        readonly int[] elementPoints = { -1, -1, -1, -1 };
        FootballRules rules;
        Phase phase;
        float phaseTimer;
        float endTimer = -1f;
        bool worldReady;                                  // сцена и физика мяча подготовлены (один раз: для обучения и для игры)
        bool tutorialActive;                              // идёт обучение: песочница на отдельных правилах, очки в результат не идут
        bool tutorialPlay;                                // идёт попытка шага: правила песочницы работают (пока читают подсказку, стоят)
        FootballTutorial tutorial;                        // условия «шаг обучения засчитан»
        TutorialStep[] tutorialSteps = new TutorialStep[0];
        float retryTimer;                                 // показывается «Попробуйте ещё раз»: песочница стоит, потом заводится заново
        int debugScore = -1;                              // --debug-score N: показать этот счёт вместо настоящего (только подпись)
        FootballElement shown;                           // элемент, который сейчас показывается
        float lastEmg;
        string resultText = "";
        FootballElement resultElement;
        int resultPoints;
        int bonusShown = -1;

        // мяч и камера
        Vector3 ballPos;
        Vector3 lastBallPos;
        Vector3 camPos, camLook;
        bool camReady;
        Vector3 flightFrom, flightTo;
        Vector3 ballScale = Vector3.one;
        bool ballVisible = true;
        float ballScaleK = 1f;
        readonly List<SpentBall> spentBalls = new List<SpentBall>();
        Rigidbody ballProxy;                              // физическое тело мяча на змейке: толкает конусы по-настоящему
        SphereCollider ballProxyCollider;
        float stopHitAge = -1f;                           // сколько секунд прошло с удара мяча о сетку остановки (−1 — удара не было)
        float stopHitSpeed;
        Vector3 stopRest;
        bool stopNetPressed;
        const int StopNetContact = 9001;
        FootballDemo demo;                                // автоигрок для демонстрационных видео (--demo right|wrong)
        FootballCone[] coneBodies;                        // конусы-твёрдые тела: мяч даёт им импульс, дальше работает физика

        // Пробитый мяч живёт по физике: скорость при ударе берётся из полёта, дальше гравитация, отскок от чехла или мишени,
        // отскок от земли, качение с трением; в сетке ворот мяч быстро гаснет. На следующую попытку берётся новый мяч.
        sealed class SpentBall
        {
            public Transform body;
            public Vector3 pos, vel;
            public bool entered;                       // мяч влетел в ворота через проём
            public bool resting;
            public bool tarpHit;                       // мячу ещё предстоит удар о ткань чехла
            public bool inContact;
            public int netMask;                         // с какими поверхностями сетки мяч сейчас в контакте (биты: задняя стенка, боковина, крыша)
            public float lastBumpTime = -1f;           // когда мяч в последний раз ударился о другой мяч (чтобы звук не стрекотал)
            public int contactId;
        }

        const float Gravity = 9.81f;
        int contactSeq;
        const float SpentBallRestitution = 0.6f;  // упругость удара мяча о мяч
        const float GroundBounce = 0.55f;         // доля вертикальной скорости, остающаяся после отскока от земли
        const float RollingDecel = 1.5f;          // торможение катящегося мяча, м/с²
        const float TarpStiffness = 1500f;        // жёсткость ткани (пружина), 1/с²: мяч глубже вдавливает при сильном ударе
        const float TarpDamping = 24f;            // затухание: после отскока остаётся около трети скорости
        const float BoardBounce = 0.34f;          // жёсткая мишень отдаёт больше
        const float NetDrag = 1.6f;               // 1/с: сопротивление воздуха и нитей, основное торможение даёт пружина сетки
        const float NetStiffness = 650f;          // пружина сетки: мяч вдавливает её и отскакивает мягко
        const float NetDamping = 11f;
        const float NetMaxStretch = 0.30f;        // дальше этого сетка мяч не пропускает совсем               // 1/с: в сетке скорость падает быстро

        // кольца прицела и подсказки
        LineRenderer zoneRing, zoneBack, aimRing, aimBack, stopRing, stopBack, beatRing, beatBack, holeRing, holeBack;
        Transform dot, dotBack;
        GUIStyle nameStyle, scoreStyle, labelStyle, bigStyle, midStyle, popupStyle, hintStyle;
        float lastBeat = -1f;
        int attemptPoints;                                // очки последней попытки для всплывающей подписи
        int attemptNumber;
        float attemptTimer;

        // ---------- запуск ----------

        void Awake()
        {
            if (System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "--fps") >= 0) gameObject.AddComponent<FootballFpsMeter>();
            string mode = ReadArg("--dribble");
            if (mode == "throttle") tuning.Dribble = DribbleMode.Throttle;
            else if (mode == "rhythm") tuning.Dribble = DribbleMode.Rhythm;
            int parsedScore;
            if (int.TryParse(ReadArg("--debug-score"), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out parsedScore) && parsedScore >= 0)
                debugScore = parsedScore;
            zoneBack = Ring("ЗонаРазбросаОбводка", 0.030f, Ink, 1);
            zoneRing = Ring("ЗонаРазброса", 0.016f, Good, 2);
            aimBack = Ring("ПрицелОбводка", 0.026f, Ink, 3);
            aimRing = Ring("Прицел", 0.012f, Cyan, 4);
            stopBack = Ring("ОстановкаОбводка", 0.07f, Ink, 1);
            stopRing = Ring("Остановка", 0.04f, Okay, 2);
            beatBack = Ring("ТактОбводка", 0.07f, Ink, 1);
            beatRing = Ring("Такт", 0.04f, Cyan, 2);
            holeBack = Ring("ЦельОбводка", 0.075f, Ink, 1);
            holeRing = Ring("Цель", 0.045f, Gold, 2);
            dotBack = Quad("ТочкаОбводка", DiscTexture(), Ink);
            dot = Quad("Точка", DiscTexture(), Cyan);
            HideAll();
        }

        protected override void OnGameStart()
        {
            PrepareWorld();
            tutorialActive = false;
            tutorialPlay = false;
            var real = new FootballRules(tuning, () => (float)random.NextDouble());
            if (Launch.MaxPoints > 0) real.MaxPoints = Launch.MaxPoints;
            StartRules(real);
        }

        // Сцена и физика мяча: один раз на запуск, и для обучения, и для игры.
        void PrepareWorld()
        {
            if (worldReady) return;
            worldReady = true;
            if (ball != null) ballScale = ball.localScale;
            if (cones != null)
            {
                coneBodies = new FootballCone[cones.Length];
                for (int i = 0; i < cones.Length; i++)
                    if (cones[i] != null) coneBodies[i] = cones[i].GetComponent<FootballCone>();
            }
            string demoMode = ReadArg("--demo");
            if (demoMode == "right" || demoMode == "wrong") demo = new FootballDemo(demoMode == "right", tuning);
            CreateBallProxy();
        }

        // Запустить правила (песочницы обучения или игры) с чистого листа: очки, надписи и физика прошлого прогона не переходят.
        void StartRules(FootballRules next)
        {
            rules = next;
            rules.Raised += OnRulesEvent;
            for (int i = 0; i < elementPoints.Length; i++) elementPoints[i] = -1;
            endTimer = -1f;
            bonusShown = -1;
            resultText = "";
            attemptTimer = 0f;
            EnterIntro(rules.Current.Kind);
        }

        // ---------- обучение: все механики по очереди, каждая в своей песочнице; шаг 4 это проверка «попади сам» ----------

        protected override string[] TutorialSteps()
        {
            tutorial = new FootballTutorial(tuning);
            tutorialSteps = FootballTutorial.StepsFor(tuning.Dribble);
            var texts = new string[tutorialSteps.Length];
            for (int i = 0; i < texts.Length; i++) texts[i] = FootballTutorial.TextFor(tutorialSteps[i], tuning.Dribble);
            return texts;
        }

        TutorialStep StepAt(int index)
        {
            return tutorialSteps[Mathf.Clamp(index, 0, tutorialSteps.Length - 1)];
        }

        protected override bool TutorialStepSkippable(int index)
        {
            return FootballTutorial.IsSkippable(StepAt(index));
        }

        protected override float TutorialStepTimeout(int index)
        {
            return FootballTutorial.TimeoutFor(StepAt(index));
        }

        // Шаг начался (первый раз или повтор после неудачи за таймаут): песочница заводится заново и ждёт. Пока подсказку читают,
        // камера доезжает, сцена видна, а правила стоят.
        protected override void OnTutorialStepStart(int index)
        {
            BeginTutorialSandbox(StepAt(index), false);
        }

        // Чтение закончилось или повтор: счётчики шага с нуля, правила пошли.
        protected override void OnTutorialTryStart(int index)
        {
            tutorial.Begin(StepAt(index));
            tutorialPlay = true;
        }

        // Песочница шага: короткие правила на копии настроек (два конуса, одна попытка, у «попади сам» пять), мяч, конусы,
        // пробитые мячи, чехол и сети сброшены. play: правила идут сразу (повтор) или ждут начала попытки.
        void BeginTutorialSandbox(TutorialStep step, bool play)
        {
            PrepareWorld();
            tutorialActive = true;
            tutorialPlay = play;
            retryTimer = 0f;
            tutorial.Begin(step);
            ClearSpent();
            ResetCones();
            var sandbox = tuning.CopyForTutorial(FootballTutorial.SandboxCones, FootballTutorial.AttemptsFor(step));
            StartRules(new FootballRules(sandbox, () => (float)random.NextDouble(), SandboxOrder(step)));
        }

        static int[] SandboxOrder(TutorialStep step)
        {
            switch (step)
            {
                case TutorialStep.Focus:
                case TutorialStep.Shot:
                case TutorialStep.Hits: return new[] { 3 };
                case TutorialStep.Gate: return new[] { 1 };
                case TutorialStep.Slow:
                case TutorialStep.StopZone: return new[] { 2 };
                default: return new[] { 0 };
            }
        }

        protected override bool OnTutorialUpdate(int index, float dt)
        {
            if (!tutorialActive || rules == null) return false;
            if (retryTimer > 0f)
            {
                // попытка провалена: песочница стоит, видна подпись; потом начинается заново, без ожидания таймаута
                retryTimer -= dt;
                if (retryTimer <= 0f) BeginTutorialSandbox(tutorial.Step, true);
                else UpdateVisuals(dt);
                return false;
            }
            StepGame(dt);
            if (!tutorialPlay) return false;
            if (!tutorial.Retry) ObserveTutorial(dt);
            if (tutorial.Retry)
            {
                retryTimer = RetryShowSeconds;
                return false;
            }
            return tutorial.Done;
        }

        // Что видно в песочнице сейчас: концентрация и скорость катящегося мяча. Остальные события приходят из правил сами.
        void ObserveTutorial(float dt)
        {
            if (phase != Phase.Playing) return;
            var aimed = rules.Current as AimedElement;
            if (aimed != null) tutorial.ObserveConcentration(aimed.Concentration, dt);
            var stop = rules.Current as StopElement;
            if (stop != null) tutorial.ObserveStopSpeed(stop.Speed, stop.HitNet);
        }

        // Обучение закончилось: песочницу убрать, мяч и конусы на места.
        protected override void OnTutorialEnd()
        {
            tutorialActive = false;
            tutorialPlay = false;
            retryTimer = 0f;
            ClearSpent();
            ResetCones();
            HideAll();
        }

        // Шкалы под подсказкой (подсказку и «Готово» рисует кит): нижняя плашка; верхняя только на шаге «попади сам».
        // Подсказка обучения стоит слева (там свободно), чтобы не закрывать ворота, мишень и мяч.
        protected override Rect TutorialHintArea
        {
            get { return new Rect(Screen.width * 0.02f, Screen.height * 0.34f, Screen.width * 0.28f, 0f); }
        }

        protected override void DrawTutorial(int index)
        {
            float s = Screen.height / 1080f;
            float w = Screen.width, h = Screen.height;
            EnsureStyles(s);
            float plaqueW = Mathf.Min(w * 0.94f, 1180f * s);
            float px = (w - plaqueW) * 0.5f;
            var bottom = new Rect(px, h - 20f * s - 112f * s, plaqueW, 112f * s);
            Plaque(bottom, s);
            DrawBars(bottom, s);
            if (StepAt(index) == TutorialStep.Hits) DrawHitsCounter(new Rect(px, 20f * s, plaqueW, 88f * s), s);
            if (retryTimer > 0f)
            {
                DrawNotice(NeurotlonTexts.TutorialRepeat, 0.40f);
            }
        }

        // Шаг «попади сам»: в верхней плашке подпись «Попаданий: n из 2», под ней точки попыток как в игре.
        void DrawHitsCounter(Rect top, float s)
        {
            Plaque(top, s);
            nameStyle.alignment = TextAnchor.MiddleCenter;
            OutlinedLabel(top, FootballTutorial.HitsText(tutorial.Hits.Hits), nameStyle);
            int used = tutorial.Hits.Used;
            DrawAttemptDots(top, s, TutorialHits.MaxAttempts, used < TutorialHits.MaxAttempts ? used : -1, tutorial.Hits.ResultOf);
        }

        protected override void OnGameUpdate(float dt)
        {
            StepGame(dt);
        }

        // Ход игры или песочницы обучения: сигналы, фазы (заставка, игра, итог элемента), картинка.
        void StepGame(float dt)
        {
            float? eeg = Bridge.Value(NeurotlonProtocol.SignalEeg);
            float? emg = Bridge.Value(NeurotlonProtocol.SignalEmg);
            if (demo != null)
            {
                float demoEeg, demoEmg;
                if (phase == Phase.Playing) demo.Step(dt);                // часы автоигрока идут, только пока идут правила: иначе «расслабление» истекает ещё в заставке
                demo.Signals(rules, out demoEeg, out demoEmg);
                eeg = demoEeg;
                emg = demoEmg;
            }
            if (emg.HasValue) lastEmg = emg.Value;
            if (tutorialActive && tutorial.Step == TutorialStep.Focus) emg = null;      // шаг сосредоточения: ударов нет, только круг разброса
            if (!tutorialActive) HandleKeys();
            phaseTimer -= dt;
            attemptTimer -= dt;
            switch (phase)
            {
                case Phase.Intro:
                    if (phaseTimer <= 0f) phase = Phase.Playing;
                    break;
                case Phase.Playing:
                    if (!tutorialActive || tutorialPlay) rules.Step(dt, eeg, emg);          // пока читают подсказку, правила песочницы стоят
                    break;
                case Phase.Result:
                    if (phaseTimer <= 0f)
                    {
                        if (rules.Over)
                        {
                            // песочница кончилась, а механика не сработала (мяч упёрся в сетку и т. п.): завести заново
                            if (tutorialActive) tutorial.MarkRetry();
                            else if (endTimer < 0f) endTimer = EndDelaySeconds;
                        }
                        else EnterIntro(rules.Current.Kind);
                    }
                    break;
            }
            if (endTimer >= 0f)
            {
                endTimer -= dt;
                if (endTimer <= 0f) FinishGame();
            }
            UpdateVisuals(dt);
        }

        protected override IList<ResultEntryData> BuildResult()
        {
            int points = rules.Score;
            if (Launch.MaxPoints > 0) points = Mathf.Min(points, Launch.MaxPoints);
            return new List<ResultEntryData> { NeurotlonResult.Completed(Launch.Participants[0].code, points) };
        }

        protected override bool DrawsOwnTimer { get { return true; } }

        protected override string FinishedMessage()
        {
            return rules == null ? base.FinishedMessage() : "Результат: " + rules.Score + " из 10";
        }

        // ---------- события правил ----------

        void OnRulesEvent(FootballEvent e)
        {
            if (tutorialActive) tutorial.ObserveEvent(e);
            if (sounds != null) sounds.Play(e);
            switch (e.Kind)
            {
                case FootballEventKind.Touch:
                    break;                                    // звук касания играет FootballSounds; конус толкает физика
                case FootballEventKind.Kick:
                    flightFrom = ballPos;
                    flightTo = AimedEnd(e.Element);
                    break;
                case FootballEventKind.Landed:
                    if (e.Element == FootballElement.Stop)
                    {
                        var stopping = rules.Current as StopElement;
                        if (stopping != null && stopping.HitNet)
                        {
                            if (sounds != null) sounds.Impact(FootballSurface.Net, 3f);
                            stopHitAge = 0f;
                            stopHitSpeed = stopping.ImpactSpeed;
                            stopRest = StartPosition(FootballElement.Stop) + Vector3.left * stopping.Distance;
                            stopNetPressed = false;
                        }
                    }
                    if (e.Element == FootballElement.Pass || e.Element == FootballElement.Kick)
                    {
                        var attempt = rules.Current as AimedElement;
                        attemptPoints = e.Points;
                        attemptNumber = attempt != null ? attempt.Attempt + 1 : 1;
                        attemptTimer = 1.4f;
                    }
                    if (e.Element == FootballElement.Pass || e.Element == FootballElement.Kick) SpawnSpent(e.Element, e.Points);
                    break;
                case FootballEventKind.ElementFinished:
                    elementPoints[(int)e.Element] = e.Points;
                    resultPoints = e.Points;
                    resultText = "готово";
                    resultElement = e.Element;
                    phase = Phase.Result;
                    phaseTimer = tutorialActive ? SandboxPhaseSeconds : ResultSeconds;
                    break;
                case FootballEventKind.GameOver:
                    bonusShown = rules.AccuracyBonus;
                    break;
            }
        }

        void EnterIntro(FootballElement kind)
        {
            ClearSpent();
            stopHitAge = -1f;
            if (stopNet != null) stopNet.Release(StopNetContact);
            if (kind == FootballElement.Snake) ResetCones();
            shown = kind;
            phase = Phase.Intro;
            phaseTimer = tutorialActive ? SandboxPhaseSeconds : IntroSeconds;
            ballPos = StartPosition(kind);
            lastBallPos = ballPos;
            if (ball != null) ball.position = ballPos;
            if (!camReady) camPos = Vector3.zero;
            var pose = CameraPose(kind);
            if (!camReady) { camPos = pose.pos; camLook = pose.look; camReady = true; }
        }

        void HandleKeys()
        {
            if (rules == null || rules.CurrentIndex != 0) return;
            try
            {
                if (Input.GetKeyDown(KeyCode.F1)) Switch(DribbleMode.Level);
                else if (Input.GetKeyDown(KeyCode.F2)) Switch(DribbleMode.Throttle);
                else if (Input.GetKeyDown(KeyCode.F3)) Switch(DribbleMode.Rhythm);
            }
            catch (System.InvalidOperationException) { }              // старая система ввода выключена: клавиши недоступны
        }

        void Switch(DribbleMode mode)
        {
            if (rules.SwitchDribble(mode)) EnterIntro(FootballElement.Snake);
        }

        // ---------- положения ----------

        static Vector3 StartPosition(FootballElement kind)
        {
            Vector3 p;
            switch (kind)
            {
                case FootballElement.Pass: p = FootballLayout.PassBall; break;
                case FootballElement.Stop: p = FootballLayout.StopBall; break;
                case FootballElement.Kick: p = FootballLayout.KickBall; break;
                default: p = FootballLayout.SnakeBall; break;
            }
            p.y = FootballLayout.BallRadius;
            return p;
        }

        static Vector3 Forward(FootballElement kind)
        {
            switch (kind)
            {
                case FootballElement.Pass: return Vector3.right;
                case FootballElement.Stop: return Vector3.left;
                default: return Vector3.forward;
            }
        }

        struct Pose { public Vector3 pos, look; }

        Pose CameraPose(FootballElement kind)
        {
            Vector3 f = Forward(kind);
            Vector3 b = StartPosition(kind);
            var pose = new Pose();
            if (kind == FootballElement.Snake && rules != null && phase != Phase.Intro && rules.CurrentIndex == 0)
            {
                pose.pos = new Vector3(ballPos.x * 0.35f, CameraHeight, ballPos.z - CameraBack);
                pose.look = new Vector3(ballPos.x * 0.6f, 0.15f, ballPos.z + 3.2f);
                return pose;
            }
            if (kind == FootballElement.Stop && phase != Phase.Intro)
            {
                // едет вслед за мячом (на 70 % его пути): мяч не уменьшается до точки, а удар о сетку виден крупно
                Vector3 anchor = Vector3.Lerp(b, ballPos, 0.7f);
                pose.pos = new Vector3(anchor.x - f.x * CameraBack, CameraHeight, anchor.z - f.z * CameraBack);
                float lookX = Mathf.Lerp(FootballLayout.ZoneCentre.x, FootballLayout.StopNet.x, 0.5f);
                pose.look = new Vector3(lookX, 0.2f, FootballLayout.ZoneCentre.z);
                return pose;
            }
            float back = (kind == FootballElement.Pass || kind == FootballElement.Kick) ? CameraBackAimed : CameraBack;
            pose.pos = new Vector3(b.x - f.x * back, CameraHeight, b.z - f.z * back);
            switch (kind)
            {
                case FootballElement.Pass: pose.look = new Vector3(FootballLayout.GoalMouth.x, 0.6f, FootballLayout.GoalMouth.z); break;
                case FootballElement.Stop: pose.look = new Vector3(FootballLayout.ZoneCentre.x + 1f, 0.15f, FootballLayout.ZoneCentre.z); break;
                case FootballElement.Kick: pose.look = new Vector3(0f, 1.0f, FootballLayout.TargetBase.z); break;
                default: pose.look = new Vector3(0f, 0.15f, FootballLayout.SnakeBall.z + 3.2f); break;
            }
            return pose;
        }

        Vector3 AimedEnd(FootballElement kind)
        {
            var a = rules.Current as AimedElement;
            if (a == null) return ballPos;
            if (kind == FootballElement.Pass)
            {
                var g = FootballLayout.GoalMouth;
                return new Vector3(g.x - 0.13f, Mathf.Max(FootballLayout.BallRadius, FootballLayout.GoalCentreHeight + a.HitZ), g.z - a.HitX);
            }
            var t = FootballLayout.TargetBase;
            return new Vector3(a.HitX, Mathf.Max(FootballLayout.BallRadius, tuning.TargetCentreZ + a.HitZ), t.z - 0.12f);
        }

        // ---------- картинка ----------

        void UpdateVisuals(float dt)
        {
            HideAll();
            if (rules == null || ball == null) return;
            ballVisible = true;
            ballScaleK = 1f;
            FootballElement kind = phase == Phase.Result ? shown : rules.Current.Kind;
            if (phase != Phase.Intro) shown = kind;
            switch (kind)
            {
                case FootballElement.Snake: VisualsSnake(dt); break;
                case FootballElement.Pass: VisualsAimed(dt, true); break;
                case FootballElement.Stop: VisualsStop(dt); break;
                default: VisualsAimed(dt, false); break;
            }
            Roll();
            ball.position = ballPos;
            ball.localScale = ballScale * ballScaleK;
            if (ball.gameObject.activeSelf != ballVisible) ball.gameObject.SetActive(ballVisible);
            UpdateSpent(dt);
            if (stopHitAge >= 0f) stopHitAge += dt;
            SyncBallProxy();
            UpdateCamera(dt);
        }

        void VisualsSnake(float dt)
        {
            if (phase == Phase.Intro) { ballPos = StartPosition(FootballElement.Snake); return; }
            var s = rules.Current as SnakeElement;
            if (s == null) return;
            ballPos = new Vector3(s.X, FootballLayout.BallRadius, s.Y);
            var rhythm = s.Dribble as RhythmDribble;
            if (rhythm != null && phase == Phase.Playing)
            {
                float phaseBeat = rhythm.BeatPhase;
                if (phaseBeat < lastBeat && sounds != null) sounds.Metronome();          // такт метронома
                lastBeat = phaseBeat;
                float r = 0.28f + 0.55f * (1f - phaseBeat);                               // кольцо сужается к мячу к моменту такта
                SetGroundRing(beatRing, beatBack, new Vector3(ballPos.x, 0.03f, ballPos.z), r, true);
            }
        }

        // Мяч упёрся в сетку-занавес: вдавливает её и мягко отходит (пружина с затуханием), сетка прогибается вместе с ним.
        void AnimateNetStop()
        {
            const float omega = 12f, damping = 3.5f;                  // мягкая сетка: вдавливание (около 0,25 м при ударе 3 м/с)
            const float rollDeceleration = 1.2f;                      // м/с²: мяч откатывается от сетки по траве и тормозит
            float pressTime = Mathf.PI / omega;                       // полупериод: пока мяч в сетке
            float p = 0f;
            if (stopHitAge <= pressTime)
            {
                p = stopHitSpeed / omega * Mathf.Exp(-damping * stopHitAge) * Mathf.Sin(omega * stopHitAge);   // > 0 — вглубь сетки
                ballPos = stopRest + Vector3.left * p;
            }
            else
            {
                float reboundSpeed = stopHitSpeed * Mathf.Exp(-damping * pressTime);                          // упругий отскок: около 0,4 скорости удара
                float t = Mathf.Min(stopHitAge - pressTime, reboundSpeed / rollDeceleration);
                ballPos = stopRest + Vector3.right * (reboundSpeed * t - 0.5f * rollDeceleration * t * t);
            }
            ballPos.y = FootballLayout.BallRadius;
            if (stopNet == null) return;
            if (p > 0f) { stopNet.Press(StopNetContact, ballPos, p, Vector3.left); stopNetPressed = true; }
            else if (stopNetPressed) { stopNet.Release(StopNetContact); stopNetPressed = false; }
        }

        void VisualsStop(float dt)
        {
            if (stopHitAge >= 0f && phase != Phase.Intro) { AnimateNetStop(); return; }
            Vector3 start = StartPosition(FootballElement.Stop);
            if (phase == Phase.Intro) { ballPos = start; return; }
            var s = rules.Current as StopElement;
            if (s != null && phase == Phase.Playing)
            {
                ballPos = start + Vector3.left * s.Distance;
                Vector3 stop = start + Vector3.left * s.PredictedStop;
                SetGroundRing(stopRing, stopBack, new Vector3(stop.x, 0.03f, stop.z), 0.32f, true);
            }
        }

        void VisualsAimed(float dt, bool pass)
        {
            FootballElement kind = pass ? FootballElement.Pass : FootballElement.Kick;
            if (phase == Phase.Intro) { ballPos = StartPosition(kind); return; }
            if (phase == Phase.Result)
            {
                ballVisible = false;                                  // последний мяч уже лежит на месте
                return;
            }
            var a = rules.Current as AimedElement;
            if (a == null) return;
            // плоскость цели, лицом к игроку
            Vector3 centre, right;
            if (pass)
            {
                centre = new Vector3(FootballLayout.GoalMouth.x - 0.05f, FootballLayout.GoalCentreHeight, FootballLayout.GoalMouth.z);
                right = new Vector3(0f, 0f, -1f);
            }
            else
            {
                centre = new Vector3(0f, tuning.TargetCentreZ, FootballLayout.TargetBase.z - 0.1f);
                right = Vector3.right;
            }
            Vector3 up = Vector3.up;
            if (a.Phase == AimedElement.PhaseKind.Flying)
            {
                float p = a.FlightProgress;
                Vector3 mid = (flightFrom + flightTo) * 0.5f + Vector3.up * 0.9f;
                ballPos = Bezier(flightFrom, mid, flightTo, p);
                return;
            }
            if (a.Phase == AimedElement.PhaseKind.Settling)
            {
                // пробитый мяч лежит копией; в конце паузы на отметке вырастает новый
                float t = a.SettleProgress;
                ballPos = StartPosition(kind);
                lastBallPos = ballPos;
                ballVisible = t >= 0.45f;
                ballScaleK = Mathf.SmoothStep(0.25f, 1f, Mathf.Clamp01((t - 0.45f) / 0.35f));
                if (pass) ShowTargetHole(a, centre, right, up);
                return;
            }
            ballPos = StartPosition(kind);
            Vector3 zoneCentre = centre + right * a.CentreX + up * a.CentreZ;
            Color zone = Color.HSVToRGB(Mathf.Lerp(0.07f, 0.40f, Mathf.Clamp01(a.Concentration)), 0.92f, 1f);
            zoneRing.startColor = zoneRing.endColor = zone;
            SetCircle(zoneBack, zoneCentre, right, up, a.Amplitude);
            SetCircle(zoneRing, zoneCentre, right, up, a.Amplitude);
            Vector3 aim = zoneCentre + right * a.AimX + up * a.AimZ;
            SetCircle(aimBack, aim, right, up, 0.07f);
            SetCircle(aimRing, aim, right, up, 0.07f);
            FaceCamera(dot, aim, 0.022f);
            FaceCamera(dotBack, aim, 0.034f);
            zoneRing.enabled = zoneBack.enabled = aimRing.enabled = aimBack.enabled = true;
            dot.gameObject.SetActive(true);
            dotBack.gameObject.SetActive(true);
            if (pass) ShowTargetHole(a, centre, right, up);
        }

        // Золотое кольцо вокруг отверстия, в которое надо бить; мигает, чтобы цель читалась сразу.
        void ShowTargetHole(AimedElement a, Vector3 centre, Vector3 right, Vector3 up)
        {
            Vector3 hole = centre + right * a.CentreX + up * a.CentreZ;
            float radius = tuning.TarpHoleRadius + 0.055f;
            SetCircle(holeBack, hole, right, up, radius);
            SetCircle(holeRing, hole, right, up, radius);
            float pulse = 0.65f + 0.35f * Mathf.Sin(Time.unscaledTime * 6f);
            holeRing.startColor = holeRing.endColor = new Color(Gold.r, Gold.g, Gold.b, pulse);
            holeRing.enabled = holeBack.enabled = true;
        }

        // Отскок от трубы рамы: жёсткий металл отдаёт мяч назад, а в сторону уводит по тому, с какой стороны от оси труба задета.
        Vector3 FrameBounce(Vector3 v, FootballTuning.FrameContact contact, float x, float z)
        {
            const float rigid = 0.55f;
            float reach = tuning.FrameTubeRadius + tuning.BallRadius;
            if (contact == FootballTuning.FrameContact.Post)
            {
                float side = Mathf.Clamp((Mathf.Abs(x) - tuning.GoalHalfWidth) / reach, -1f, 1f) * Mathf.Sign(x);   // + наружу, − внутрь
                return new Vector3(-Mathf.Abs(v.x) * rigid, v.y * 0.7f, -(v.z + side * 2.2f));
            }
            float above = Mathf.Clamp((z - tuning.GoalHeight * 0.5f) / reach, -1f, 1f);
            return new Vector3(-Mathf.Abs(v.x) * rigid, Mathf.Abs(v.y) * 0.4f + above * 2.2f, v.z * 0.8f);
        }

        // Физическое тело мяча (кинематическое): идёт по траектории игры и толкает конусы, на которые наталкивается.
        // Включено только пока идёт змейка; на других элементах мяч конусов не касается.
        void CreateBallProxy()
        {
            var go = new GameObject("МячФизика");
            go.transform.SetParent(transform, false);
            ballProxy = go.AddComponent<Rigidbody>();
            ballProxy.isKinematic = true;
            ballProxy.interpolation = RigidbodyInterpolation.Interpolate;
            ballProxyCollider = go.AddComponent<SphereCollider>();
            ballProxyCollider.radius = FootballLayout.BallRadius;
            ballProxyCollider.sharedMaterial = FootballCone.MakeMaterial("BallPhysics", 0.4f, FootballCone.BallBounciness);
            Physics.bounceThreshold = FootballCone.BounceThreshold;
            ballProxyCollider.enabled = false;
        }

        void SyncBallProxy()
        {
            if (ballProxy == null || rules == null) return;
            bool solid = phase == Phase.Playing && rules.Current is SnakeElement;
            if (ballProxyCollider.enabled != solid)
            {
                ballProxyCollider.enabled = solid;
                ballProxy.position = ballPos;                 // включается на месте мяча: без «проезда» по полю
                ballProxy.rotation = Quaternion.identity;
                return;
            }
            if (solid) ballProxy.MovePosition(ballPos);
        }

        void ResetCones()
        {
            if (coneBodies == null) return;
            foreach (var cone in coneBodies)
                if (cone != null) cone.ResetPose();
        }

        void SpawnSpent(FootballElement kind, int points)
        {
            if (ball == null) return;
            // скорость в конце полёта: производная квадратичной кривой Безье
            Vector3 mid = (flightFrom + flightTo) * 0.5f + Vector3.up * 0.9f;
            Vector3 v = 2f * (flightTo - mid) / tuning.KickFlightSeconds;
            float incoming = v.magnitude;
            bool tarpHit = false;
            if (kind == FootballElement.Pass)
            {
                var attempt = rules.Current as AimedElement;
                bool through = points >= 2 || (attempt != null && points == 1 && tuning.InAnyHole(attempt.HitX, attempt.HitZ));
                if (through) v *= 0.85f;                                               // в отверстие: летит дальше, в сетку
                else if (points == 1)                                                  // удар в чехол
                {
                    v = new Vector3(v.x, v.y * 0.8f, v.z * 0.8f);                // дальше ткань действует как пружина (TarpContact)
                    tarpHit = true;
                    if (sounds != null) sounds.Impact(FootballSurface.Tarp, incoming);
                }
                else
                {
                    var shot = rules.Current as AimedElement;
                    var contact = shot != null ? tuning.FrameAt(shot.HitX, shot.HitZ) : FootballTuning.FrameContact.None;
                    if (contact == FootballTuning.FrameContact.None && AtFabric(flightTo))
                    {
                        // низ чехла: ниже зачётной зоны, но мяч всё равно достигает ткани у земли и отскакивает от неё, а не проходит насквозь
                        v = new Vector3(v.x, v.y * 0.8f, v.z * 0.8f);
                        tarpHit = true;
                        if (sounds != null) sounds.Impact(FootballSurface.Tarp, incoming);
                    }
                    else if (contact == FootballTuning.FrameContact.None) v *= 0.55f;          // мимо ворот: тишина до падения
                    else
                    {
                        v = FrameBounce(v, contact, shot.HitX, shot.HitZ);                         // штанга или перекладина
                        if (sounds != null) sounds.Impact(FootballSurface.Post, incoming);
                    }
                }
            }
            else
            {
                if (points >= 1)                                                       // удар в мишень
                {
                    v = new Vector3(v.x * 0.7f, v.y * 0.45f, -Mathf.Abs(v.z) * BoardBounce);
                    if (sounds != null) sounds.Impact(FootballSurface.Target, incoming);                          // мишень из одного материала: звук везде один
                }
                else v *= 0.55f;                                                       // мимо мишени
            }
            var body = Instantiate(ball.gameObject).transform;
            body.name = "ПробитыйМяч";
            body.localScale = ballScale;
            body.position = flightTo;
            body.rotation = ball.rotation;
            body.gameObject.SetActive(true);
            spentBalls.Add(new SpentBall { body = body, pos = flightTo, vel = v, tarpHit = tarpHit, contactId = ++contactSeq });
        }

        void UpdateSpent(float dt)
        {
            const float step = 1f / 120f;
            float left = Mathf.Min(dt, 0.1f);
            while (left > 0f)
            {
                float h = Mathf.Min(step, left);
                left -= h;
                foreach (var sb in spentBalls) if (!sb.resting) StepSpent(sb, h);
                CollideSpent();
            }
            foreach (var sb in spentBalls) sb.body.position = sb.pos;
        }

        // Мячи на поле сталкиваются между собой: новый мяч толкает лежащие, а те катятся.
        void CollideSpent()
        {
            float r = FootballLayout.BallRadius;
            for (int i = 0; i < spentBalls.Count; i++)
            {
                for (int j = i + 1; j < spentBalls.Count; j++)
                {
                    var a = spentBalls[i];
                    var b = spentBalls[j];
                    if (a.resting && b.resting) continue;
                    float impact;
                    if (BallCollisions.Resolve(ref a.pos, ref a.vel, ref b.pos, ref b.vel, r, SpentBallRestitution, out impact))
                    {
                        if (impact > 0.4f && Time.time - Mathf.Max(a.lastBumpTime, b.lastBumpTime) > 0.12f && sounds != null)
                        {
                            sounds.Impact(FootballSurface.Ball, impact * 1.5f);                // мяч о мяч — тот же глухой удар, что мяч о землю
                            a.lastBumpTime = b.lastBumpTime = Time.time;
                        }
                        if (a.vel.sqrMagnitude > 1e-4f) a.resting = false;
                        if (b.vel.sqrMagnitude > 1e-4f) b.resting = false;
                    }
                }
            }
        }

        // Сетка ворот как пружина: мяч, влетевший внутрь, давит на наклонную заднюю стенку, боковины и крышу;
        // сетка прогибается наружу (FootballNet), а мяч мягко останавливается и отскакивает.
        void NetContact(SpentBall sb, float front, Vector3 g, float r, float dt)
        {
            float height = tuning.GoalHeight;
            var wallBottom = new Vector2(front + tuning.GoalDepthBottom, 0f);
            var wallTop = new Vector2(front + tuning.GoalDepthTop, height);
            Vector2 along = (wallTop - wallBottom).normalized;
            var outward = new Vector2(along.y, -along.x);                                   // наружу от внутренности ворот: назад и вверх
            float back = Vector2.Dot(new Vector2(sb.pos.x, sb.pos.y) - wallBottom, outward) + r;
            float lateral = sb.pos.z - g.z;
            float sidePenetration = Mathf.Abs(lateral) + r - tuning.GoalHalfWidth;
            float roof = sb.pos.x < front + tuning.GoalDepthTop + r ? sb.pos.y + r - height : -1f;
            NetSurface(sb, 0, back, new Vector3(outward.x, outward.y, 0f), dt);
            NetSurface(sb, 1, sidePenetration, new Vector3(0f, 0f, lateral >= 0f ? 1f : -1f), dt);
            NetSurface(sb, 2, roof, Vector3.up, dt);
        }

        void NetSurface(SpentBall sb, int surface, float penetration, Vector3 normal, float dt)
        {
            int id = sb.contactId * 4 + surface;
            int bit = 1 << surface;
            if (penetration > 0f)
            {
                float outwardSpeed = Mathf.Max(0f, Vector3.Dot(sb.vel, normal));
                sb.vel -= normal * ((NetStiffness * penetration + NetDamping * outwardSpeed) * dt);
                sb.netMask |= bit;
                if (goalNet != null) goalNet.Press(id, sb.pos, Mathf.Min(penetration, NetMaxStretch), normal);
            }
            else if ((sb.netMask & bit) != 0)
            {
                sb.netMask &= ~bit;
                if (goalNet != null) goalNet.Release(id);
            }
        }

        // Точка p (мировая) лежит против ткани чехла: в пределах проёма по ширине и высоте.
        bool AtFabric(Vector3 p)
        {
            return Mathf.Abs(p.z - FootballLayout.GoalMouth.z) <= tuning.GoalHalfWidth && p.y <= tuning.GoalHeight + FootballLayout.BallRadius;
        }

        // Мяч давит на ткань чехла: пружина с затуханием даёт мягкий отскок и вдавливание, которое видно на чехле.
        void TarpContact(SpentBall sb, float dt)
        {
            var g = FootballLayout.GoalMouth;
            float r = FootballLayout.BallRadius, front = g.x - 0.014f;
            float depth = sb.pos.x + r - front;
            bool onFabric = AtFabric(sb.pos);
            if (depth > 0f && onFabric)
            {
                sb.inContact = true;
                sb.vel.x += (-TarpStiffness * depth - TarpDamping * sb.vel.x) * dt;
                float slide = Mathf.Exp(-2.5f * dt);                       // трение о ткань
                sb.vel.y *= slide;
                sb.vel.z *= slide;
                if (depth > 0.30f) { sb.pos.x = front - r + 0.30f; sb.vel.x = Mathf.Min(sb.vel.x, 0f); }
                if (tarp != null) tarp.Press(sb.contactId, sb.pos, depth);
            }
            else if (sb.inContact)
            {
                sb.inContact = false;
                sb.tarpHit = false;
                if (tarp != null) tarp.Release(sb.contactId);
            }
        }

        void StepSpent(SpentBall sb, float dt)
        {
            float r = FootballLayout.BallRadius;
            Vector3 before = sb.pos;
            sb.vel.y -= Gravity * dt;
            sb.pos += sb.vel * dt;
            if (sb.tarpHit) TarpContact(sb, dt);
            // сетка ворот: внутрь мяч попадает только через проём (под перекладиной, не задев чехол); сверху и сзади садится на сетку
            var g = FootballLayout.GoalMouth;
            float front = g.x - 0.014f, side = tuning.GoalHalfWidth - r;
            float lateral = Mathf.Abs(sb.pos.z - g.z);
            if (!sb.entered && !sb.tarpHit && before.x <= front && sb.pos.x > front && lateral < side && sb.pos.y < tuning.GoalHeight - r * 0.5f)
            {
                sb.entered = true;
                if (sounds != null) sounds.Impact(FootballSurface.Net, sb.vel.magnitude);
            }
            if (sb.entered)
            {
                float k = Mathf.Exp(-NetDrag * dt);
                sb.vel.x *= k;
                sb.vel.z *= k;
                NetContact(sb, front, g, r, dt);
                // жёсткие границы на случай очень сильного удара: сетка растягивается не дальше NetMaxStretch
                float limit = front + tuning.NetBackDepth(sb.pos.y) + NetMaxStretch - r * 0.8f;
                if (sb.pos.x > limit) { sb.pos.x = limit; sb.vel.x = -Mathf.Abs(sb.vel.x) * 0.1f; }
                float sideLimit = side + NetMaxStretch;
                if (lateral > sideLimit) { sb.pos.z = g.z + Mathf.Sign(sb.pos.z - g.z) * sideLimit; sb.vel.z = -sb.vel.z * 0.1f; }
                float ceiling = tuning.GoalHeight - r + NetMaxStretch;
                if (sb.pos.y > ceiling) { sb.pos.y = ceiling; sb.vel.y = Mathf.Min(sb.vel.y, 0f); }
            }
            else if (!sb.tarpHit && lateral < tuning.GoalHalfWidth + r)
            {
                // мяч снаружи: над воротами он падает на крышу сетки или на её наклонную заднюю стенку и скатывается
                float top = tuning.NetTopHeight(sb.pos.x - front);
                float topBefore = tuning.NetTopHeight(before.x - front);
                if (top > 0f && sb.pos.y < top + r && before.y >= Mathf.Max(top, topBefore) + r - 0.03f)
                {
                    sb.pos.y = top + r;
                    if (sb.vel.y < 0f) sb.vel.y = -sb.vel.y * 0.12f;
                    sb.vel.x *= 0.94f;
                    if (sb.pos.x - front > tuning.GoalDepthTop) sb.vel.x += Gravity * 0.5f * dt;     // по наклонной стенке мяч съезжает назад
                }
            }
            // земля
            if (sb.pos.y <= r)
            {
                sb.pos.y = r;
                if (sb.vel.y < -0.7f)
                {
                    if (sounds != null) sounds.Impact(FootballSurface.Ground, -sb.vel.y * 1.5f);
                    sb.vel.y = -sb.vel.y * GroundBounce;
                    sb.vel.x *= 0.9f;
                    sb.vel.z *= 0.9f;
                }
                else
                {
                    sb.vel.y = 0f;
                    float speed = new Vector2(sb.vel.x, sb.vel.z).magnitude;
                    float slowed = Mathf.Max(0f, speed - RollingDecel * dt);
                    if (speed > 1e-4f) { float f = slowed / speed; sb.vel.x *= f; sb.vel.z *= f; }
                    if (slowed < 0.03f) { sb.vel = Vector3.zero; sb.resting = true; }
                }
            }
            // граница поля: за бортами мяч не катится
            float limitX = FootballLayout.FieldWidth * 0.5f - 0.5f, limitZ = FootballLayout.FieldDepth * 0.5f - 0.2f;
            sb.pos.x = Mathf.Clamp(sb.pos.x, -limitX, limitX);
            sb.pos.z = Mathf.Clamp(sb.pos.z, -limitZ, limitZ);
            // вращение по пройденному пути
            Vector3 d = sb.pos - before;
            d.y = 0f;
            if (d.sqrMagnitude > 1e-10f)
            {
                Vector3 axis = Vector3.Cross(Vector3.up, d.normalized);
                sb.body.Rotate(axis, d.magnitude / r * Mathf.Rad2Deg, Space.World);
            }
        }

        void ClearSpent()
        {
            foreach (var sb in spentBalls) ReleaseContacts(sb);
            foreach (var sb in spentBalls) if (sb.body != null) Destroy(sb.body.gameObject);
            spentBalls.Clear();
        }

        // Убираемый мяч мог давить на чехол и сетку ворот: отпустить их, иначе прогиб останется.
        void ReleaseContacts(SpentBall sb)
        {
            if (tarp != null) tarp.Release(sb.contactId);
            if (goalNet == null) return;
            for (int surface = 0; surface < 3; surface++) goalNet.Release(sb.contactId * 4 + surface);
        }

        void Roll()
        {
            Vector3 d = ballPos - lastBallPos;
            d.y = 0f;
            if (d.sqrMagnitude > 1e-8f)
            {
                Vector3 axis = Vector3.Cross(Vector3.up, d.normalized);
                ball.Rotate(axis, d.magnitude / FootballLayout.BallRadius * Mathf.Rad2Deg, Space.World);
            }
            lastBallPos = ballPos;
        }

        void UpdateCamera(float dt)
        {
            if (viewCamera == null) return;
            var pose = CameraPose(shown);
            float k = 1f - Mathf.Exp(-dt / CameraSmoothSeconds);
            camPos = Vector3.Lerp(camPos, pose.pos, k);
            camLook = Vector3.Lerp(camLook, pose.look, k);
            viewCamera.transform.position = camPos;
            viewCamera.transform.rotation = Quaternion.LookRotation(camLook - camPos, Vector3.up);
        }

        static Vector3 Bezier(Vector3 a, Vector3 b, Vector3 c, float t)
        {
            float u = 1f - t;
            return u * u * a + 2f * u * t * b + t * t * c;
        }

        void HideAll()
        {
            if (zoneRing == null) return;
            zoneRing.enabled = zoneBack.enabled = aimRing.enabled = aimBack.enabled = false;
            stopRing.enabled = stopBack.enabled = beatRing.enabled = beatBack.enabled = holeRing.enabled = holeBack.enabled = false;
            dot.gameObject.SetActive(false);
            dotBack.gameObject.SetActive(false);
        }

        // ---------- построение колец ----------

        LineRenderer Ring(string name, float width, Color color, int order)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace = true;
            lr.loop = true;
            lr.positionCount = RingSegments;
            lr.startWidth = lr.endWidth = width;
            lr.startColor = lr.endColor = color;
            lr.sharedMaterial = reticleMaterial;
            lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            lr.receiveShadows = false;
            lr.sortingOrder = order;
            return lr;
        }

        static void SetCircle(LineRenderer lr, Vector3 centre, Vector3 right, Vector3 up, float radius)
        {
            for (int i = 0; i < RingSegments; i++)
            {
                float a = i * Mathf.PI * 2f / RingSegments;
                lr.SetPosition(i, centre + (right * Mathf.Cos(a) + up * Mathf.Sin(a)) * radius);
            }
        }

        void SetGroundRing(LineRenderer ring, LineRenderer back, Vector3 centre, float radius, bool on)
        {
            SetCircle(back, centre, Vector3.right, Vector3.forward, radius);
            SetCircle(ring, centre, Vector3.right, Vector3.forward, radius);
            ring.enabled = back.enabled = on;
        }

        Transform Quad(string name, Texture2D texture, Color color)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = name;
            go.transform.SetParent(transform, false);
            Destroy(go.GetComponent<Collider>());
            var material = new Material(reticleMaterial);
            material.mainTexture = texture;
            material.color = color;
            var renderer = go.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.sortingOrder = 5;
            return go.transform;
        }

        void FaceCamera(Transform quad, Vector3 position, float radius)
        {
            quad.position = position;
            if (viewCamera != null) quad.rotation = Quaternion.LookRotation(viewCamera.transform.forward, Vector3.up);
            quad.localScale = new Vector3(radius * 2f, radius * 2f, 1f);
        }

        static Texture2D DiscTexture()
        {
            const int size = 64;
            var tex = new Texture2D(size, size, TextureFormat.RGBA32, true);
            tex.wrapMode = TextureWrapMode.Clamp;
            var pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float dx = (x + 0.5f) / size * 2f - 1f, dy = (y + 0.5f) / size * 2f - 1f;
                    float d = Mathf.Sqrt(dx * dx + dy * dy);
                    pixels[y * size + x] = new Color32(255, 255, 255, (byte)(255f * Mathf.Clamp01((1f - d) / 0.08f)));
                }
            }
            tex.SetPixels32(pixels);
            tex.Apply();
            return tex;
        }

        // ---------- экран игрока ----------

        protected override void DrawGame()
        {
            float s = Screen.height / 1080f;
            float w = Screen.width, h = Screen.height;
            EnsureStyles(s);
            float plaqueW = Mathf.Min(w * 0.94f, 1180f * s);
            float px = (w - plaqueW) * 0.5f;

            var top = new Rect(px, 20f * s, plaqueW, 88f * s);
            Plaque(top, s);
            nameStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(new Rect(top.x + 36f * s, top.y, plaqueW * 0.3f, top.height), PlayerName(), nameStyle);
            DrawPips(top, s);
            scoreStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(FootballHud.TimerRect(top, s), TimerText(), scoreStyle);
            scoreStyle.alignment = TextAnchor.MiddleRight;
            int score = debugScore >= 0 ? debugScore : (rules != null ? rules.Score : 0);          // --debug-score меняет только подпись, в результат не идёт
            OutlinedLabel(FootballHud.ScoreRect(top, s, score, scoreStyle.fontSize), NeurotlonHud.ScoreText(score), scoreStyle);

            // шкалы внизу (без подсказок: правила показаны в обучении)
            var bottom = new Rect(px, h - 20f * s - 112f * s, plaqueW, 112f * s);
            Plaque(bottom, s);
            DrawBars(bottom, s);

            DrawAttempts(top, s);
            if (phase == Phase.Intro) DrawIntro(s);
            else
            {
                if (attemptTimer > 0f && phase != Phase.Result) DrawAttemptPopup(s);                // в итоге элемента отдельная надпись попытки не нужна: она бы наложилась на итог
                if (phase == Phase.Result && !string.IsNullOrEmpty(resultText)) DrawResultPopup(s);
            }
        }

        void DrawIntro(float s)
        {
            float w = Screen.width, h = Screen.height;
            GUI.color = new Color(0f, 0f, 0f, 0.55f);
            GUI.DrawTexture(new Rect(0f, h * 0.30f, w, h * 0.30f), Texture2D.whiteTexture);
            GUI.color = Color.white;
            bigStyle.alignment = TextAnchor.MiddleCenter;
            midStyle.alignment = TextAnchor.MiddleCenter;
            OutlinedLabel(new Rect(0f, h * 0.32f, w, 50f * s), "ЭЛЕМЕНТ " + ((int)shown + 1) + " ИЗ 4", midStyle);
            OutlinedLabel(new Rect(0f, h * 0.38f, w, 100f * s), ElementName(shown).ToUpper(), bigStyle);
        }

        // Под верхней плашкой: три кружка попыток у передачи и удара (цвет — очки попытки, рамка — текущая).
        void DrawAttempts(Rect top, float s)
        {
            if (rules == null || rules.Over) return;
            var a = rules.Current as AimedElement;
            if (a == null || (shown != FootballElement.Pass && shown != FootballElement.Kick) || phase == Phase.Intro) return;
            DrawAttemptDots(top, s, a.AttemptCount, a.Finished ? -1 : Mathf.Min(a.Attempt, a.AttemptCount - 1), a.AttemptResult);
        }

        // Кружки попыток под плашкой top: count штук, цвет по очкам попытки (resultOf: -1 — ещё не сделана), рамка у current (−1: нет).
        // Те же кружки рисует шаг обучения «попади сам».
        void DrawAttemptDots(Rect top, float s, int count, int current, System.Func<int, int> resultOf)
        {
            float size = 30f * s, gap = 14f * s;
            float total = count * size + (count - 1) * gap;
            float x0 = top.x + (top.width - total) * 0.5f, y0 = top.yMax + 10f * s;
            for (int i = 0; i < count; i++)
            {
                int r = resultOf(i);
                GUI.color = i == current ? Cyan : Ink;
                GUI.DrawTexture(new Rect(x0 + i * (size + gap) - 3f, y0 - 3f, size + 6f, size + 6f), Texture2D.whiteTexture);
                GUI.color = r < 0 ? new Color(0.20f, 0.26f, 0.38f) : (r >= 2 ? Good : (r == 1 ? Okay : Bad));
                GUI.DrawTexture(new Rect(x0 + i * (size + gap), y0, size, size), Texture2D.whiteTexture);
            }
            GUI.color = Color.white;
        }

        void DrawAttemptPopup(float s)
        {
            float w = Screen.width, h = Screen.height;
            popupStyle.alignment = TextAnchor.MiddleCenter;
            string text = "Попытка " + attemptNumber + ": " + (attemptPoints > 0 ? "+" + attemptPoints : "мимо");
            int old = popupStyle.fontSize;
            popupStyle.fontSize = Mathf.RoundToInt(58f * s);
            popupStyle.normal.textColor = attemptPoints >= 2 ? Good : (attemptPoints == 1 ? Okay : Bad);
            OutlinedLabel(new Rect(0f, h * 0.25f, w, 90f * s), text, popupStyle);                 // под плашкой и выше мишени: мяч и мишень ниже
            popupStyle.fontSize = old;
        }

        void DrawResultPopup(float s)
        {
            float w = Screen.width, h = Screen.height;
            popupStyle.alignment = TextAnchor.MiddleCenter;
            midStyle.alignment = TextAnchor.MiddleCenter;
            Color c = resultPoints >= 2 ? Good : (resultPoints == 1 ? Okay : Bad);
            popupStyle.normal.textColor = c;
            // в верхней части экрана, под плашкой игрока: ниже летают мяч и мишень, надпись их не закрывает
            OutlinedLabel(new Rect(0f, h * 0.15f, w, 50f * s), ElementName(resultElement).ToUpper(), midStyle);
            OutlinedLabel(new Rect(0f, h * 0.19f, w, 150f * s), resultPoints > 0 ? "+" + resultPoints : "мимо", popupStyle);
        }

        void DrawPips(Rect plaque, float s)
        {
            float size = 36f * s, gap = 16f * s;
            float total = 4 * size + 3 * gap;
            float x0 = plaque.x + (plaque.width - total) * 0.5f, y0 = plaque.y + (plaque.height - size) * 0.5f;
            for (int i = 0; i < 4; i++)
            {
                int result = elementPoints[i];
                Color c = result < 0 ? new Color(0.20f, 0.26f, 0.38f) : (result >= 2 ? Good : (result == 1 ? Okay : Bad));
                bool current = rules != null && !rules.Over && i == (int)shown;
                GUI.color = current ? Cyan : Ink;
                GUI.DrawTexture(new Rect(x0 + i * (size + gap) - 4f, y0 - 4f, size + 8f, size + 8f), Texture2D.whiteTexture);
                GUI.color = c;
                GUI.DrawTexture(new Rect(x0 + i * (size + gap), y0, size, size), Texture2D.whiteTexture);
            }
            GUI.color = Color.white;
        }

        void DrawBars(Rect bottom, float s)
        {
            float pad = 40f * s, barW = (bottom.width - pad * 3f) * 0.5f, barH = 22f * s, y = bottom.y + 72f * s;
            bool aimed = shown == FootballElement.Pass || shown == FootballElement.Kick;
            float grip = tuning.GripOn;
            string leftLabel = "МЫШЦА";
            Color leftColor = aimed && lastEmg >= grip ? Good : Okay;
            DrawBar(new Rect(bottom.x + pad, y, barW, barH), leftLabel, lastEmg, leftColor, aimed ? grip : -1f, s);
            string rightLabel;
            float rightValue = 0f;
            if (aimed)
            {
                var a = rules != null ? rules.Current as AimedElement : null;
                rightLabel = "СОСРЕДОТОЧЕНИЕ";
                rightValue = a != null ? a.Concentration : 0f;
            }
            else if (shown == FootballElement.Stop)
            {
                var st = rules != null ? rules.Current as StopElement : null;
                rightLabel = "СКОРОСТЬ МЯЧА";
                rightValue = st != null ? Mathf.Clamp01(st.Speed / tuning.StopStartSpeed) : 1f;
            }
            else
            {
                var sn = rules != null ? rules.Current as SnakeElement : null;
                var rh = sn != null ? sn.Dribble as RhythmDribble : null;
                if (rh != null) { rightLabel = "КОНТРОЛЬ РИТМА"; rightValue = rh.Quality; }
                else if (tuning.Dribble == DribbleMode.Throttle) { rightLabel = "СКОРОСТЬ"; rightValue = sn != null ? Mathf.Clamp01((sn.Dribble.Speed - tuning.ThrottleMinSpeed) / (tuning.ThrottleMaxSpeed - tuning.ThrottleMinSpeed)) : 0f; }
                else { rightLabel = "ПОЛОЖЕНИЕ МЯЧА"; rightValue = sn != null ? Mathf.Clamp01(sn.X / (2f * tuning.LateralMax) + 0.5f) : 0.5f; }
            }
            DrawBar(new Rect(bottom.x + pad * 2f + barW, y, barW, barH), rightLabel, rightValue, Cyan, -1f, s);
        }

        void DrawBar(Rect area, string label, float value, Color color, float threshold, float s)
        {
            labelStyle.alignment = TextAnchor.LowerLeft;
            OutlinedLabel(new Rect(area.x, area.y - 36f * s, area.width, 34f * s), label, labelStyle);
            GUI.color = new Color(0.12f, 0.16f, 0.26f, 1f);
            GUI.DrawTexture(area, Texture2D.whiteTexture);
            GUI.color = color;
            GUI.DrawTexture(new Rect(area.x, area.y, area.width * Mathf.Clamp01(value), area.height), Texture2D.whiteTexture);
            if (threshold >= 0f)
            {
                GUI.color = Color.white;
                GUI.DrawTexture(new Rect(area.x + area.width * threshold - 3f * s, area.y - 8f * s, 6f * s, area.height + 16f * s), Texture2D.whiteTexture);
            }
            GUI.color = Color.white;
        }

        static void Plaque(Rect area, float s)
        {
            float b = Mathf.Max(3f, 4f * s);
            GUI.color = PlaqueEdge;
            GUI.DrawTexture(area, Texture2D.whiteTexture);
            GUI.color = PlaqueFill;
            GUI.DrawTexture(new Rect(area.x + b, area.y + b, area.width - 2f * b, area.height - 2f * b), Texture2D.whiteTexture);
            GUI.color = Color.white;
        }

        void EnsureStyles(float s)
        {
            if (nameStyle == null)
            {
                nameStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                scoreStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                NeurotlonHud.SingleLine(scoreStyle);
                labelStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                bigStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                midStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                popupStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                hintStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                foreach (var st in new[] { nameStyle, scoreStyle, labelStyle, bigStyle, midStyle, hintStyle })
                    st.normal.textColor = Cream;
            }
            nameStyle.fontSize = Mathf.RoundToInt(38f * s);
            scoreStyle.fontSize = Mathf.RoundToInt(48f * s);
            labelStyle.fontSize = Mathf.RoundToInt(24f * s);
            bigStyle.fontSize = Mathf.RoundToInt(78f * s);
            midStyle.fontSize = Mathf.RoundToInt(32f * s);
            popupStyle.fontSize = Mathf.RoundToInt(120f * s);
            hintStyle.fontSize = Mathf.RoundToInt(27f * s);
        }

        // ---------- тексты ----------

        string PlayerName()
        {
            if (Launch == null) return "";
            var p = Launch.Participants[0];
            return string.IsNullOrEmpty(p.display_name) ? p.code : p.display_name;
        }

        static string ElementName(FootballElement e)
        {
            switch (e)
            {
                case FootballElement.Pass: return "Передача в ворота";
                case FootballElement.Stop: return "Остановка в зоне";
                case FootballElement.Kick: return "Удар в мишень";
                default: return "Ведение змейкой";
            }
        }

        static string ReadArg(string name)
        {
            string[] args = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }
    }
}
