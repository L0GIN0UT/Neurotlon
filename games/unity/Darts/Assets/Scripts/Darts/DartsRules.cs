using System;
using Neurotlon;

namespace Neurotlon.Games.Darts
{
    public enum DartsPhase { Aiming, Flying, Showing, Over }

    public enum DartsEventKind { Throw, Hit, GameOver }

    public struct DartsEvent
    {
        public readonly DartsEventKind Kind;
        public readonly int Points;

        public DartsEvent(DartsEventKind kind, int points)
        {
            Kind = kind;
            Points = points;
        }
    }

    // Настройки по умолчанию: методики очков для дартса пока нет, поэтому числа здесь, в одном месте.
    // Единицы: метры на плоскости мишени (мишень увеличена в 1,6 раза, см. ArtSource/Darts/build_darts.py).
    public sealed class DartsTuning
    {
        public int Throws = 5;
        public float TwoPointRadius = 0.080f;      // зелёное кольцо вокруг центра: граница 2 очков
        public float OnePointRadius = 0.1712f;     // внешний край трибла: граница 1 очка
        public float BoardRadius = 0.3608f;        // вся мишень; за её пределами — промах
        public float WobbleMax = 0.30f;            // разброс прицела без сосредоточения
        public float WobbleMin = 0.035f;           // и при полном сосредоточении
        public float WobbleGamma = 1.0f;           // 1: линейно; больше — награда за сосредоточение растёт к концу шкалы
        public float EegSmoothSeconds = 0.6f;      // сглаживание сигнала ЭЭГ
        public float GripOn = 0.6f;                // порог сжатия руки (бросок)
        public float GripOff = 0.35f;              // порог отпускания; после броска надо отпустить
        public float FlightSeconds = 0.42f;
        public float ShowSeconds = 1.1f;           // сколько показывается результат броска
    }

    // Правила и модель прицела дартса без Unity: тестируются отдельно.
    // Прицел сам «гуляет» вокруг центра мишени, чем выше сосредоточение (ЭЭГ), тем меньше размах.
    // Бросок — по сжатию руки (ЭМГ): дротик летит в точку прицела. Очки по кольцам: 2 / 1 / 0.
    public sealed class DartsRules
    {
        readonly DartsTuning t;
        readonly AimWobble aim;
        float phaseTimer;
        bool gripArmed;                     // рука отпущена и готова к броску
        int[] results;

        public event Action<DartsEvent> Raised;

        public DartsPhase Phase { get; private set; }
        public int ThrowsMade { get; private set; }
        public int Score { get; private set; }
        public int LastPoints { get; private set; }
        public float HitX { get; private set; }
        public float HitZ { get; private set; }
        public float AimX { get { return aim.X; } }
        public float AimZ { get { return aim.Z; } }
        public float Amplitude { get { return aim.Amplitude; } }
        public float Concentration { get { return aim.Concentration; } }
        public float Progress { get; private set; }      // ход полёта 0…1
        public DartsTuning Tuning { get { return t; } }

        public DartsRules(DartsTuning tuning, Func<float> random01)
        {
            t = tuning;
            aim = new AimWobble(tuning.WobbleMax, tuning.WobbleMin, tuning.WobbleGamma, tuning.EegSmoothSeconds, random01);
            results = new int[tuning.Throws];
            for (int i = 0; i < results.Length; i++) results[i] = -1;
            Phase = DartsPhase.Aiming;
        }

        // Результат i-го броска: 0, 1, 2 или -1, пока не брошен.
        public int ResultOf(int index)
        {
            return results[index];
        }

        // eeg и emg — текущие значения сигналов 0…1 или null, если сигнала сейчас нет (артефакт, нет контакта).
        public void Step(float dt, float? eeg, float? emg)
        {
            switch (Phase)
            {
                case DartsPhase.Aiming:
                    aim.Step(dt, eeg);
                    TryThrow(emg);
                    break;
                case DartsPhase.Flying:
                    aim.Step(dt, eeg);
                    phaseTimer -= dt;
                    Progress = Math.Min(1f, 1f - phaseTimer / t.FlightSeconds);
                    if (phaseTimer <= 0f) Land();
                    break;
                case DartsPhase.Showing:
                    aim.Step(dt, eeg);
                    if (emg.HasValue && emg.Value <= t.GripOff) gripArmed = true;
                    phaseTimer -= dt;
                    if (phaseTimer <= 0f) NextThrow();
                    break;
            }
        }

        // Очки за попадание в точку (x, z) на плоскости мишени относительно центра.
        public static int PointsFor(DartsTuning t, float x, float z)
        {
            float r = (float)Math.Sqrt(x * x + z * z);
            if (r <= t.TwoPointRadius) return 2;
            if (r <= t.OnePointRadius) return 1;
            return 0;
        }

        void TryThrow(float? emg)
        {
            if (!emg.HasValue) return;
            if (emg.Value <= t.GripOff) gripArmed = true;
            if (!gripArmed || emg.Value < t.GripOn) return;
            gripArmed = false;
            HitX = aim.X;
            HitZ = aim.Z;
            LastPoints = PointsFor(t, HitX, HitZ);
            Phase = DartsPhase.Flying;
            phaseTimer = t.FlightSeconds;
            Progress = 0f;
            Raise(DartsEventKind.Throw, 0);
        }

        void Land()
        {
            results[ThrowsMade] = LastPoints;
            ThrowsMade++;
            Score += LastPoints;
            Phase = DartsPhase.Showing;
            phaseTimer = t.ShowSeconds;
            Progress = 1f;
            Raise(DartsEventKind.Hit, LastPoints);
        }

        void NextThrow()
        {
            if (ThrowsMade >= t.Throws)
            {
                Phase = DartsPhase.Over;
                Raise(DartsEventKind.GameOver, Score);
                return;
            }
            Phase = DartsPhase.Aiming;
        }

        void Raise(DartsEventKind kind, int points)
        {
            var handler = Raised;
            if (handler != null) handler(new DartsEvent(kind, points));
        }
    }
}
