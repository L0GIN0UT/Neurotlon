namespace Neurotlon.Games.Pong
{
    // Условия шагов обучения понга без Unity: тестируется отдельно. Обучение идёт у обоих игроков одновременно,
    // шаг засчитан, когда механика сработала у каждого. Учёт у каждого игрока свой.
    //   0 «Ракетка»: сигнал игрока за шаг побывал и низко (<= LowThreshold), и высоко (>= HighThreshold), без удержания.
    //   1 «Удар»: каждый отбил мяч ракеткой (подача не в счёт: это не отбитие).
    //   2 «Счёт»: сыграно первое очко.
    // Reset вызывается в начале каждой попытки шага: всё накопленное сбрасывается.
    public sealed class PongTutorial
    {
        public const int StepCount = 3;
        public const int PaddleStep = 0;
        public const int HitStep = 1;
        public const int ScoreStep = 2;

        public const float LowThreshold = 0.3f;
        public const float HighThreshold = 0.7f;

        readonly bool[] sawLow = new bool[2];
        readonly bool[] sawHigh = new bool[2];
        readonly bool[] hit = new bool[2];
        readonly bool[] awaitingLaunch = new bool[2];   // после подачи следующий PaddleHit этой стороны — это сама подача
        bool pointScored;

        // Тексты подсказок по одному на шаг; targetScore — до скольки очков идёт матч.
        public static string[] Texts(int targetScore)
        {
            return new[]
            {
                "Сила мышцы с датчиком двигает вашу ракетку: слабее в одну сторону, сильнее в другую",
                "Отбейте мяч ракеткой: встаньте на его пути",
                "Кто пропустит мяч, отдаёт очко сопернику. Играем до " + targetScore + " очков",
            };
        }

        public void Reset()
        {
            for (int i = 0; i < 2; i++)
            {
                sawLow[i] = false;
                sawHigh[i] = false;
                hit[i] = false;
                awaitingLaunch[i] = false;
            }
            pointScored = false;
        }

        // Сигналы игроков 0…1 в этом кадре; null — сигнала нет, шаг не продвигается.
        public void StepSignals(float? left, float? right)
        {
            Note(Side.Left, left);
            Note(Side.Right, right);
        }

        // События правил песочницы. Первое событие подачи (Serve) конструктор правил поднимает до подписки,
        // поэтому игра передаёт его сюда сама.
        public void OnRulesEvent(PongEventKind kind, Side side)
        {
            switch (kind)
            {
                case PongEventKind.Serve:
                    awaitingLaunch[(int)side] = true;
                    break;
                case PongEventKind.PaddleHit:
                    if (awaitingLaunch[(int)side]) awaitingLaunch[(int)side] = false;
                    else hit[(int)side] = true;
                    break;
                case PongEventKind.Point:
                    pointScored = true;
                    break;
            }
        }

        public bool PaddleDone(Side side)
        {
            return sawLow[(int)side] && sawHigh[(int)side];
        }

        public bool HitDone(Side side)
        {
            return hit[(int)side];
        }

        public bool IsDone(int step)
        {
            switch (step)
            {
                case PaddleStep: return PaddleDone(Side.Left) && PaddleDone(Side.Right);
                case HitStep: return HitDone(Side.Left) && HitDone(Side.Right);
                case ScoreStep: return pointScored;
                default: return false;
            }
        }

        void Note(Side side, float? value)
        {
            if (!value.HasValue) return;
            if (value.Value <= LowThreshold) sawLow[(int)side] = true;
            if (value.Value >= HighThreshold) sawHigh[(int)side] = true;
        }
    }
}
