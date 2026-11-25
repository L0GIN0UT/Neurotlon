namespace Neurotlon.Games.Darts
{
    // Счётчик шага-проверки «попади сам» без Unity: нужно Needed попаданий (очки броска >= 1) из Throws бросков.
    // Каждый бросок занимает точку (квадратик), как в основной игре; промах бросок тратит, но попаданием не считается.
    // Пять бросков сделано, а попаданий меньше двух: шаг надо начать заново (MustRestart).
    public sealed class DartsHitCounter
    {
        public const int Needed = 2;
        public const int Throws = 5;

        public int Hits { get; private set; }
        public int Thrown { get; private set; }

        // Шаг выполнен: нужное число попаданий набрано (дальше броски не считаются).
        public bool Passed { get { return Hits >= Needed; } }

        // Все броски сделаны, а двух попаданий нет: песочницу надо завести заново.
        public bool MustRestart { get { return !Passed && Thrown >= Throws; } }

        // Бросок приземлился с этим числом очков.
        public void NoteThrow(int points)
        {
            if (Passed || Thrown >= Throws) return;
            Thrown++;
            if (points >= 1) Hits++;
        }

        public void Reset()
        {
            Hits = 0;
            Thrown = 0;
        }

        // Подпись рядом с квадратиками.
        public static string Label(int hits)
        {
            return "Попаданий: " + hits + " из " + Needed;
        }
    }
}
