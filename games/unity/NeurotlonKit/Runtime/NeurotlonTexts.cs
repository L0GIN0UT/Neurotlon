namespace Neurotlon
{
    // Общие формулировки для игрока: во всех играх и в калибровке говорим одинаково. Датчик может стоять на любой мышце
    // (в футболе на ноге), поэтому не «рука» и не «кулак», а «мышца с датчиком». Названия сигналов (emg, eeg) не меняются.
    public static class NeurotlonTexts
    {
        public const string SensorMuscle = "мышца с датчиком";

        public const string Tense = "Напрягите мышцу с датчиком";
        public const string Relax = "Расслабьте мышцу с датчиком";
        public const string RelaxShort = "Расслабьте";
        public const string TenseThenRelax = "Напрягите мышцу с датчиком, затем расслабьте";
        public const string RelaxBeforeNext = "Расслабьте мышцу с датчиком, чтобы подготовить следующий раз";
        public const string Focus = "Сосредоточьтесь";

        public const string TutorialDone = "Готово";
        public const string TestTitle = "ПРОВЕРКА";
        public const string TutorialRepeat = "Попробуйте ещё раз";
        public const string CallVolunteer = "Позовите волонтёра";

        public static string TutorialCounter(int step, int count)
        {
            return "Обучение: " + step + " из " + count;
        }
    }
}
