namespace Neurotlon.Games.Pong
{
    // Демо-проверка перед матчем: игрок показывает, что владеет ракеткой, напрягая мышцу с датчиком до упора и расслабляя её до конца,
    // каждое положение удерживается недолго. Чистый C#: проверяется тестами без Unity. Очки проверки в результат не идут.
    public sealed class PongCheck
    {
        public const float HighThreshold = 0.8f;      // «сильно»: ракетка у одного края стола
        public const float LowThreshold = 0.2f;       // «слабо»: ракетка у другого края
        public const float HoldSeconds = 0.3f;        // сколько держать каждое положение

        float highHeld;
        float lowHeld;

        public bool HighDone { get; private set; }
        public bool LowDone { get; private set; }
        public bool Passed { get { return HighDone && LowDone; } }

        // value — сигнал игрока 0…1 или null, если сигнала сейчас нет (тогда удержание сбрасывается).
        public void Step(float dt, float? value)
        {
            if (!value.HasValue)
            {
                highHeld = 0f;
                lowHeld = 0f;
                return;
            }
            float v = value.Value;
            highHeld = v >= HighThreshold ? highHeld + dt : 0f;
            lowHeld = v <= LowThreshold ? lowHeld + dt : 0f;
            if (highHeld >= HoldSeconds) HighDone = true;
            if (lowHeld >= HoldSeconds) LowDone = true;
        }
    }
}
