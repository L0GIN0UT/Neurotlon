using System;
using System.Collections.Generic;
using NUnit.Framework;

namespace Neurotlon.Games.Pong.Tests
{
    public class PongRulesTests
    {
        const float Dt = 0.01f;

        static PongRules NewRules(float random = 0.5f, Side firstServer = Side.Left)
        {
            return new PongRules(new PongTuning(), () => random, firstServer);
        }

        // Шагает, пока не наступит нужная фаза (или не кончится время).
        static void RunUntil(PongRules r, Func<bool> done, Func<float> leftZ, Func<float> rightZ, float maxSeconds = 60f)
        {
            for (float t = 0f; t < maxSeconds && !done(); t += Dt) r.Step(Dt, leftZ(), rightZ());
        }

        // Обе ракетки идут точно за мячом: отбивают всегда.
        static void Track(PongRules r, float seconds)
        {
            for (float t = 0f; t < seconds && r.Phase != PongPhase.Over; t += Dt) r.Step(Dt, r.BallZ, r.BallZ);
        }

        // Левая ракетка стоит по центру и отбивает, правая далеко от мяча и пропускает.
        static void RunOnePointForLeft(PongRules r)
        {
            int before = r.ScoreLeft;
            RunUntil(r, () => r.ScoreLeft > before || r.Phase == PongPhase.Over, () => r.BallZ, () => 99f);
        }

        [Test]
        public void ServeLaunchesTowardOpponentAfterDelay()
        {
            var r = NewRules();
            Assert.AreEqual(PongPhase.Serving, r.Phase);
            for (float t = 0f; t < 1.1f; t += Dt) r.Step(Dt, 0f, 0f);
            Assert.AreEqual(PongPhase.Rally, r.Phase);
            Assert.Greater(r.VelX, 0f, "первая подача левого летит вправо");
        }

        [Test]
        public void PaddleAtBallHeightReturnsTheBall()
        {
            var r = NewRules();
            RunUntil(r, () => r.VelX < 0f && r.Phase == PongPhase.Rally, () => 0f, () => 0f, 10f);
            Assert.AreEqual(PongPhase.Rally, r.Phase);
            Assert.Less(r.VelX, 0f, "мяч отбит и летит влево");
            Assert.AreEqual(0, r.ScoreLeft + r.ScoreRight);
        }

        [Test]
        public void MissGivesPointToOpponent()
        {
            var r = NewRules();
            RunOnePointForLeft(r);
            Assert.AreEqual(1, r.ScoreLeft);
            Assert.AreEqual(0, r.ScoreRight);
            Assert.AreEqual(PongPhase.PointPause, r.Phase);
        }

        [Test]
        public void FirstToTargetScoreWins()
        {
            var r = NewRules();
            for (int i = 0; i < 40 && r.Phase != PongPhase.Over; i++) RunOnePointForLeft(r);
            Assert.AreEqual(PongPhase.Over, r.Phase);
            Assert.AreEqual(Side.Left, r.Winner);
            Assert.AreEqual(11, r.ScoreLeft);
            Assert.AreEqual(0, r.ScoreRight);
        }

        [Test]
        public void ServeChangesEveryTwoPoints()
        {
            var r = NewRules();
            var servers = new List<Side> { r.Server };   // первая подача началась в конструкторе
            r.Raised += e => { if (e.Kind == PongEventKind.Serve) servers.Add(e.Side); };
            for (int i = 0; i < 4; i++) RunOnePointForLeft(r);
            // подачи: до очков 0, 1 — левый; 2, 3 — правый; дальше снова левый
            Assert.AreEqual(Side.Left, servers[0]);
            Assert.AreEqual(Side.Left, servers[1]);
            Assert.AreEqual(Side.Right, servers[2]);
            Assert.AreEqual(Side.Right, servers[3]);
        }

        [Test]
        public void TimeExpiredWithLeadEndsTheGameForTheLeader()
        {
            var r = NewRules();
            RunOnePointForLeft(r);
            r.TimeExpired();
            Assert.AreEqual(PongPhase.Over, r.Phase);
            Assert.AreEqual(Side.Left, r.Winner);
            Assert.IsFalse(r.Overtime);
        }

        [Test]
        public void TimeExpiredWithTieStartsGoldenBallAndNextPointDecides()
        {
            var r = NewRules();
            r.TimeExpired();
            Assert.IsTrue(r.Overtime);
            Assert.AreNotEqual(PongPhase.Over, r.Phase);
            Assert.IsNull(r.Winner);
            RunOnePointForLeft(r);
            Assert.AreEqual(PongPhase.Over, r.Phase);
            Assert.AreEqual(Side.Left, r.Winner);
        }

        [Test]
        public void BallNeverLeavesTableWidth()
        {
            var r = NewRules(1f);   // подача под углом
            float limit = r.Tuning.HalfWidth;
            for (float t = 0f; t < 8f; t += Dt)
            {
                r.Step(Dt, r.BallZ, r.BallZ);
                Assert.LessOrEqual(Math.Abs(r.BallZ), limit);
            }
        }

        [Test]
        public void SpeedStaysWithinMaxInNormalPlay()
        {
            var r = NewRules();
            for (float t = 0f; t < 30f; t += Dt)
            {
                r.Step(Dt, r.BallZ, r.BallZ);
                float speed = (float)Math.Sqrt(r.VelX * r.VelX + r.VelZ * r.VelZ);
                Assert.LessOrEqual(speed, r.Tuning.MaxSpeed + 0.001f);
            }
        }

        [Test]
        public void GoldenBallSpeedGrowsSoThePointAlwaysEnds()
        {
            var r = NewRules();
            r.TimeExpired();
            Track(r, 8f);
            float speed = (float)Math.Sqrt(r.VelX * r.VelX + r.VelZ * r.VelZ);
            Assert.Greater(speed, r.Tuning.MaxSpeed, "в золотом мяче скорость выше обычного максимума");
        }
    }
}
