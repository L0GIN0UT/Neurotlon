using System;

namespace Neurotlon.Games.Football
{
    // Полоса из четырёх элементов по очереди: змейка → передача в ворота → остановка в зоне → удар в мишень.
    // Очки: за каждый элемент 0…2, плюс до 2 за среднюю точность, итог не больше MaxPoints (по умолчанию 10).
    public sealed class FootballRules
    {
        public const int ElementCount = 4;
        readonly FootballTuning t;
        readonly Func<float> random01;
        readonly IElement[] elements = new IElement[ElementCount];
        readonly int[] results = { -1, -1, -1, -1 };
        int index;
        public event Action<FootballEvent> Raised;

        public FootballRules(FootballTuning tuning, Func<float> random01)
        {
            t = tuning;
            this.random01 = random01;
            Begin(0);
        }

        public FootballTuning Tuning { get { return t; } }
        public int CurrentIndex { get { return index; } }
        public bool Over { get; private set; }
        public IElement Current { get { return elements[Math.Min(index, ElementCount - 1)]; } }
        public int PointsOf(int i) { return results[i]; }

        // Очки за элементы без бонуса.
        public int ElementPoints
        {
            get
            {
                int sum = 0;
                for (int i = 0; i < ElementCount; i++) if (results[i] > 0) sum += results[i];
                return sum;
            }
        }

        // Бонус за точность: 0…2 по среднему по выполненным элементам, считается, когда игра окончена.
        public int AccuracyBonus
        {
            get
            {
                if (!Over) return 0;
                float sum = 0f;
                for (int i = 0; i < ElementCount; i++) sum += elements[i].Accuracy;
                return (int)Math.Round(2.0 * sum / ElementCount, MidpointRounding.AwayFromZero);
            }
        }

        public int Score { get { return Math.Min(MaxPoints, ElementPoints + AccuracyBonus); } }
        public int MaxPoints { get; set; } = 10;

        public void Step(float dt, float? eeg, float? emg)
        {
            if (Over) return;
            var e = elements[index];
            e.Step(dt, eeg, emg);
            if (e.Finished)
            {
                results[index] = e.Points;
                if (index + 1 >= ElementCount)
                {
                    Over = true;
                    Raise(new FootballEvent(FootballEventKind.GameOver, e.Kind, Score));
                }
                else
                {
                    Begin(index + 1);
                }
            }
        }

        // Для показа вариантов: пока идёт змейка, можно переключить способ ведения и начать её заново.
        public bool SwitchDribble(DribbleMode mode)
        {
            if (Over || index != 0) return false;
            t.Dribble = mode;
            Begin(0);
            return true;
        }

        void Begin(int i)
        {
            index = i;
            IElement e;
            switch (i)
            {
                case 0: e = new SnakeElement(t); break;
                case 1: e = new PassElement(t, random01); break;
                case 2: e = new StopElement(t); break;
                default: e = new KickElement(t, random01); break;
            }
            e.Raised += OnElementEvent;
            elements[i] = e;
            Raise(new FootballEvent(FootballEventKind.ElementStarted, e.Kind, 0));
        }

        void OnElementEvent(FootballEvent e)
        {
            Raise(e);
        }

        void Raise(FootballEvent e)
        {
            var handler = Raised;
            if (handler != null) handler(e);
        }
    }
}
