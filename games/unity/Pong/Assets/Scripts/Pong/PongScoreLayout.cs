using System;
using System.Globalization;

namespace Neurotlon.Games.Pong
{
    // Раскладка крупного счёта «L:R» по центру сверху и параметр запуска --debug-score. Без Unity: тестируется отдельно.
    public static class PongScoreLayout
    {
        public const string DebugScoreArg = "--debug-score";
        public const float FontSize = 84f;
        public const float NameGap = 24f;           // запас между счётом и именем

        public static string Text(int left, int right)
        {
            return left + ":" + right;
        }

        // Ширина поля под счёт: по числу знаков, чтобы «11:10» и «100:99» не переносились.
        public static float Width(string scoreText)
        {
            return NeurotlonHud.TextWidth(scoreText, FontSize);
        }

        // На сколько имена отодвинуты от центра: половина ширины счёта и запас.
        public static float NameOffset(string scoreText)
        {
            return Width(scoreText) * 0.5f + NameGap;
        }

        // «--debug-score L:R» или «--debug-score N» (тогда N:N). Некорректное значение: false, счёт настоящий.
        public static bool TryParseDebugScore(string[] args, out int left, out int right)
        {
            left = 0;
            right = 0;
            if (args == null) return false;
            for (int i = 0; i < args.Length; i++)
            {
                string value = null;
                if (args[i] == DebugScoreArg && i + 1 < args.Length) value = args[i + 1];
                else if (args[i].StartsWith(DebugScoreArg + "=", StringComparison.Ordinal)) value = args[i].Substring(DebugScoreArg.Length + 1);
                if (value == null) continue;
                string[] parts = value.Split(':');
                if (parts.Length == 1 && TryNonNegative(parts[0], out left))
                {
                    right = left;
                    return true;
                }
                if (parts.Length == 2 && TryNonNegative(parts[0], out left) && TryNonNegative(parts[1], out right)) return true;
                left = 0;
                right = 0;
                return false;
            }
            return false;
        }

        static bool TryNonNegative(string text, out int value)
        {
            return int.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out value);
        }
    }
}
