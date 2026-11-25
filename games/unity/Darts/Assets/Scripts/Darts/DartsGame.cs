using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon.Games.Darts
{
    // Дартс от первого лица. Прицел сам «гуляет» по мишени, размах зависит от сосредоточения (ЭЭГ, сигнал `eeg`);
    // бросок — по напряжению мышцы с датчиком (ЭМГ, сигнал `emg`). Запуск, мост, калибровку, отсчёт, таймер, Esc, паузу и запись
    // результата делает NeurotlonGame; здесь правила (DartsRules), картинка, звук и экран игрока.
    //
    // Раскладка экрана: сверху полоса (имя, броски, очки), снизу полоса (две шкалы), мишень между ними;
    // поверх мишени рисуются только прицел и результат броска рядом с ней.
    public sealed class DartsGame : NeurotlonGame
    {
        static readonly Vector3 HandOffset = new Vector3(0.21f, -0.10f, 0.55f);   // дротик в руке относительно камеры
        const float EndDelaySeconds = 1.8f;
        const float ArcHeight = 0.22f;                                              // дуга полёта: дротик чуть провисает
        const float EmbedDepth = 0.012f;                                            // на сколько острие входит в мишень
        const float PopupSeconds = 1.1f;
        const float AimStepTimeoutSeconds = 90f;                                    // попытка шага «попади сам»
        const float RepeatShowSeconds = 1f;                                         // «Попробуйте ещё раз» после перезапуска
        const string AimHint = "Попадите дважды в зелёное или оранжевое кольцо";

        // Прожектор — это зона разброса прицела: вокруг центра светлый круг радиусом в текущий разброс, снаружи мишень
        // затемнена. Чем выше сосредоточение, тем меньше круг. Прицел гуляет внутри него.
        // Зоны очков (2 и 1) — отдельные кольца с небольшой обводкой по настоящим проволокам мишени (радиусы из
        // DartsTuning совпадают с кольцами: зелёное кольцо вокруг центра и внешний край трибла).
        // Прицел — голубое кольцо с точкой: голубого на мишени нет, поэтому не теряется.
        const float ZoneLineWidth = 0.0070f;
        const float ZoneOutline = 0.0090f;           // обводка шире линии с каждой стороны: кольца видно на любой секции
        const float EdgeRadius = 0.272f;             // внешний проволочный край мишени (R_DOUBLE_OUT в build_darts.py): дальше 0
        const float DimRadius = 0.40f;              // затемнение доходит до пробкового кольца вокруг мишени
        const float SpotlightSoft = 0.03f;
        const float ReticleRadius = 0.020f;
        const float ReticleWidth = 0.009f;
        const float OutlineExtra = 0.008f;
        const float DotRadius = 0.0075f;
        const int RingSegments = 64;

        [Header("Объекты сцены")]
        [SerializeField] Transform board;           // центр мишени; лицом к камере, x вправо, y вверх
        [SerializeField] Transform heldDart;        // дротик в руке (+Z — куда смотрит острие)
        [SerializeField] Transform dartTemplate;    // шаблон для воткнутых дротиков (отключён в сцене)
        [SerializeField] Camera viewCamera;
        [SerializeField] DartsSounds sounds;
        [SerializeField] Material reticleMaterial;  // прозрачный материал без освещения для прицела
        [SerializeField] Material spotlightMaterial; // шейдер Neurotlon/DartsSpotlight: затемнение с круглой дырой

        static readonly Color Ink = new Color(0.02f, 0.02f, 0.05f, 0.92f);
        static readonly Color Brass = new Color(0.84f, 0.66f, 0.35f, 1f);
        static readonly Color Cream = new Color(0.96f, 0.89f, 0.74f, 1f);
        static readonly Color PlaqueFill = new Color(0.09f, 0.055f, 0.035f, 0.90f);
        static readonly Color Cyan = new Color(0.3f, 0.9f, 1f, 1f);
        static readonly Color TestAccent = new Color(0.35f, 0.90f, 0.45f, 1f);      // рамка плашки на шаге-проверке
        const string PracticeLabel = "Тренировка";
        static readonly Color ReticleColor = new Color(0.25f, 0.92f, 1f, 1f);
        static readonly Color ZoneTwo = new Color(0.15f, 1f, 0.40f, 1f);
        static readonly Color ZoneOne = new Color(1f, 0.56f, 0.04f, 1f);        // оранжевый: не сливается с кремовыми секторами
        static readonly Color ZoneZero = new Color(0.95f, 0.35f, 0.35f, 1f);       // «мимо»: тот же красный, что у квадратика броска

        readonly DartsTuning tuning = new DartsTuning();
        readonly List<Transform> stuck = new List<Transform>();
        readonly System.Random random = new System.Random();
        DartsRules rules;
        Transform flying;
        Vector3 flightStart;
        Vector3 hitPoint;
        LineRenderer reticleRing, reticleBack, twoRing, twoBack, oneRing, oneBack, zeroRing, zeroBack;
        Transform dot, dotBack, dim;
        Material spotlight;
        bool reticleVisible;
        float lastEmg;
        float endTimer;
        float popupTimer;
        int popupPoints;
        readonly DartsTutorial dartsTutorial = new DartsTutorial();
        int[] debugScores = new int[0];                            // --debug-score N: только подпись очков на экране, в результат не идёт
        float repeatTimer;                          // шаг «попади сам» начат заново: «Попробуйте ещё раз» ещё показывается
        GUIStyle nameStyle, scoreStyle, labelStyle, popupStyle;

        void Awake()
        {
            debugScores = NeurotlonHud.ParseValues(DartsArgs.TextValue(System.Environment.GetCommandLineArgs(), DartsArgs.DebugScore));
            dim = SpotlightQuad();
            zeroBack = Ring("ЗонаНольОбводка", ZoneLineWidth + ZoneOutline, Ink, 1);
            zeroRing = Ring("ЗонаНоль", ZoneLineWidth, new Color(ZoneZero.r, ZoneZero.g, ZoneZero.b, 0.98f), 2);
            oneBack = Ring("ЗонаОдинОбводка", ZoneLineWidth + ZoneOutline, Ink, 1);
            twoBack = Ring("ЗонаДваОбводка", ZoneLineWidth + ZoneOutline, Ink, 1);
            oneRing = Ring("ЗонаОдин", ZoneLineWidth, new Color(ZoneOne.r, ZoneOne.g, ZoneOne.b, 0.98f), 2);
            twoRing = Ring("ЗонаДва", ZoneLineWidth, new Color(ZoneTwo.r, ZoneTwo.g, ZoneTwo.b, 0.98f), 2);
            reticleBack = Ring("ПрицелОбводка", ReticleWidth + OutlineExtra, Ink, 3);
            reticleRing = Ring("Прицел", ReticleWidth, ReticleColor, 4);
            Texture2D round = DiscTexture();
            dotBack = Quad("ТочкаОбводка", round, Ink, 4);
            dot = Quad("Точка", round, ReticleColor, 5);
            if (dartTemplate != null) dartTemplate.gameObject.SetActive(false);
            SetReticleVisible(false);
        }

        // --- что реализует игра ---

        protected override void OnGameStart()
        {
            rules = new DartsRules(tuning, () => (float)random.NextDouble());
            rules.Raised += OnRulesEvent;
            SetReticleVisible(true);
        }

        // Подсказка обучения стоит слева от мишени (там свободно), чтобы не закрывать её.
        protected override Rect TutorialHintArea
        {
            get { return new Rect(Screen.width * 0.03f, Screen.height * 0.34f, Screen.width * 0.28f, 0f); }
        }

        // Обучение: три шага, по одной механике; третий — проверка «попади сам». Условия шагов в DartsTutorial.
        protected override string[] TutorialSteps()
        {
            return new[]
            {
                NeurotlonTexts.Focus + ": светлый круг сужается, прицел меньше дрожит",
                NeurotlonTexts.Tense + " выше линии: дротик полетит в прицел. После броска расслабьте её",
                AimHint,
            };
        }

        // Шаг-проверка не пропускается Enter и длится дольше: нужно два попадания из пяти бросков.
        protected override bool TutorialStepSkippable(int index) { return index != DartsTutorial.AimStep; }

        protected override float TutorialStepTimeout(int index)
        {
            return index == DartsTutorial.AimStep ? AimStepTimeoutSeconds : base.TutorialStepTimeout(index);
        }

        // Песочница шага: отдельные правила, чистая мишень. Правила не двигаются, пока подсказку читают.
        // Очки песочницы в результат не идут.
        protected override void OnTutorialStepStart(int index)
        {
            StartSandbox(index);
        }

        // Попытка началась (чтение закончилось или повтор): счётчики условия шага с нуля.
        protected override void OnTutorialTryStart(int index)
        {
            dartsTutorial.Reset();
        }

        void StartSandbox(int index)
        {
            ClearBoard();
            dartsTutorial.Reset();
            repeatTimer = 0f;
            int throws = index == DartsTutorial.AimStep ? DartsHitCounter.Throws : 99;
            rules = new DartsRules(new DartsTuning { Throws = throws }, () => (float)random.NextDouble());
            rules.Raised += OnRulesEvent;
            SetReticleVisible(true);
        }

        protected override bool OnTutorialUpdate(int index, float dt)
        {
            if (repeatTimer > 0f) repeatTimer -= dt;
            if (popupTimer > 0f) popupTimer -= dt;
            if (!TutorialInPlay)
            {
                UpdateVisuals();            // чтение подсказки: только картинка, правила стоят
                return false;
            }
            float? eeg = Bridge.Value(NeurotlonProtocol.SignalEeg);
            float? emg = Bridge.Value(NeurotlonProtocol.SignalEmg);
            if (emg.HasValue) lastEmg = emg.Value;
            // на шаге про сосредоточение бросков нет: сигнал мышцы не передаём
            rules.Step(dt, eeg, index == DartsTutorial.FocusStep ? (float?)null : emg);
            UpdateVisuals();
            bool worked = dartsTutorial.Update(index, dt, rules.Concentration);
            // все броски сделаны, а двух попаданий нет: песочница заново, не дожидаясь таймаута (после показа последнего броска)
            if (!worked && index == DartsTutorial.AimStep && dartsTutorial.Counter.MustRestart && rules.Phase == DartsPhase.Over)
            {
                StartSandbox(index);
                repeatTimer = RepeatShowSeconds;
            }
            return worked;
        }

        // Под подсказкой: на шаге-проверке верхняя плашка (имя, точки бросков, попадания), везде нижняя плашка с двумя шкалами.
        protected override void DrawTutorial(int index)
        {
            float s = Screen.height / 1080f;
            EnsureStyles(s);
            float plaqueW, px;
            PlaqueLayout(s, out px, out plaqueW);
            if (index == DartsTutorial.AimStep) DrawAimTop(px, plaqueW, s);
            else if (index == DartsTutorial.ThrowStep) DrawPracticeTop(px, plaqueW, s);
            DrawBars(px, plaqueW, s);
            DrawPopup(s);
        }

        // Верхняя плашка тренировки броска: те же квадратики бросков, что в игре, и подпись «Тренировка» вместо очков.
        void DrawPracticeTop(float px, float plaqueW, float s)
        {
            var top = new Rect(px, 22f * s, plaqueW, 92f * s);
            Plaque(top, s);
            nameStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(new Rect(top.x + 38f * s, top.y, plaqueW * 0.3f, top.height), PlayerName(), nameStyle);
            DrawThrowDots(top, s);
            NeurotlonHud.SingleLine(scoreStyle);
            scoreStyle.alignment = TextAnchor.MiddleRight;
            Rect label = NeurotlonHud.RightAligned(top.xMax - 38f * s, top.y, top.height, PracticeLabel, scoreStyle.fontSize, plaqueW * 0.2f);
            OutlinedLabel(label, PracticeLabel, scoreStyle);
        }

        // Верхняя плашка шага-проверки: как в игре, но вместо очков «Попаданий: n из 2», таймера нет.
        void DrawAimTop(float px, float plaqueW, float s)
        {
            var top = new Rect(px, 22f * s, plaqueW, 92f * s);
            Plaque(top, s, TestAccent);                 // проверка выглядит иначе, чем тренировка: зелёная рамка плашки
            nameStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(new Rect(top.x + 38f * s, top.y, plaqueW * 0.3f, top.height), PlayerName(), nameStyle);
            DrawThrowDots(top, s);
            string text = DartsHitCounter.Label(dartsTutorial.Counter.Hits);
            NeurotlonHud.SingleLine(scoreStyle);
            scoreStyle.alignment = TextAnchor.MiddleRight;
            Rect hitsRect = NeurotlonHud.RightAligned(top.xMax - 38f * s, top.y, top.height, text, scoreStyle.fontSize, plaqueW * 0.2f);
            OutlinedLabel(hitsRect, text, scoreStyle);
            if (repeatTimer > 0f)
            {
                DrawNotice(NeurotlonTexts.TutorialRepeat, 0.22f);
            }
        }

        protected override void OnTutorialEnd()
        {
            ClearBoard();
            rules = null;
            SetReticleVisible(false);
            if (heldDart != null) heldDart.gameObject.SetActive(false);
        }

        // Убрать воткнутые и летящие дротики: песочница не должна оставлять следов на мишени.
        void ClearBoard()
        {
            foreach (var dart in stuck) if (dart != null) Destroy(dart.gameObject);
            stuck.Clear();
            if (flying != null) Destroy(flying.gameObject);
            flying = null;
            popupTimer = 0f;
        }

        protected override void OnGameUpdate(float dt)
        {
            float? eeg = Bridge.Value(NeurotlonProtocol.SignalEeg);
            float? emg = Bridge.Value(NeurotlonProtocol.SignalEmg);
            if (emg.HasValue) lastEmg = emg.Value;
            rules.Step(dt, eeg, emg);
            UpdateVisuals();
            if (popupTimer > 0f) popupTimer -= dt;
            if (rules.Phase == DartsPhase.Over)
            {
                endTimer += dt;
                if (endTimer >= EndDelaySeconds) FinishGame();
            }
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
            return rules == null ? base.FinishedMessage() : "Результат: " + rules.Score + " из " + tuning.Throws * 2;
        }

        // --- экран игрока ---

        protected override void DrawGame()
        {
            float s = Screen.height / 1080f;
            EnsureStyles(s);
            float plaqueW, px;
            PlaqueLayout(s, out px, out plaqueW);

            // верхняя плашка: имя слева, броски по центру, таймер справа от центра, очки у правого края
            var top = new Rect(px, 22f * s, plaqueW, 92f * s);
            Plaque(top, s);
            nameStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(new Rect(top.x + 38f * s, top.y, plaqueW * 0.3f, top.height), PlayerName(), nameStyle);
            DrawThrowDots(top, s);

            // Очки прижаты к правому краю, число растёт влево; таймер сдвигается влево, если очки подходят вплотную.
            NeurotlonHud.SingleLine(scoreStyle);
            scoreStyle.alignment = TextAnchor.MiddleRight;
            int shownScore = debugScores.Length > 0 ? NeurotlonHud.Cycle(debugScores, Time.unscaledTime, 3f) : (rules != null ? rules.Score : 0);
            Rect scoreRect = NeurotlonHud.RightAligned(top.xMax - 38f * s, top.y, top.height,
                NeurotlonHud.ScoreText(shownScore), scoreStyle.fontSize, plaqueW * 0.2f);
            OutlinedLabel(scoreRect, NeurotlonHud.ScoreText(shownScore), scoreStyle);

            float timerW = 150f * s;
            scoreStyle.alignment = TextAnchor.MiddleLeft;
            OutlinedLabel(new Rect(Mathf.Min(top.center.x + 150f * s, scoreRect.x - timerW), top.y, timerW, top.height),
                TimerText(), scoreStyle);

            DrawBars(px, plaqueW, s);
            DrawPopup(s);
        }

        // Общая ширина и левый край плашек экрана (верхней и нижней).
        static void PlaqueLayout(float s, out float px, out float plaqueW)
        {
            plaqueW = Mathf.Min(Screen.width * 0.94f, 1400f * s);
            px = (Screen.width - plaqueW) * 0.5f;
        }

        // Нижняя плашка: две шкалы рядом (сосредоточение и мышца с линией порога).
        void DrawBars(float px, float plaqueW, float s)
        {
            float h = Screen.height;
            var bottom = new Rect(px, h - 22f * s - 124f * s, plaqueW, 124f * s);
            Plaque(bottom, s);
            float pad = 40f * s, barW = (plaqueW - pad * 3f) * 0.5f, barH = 22f * s, y = bottom.y + 72f * s;
            DrawBar(new Rect(bottom.x + pad, y, barW, barH), "СОСРЕДОТОЧЕНИЕ", rules != null ? rules.Concentration : 0f, Cyan, -1f, s);
            bool gripped = lastEmg >= tuning.GripOn;
            DrawBar(new Rect(bottom.x + pad * 2f + barW, y, barW, barH), "МЫШЦА", lastEmg,
                gripped ? new Color(0.4f, 1f, 0.5f) : new Color(1f, 0.75f, 0.2f), tuning.GripOn, s);
        }

        void DrawPopup(float s)
        {
            float w = Screen.width, h = Screen.height;
            // результат броска справа от мишени, не на ней
            if (popupTimer > 0f)
            {
                float a = Mathf.Clamp01(popupTimer / 0.4f);
                Color c = popupPoints >= 2 ? new Color(0.4f, 1f, 0.5f) : (popupPoints == 1 ? new Color(1f, 0.9f, 0.3f) : new Color(1f, 0.45f, 0.45f));
                c.a = a;
                popupStyle.normal.textColor = c;
                OutlinedLabel(new Rect(w * 0.5f + h * 0.36f, h * 0.5f - 60f * s, w * 0.2f, 120f * s), popupPoints > 0 ? "+" + popupPoints : "мимо", popupStyle);
            }
        }

        // --- внутреннее ---

        string PlayerName()
        {
            if (Launch == null) return "";
            var p = Launch.Participants[0];
            return string.IsNullOrEmpty(p.display_name) ? p.code : p.display_name;
        }

        void OnRulesEvent(DartsEvent e)
        {
            if (sounds != null) sounds.Play(e);
            if (CurrentStage == Stage.Tutorial) dartsTutorial.NoteEvent(e);
            if (e.Kind == DartsEventKind.Throw) BeginFlight();
            else if (e.Kind == DartsEventKind.Hit) OnLanded(e.Points);
        }

        void BeginFlight()
        {
            hitPoint = board.position + board.right * rules.HitX + board.up * rules.HitZ;
            flightStart = HeldPosition();
            flying = Instantiate(dartTemplate, flightStart, Quaternion.identity, transform);
            flying.gameObject.SetActive(true);
        }

        void OnLanded(int points)
        {
            if (flying != null)
            {
                float tilt = ((float)random.NextDouble() - 0.5f) * 10f;
                float tiltUp = ((float)random.NextDouble() - 0.5f) * 10f;
                flying.position = hitPoint + board.forward * EmbedDepth;     // острие чуть входит в мишень
                flying.rotation = Quaternion.LookRotation(board.forward, Vector3.up) * Quaternion.Euler(tiltUp, tilt, 0f);
                stuck.Add(flying);
                flying = null;
            }
            popupPoints = points;
            popupTimer = PopupSeconds;
        }

        Vector3 HeldPosition()
        {
            return viewCamera.transform.TransformPoint(HandOffset);
        }

        void UpdateVisuals()
        {
            Vector3 aim = board.position + board.right * rules.AimX + board.up * rules.AimZ;
            bool aiming = rules.Phase == DartsPhase.Aiming;
            SetReticleVisible(rules.Phase != DartsPhase.Over);
            UpdateReticle(aim);
            if (heldDart != null) heldDart.gameObject.SetActive(aiming);
            if (aiming && heldDart != null)
            {
                Vector3 p = HeldPosition() + Vector3.up * 0.006f * Mathf.Sin(Time.unscaledTime * 2.1f);
                heldDart.position = p;
                heldDart.rotation = Quaternion.LookRotation(aim - p, Vector3.up);
            }
            if (rules.Phase == DartsPhase.Flying && flying != null)
            {
                float t = rules.Progress;
                Vector3 end = hitPoint + board.forward * EmbedDepth;
                Vector3 mid = (flightStart + end) * 0.5f + Vector3.up * ArcHeight;
                flying.position = Bezier(flightStart, mid, end, t);
                Vector3 dir = Bezier(flightStart, mid, end, Mathf.Min(1f, t + 0.02f)) - flying.position;
                if (dir.sqrMagnitude > 1e-8f) flying.rotation = Quaternion.LookRotation(dir, Vector3.up);
            }
        }

        static Vector3 Bezier(Vector3 a, Vector3 b, Vector3 c, float t)
        {
            float u = 1f - t;
            return u * u * a + 2f * u * t * b + t * t * c;
        }

        void UpdateReticle(Vector3 aim)
        {
            Vector3 toCamera = -board.forward * 0.010f;
            Vector3 r = board.right, u = board.up;
            Vector3 p = aim + toCamera * 2f;
            Vector3 zoneCenter = board.position + toCamera * 0.8f;
            Face(dim, zoneCenter, DimRadius);
            spotlight.SetFloat("_Radius", rules.Amplitude);       // светлый круг = текущий разброс прицела
            SetCircle(zeroBack, zoneCenter, r, u, EdgeRadius);
            SetCircle(zeroRing, zoneCenter + toCamera * 0.2f, r, u, EdgeRadius);
            SetCircle(oneBack, zoneCenter, r, u, tuning.OnePointRadius);
            SetCircle(oneRing, zoneCenter + toCamera * 0.2f, r, u, tuning.OnePointRadius);
            SetCircle(twoBack, zoneCenter, r, u, tuning.TwoPointRadius);
            SetCircle(twoRing, zoneCenter + toCamera * 0.2f, r, u, tuning.TwoPointRadius);
            SetCircle(reticleBack, p, r, u, ReticleRadius);
            SetCircle(reticleRing, p + toCamera * 0.2f, r, u, ReticleRadius);
            Face(dotBack, p + toCamera * 0.5f, DotRadius + OutlineExtra * 0.6f);
            Face(dot, p + toCamera * 0.7f, DotRadius);
        }

        void Face(Transform quad, Vector3 position, float radius)
        {
            quad.position = position;
            quad.rotation = Quaternion.LookRotation(board.forward, board.up);
            quad.localScale = new Vector3(radius * 2f, radius * 2f, 1f);
        }

        void SetReticleVisible(bool visible)
        {
            if (dot == null) return;
            reticleVisible = visible;
            reticleRing.enabled = reticleBack.enabled = visible;
            oneRing.enabled = twoRing.enabled = oneBack.enabled = twoBack.enabled = zeroRing.enabled = zeroBack.enabled = visible;
            dim.gameObject.SetActive(visible);
            dot.gameObject.SetActive(visible);
            dotBack.gameObject.SetActive(visible);
        }

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

        // Квадрат на мишени с шейдером прожектора; радиус светлого круга выставляется каждый кадр.
        Transform SpotlightQuad()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = "Прожектор";
            go.transform.SetParent(transform, false);
            Destroy(go.GetComponent<Collider>());
            spotlight = new Material(spotlightMaterial);
            spotlight.SetFloat("_Extent", DimRadius);
            spotlight.SetFloat("_Soft", SpotlightSoft);
            var renderer = go.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = spotlight;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.sortingOrder = 0;
            return go.transform;
        }

        static void SetCircle(LineRenderer lr, Vector3 center, Vector3 right, Vector3 up, float radius)
        {
            for (int i = 0; i < RingSegments; i++)
            {
                float a = i * Mathf.PI * 2f / RingSegments;
                lr.SetPosition(i, center + (right * Mathf.Cos(a) + up * Mathf.Sin(a)) * radius);
            }
        }

        Transform Quad(string name, Texture2D texture, Color color, int order)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = name;
            go.transform.SetParent(transform, false);
            Destroy(go.GetComponent<Collider>());
            var renderer = go.GetComponent<MeshRenderer>();
            var material = new Material(reticleMaterial);
            material.mainTexture = texture;
            material.color = color;
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.sortingOrder = order;
            return go.transform;
        }

        // Круглая текстура с мягким краем: зона разброса рисуется заливкой, без тонких контуров.
        static Texture2D DiscTexture()
        {
            const int size = 128;
            var tex = new Texture2D(size, size, TextureFormat.RGBA32, true);
            tex.wrapMode = TextureWrapMode.Clamp;
            var pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float dx = (x + 0.5f) / size * 2f - 1f, dy = (y + 0.5f) / size * 2f - 1f;
                    float d = Mathf.Sqrt(dx * dx + dy * dy);
                    byte a = (byte)(255f * Mathf.Clamp01((1f - d) / 0.06f));
                    pixels[y * size + x] = new Color32(255, 255, 255, a);
                }
            }
            tex.SetPixels32(pixels);
            tex.Apply();
            return tex;
        }

        void EnsureStyles(float s)
        {
            if (nameStyle == null)
            {
                nameStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                scoreStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold };
                labelStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.LowerLeft };
                popupStyle = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleLeft };
                nameStyle.normal.textColor = scoreStyle.normal.textColor = Cream;
                labelStyle.normal.textColor = Cream;
            }
            nameStyle.fontSize = Mathf.RoundToInt(40f * s);
            scoreStyle.fontSize = Mathf.RoundToInt(52f * s);
            labelStyle.fontSize = Mathf.RoundToInt(24f * s);
            popupStyle.fontSize = Mathf.RoundToInt(96f * s);
        }

        // Латунная плашка с тёмной вставкой: единый вид всех панелей экрана.
        static void Plaque(Rect area, float s)
        {
            Plaque(area, s, Brass);
        }

        static void Plaque(Rect area, float s, Color edge)
        {
            float b = Mathf.Max(3f, 4f * s);
            GUI.color = edge;
            GUI.DrawTexture(area, Texture2D.whiteTexture);
            GUI.color = PlaqueFill;
            GUI.DrawTexture(new Rect(area.x + b, area.y + b, area.width - 2f * b, area.height - 2f * b), Texture2D.whiteTexture);
            GUI.color = Color.white;
        }

        void DrawThrowDots(Rect plaque, float s)
        {
            float size = 38f * s, gap = 18f * s;
            float total = tuning.Throws * size + (tuning.Throws - 1) * gap;
            float x0 = plaque.x + (plaque.width - total) * 0.5f, y0 = plaque.y + (plaque.height - size) * 0.5f;
            for (int i = 0; i < tuning.Throws; i++)
            {
                int result = rules != null ? rules.ResultOf(i) : -1;
                Color c = result < 0 ? new Color(0.30f, 0.22f, 0.16f) : (result >= 2 ? ZoneTwo : (result == 1 ? ZoneOne : ZoneZero));
                GUI.color = Ink;
                GUI.DrawTexture(new Rect(x0 + i * (size + gap) - 3f, y0 - 3f, size + 6f, size + 6f), Texture2D.whiteTexture);
                GUI.color = c;
                GUI.DrawTexture(new Rect(x0 + i * (size + gap), y0, size, size), Texture2D.whiteTexture);
            }
            GUI.color = Color.white;
        }

        void DrawBar(Rect area, string label, float value, Color color, float threshold, float s)
        {
            OutlinedLabel(new Rect(area.x, area.y - 40f * s, area.width, 38f * s), label, labelStyle);
            GUI.color = new Color(0.20f, 0.14f, 0.10f, 1f);
            GUI.DrawTexture(area, Texture2D.whiteTexture);
            GUI.color = color;
            GUI.DrawTexture(new Rect(area.x, area.y, area.width * Mathf.Clamp01(value), area.height), Texture2D.whiteTexture);
            if (threshold >= 0f)        // линия порога: выше неё мышца считается напряжённой и бросок идёт
            {
                GUI.color = Color.white;
                GUI.DrawTexture(new Rect(area.x + area.width * threshold - 3f * s, area.y - 8f * s, 6f * s, area.height + 16f * s), Texture2D.whiteTexture);
            }
            GUI.color = Color.white;
        }
    }
}
