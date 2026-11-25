using System;

namespace Neurotlon.Games.Pong
{
    public enum Side { Left = 0, Right = 1 }

    public enum PongPhase { Serving, Rally, PointPause, Over }

    public enum PongEventKind { Serve, PaddleHit, WallBounce, Point, Overtime, GameOver }

    public struct PongEvent
    {
        public readonly PongEventKind Kind;
        public readonly Side Side;

        public PongEvent(PongEventKind kind, Side side)
        {
            Kind = kind;
            Side = side;
        }
    }

    // Настройки по умолчанию: методики подсчёта очков для понга пока нет, поэтому числа здесь,
    // в одном месте. Единицы: метры и секунды; ось X вдоль стола, Z поперёк.
    public sealed class PongTuning
    {
        public float HalfLength = 1.37f;          // половина длины стола
        public float HalfWidth = 0.7625f;         // половина ширины стола
        public float PaddleX = 1.55f;             // где стоят ракетки по X
        public float PaddleRange = 0.62f;         // ход ракетки по Z: от -PaddleRange до +PaddleRange
        // Зона отбития — вся ракетка, как её видит игрок: от центра лопасти до края лопасти в сторону «вправо» для игрока
        // и до конца ручки в сторону «влево» (ракетка повёрнута в своей плоскости); плюс радиус мяча.
        public float HitReachRight = 0.15f;       // до края лопасти (~0,13 м) и мяч
        public float HitReachLeft = 0.29f;        // до конца ручки (~0,27 м) и мяч
        public float HitHalfHeight = 0.14f;       // масштаб угла отскока: у края лопасти мяч уходит под максимальным углом
        public float BallRadius = 0.02f;
        // Мяч разворачивается на поверхности лопасти: ракетка в момент контакта выдвинута вперёд на 0,12 м, толщина лопасти
        // ~2,4 см и радиус мяча 2 см: 0,12 + 0,012 + 0,02 = 0,152 м от центра ракетки.
        public float PaddleFaceInset = 0.17f;     // +1,5 см запаса на наклон лопасти
        public float StartSpeed = 1.7f;
        public float SpeedStep = 0.12f;           // прибавка скорости за каждое отбитие
        public float MaxSpeed = 3.4f;
        public float MaxAngleDegrees = 50f;       // максимальный угол отскока от края ракетки
        public float ServeDelay = 0.75f;
        public float PointPause = 1.3f;
        public float OvertimeAcceleration = 0.3f; // золотой мяч: скорость растёт, чтобы розыгрыш точно закончился
        public int TargetScore = 11;
        public int ServesPerTurn = 2;             // подача меняется через каждые 2 очка

        // Копия настроек: песочница обучения меняет свои числа, не трогая настоящие.
        public PongTuning Clone()
        {
            return (PongTuning)MemberwiseClone();
        }
    }

    // Правила и физика понга без Unity: тестируется отдельно.
    // Матч до TargetScore очков. Время вышло при разном счёте: побеждает ведущий. При равном счёте
    // играется золотой мяч: следующее очко решает матч.
    public sealed class PongRules
    {
        const float Deg2Rad = (float)(Math.PI / 180.0);

        readonly PongTuning t;
        readonly Func<float> random01;
        readonly Side firstServer;
        float phaseTimer;
        float overtimeElapsed;
        int hits;
        int pointsPlayed;

        public event Action<PongEvent> Raised;

        public int ScoreLeft { get; private set; }
        public int ScoreRight { get; private set; }
        public float BallX { get; private set; }
        public float BallZ { get; private set; }
        public float VelX { get; private set; }
        public float VelZ { get; private set; }
        public PongPhase Phase { get; private set; }
        public Side Server { get; private set; }
        public bool Overtime { get; private set; }
        public Side? Winner { get; private set; }
        public PongTuning Tuning { get { return t; } }
        // Сколько секунд осталось до удара подающего (0 вне подачи): по нему рисуется подброс мяча и замах.
        public float ServeTimeLeft { get { return Phase == PongPhase.Serving ? Math.Max(0f, phaseTimer) : 0f; } }

        // random01: источник случайных чисел [0, 1); в тестах подставляется.
        public PongRules(PongTuning tuning, Func<float> random01, Side firstServer = Side.Left)
        {
            t = tuning;
            this.random01 = random01;
            this.firstServer = firstServer;
            BeginServe();
        }

        public int ScoreOf(Side side)
        {
            return side == Side.Left ? ScoreLeft : ScoreRight;
        }

        public static Side Other(Side side)
        {
            return side == Side.Left ? Side.Right : Side.Left;
        }

        // dt — секунды; leftZ / rightZ — положение ракеток по Z.
        public void Step(float dt, float leftZ, float rightZ)
        {
            switch (Phase)
            {
                case PongPhase.Serving:
                    BallZ = Server == Side.Left ? leftZ : rightZ;
                    phaseTimer -= dt;
                    if (phaseTimer <= 0f) Launch();
                    break;
                case PongPhase.Rally:
                    StepRally(dt, leftZ, rightZ);
                    break;
                case PongPhase.PointPause:
                    Move(dt);
                    phaseTimer -= dt;
                    if (phaseTimer <= 0f) BeginServe();
                    break;
                case PongPhase.Over:
                    Move(dt);
                    break;
            }
        }

