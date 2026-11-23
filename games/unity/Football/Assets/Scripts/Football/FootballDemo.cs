namespace Neurotlon.Games.Football
{
    // Автоигрок для записи демонстрационных видео: вместо датчиков подаёт сигналы ноги (ЭМГ) и сосредоточения (ЭЭГ).
    // Включается только параметром запуска --demo right|wrong; в обычной игре не используется.
    //   right — всё сделано правильно: змейка по пути между конусами, полная концентрация (удар только когда она набралась),
    //           остановка в зоне;
    //   wrong — всё сделано неправильно: змейка прямо через конусы, концентрации нет, мяч не тормозят.
    public sealed class FootballDemo
    {
        const float RelaxedSeconds = 1.7f;                 // нога расслаблена перед ударом: за это время концентрация успевает набраться

        readonly bool right;
        readonly FootballTuning tuning;
        float aimClock;                                    // сколько секунд идёт нынешняя попытка прицеливания
        int lastElement = -1;
        int lastAttempt = -1;
        AimedElement.PhaseKind lastPhase = AimedElement.PhaseKind.Settling;

        public FootballDemo(bool right, FootballTuning tuning)
        {
            this.right = right;
            this.tuning = tuning;
        }

        public void Step(float dt)
        {
            aimClock += dt;
        }

        public void Signals(FootballRules rules, out float eeg, out float emg)
        {
            eeg = right ? 1f : 0f;
            emg = 0.5f;
            var snake = rules.Current as SnakeElement;
            if (snake != null)
            {
                // «Уровень напряжения» задаёт положение мяча по X; правильный игрок ведёт его по пути между конусами
                emg = right ? SnakePath.DesiredX(tuning, snake.Y) / (2f * tuning.LateralMax) + 0.5f : 0.5f;
                eeg = 0.5f;
                return;
            }
            if (rules.Current is StopElement)
            {
                emg = right ? 0.30f : 0f;                  // нужное торможение подобрано по параметрам; без торможения мяч проскакивает зону
                eeg = 0.5f;
                return;
            }
            // передача и удар: каждую попытку сначала расслабить ногу и сосредоточиться, потом сжать
            var aimed = rules.Current as AimedElement;
            if (aimed == null) { emg = 0.1f; return; }
            if (rules.CurrentIndex != lastElement || aimed.Attempt != lastAttempt || aimed.Phase != lastPhase)
            {
                if (aimed.Phase == AimedElement.PhaseKind.Aiming && (aimed.Phase != lastPhase || aimed.Attempt != lastAttempt || rules.CurrentIndex != lastElement)) aimClock = 0f;
                lastElement = rules.CurrentIndex;
                lastAttempt = aimed.Attempt;
                lastPhase = aimed.Phase;
            }
            emg = aimed.Phase == AimedElement.PhaseKind.Aiming && aimClock >= RelaxedSeconds ? 0.9f : 0.1f;
        }
    }
}
