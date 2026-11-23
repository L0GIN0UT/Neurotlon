using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Где что стоит на поле (мир Unity: X вправо, Y вверх, Z вдоль поля вперёд). Те же числа использует сборщик сцены.
    // Поле 48 × 30 м; станции разнесены, камера на каждом элементе встаёт сзади мяча.
    public static class FootballLayout
    {
        public const float FieldWidth = 48f;
        public const float FieldDepth = 30f;

        public static readonly Vector3 SnakeBall = new Vector3(0f, 0f, -10f);       // старт змейки (конусы по X = 0)
        public static readonly Vector3 PassBall = new Vector3(6f, 0f, 2f);          // мяч для передачи
        public static readonly Vector3 GoalMouth = new Vector3(9.5f, 0f, 2f);       // проём ворот (смотрят в −X)
        public const float GoalCentreHeight = 0.7f;
        public static readonly Vector3 StopBall = new Vector3(-2f, 0f, 4.5f);       // мяч катится в −X
        public static readonly Vector3 ZoneCentre = new Vector3(-8f, 0f, 4.5f);     // центр жёлтой зоны
        public const float StopNetDistance = 9.0f;                                   // сетка за зоной: от места удара вдоль качения мяча, м
        public static Vector3 StopNet { get { return new Vector3(StopBall.x - StopNetDistance, 0f, StopBall.z); } }     // середина сетки, мяч катится в −X
        public const float ZoneSize = 2.6f;
        public static readonly Vector3 KickBall = new Vector3(0f, 0f, 8f);          // мяч для удара в мишень
        public static readonly Vector3 TargetBase = new Vector3(0f, 0f, 12.5f);     // стойка мишени (лицо смотрит в −Z)
        public const float BallRadius = 0.11f;
        public const float GrassSurface = 0.025f;                                   // верх травы: конусы и другие тела ложатся на эту высоту, а не тонут в траве
    }
}
