using System;

namespace Neurotlon.Games.Football
{
    public enum FootballEventKind { ElementStarted, Touch, Kick, Landed, ElementFinished, GameOver }

    public struct FootballEvent
    {
        public readonly FootballEventKind Kind;
        public readonly FootballElement Element;
        public readonly int Points;

        public FootballEvent(FootballEventKind kind, FootballElement element, int points)
        {
            Kind = kind;
            Element = element;
            Points = points;
        }
    }

    // Один элемент полосы. Правила чистые: без Unity, без сцены.
    public interface IElement
    {
        FootballElement Kind { get; }
        bool Finished { get; }
        int Points { get; }                 // 0…2, определён после окончания
        float Accuracy { get; }             // 0…1, определён после окончания
        float TimeLeft { get; }
        void Step(float dt, float? eeg, float? emg);
        event Action<FootballEvent> Raised;
    }

    public abstract class ElementBase : IElement
    {
        protected readonly FootballTuning T;
        float timeLeft;

        public abstract FootballElement Kind { get; }
        public bool Finished { get; protected set; }
        public int Points { get; protected set; }
        public float Accuracy { get; protected set; }
        public float TimeLeft { get { return timeLeft; } }
        public event Action<FootballEvent> Raised;

        protected ElementBase(FootballTuning t)
        {
            T = t;
            timeLeft = t.ElementSeconds;
        }

        public void Step(float dt, float? eeg, float? emg)
        {
            if (Finished) return;
            timeLeft -= dt;
            Update(dt, eeg, emg);
            if (!Finished && timeLeft <= 0f) TimeUp();
        }

        protected abstract void Update(float dt, float? eeg, float? emg);

        // Время вышло: по умолчанию элемент не выполнен.
        protected virtual void TimeUp()
        {
            Finish(0, 0f);
        }

        protected void Finish(int points, float accuracy)
        {
            Finished = true;
            Points = points;
            Accuracy = accuracy < 0f ? 0f : (accuracy > 1f ? 1f : accuracy);
            Raise(FootballEventKind.ElementFinished, points);
        }

        protected void Raise(FootballEventKind kind, int points)
        {
            var handler = Raised;
            if (handler != null) handler(new FootballEvent(kind, Kind, points));
        }
    }

    // Ведение змейкой: пройти конусы, не задев их. Вариант управления задаётся в FootballTuning.Dribble.
    public sealed class SnakeElement : ElementBase
    {
        readonly IDribble dribble;
        readonly bool[] touched;
        public override FootballElement Kind { get { return FootballElement.Snake; } }
        public IDribble Dribble { get { return dribble; } }
        public int Touches { get; private set; }
        public float FinishY { get { return T.ConeY[T.ConeY.Length - 1] + T.FinishPastLastCone; } }
        public float X { get { return dribble.X; } }
        public float Y { get { return dribble.Y; } }

        public SnakeElement(FootballTuning t) : base(t)
        {
            dribble = DribbleFactory.Create(t);
            touched = new bool[t.ConeY.Length];
        }

        protected override void Update(float dt, float? eeg, float? emg)
        {
            dribble.Step(dt, emg);
            for (int i = 0; i < touched.Length; i++)
            {
                if (touched[i]) continue;
                float dy = dribble.Y - T.ConeY[i];
                if (Math.Abs(dy) < T.TouchRadius && Math.Abs(dribble.X) < T.TouchRadius)
                {
                    touched[i] = true;
                    Touches++;
                    Raise(FootballEventKind.Touch, i);                          // Points у Touch — номер конуса
                }
            }
            if (dribble.Y >= FinishY)
            {
                int points = Touches <= 1 ? 2 : 1;
                Finish(points, 1f - (float)Touches / touched.Length);
            }
        }
    }

    // Общая часть «прицельных» элементов (передача и удар): три попытки подряд. Прицел гуляет по цели, бросок — напряжение мышцы.
    // Очки элемента из суммы попыток (каждая 0…2): 5–6 → 2, 2–4 → 1, меньше → 0.
    public abstract class AimedElement : ElementBase
    {
        readonly AimWobble aim;
        readonly int[] attemptPoints;
        readonly float[] attemptAccuracy;
        float flightLeft;
        float pauseLeft;
        bool armed;
        public enum PhaseKind { Aiming, Flying, Settling }
        public PhaseKind Phase { get; private set; }
        public int Attempt { get; private set; }                          // номер текущей попытки, с нуля
        public int AttemptCount { get { return attemptPoints.Length; } }
        public float AimX { get { return aim.X; } }
        public float AimZ { get { return aim.Z; } }
        public float Amplitude { get { return aim.Amplitude; } }
        public float Concentration { get { return aim.Concentration; } }
        // Центр зоны разброса: у передачи это отверстие текущей попытки, у удара центр мишени.
        public virtual float CentreX { get { return 0f; } }
        public virtual float CentreZ { get { return 0f; } }
        public float HitX { get; private set; }
        public float HitZ { get; private set; }
        public float FlightProgress { get; private set; }
        public float SettleProgress { get; private set; }                 // 0…1 за время паузы после попытки

