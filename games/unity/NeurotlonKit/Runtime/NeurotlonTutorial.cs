using System;

namespace Neurotlon
{
    // Ход обучения без Unity: тестируется отдельно. Игрок пробует механики по одной. Сначала ReadSeconds подсказка
    // показана крупно, чтобы её прочитать (механика в это время не считается), потом идёт попытка. Шаг засчитан, когда механика
    // сработала (игра сообщает об этом в Update); не сработала за StepSeconds, шаг начинается заново (песочница
    // сбрасывается); после HelpAfterTimeouts неудач просят волонтёра. Волонтёр может пропустить шаг (Skip, клавиша Enter).
    // Последний шаг заканчивает обучение (State == Finished).
    public sealed class NeurotlonTutorial
    {
        public const float StepSeconds = 20f;           // на одну попытку шага
        public const float ReadSeconds = 3f;            // сколько новая подсказка показывается крупно перед попыткой
        public const float DoneShowSeconds = 1.5f;      // сколько показывается «Готово»
        public const int HelpAfterTimeouts = 2;         // после стольких неудач на шаге: «Позовите волонтёра»

        public enum Phase { Reading, Trying, Done, Finished }

        readonly int count;
        readonly Func<int, bool> skippable;              // можно ли пропустить шаг клавишей Enter (шаги-проверки нельзя)
        readonly Func<int, float> timeout;               // сколько секунд на одну попытку шага
        float doneLeft;
        float tried;                                    // сколько секунд идёт текущая попытка шага
        float readLeft;

        // Не засчитывать шаг раньше стольких секунд после начала попытки (для показа: успеть прочитать подсказку). По умолчанию 0.
        public float MinTrySeconds { get; set; }

        public int Count { get { return count; } }
        public bool CanSkipNow { get { return State != Phase.Finished && skippable(Index); } }
        public int Index { get; private set; }                  // текущий шаг, с нуля
        public Phase State { get; private set; }
        public float TimeLeft { get; private set; }             // до конца попытки
        public int Timeouts { get; private set; }               // неудачи на текущем шаге
        public bool NeedsHelp { get { return State == Phase.Trying && Timeouts >= HelpAfterTimeouts; } }
        public bool InPlay { get { return State == Phase.Trying || State == Phase.Done; } }          // песочница живёт: чтение уже закончилось

        // Шаг начался (первый раз или заново после неудачи): игра готовит песочницу под него.
        public event Action<int> StepStarted;

        // Началась попытка (чтение закончилось или это повтор): игра сбрасывает счётчики условия шага.
        public event Action<int> TryStarted;

        public NeurotlonTutorial(int stepCount) : this(stepCount, null, null)
        {
        }

        // skippable(i): можно ли пропустить шаг i (по умолчанию все); timeout(i): секунд на попытку шага i (по умолчанию StepSeconds).
        public NeurotlonTutorial(int stepCount, Func<int, bool> skippable, Func<int, float> timeout)
        {
            count = stepCount;
            this.skippable = skippable ?? (i => true);
            this.timeout = timeout ?? (i => StepSeconds);
            State = stepCount > 0 ? Phase.Reading : Phase.Finished;
        }

        // Вызвать один раз после подписки на StepStarted.
        public void Begin()
        {
            if (State == Phase.Reading) StartStep(true);
        }

        // dt: секунды; mechanicWorked: игра подтвердила, что механика этого шага сработала.
        public void Update(float dt, bool mechanicWorked)
        {
            switch (State)
            {
                case Phase.Reading:
                    readLeft -= dt;
                    if (readLeft <= 0f)
                    {
                        State = Phase.Trying;
                        TimeLeft = timeout(Index);
                        tried = 0f;
                        RaiseTryStarted();
                    }
                    break;
                case Phase.Trying:
                    tried += dt;
                    if (mechanicWorked && tried >= MinTrySeconds)
                    {
                        State = Phase.Done;
                        doneLeft = DoneShowSeconds;
                        return;
                    }
                    TimeLeft -= dt;
                    if (TimeLeft <= 0f)
                    {
                        Timeouts++;
                        StartStep(false);                       // повтор: подсказку уже читали, сразу попытка
                    }
                    break;
                case Phase.Done:
                    doneLeft -= dt;
                    if (doneLeft <= 0f) Next();
                    break;
            }
        }

        // Волонтёр пропускает шаг: сразу к следующему. Шаги-проверки (skippable == false) пропустить нельзя; вернёт false.
        public bool Skip()
        {
            if (!CanSkipNow) return false;
            Next();
            return true;
        }

        void Next()
        {
            Index++;
            Timeouts = 0;
            if (Index >= count)
            {
                State = Phase.Finished;
                return;
            }
            StartStep(true);
        }

        void StartStep(bool withReading)
        {
            State = withReading ? Phase.Reading : Phase.Trying;
            readLeft = ReadSeconds;
            TimeLeft = timeout(Index);
            tried = 0f;
            var handler = StepStarted;
            if (handler != null) handler(Index);
            if (!withReading) RaiseTryStarted();
        }

        void RaiseTryStarted()
        {
            var handler = TryStarted;
            if (handler != null) handler(Index);
        }
    }
}
