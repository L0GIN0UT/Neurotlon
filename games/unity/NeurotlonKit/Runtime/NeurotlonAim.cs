using System;

namespace Neurotlon
{
    // Прицел, который «гуляет» вокруг центра; размах зависит от сосредоточения (ЭЭГ): чем выше сигнал, тем он меньше.
    // Чистый C#, без Unity: тестируется отдельно. Нужен играм, где бросок или удар идёт в точку прицела
    // (дартс, передача и удар в футболе). Единицы по осям X и Z — метры на плоскости цели.
    public sealed class AimWobble
    {
        readonly float wobbleMax, wobbleMin, gamma, eegSmoothSeconds;
        readonly float p1, p2, p3, p4;
        float time;

        public float Concentration { get; private set; }
        public float Amplitude { get; private set; }
        public float X { get; private set; }
        public float Z { get; private set; }

        // wobbleMax — размах без сосредоточения, wobbleMin — при полном; gamma 1 — линейно, больше — награда растёт к концу шкалы.
        public AimWobble(float wobbleMax, float wobbleMin, float gamma, float eegSmoothSeconds, Func<float> random01)
        {
            this.wobbleMax = wobbleMax;
            this.wobbleMin = wobbleMin;
            this.gamma = gamma;
            this.eegSmoothSeconds = eegSmoothSeconds;
            float twoPi = (float)(Math.PI * 2.0);
            p1 = random01() * twoPi;
            p2 = random01() * twoPi;
            p3 = random01() * twoPi;
            p4 = random01() * twoPi;
            Amplitude = wobbleMax;
            Place();
        }

        // eeg — текущее значение 0…1 или null, если сигнала сейчас нет (артефакт, нет контакта): тогда размах не меняется.
        public void Step(float dt, float? eeg)
        {
            if (eeg.HasValue)
            {
                float k = 1f - (float)Math.Exp(-dt / eegSmoothSeconds);
                Concentration += (Clamp01(eeg.Value) - Concentration) * k;
            }
            float shaped = (float)Math.Pow(Concentration, gamma);
            Amplitude = wobbleMax + (wobbleMin - wobbleMax) * shaped;
            time += dt;
            Place();
        }

        void Place()
        {
            X = Amplitude * (0.6f * (float)Math.Sin(1.7 * time + p1) + 0.4f * (float)Math.Sin(3.3 * time + p2));
            Z = Amplitude * (0.6f * (float)Math.Sin(1.3 * time + p3) + 0.4f * (float)Math.Sin(2.7 * time + p4));
            float length = (float)Math.Sqrt(X * X + Z * Z);        // прицел остаётся внутри круга разброса
            if (length > Amplitude && length > 0f)
            {
                X *= Amplitude / length;
                Z *= Amplitude / length;
            }
        }

        static float Clamp01(float v)
        {
            return v < 0f ? 0f : (v > 1f ? 1f : v);
        }
    }
}