        // Очки попытки i или -1, если она ещё не сделана.
        public int AttemptResult(int i) { return i < Attempt || (i == Attempt && Finished) ? attemptPoints[i] : -1; }
        public int AttemptsDone { get { return Math.Min(Attempt, AttemptCount); } }

        protected AimedElement(FootballTuning t, float wobbleMax, float wobbleMin, Func<float> random01) : base(t)
        {
            aim = new AimWobble(wobbleMax, wobbleMin, t.WobbleGamma, t.EegSmoothSeconds, random01);
            attemptPoints = new int[t.Attempts];
            attemptAccuracy = new float[t.Attempts];
        }

        protected override void Update(float dt, float? eeg, float? emg)
        {
            aim.Step(dt, eeg);
            switch (Phase)
            {
                case PhaseKind.Aiming:
                    if (!emg.HasValue) return;
                    if (emg.Value <= T.GripOff) armed = true;
                    if (armed && emg.Value >= T.GripOn)
                    {
                        armed = false;
                        HitX = CentreX + aim.X;
                        HitZ = CentreZ + aim.Z;
                        Phase = PhaseKind.Flying;
                        flightLeft = T.KickFlightSeconds;
                        FlightProgress = 0f;
                        Raise(FootballEventKind.Kick, 0);
                    }
                    break;
                case PhaseKind.Flying:
                    flightLeft -= dt;
                    FlightProgress = Math.Min(1f, 1f - flightLeft / T.KickFlightSeconds);
                    if (flightLeft <= 0f) Land();
                    break;
                default:
                    pauseLeft -= dt;
                    SettleProgress = Math.Min(1f, 1f - pauseLeft / T.AttemptPauseSeconds);
                    if (pauseLeft <= 0f)
                    {
                        Phase = PhaseKind.Aiming;
                        armed = false;                                    // новая попытка только после расслабления мышцы
                    }
                    break;
            }
        }

        void Land()
        {
            int points;
            float accuracy;
            Evaluate(HitX, HitZ, out points, out accuracy);
            attemptPoints[Attempt] = points;
            attemptAccuracy[Attempt] = accuracy;
            Raise(FootballEventKind.Landed, points);
            Attempt++;
            if (Attempt >= AttemptCount)
            {
                FinishAll();
                return;
            }
            Phase = PhaseKind.Settling;
            pauseLeft = T.AttemptPauseSeconds;
            SettleProgress = 0f;
        }

        // Время вышло: несделанные попытки считаются нулём.
        protected override void TimeUp()
        {
            FinishAll();
        }

        void FinishAll()
        {
            int sum = 0;
            float acc = 0f;
            for (int i = 0; i < AttemptCount; i++)
            {
                if (i < Attempt) { sum += attemptPoints[i]; acc += attemptAccuracy[i]; }
            }
            Finish(PointsFromSum(sum, AttemptCount), acc / AttemptCount);
        }

        // Сумма очков попыток (каждая 0…2) → очки элемента: от 5/6 максимума 2, от 1/3 максимума 1.
        public static int PointsFromSum(int sum, int attempts)
        {
            int max = 2 * attempts;
            return sum * 6 >= max * 5 ? 2 : (sum * 3 >= max ? 1 : 0);
        }

        // Точка (x вправо, z вверх от центра цели) → очки попытки и точность 0…1.
        protected abstract void Evaluate(float x, float z, out int points, out float accuracy);
    }

    // Передача в ворота: чехол с отверстиями в углах. Куда бить на каждой попытке, задано в FootballTuning.
    // В отверстие — 2, в ворота мимо отверстия — 1, мимо ворот — 0.
    public sealed class PassElement : AimedElement
    {
        public override FootballElement Kind { get { return FootballElement.Pass; } }

        public PassElement(FootballTuning t, Func<float> random01) : base(t, t.PassWobbleMax, t.PassWobbleMin, random01) { }

