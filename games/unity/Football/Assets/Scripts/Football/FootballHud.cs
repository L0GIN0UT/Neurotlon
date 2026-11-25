using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Раскладка верхней плашки: таймер и подпись очков. Отдельно от игры, чтобы проверить в тестах, что поле очков,
    // растущее влево, не наезжает на таймер ни при каком счёте.
    public static class FootballHud
    {
        // Таймер стоит правее центра, сразу за плитками элементов (они занимают около 100 единиц масштаба от центра).
        public static Rect TimerRect(Rect top, float s)
        {
            return new Rect(top.center.x + 104f * s, top.y, 112f * s, top.height);
        }

        // Правый край подписи очков неподвижен, число растёт влево.
        public static float ScoreRightEdge(Rect top, float s)
        {
            return top.xMax - 36f * s;
        }

        public static Rect ScoreRect(Rect top, float s, int score, float fontSize)
        {
            return NeurotlonHud.RightAligned(ScoreRightEdge(top, s), top.y, top.height, NeurotlonHud.ScoreText(score), fontSize, top.width * 0.2f);
        }
    }
}
