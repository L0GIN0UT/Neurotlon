using System;
using System.Globalization;

namespace Neurotlon.Games.Darts
{
    // Необязательные параметры запуска дартса (для показа и отладки). Без параметра игра работает как обычно.
    public static class DartsArgs
    {
        public const string DebugScore = "--debug-score";

        // Текст после имени параметра (`--имя X` или `--имя=X`) или null, если параметра нет.
        public static string TextValue(string[] args, string name)
        {
            string text = null;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == name && i + 1 < args.Length) text = args[i + 1];
                else if (args[i].StartsWith(name + "=", StringComparison.Ordinal)) text = args[i].Substring(name.Length + 1);
            }
            return text;
        }

        // Целое значение после имени параметра (`--имя N` или `--имя=N`) или null, если параметра нет или он не число.
        public static int? IntValue(string[] args, string name)
        {
            string text = null;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == name && i + 1 < args.Length) text = args[i + 1];
                else if (args[i].StartsWith(name + "=", StringComparison.Ordinal)) text = args[i].Substring(name.Length + 1);
            }
            int value;
            if (text != null && int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out value)) return value;
            return null;
        }
    }
}
