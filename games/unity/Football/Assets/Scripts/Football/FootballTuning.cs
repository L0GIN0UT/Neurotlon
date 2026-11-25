using System;

namespace Neurotlon.Games.Football
{
    public enum FootballElement { Snake, Pass, Stop, Kick }

    // Три варианта ведения мяча змейкой (владелец выберет один после показа).
    public enum DribbleMode { Level, Throttle, Rhythm }

    // Все числа футбола в одном месте. Методики очков для футбола пока нет, поэтому значения по умолчанию:
    // за элемент 0…2 (передача и удар: три попытки по 0…2, сумма 5–6 дают 2, 2–4 дают 1), , плюс до 2 очков за среднюю точность, всего не больше 10.
    // Длины — метры в мире поля (ось Y — вдоль поля вперёд, X — вправо, Z — вверх).
    public sealed class FootballTuning
    {
        public DribbleMode Dribble = DribbleMode.Throttle;     // по умолчанию «газ и тормоз»; окончательный выбор способа за владельцем (открытый вопрос)
        public float ElementSeconds = 60f;                 // время на один элемент
        public float GripOn = 0.6f;                        // порог напряжения мышцы (удар/передача)
        public float GripOff = 0.35f;                      // порог отпускания; после удара надо расслабить мышцу

        // --- змейка ---
        public float[] ConeY = { -6.5f, -4.3f, -2.1f, 0.1f, 2.3f };       // конусы в одну линию по X = 0
        public float StartY = -10f;
        public float FinishPastLastCone = 1.6f;
        public float PassSideOffset = 0.8f;                // на сколько обходить конус сбоку
        public const float TutorialElementSeconds = 150f;  // в песочнице элемент не кончается по времени раньше таймаута шага (до 90 с)

        // Копия для песочницы обучения: первые coneCount конусов настоящего поля, attempts попыток в прицельных элементах.
        public FootballTuning CopyForTutorial(int coneCount, int attempts)
        {
            var copy = (FootballTuning)MemberwiseClone();
            int cones = Math.Max(1, Math.Min(coneCount, ConeY.Length));
            copy.ConeY = new float[cones];
            Array.Copy(ConeY, copy.ConeY, cones);
            copy.Attempts = attempts;
            copy.ElementSeconds = Math.Max(ElementSeconds, TutorialElementSeconds);
            return copy;
        }

        public float TouchRadius = 0.28f;                  // ближе — касание конуса
        public float LateralMax = 1.4f;                    // край коридора по X
        public float ForwardSpeed = 1.7f;                  // скорость вперёд (уровень и ритм)
        public float LevelResponseSeconds = 0.18f;         // насколько быстро мяч идёт за уровнем напряжения
        public float ThrottleMinSpeed = 0.6f;
        public float ThrottleMaxSpeed = 3.2f;
        public float ThrottleLagBase = 0.10f;              // запаздывание руля: база + k * скорость
        public float ThrottleLagPerSpeed = 0.12f;
        public float RhythmBeatSeconds = 0.75f;            // период метронома
        public float RhythmWindowSeconds = 0.20f;          // допуск попадания в такт
        public float RhythmStepMeters = 1.1f;              // шаг за точное касание
        public float RhythmTapOn = 0.6f;
        public float RhythmTapOff = 0.35f;

        // --- передача и удар: по три попытки ---
        public int Attempts = 3;
        public float AttemptPauseSeconds = 1.3f;           // пауза между попытками: мяч возвращается на отметку
        public float BallRadius = 0.11f;
        public float WobbleGamma = 1.0f;
        public float EegSmoothSeconds = 0.6f;
        public float KickFlightSeconds = 0.85f;
        public float ResultSeconds = 1.6f;                 // сколько показывается итог элемента

        // --- передача в ворота: чехол с тремя отверстиями по диагонали ---
        public float GoalHalfWidth = 1.2f;
        public float GoalHeight = 1.4f;
        public float PassWobbleMax = 1.6f;                 // разброс без сосредоточения, м
        public float PassWobbleMin = 0.10f;
        public float TarpHoleRadius = 0.26f;               // радиус отверстия в чехле
        // Мяч проходит сквозь отверстие, если его центр не дальше этого от центра отверстия (иначе он заденет край).
        public float PassHoleRadius { get { return TarpHoleRadius - BallRadius; } }
        // Три отверстия чехла по диагонали (x вправо с места игрока, z от середины проёма): верх-лево, центр, низ-право.
        public float[] TarpHoleX = { -0.80f, 0f, 0.80f };
        public float[] TarpHoleZ = { 0.33f, 0f, -0.33f };
        // В какие отверстия бить по попыткам: верх-лево, низ-право, центр.
        public int[] PassOrder = { 0, 2, 1 };