        // Время игры из launch.json вышло.
        public void TimeExpired()
        {
            if (Phase == PongPhase.Over) return;
            if (ScoreLeft != ScoreRight)
            {
                End(ScoreLeft > ScoreRight ? Side.Left : Side.Right);
                return;
            }
            Overtime = true;
            overtimeElapsed = 0f;
            Raise(PongEventKind.Overtime, Side.Left);
        }

        // --- внутреннее ---

        void StepRally(float dt, float leftZ, float rightZ)
        {
            if (Overtime)
            {
                overtimeElapsed += dt;
                Rescale(Speed());
            }
            Move(dt);
            float limit = t.HalfWidth - t.BallRadius;
            if (BallZ > limit)
            {
                BallZ = limit;
                VelZ = -VelZ;
                Raise(PongEventKind.WallBounce, VelX > 0 ? Side.Right : Side.Left);
            }
            else if (BallZ < -limit)
            {
                BallZ = -limit;
                VelZ = -VelZ;
                Raise(PongEventKind.WallBounce, VelX > 0 ? Side.Right : Side.Left);
            }
            float plane = t.PaddleX - t.PaddleFaceInset;
            if (VelX > 0f && BallX >= plane) ResolvePaddle(Side.Right, rightZ, plane);
            else if (VelX < 0f && BallX <= -plane) ResolvePaddle(Side.Left, leftZ, -plane);
        }

        void ResolvePaddle(Side side, float paddleZ, float planeX)
        {
            // «вправо» для игрока слева — это -Z, для игрока справа — +Z
            float along = (BallZ - paddleZ) * (side == Side.Left ? -1f : 1f);
            if (along > t.HitReachRight || along < -t.HitReachLeft)
            {
                Award(Other(side));
                return;
            }
            hits++;
            float offset = (BallZ - paddleZ) / t.HitHalfHeight;
            float angle = Clamp(offset, -1f, 1f) * t.MaxAngleDegrees * Deg2Rad;
            float speed = Speed();
            float dir = side == Side.Right ? -1f : 1f;
            VelX = dir * speed * (float)Math.Cos(angle);
            VelZ = speed * (float)Math.Sin(angle);
            BallX = planeX;
            Raise(PongEventKind.PaddleHit, side);
        }

        void Award(Side scorer)
        {
            if (scorer == Side.Left) ScoreLeft++; else ScoreRight++;
            pointsPlayed++;
            Raise(PongEventKind.Point, scorer);
            if (ScoreOf(scorer) >= t.TargetScore || Overtime)
            {
                End(scorer);
                return;
            }
            Phase = PongPhase.PointPause;
            phaseTimer = t.PointPause;
        }

        void End(Side winner)
        {
            Phase = PongPhase.Over;
            Winner = winner;
            Raise(PongEventKind.GameOver, winner);
        }

        void BeginServe()
        {
            Phase = PongPhase.Serving;
            phaseTimer = t.ServeDelay;
            hits = 0;
            VelX = 0f;
            VelZ = 0f;
            int turn = (pointsPlayed / t.ServesPerTurn) % 2;
            Server = turn == 0 ? firstServer : Other(firstServer);
            BallX = (Server == Side.Left ? -1f : 1f) * (t.PaddleX - t.PaddleFaceInset - 0.02f);
            Raise(PongEventKind.Serve, Server);
        }

        void Launch()
        {
            float angle = (random01() * 2f - 1f) * 15f * Deg2Rad;
            float speed = Speed();
            float dir = Server == Side.Left ? 1f : -1f;
            VelX = dir * speed * (float)Math.Cos(angle);
            VelZ = speed * (float)Math.Sin(angle);
            Phase = PongPhase.Rally;
            Raise(PongEventKind.PaddleHit, Server);     // подача — тоже удар ракеткой
        }

        float Speed()
        {
            float s = t.StartSpeed + hits * t.SpeedStep;
            if (Overtime) return s + overtimeElapsed * t.OvertimeAcceleration;
            return Math.Min(s, t.MaxSpeed);
        }

        void Rescale(float speed)
        {
            float current = (float)Math.Sqrt(VelX * VelX + VelZ * VelZ);
            if (current < 1e-4f) return;
            float k = speed / current;
            VelX *= k;
            VelZ *= k;
        }

        void Move(float dt)
        {
            BallX += VelX * dt;
            BallZ += VelZ * dt;
        }

        void Raise(PongEventKind kind, Side side)
        {
            var handler = Raised;
            if (handler != null) handler(new PongEvent(kind, side));
        }

        static float Clamp(float v, float lo, float hi)
        {
            return v < lo ? lo : (v > hi ? hi : v);
        }
    }
}
