namespace Neurotlon.Games.Darts
{
    // Условия шагов обучения дартса без Unity: тестируются отдельно.
    // Шаг 0 «Сосредоточение»: сосредоточение держится не ниже FocusLevel непрерывно FocusHoldSeconds.
    // Шаг 1 «Бросок»: засчитан по событию DartsEventKind.Throw (дротик вылетел).
    // Шаг 2 «Попади сам» (проверка): два попадания в зелёное или оранжевое кольцо из пяти бросков (DartsHitCounter).
    public sealed class DartsTutorial
    {
        public const int FocusStep = 0;
        public const int ThrowStep = 1;
        public const int AimStep = 2;
        public const int StepCount = 3;

        public const float FocusLevel = 0.6f;
        public const float FocusHoldSeconds = 0.5f;

        readonly DartsHitCounter counter = new DartsHitCounter();
        float focusHeld;
        bool threw;
        bool done;

        // Сколько секунд подряд сосредоточение не ниже порога.
        public float FocusHeld { get { return focusHeld; } }

        // Шаг уже засчитан (остаётся true, пока показано «Готово»).
        public bool Done { get { return done; } }

        // Счётчик попаданий шага-проверки.
        public DartsHitCounter Counter { get { return counter; } }

        // Новая попытка шага: накопленное сбрасывается.
        public void Reset()
        {
            focusHeld = 0f;
            threw = false;
            done = false;
            counter.Reset();
        }

        // Событие правил: запоминаем вылет дротика и результат приземлившегося.
        public void NoteEvent(DartsEvent e)
        {
            if (e.Kind == DartsEventKind.Throw) threw = true;
            else if (e.Kind == DartsEventKind.Hit) counter.NoteThrow(e.Points);
        }

        // Каждый кадр шага. Возвращает true, когда механика шага сработала (и дальше остаётся true).
        public bool Update(int step, float dt, float concentration)
        {
            if (done) return true;
            if (step == FocusStep)
            {
                if (concentration >= FocusLevel) focusHeld += dt;
                else focusHeld = 0f;
                done = focusHeld >= FocusHoldSeconds;
            }
            else if (step == ThrowStep)
            {
                done = threw;
            }
            else if (step == AimStep)
            {
                done = counter.Passed;
            }
            return done;
        }
    }
}
