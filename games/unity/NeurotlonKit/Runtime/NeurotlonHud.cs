using System;
using System.Globalization;
using UnityEngine;

namespace Neurotlon
{
    // Общая раскладка подписей счёта: чтобы число из нескольких цифр не переносилось на вторую строку и не «ехало».
    // Причина прежнего сдвига: у подписи IMGUI включён перенос слов, поле было впритык, «Очки  10» не влезало и
    // переносилось. Теперь поле считается по числу знаков, перенос выключен, правый край стоит на месте, а число
    // растёт влево.
    public static class NeurotlonHud
    {
        // Ширина цифры и буквы жирного шрифта относительно размера шрифта (с запасом).
        const float GlyphWidth = 0.70f;

        public static string ScoreText(int score)
        {
            return "Очки  " + score;
        }

        // Ширина поля под текст в пикселях: по числу знаков и размеру шрифта.
        public static float TextWidth(string text, float fontSize)
        {
            return text.Length * fontSize * GlyphWidth + fontSize * 0.5f;
        }

        // Поле подписи, прижатой к правому краю rightEdge: не уже, чем нужно тексту, и не уже minWidth.
        public static Rect RightAligned(float rightEdge, float top, float height, string text, float fontSize, float minWidth)
        {
            float width = Mathf.Max(minWidth, TextWidth(text, fontSize));
            return new Rect(rightEdge - width, top, width, height);
        }

        // «--debug-score 0,9,10,25,100»: список чисел для показа подписи (пусто или мусор: пустой список).
        public static int[] ParseValues(string text)
        {
            if (string.IsNullOrEmpty(text)) return new int[0];
            var values = new System.Collections.Generic.List<int>();
            foreach (string part in text.Split(','))
            {
                int value;
                if (int.TryParse(part.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out value)) values.Add(value);
            }
            return values.ToArray();
        }

        // Какое число из списка показывать сейчас: меняются каждые period секунд по кругу.
        public static int Cycle(int[] values, float time, float period)
        {
            if (values == null || values.Length == 0) return 0;
            int index = (int)Math.Floor(Math.Max(0f, time) / Math.Max(0.1f, period)) % values.Length;
            return values[index];
        }

        // Стиль подписи счёта: одна строка, без переноса, без обрезки.
        public static void SingleLine(GUIStyle style)
        {
            style.wordWrap = false;
            style.clipping = TextClipping.Overflow;
        }
    }
}
