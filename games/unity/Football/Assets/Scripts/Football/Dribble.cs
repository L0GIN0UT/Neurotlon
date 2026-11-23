using System;

namespace Neurotlon.Games.Football
{
    // Путь змейки: конусы в линию, обходить их надо поочерёдно слева и справа.
    public static class SnakePath
    {
        // Желаемое положение по X при данной координате Y (плавная синусоида между точками обхода конусов).
        public static float DesiredX(FootballTuning t, float y)
        {
            int n = t.ConeY.Length;
            if (y <= t.ConeY[0]) return Side(0) * t.PassSideOffset * Smooth((y - (t.ConeY[0] - 2.2f)) / 2.2f);
            for (int i = 0; i < n - 1; i++)
            {
                if (y <= t.ConeY[i + 1])
                {
                    float u = (y - t.ConeY[i]) / (t.ConeY[i + 1] - t.ConeY[i]);
                    return Lerp(Side(i), Side(i + 1), Smooth(u)) * t.PassSideOffset;
                }
            }
            return Side(n - 1) * t.PassSideOffset;
        }

        // Первый конус обходят слева (отрицательный X), следующий — справа, и так далее.
        public static float Side(int coneIndex)
        {
            return coneIndex % 2 == 0 ? -1f : 1f;
        }

        static float Smooth(float u)
        {
            u = u < 0f ? 0f : (u > 1f ? 1f : u);
            return u * u * (3f - 2f * u);
        }

        static float Lerp(float a, float b, float u)
        {
            return a + (b - a) * u;
        }
    }

    // Способ управления мячом при ведении. Сигнал `emg` — напряжение мышц ноги 0…1 или null, если сигнала нет.
    public interface IDribble
    {
        float X { get; }
        float Y { get; }
        float Speed { get; }
        void Step(float dt, float? emg);
    }

    // Вариант «уровень»: мяч сам идёт вперёд, а напряжение ноги задаёт положение мяча поперёк полосы (как ракетка в понге).
    public sealed class LevelDribble : IDribble
    {
        readonly FootballTuning t;
        public float X { get; private set; }
        public float Y { get; private set; }
        public float Speed { get { return t.ForwardSpeed; } }

        public LevelDribble(FootballTuning tuning)
        {
            t = tuning;
            Y = t.StartY;
        }

        public void Step(float dt, float? emg)
        {
            if (emg.HasValue)
            {
                float target = (Clamp01(emg.Value) - 0.5f) * 2f * t.LateralMax;
                float k = 1f - (float)Math.Exp(-dt / t.LevelResponseSeconds);
                X += (target - X) * k;
            }
            Y += t.ForwardSpeed * dt;
        }

        static float Clamp01(float v) { return v < 0f ? 0f : (v > 1f ? 1f : v); }
    }

    // Вариант «газ и тормоз»: напряжение разгоняет мяч, расслабление тормозит. Мяч сам идёт по змейке, но чем быстрее,
    // тем больше запаздывает на поворотах и уходит к конусу: на поворотах нужно сбавлять.
    public sealed class ThrottleDribble : IDribble
    {
        readonly FootballTuning t;
        float speed;
        public float X { get; private set; }
        public float Y { get; private set; }
        public float Speed { get { return speed; } }

        public ThrottleDribble(FootballTuning tuning)
        {
            t = tuning;
            Y = t.StartY;
            speed = t.ThrottleMinSpeed;
        }

        public void Step(float dt, float? emg)
        {
            if (emg.HasValue)
            {
                float v = t.ThrottleMinSpeed + Clamp01(emg.Value) * (t.ThrottleMaxSpeed - t.ThrottleMinSpeed);
                speed += (v - speed) * (1f - (float)Math.Exp(-dt / 0.2f));
            }
            Y += speed * dt;
            float desired = SnakePath.DesiredX(t, Y);
            float tau = t.ThrottleLagBase + t.ThrottleLagPerSpeed * speed;
            X += (desired - X) * (1f - (float)Math.Exp(-dt / tau));
        }

        static float Clamp01(float v) { return v < 0f ? 0f : (v > 1f ? 1f : v); }
    }

    // Вариант «ритм»: мяч идёт вперёд, только если нога напрягается в такт метроному. Сбитый ритм ухудшает контроль:
    // мяч начинает «гулять» поперёк и задевает конусы.
    public sealed class RhythmDribble : IDribble
    {
        readonly FootballTuning t;
        float time;
        float quality = 1f;                // 0 — контроль потерян, 1 — идеально
        bool armed = true;                 // нога расслаблена и готова к новому касанию
        float glideLeft;                   // сколько ещё метров мяч «доезжает» после касания
        public float X { get; private set; }
        public float Y { get; private set; }
        public float Speed { get; private set; }
        public int GoodTaps { get; private set; }
        public int BadTaps { get; private set; }
        public float Quality { get { return quality; } }

        // Положение метронома: 0 в момент такта, растёт к 1 перед следующим (для подсказки на экране).
        public float BeatPhase { get { return (time % t.RhythmBeatSeconds) / t.RhythmBeatSeconds; } }

        public RhythmDribble(FootballTuning tuning)
        {
            t = tuning;
            Y = t.StartY;
        }

        public void Step(float dt, float? emg)
        {
            time += dt;
            if (emg.HasValue)
            {
                if (emg.Value <= t.RhythmTapOff) armed = true;
                if (armed && emg.Value >= t.RhythmTapOn)
                {
                    armed = false;
                    Tap();
                }
            }
            float glide = Math.Min(glideLeft, 3.4f * dt);
            glideLeft -= glide;
            Y += glide;
            Speed = dt > 0f ? glide / dt : 0f;
            quality = Math.Max(0f, quality - 0.05f * dt);                     // без касаний контроль медленно уходит
            float wobble = (1f - quality) * 1.1f * (float)Math.Sin(2.3f * time);
            float desired = SnakePath.DesiredX(t, Y);
            float target = desired + wobble;
            X += (target - X) * (1f - (float)Math.Exp(-dt / 0.12f));
        }

        void Tap()
        {
            float phase = time % t.RhythmBeatSeconds;
            float offset = Math.Min(phase, t.RhythmBeatSeconds - phase);        // расстояние до ближайшего такта
            if (offset <= t.RhythmWindowSeconds)
            {
                GoodTaps++;
                glideLeft += t.RhythmStepMeters;
                quality = Math.Min(1f, quality + 0.25f);
            }
            else
            {
                BadTaps++;
                quality = Math.Max(0f, quality - 0.35f);
            }
        }
    }

    public static class DribbleFactory
    {
        public static IDribble Create(FootballTuning t)
        {
            switch (t.Dribble)
            {
                case DribbleMode.Throttle: return new ThrottleDribble(t);
                case DribbleMode.Rhythm: return new RhythmDribble(t);
                default: return new LevelDribble(t);
            }
        }
    }
}
