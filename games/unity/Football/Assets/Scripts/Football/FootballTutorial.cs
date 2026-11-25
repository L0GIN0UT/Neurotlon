using System;

namespace Neurotlon.Games.Football
{
    // Механики футбола, которые игрок пробует по очереди в обучении. Hits: шаг-проверка «попади сам».
    public enum TutorialStep { Cones, Focus, Shot, Hits, Gate, Slow, StopZone }

    // Счётчик шага «попади сам»: нужно Needed попаданий из MaxAttempts ударов (как точки попыток в игре). Попадание: очки
    // попытки >= 1. Пять ударов сделаны, а попаданий меньше двух: шаг начинается заново (Exhausted).
    // Чистый класс без Unity.
    public sealed class TutorialHits
    {
        public const int Needed = 2;           // сколько попаданий засчитывают шаг
        public const int MaxAttempts = 5;      // сколько ударов на попытку шага (по числу точек попыток)

        readonly int[] results = new int[MaxAttempts];

        public int Hits { get; private set; }
        public int Used { get; private set; }  // сколько ударов уже сделано
        public bool Passed { get { return Hits >= Needed; } }
        public bool Exhausted { get { return !Passed && Used >= MaxAttempts; } }

        // Очки i-го удара или -1, если он ещё не сделан.
        public int ResultOf(int i)
        {
            return i >= 0 && i < Used ? results[i] : -1;
        }

        // Удар приземлился с этими очками. После зачёта шага и после пятого удара новые не учитываются.
        public void Register(int points)
        {
            if (Passed || Used >= MaxAttempts) return;
            results[Used] = points;
            Used++;
            if (points >= 1) Hits++;
        }

        public void Reset()
        {
            Hits = 0;
            Used = 0;
        }
    }

    // Условия «шаг обучения засчитан»: чистый класс без Unity. Игра подаёт концентрацию, скорость мяча и события правил,
    // класс отвечает, сработала ли механика. Одна механика на шаг; Begin начинает попытку шага с чистого листа.
    public sealed class FootballTutorial
    {
        public const float FocusLevel = 0.6f;               // концентрация, которую надо держать
        public const float FocusHoldSeconds = 0.5f;         // сколько держать непрерывно
        public const int StopZonePoints = 2;                // очки остановки, при которых шаг засчитан: мяч внутри жёлтого квадрата
        public const float SlowShare = 0.5f;                // мяч замедлился, когда скорость упала ниже этой доли начальной
        public const float CheckTimeoutSeconds = 90f;       // на шаг-проверку «попади сам»
        public const int SandboxCones = 2;                  // конусов в песочнице змейки
        public const int CheckAttempts = TutorialHits.MaxAttempts;       // ударов в песочнице шага-проверки: пять, как точек попыток в игре
        public const string HitsFormat = "Попаданий: {0} из {1}";

        readonly FootballTuning tuning;
        TutorialStep step;
        float focusHeld;

        public FootballTutorial(FootballTuning tuning)
        {
            this.tuning = tuning;
        }

        public TutorialStep Step { get { return step; } }
        public bool Done { get; private set; }                  // механика сработала (остаётся true до следующего Begin)
        public bool Retry { get; private set; }                 // попытка провалена сразу: песочницу надо завести заново
        public TutorialHits Hits { get; private set; } = new TutorialHits();
        public float FocusProgress { get { return Math.Min(1f, focusHeld / FocusHoldSeconds); } }

        // Шаги в порядке показа. Список один для всех способов ведения: от способа зависит только текст первого шага.
        public static TutorialStep[] StepsFor(DribbleMode mode)
        {
            return new[]
            {
                TutorialStep.Cones, TutorialStep.Focus, TutorialStep.Shot, TutorialStep.Hits,
                TutorialStep.Gate, TutorialStep.Slow, TutorialStep.StopZone,
            };
        }

        // Шаг-проверку Enter не пропускает.
        public static bool IsSkippable(TutorialStep step)
        {
            return step != TutorialStep.Hits;
        }

        // Секунд на одну попытку шага.
        public static float TimeoutFor(TutorialStep step)
        {
            return step == TutorialStep.Hits ? CheckTimeoutSeconds : NeurotlonTutorial.StepSeconds;
        }

        // Сколько попыток в прицельном элементе шага.
        public static int AttemptsFor(TutorialStep step)
        {
            return step == TutorialStep.Hits ? CheckAttempts : 1;
        }

        public static string HitsText(int hits)
        {
            return string.Format(HitsFormat, hits, TutorialHits.Needed);
        }