        public float PassX(int attempt) { return TarpHoleX[PassOrder[Math.Min(attempt, PassOrder.Length - 1)]]; }
        public float PassZ(int attempt) { return TarpHoleZ[PassOrder[Math.Min(attempt, PassOrder.Length - 1)]]; }

        // Сетка ворот: крыша на высоте перекладины глубиной GoalDepthTop, дальше задняя стенка наклонно вниз до глубины GoalDepthBottom.
        public float GoalDepthBottom = 1.0f;
        public float GoalDepthTop = 0.55f;

        // Высота верха сетки на расстоянии depth от передней рамы (м) или −1, если это перед воротами.
        public float NetTopHeight(float depth)
        {
            if (depth < 0f) return -1f;
            if (depth <= GoalDepthTop) return GoalHeight;
            if (depth >= GoalDepthBottom) return 0f;
            return GoalHeight * (1f - (depth - GoalDepthTop) / (GoalDepthBottom - GoalDepthTop));
        }

        // Глубина задней стенки сетки на высоте y: вверху ближе к проёму, внизу дальше.
        public float NetBackDepth(float y)
        {
            float k = Math.Max(0f, Math.Min(1f, y / GoalHeight));
            return GoalDepthBottom + (GoalDepthTop - GoalDepthBottom) * k;
        }

        // Рама ворот: чехол закрывает проём почти до самой трубы, дальше мяч бьёт уже по штанге или перекладине.
        public float TarpEdge = 0.025f;                    // ширина полосы между краем чехла и осью трубы
        public float FrameTubeRadius = 0.038f;
        public enum FrameContact { None, Post, Crossbar }

        // Куда попал мяч (x вправо, z от середины проёма): в чехол, в штангу, в перекладину или мимо.
        public bool OnTarp(float x, float z)
        {
            return Math.Abs(x) <= GoalHalfWidth - TarpEdge && Math.Abs(z) <= GoalHeight * 0.5f - TarpEdge;
        }

        public FrameContact FrameAt(float x, float z)
        {
            if (OnTarp(x, z)) return FrameContact.None;
            float reach = FrameTubeRadius + BallRadius;               // центр мяча ближе этого к оси трубы — удар по трубе
            float ax = Math.Abs(x), top = GoalHeight * 0.5f;
            bool post = Math.Abs(ax - GoalHalfWidth) <= reach && z <= top + reach;
            bool bar = Math.Abs(z - top) <= reach && ax <= GoalHalfWidth + reach;
            if (post) return FrameContact.Post;
            return bar ? FrameContact.Crossbar : FrameContact.None;
        }

        // Попадает ли точка в любое из отверстий (мяч пролетит сквозь чехол).
        public bool InAnyHole(float x, float z)
        {
            for (int i = 0; i < TarpHoleX.Length; i++)
            {
                float dx = x - TarpHoleX[i], dz = z - TarpHoleZ[i];
                if (dx * dx + dz * dz <= PassHoleRadius * PassHoleRadius) return true;
            }
            return false;
        }

        // --- остановка мяча в зоне ---
        public float StopZoneDistance = 6.0f;              // от точки удара до центра зоны вдоль движения
        public float StopZoneHalf = 1.3f;                  // половина стороны зоны
        public float StopStartSpeed = 4.5f;
        public float StopNetDistance = FootballLayout.StopNetDistance;   // за зоной стоит сетка: мяч, докатившись до неё, останавливается
        public float StopFriction = 0.5f;                  // собственное торможение мяча, м/с²
        public float StopBrakeGain = 4.0f;                 // торможение при полном напряжении, м/с²

        // --- удар в круглую мишень ⌀ 1,6 м: жёлтое и красное — 2 очка, остальные кольца — 1, мимо — 0 ---
        public float TargetRadius = 0.8f;
        public float TargetInnerRadius = 0.304f;
        public float TargetCentreZ = 1.25f;
        public float KickWobbleMax = 1.7f;
        public float KickWobbleMin = 0.12f;
    }
}