        public float TargetX { get { return T.PassX(Attempt); } }
        public float TargetZ { get { return T.PassZ(Attempt); } }
        public override float CentreX { get { return TargetX; } }
        public override float CentreZ { get { return TargetZ; } }

        public static int PointsAt(FootballTuning t, float x, float z, float targetX, float targetZ)
        {
            float d = (float)Math.Sqrt((x - targetX) * (x - targetX) + (z - targetZ) * (z - targetZ));
            if (d <= t.PassHoleRadius) return 2;
            return t.OnTarp(x, z) ? 1 : 0;                                  // штанга и перекладина — как мимо
        }

        protected override void Evaluate(float x, float z, out int points, out float accuracy)
        {
            float d = (float)Math.Sqrt((x - TargetX) * (x - TargetX) + (z - TargetZ) * (z - TargetZ));
            points = PointsAt(T, x, z, TargetX, TargetZ);
            accuracy = points == 2 ? 1f - 0.3f * d / T.PassHoleRadius : (points == 1 ? 0.4f * (1f - Math.Min(1f, d / 1.6f)) : 0f);
        }
    }

    // Удар в круглую мишень: жёлтое и красное кольцо — 2, дальше до края — 1, мимо — 0.
    public sealed class KickElement : AimedElement
    {
        public override FootballElement Kind { get { return FootballElement.Kick; } }

        public KickElement(FootballTuning t, Func<float> random01) : base(t, t.KickWobbleMax, t.KickWobbleMin, random01) { }

        public static int PointsAt(FootballTuning t, float x, float z)
        {
            float d = (float)Math.Sqrt(x * x + z * z);
            return d <= t.TargetInnerRadius ? 2 : (d <= t.TargetRadius ? 1 : 0);
        }

        protected override void Evaluate(float x, float z, out int points, out float accuracy)
        {
            float d = (float)Math.Sqrt(x * x + z * z);
            points = PointsAt(T, x, z);
            accuracy = points == 0 ? 0f : 1f - Math.Min(1f, d / T.TargetRadius) * 0.7f;
        }
    }

    // Остановка мяча в зоне: мяч катится сам; напряжение мышцы тормозит. Нужно остановить его в жёлтом квадрате.
    public sealed class StopElement : ElementBase
    {
        float distance;
        float speed;
        public override FootballElement Kind { get { return FootballElement.Stop; } }
        public float Distance { get { return distance; } }              // пройдено от точки удара, м
        public float Speed { get { return speed; } }
        public float ZoneCentre { get { return T.StopZoneDistance; } }
        public float Brake { get; private set; }                         // текущее торможение от мышцы, м/с²
        public bool HitNet { get; private set; }                         // мяч докатился до сетки за зоной и остановился в ней
        public float ImpactSpeed { get; private set; }                   // скорость мяча в момент удара о сетку, м/с

        // Где мяч остановится, если держать нынешнее торможение (подсказка на экране).
        public float PredictedStop
        {
            get
            {
                float decel = T.StopFriction + Brake;
                float stop = decel <= 0f ? distance + 99f : distance + speed * speed / (2f * decel);
                return Math.Min(stop, NetStop);
            }
        }

        float NetStop { get { return T.StopNetDistance - T.BallRadius; } }     // докуда доходит центр мяча: до сетки

        public StopElement(FootballTuning t) : base(t)
        {
            speed = t.StopStartSpeed;
        }

        protected override void Update(float dt, float? eeg, float? emg)
        {
            if (emg.HasValue) Brake = (emg.Value < 0f ? 0f : (emg.Value > 1f ? 1f : emg.Value)) * T.StopBrakeGain;
            float decel = T.StopFriction + Brake;
            speed = Math.Max(0f, speed - decel * dt);
            distance += speed * dt;
            if (distance >= NetStop)
            {
                distance = NetStop;                                       // мяч упёрся в сетку и остановился: ждать, пока он докатится, не нужно
                ImpactSpeed = speed;
                speed = 0f;
                HitNet = true;
            }
            if (speed <= 0.02f) Resolve();
        }

        protected override void TimeUp()
        {
            Resolve();
        }

        void Resolve()
        {
            float miss = Math.Abs(distance - T.StopZoneDistance);
            int points = miss <= T.StopZoneHalf ? 2 : (miss <= T.StopZoneHalf * 2f ? 1 : 0);
            Raise(FootballEventKind.Landed, points);
            Finish(points, 1f - Math.Min(1f, miss / (T.StopZoneHalf * 2f)));
        }
    }
}