        // Подсказка шага: 1-2 коротких строки, только про эту механику.
        public static string TextFor(TutorialStep step, DribbleMode mode)
        {
            switch (step)
            {
                case TutorialStep.Cones: return ConesText(mode);
                case TutorialStep.Focus: return NeurotlonTexts.Focus + ": круг разброса сужается, прицел меньше дрожит";
                case TutorialStep.Shot: return NeurotlonTexts.Tense + ": мяч полетит в прицел";
                case TutorialStep.Hits: return "Попадите в мишень дважды";
                case TutorialStep.Gate: return "Теперь ворота: бейте в золотое кольцо";
                case TutorialStep.Slow: return "Мяч катится сам: напрягите мышцу, чтобы он замедлился";
                default: return "Остановите мяч в жёлтой зоне";
            }
        }

        static string ConesText(DribbleMode mode)
        {
            const string task = "\nОбведите два конуса, не задев их";
            switch (mode)
            {
                case DribbleMode.Level:
                    return NeurotlonTexts.Tense + ": мяч смещается вправо, " + NeurotlonTexts.RelaxShort.ToLowerInvariant() + ": влево." + task;
                case DribbleMode.Rhythm:
                    return "Напрягайте мышцу с датчиком в такт, когда кольцо сузится." + task;
                default:
                    return NeurotlonTexts.Tense + ": мяч едет быстрее, " + NeurotlonTexts.RelaxShort.ToLowerInvariant() + ": тормозит." + task;
            }
        }

        // Новая попытка шага: все счётчики с нуля.
        public void Begin(TutorialStep next)
        {
            step = next;
            Done = false;
            Retry = false;
            focusHeld = 0f;
            Hits.Reset();
        }

        // Попытка не может закончиться засчитанным шагом (элемент кончился сам): завести песочницу заново.
        public void MarkRetry()
        {
            if (!Done) Retry = true;
        }

        // Концентрация 0…1: держится не меньше FocusLevel непрерывно FocusHoldSeconds; упала — отсчёт заново.
        public void ObserveConcentration(float concentration, float dt)
        {
            if (Done || Retry || step != TutorialStep.Focus) return;
            if (concentration >= FocusLevel) focusHeld += dt;
            else focusHeld = 0f;
            if (focusHeld >= FocusHoldSeconds - 1e-4f) Done = true;      // допуск на накопление float
        }

        // Скорость катящегося мяча («остановка, торможение»): ниже доли SlowShare от начальной. Мяч, остановленный сеткой
        // за зоной, не считается: так шаг не засчитывается без напряжения мышцы.
        public void ObserveStopSpeed(float speed, bool hitNet)
        {
            if (Done || Retry || step != TutorialStep.Slow || hitNet) return;
            if (speed < tuning.StopStartSpeed * SlowShare) Done = true;
        }

        // События правил песочницы.
        public void ObserveEvent(FootballEvent e)
        {
            if (Done || Retry) return;
            switch (step)
            {
                case TutorialStep.Cones:
                    // задет конус: новая попытка; оба конуса пройдены без касаний (змейка закончилась): шаг засчитан
                    if (e.Kind == FootballEventKind.Touch) Retry = true;
                    else if (e.Kind == FootballEventKind.ElementFinished && e.Element == FootballElement.Snake) Done = true;
                    break;
                case TutorialStep.Shot:
                    if (e.Kind == FootballEventKind.Kick && e.Element == FootballElement.Kick) Done = true;
                    break;
                case TutorialStep.Hits:
                    if (e.Kind != FootballEventKind.Landed || e.Element != FootballElement.Kick) break;
                    Hits.Register(e.Points);
                    if (Hits.Passed) Done = true;           // два попадания из пяти
                    else if (Hits.Exhausted) Retry = true;  // пять ударов, а попаданий меньше двух: заново
                    break;
                case TutorialStep.Gate:
                    if (e.Kind == FootballEventKind.Kick && e.Element == FootballElement.Pass) Done = true;
                    break;
                case TutorialStep.StopZone:
                    // строго: засчитано, только если мяч встал внутри жёлтого квадрата (2 очка); рядом (1 очко), проехал
                    // или не доехал: сразу новая попытка
                    if (e.Kind == FootballEventKind.ElementFinished && e.Element == FootballElement.Stop)
                    {
                        if (e.Points >= StopZonePoints) Done = true;
                        else Retry = true;
                    }
                    break;
            }
        }
    }
}
