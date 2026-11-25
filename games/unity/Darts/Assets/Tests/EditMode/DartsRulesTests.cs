using System;
using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    public class DartsRulesTests
    {
        const float Dt = 0.01f;

        static DartsRules NewRules(float random = 0.3f)
        {
            return new DartsRules(new DartsTuning(), () => random);
        }

        // Шагает, пока не выполнится условие (или не кончится время).
        static void RunUntil(DartsRules r, Func<bool> done, float? eeg, Func<float?> emg, float maxSeconds = 30f)
        {
            for (float t = 0f; t < maxSeconds && !done(); t += Dt) r.Step(Dt, eeg, emg());
        }

        // Напрячь мышцу, пока не начнётся бросок, затем отпустить и дождаться, пока дротик не приземлится.
        static void ThrowOnce(DartsRules r, float? eeg = 0.5f)
        {
            int before = r.ThrowsMade;
            RunUntil(r, () => false, eeg, () => 0.0f, 0.1f);                       // мышца расслаблена: готова к броску
            RunUntil(r, () => r.Phase == DartsPhase.Flying, eeg, () => 0.9f, 5f);
            RunUntil(r, () => r.ThrowsMade > before, eeg, () => 0.0f, 5f);
        }

        [Test]
        public void PointsFollowTheRings()
        {
            var t = new DartsTuning();
            Assert.AreEqual(2, DartsRules.PointsFor(t, 0f, 0f));
            Assert.AreEqual(2, DartsRules.PointsFor(t, t.TwoPointRadius - 0.001f, 0f));
            Assert.AreEqual(1, DartsRules.PointsFor(t, t.TwoPointRadius + 0.001f, 0f));
            Assert.AreEqual(1, DartsRules.PointsFor(t, 0f, -(t.OnePointRadius - 0.001f)));
            Assert.AreEqual(0, DartsRules.PointsFor(t, t.OnePointRadius + 0.001f, 0f));
            Assert.AreEqual(0, DartsRules.PointsFor(t, 1f, 1f));
        }

        [Test]
        public void GripStartsTheThrowOnlyAfterTheHandWasReleased()
        {
            var r = NewRules();
            // мышца напряжена с первого кадра: бросок не начинается, пока её не расслабили
            RunUntil(r, () => r.Phase != DartsPhase.Aiming, 0.5f, () => 0.9f, 1f);
            Assert.AreEqual(DartsPhase.Aiming, r.Phase);
            RunUntil(r, () => r.Phase != DartsPhase.Aiming, 0.5f, () => 0.0f, 0.1f);
            Assert.AreEqual(DartsPhase.Aiming, r.Phase);
            RunUntil(r, () => r.Phase != DartsPhase.Aiming, 0.5f, () => 0.9f, 1f);
            Assert.AreEqual(DartsPhase.Flying, r.Phase);
        }

        [Test]
        public void NoThrowWithoutAnEmgSignal()
        {
            var r = NewRules();
            RunUntil(r, () => false, 0.5f, () => null, 3f);
            Assert.AreEqual(DartsPhase.Aiming, r.Phase);
            Assert.AreEqual(0, r.ThrowsMade);
        }

        [Test]
        public void ThrowLandsAtTheAimPointAndScoresIt()
        {
            var r = NewRules();
            RunUntil(r, () => false, 0.5f, () => 0.0f, 0.1f);
            RunUntil(r, () => r.Phase == DartsPhase.Flying, 0.5f, () => 0.9f, 5f);
            float x = r.HitX, z = r.HitZ;
            int expected = DartsRules.PointsFor(r.Tuning, x, z);
            RunUntil(r, () => r.ThrowsMade == 1, 0.5f, () => 0.0f, 3f);
            Assert.AreEqual(1, r.ThrowsMade);
            Assert.AreEqual(expected, r.LastPoints);
            Assert.AreEqual(expected, r.Score);
            Assert.AreEqual(expected, r.ResultOf(0));
        }

        [Test]
        public void GameEndsAfterFiveThrowsWithTheSumOfPoints()
        {
            var r = NewRules();
            for (int i = 0; i < 5; i++) ThrowOnce(r);
            RunUntil(r, () => r.Phase == DartsPhase.Over, 0.5f, () => 0.0f, 5f);
            Assert.AreEqual(DartsPhase.Over, r.Phase);
            Assert.AreEqual(5, r.ThrowsMade);
            int sum = 0;
            for (int i = 0; i < 5; i++) sum += r.ResultOf(i);
            Assert.AreEqual(sum, r.Score);
            Assert.LessOrEqual(r.Score, 10, "максимум за секцию 10");
        }

        [Test]
        public void ConcentrationShrinksTheWobble()
        {
            var calm = NewRules();
            var tense = NewRules();
            for (float t = 0f; t < 4f; t += Dt)
            {
                calm.Step(Dt, 1.0f, 0.0f);
                tense.Step(Dt, 0.0f, 0.0f);
            }
            Assert.Less(calm.Amplitude, tense.Amplitude * 0.5f);
            Assert.Greater(calm.Concentration, 0.9f);
        }

        [Test]
        public void ReticleStaysInsideItsWobbleRange()
        {
            var r = NewRules();
            for (float t = 0f; t < 20f; t += Dt)
            {
                r.Step(Dt, 0.0f, 0.0f);
                Assert.LessOrEqual(Math.Abs(r.AimX), r.Tuning.WobbleMax + 1e-4f);
                Assert.LessOrEqual(Math.Abs(r.AimZ), r.Tuning.WobbleMax + 1e-4f);
            }
        }

        [Test]
        public void ReticleNeverLeavesTheWobbleCircle()
        {
            var r = NewRules(0.8f);
            for (float t = 0f; t < 30f; t += Dt)
            {
                r.Step(Dt, 0.5f, 0.0f);
                float distance = (float)Math.Sqrt(r.AimX * r.AimX + r.AimZ * r.AimZ);
                Assert.LessOrEqual(distance, r.Amplitude + 1e-4f);
            }
        }

        [Test]
        public void WithoutEegTheWobbleStaysAtItsMaximum()
        {
            var r = NewRules();
            for (float t = 0f; t < 3f; t += Dt) r.Step(Dt, null, 0.0f);
            Assert.AreEqual(r.Tuning.WobbleMax, r.Amplitude, 1e-5f);
        }
    

        static DartsRules NewBurstRules()
        {
            var r = NewRules();
            r.BurstMode = true;
            return r;
        }

        [Test]
        public void BurstFiresExactlyOneThrow()
        {
            var r = NewBurstRules();
            int throws = 0;
            r.Raised += e => { if (e.Kind == DartsEventKind.Throw) throws++; };
            Assert.IsTrue(r.Fire());
            Assert.AreEqual(DartsPhase.Flying, r.Phase);
            Assert.AreEqual(1, throws);
        }

        [Test]
        public void TwoBurstsInOneFrameMakeOneThrow()
        {
            var r = NewBurstRules();
            int throws = 0;
            r.Raised += e => { if (e.Kind == DartsEventKind.Throw) throws++; };
            Assert.IsTrue(r.Fire());
            Assert.IsFalse(r.Fire());
            Assert.AreEqual(1, throws);
        }

        [Test]
        public void BurstIsIgnoredWhileFlyingAndShowing()
        {
            var r = NewBurstRules();
            r.Fire();
            r.Step(Dt, 0.5f, 0f);
            Assert.IsFalse(r.ReadyToThrow);
            Assert.IsFalse(r.Fire());
            RunUntil(r, () => r.Phase == DartsPhase.Showing, 0.5f, () => 0f, 5f);
            Assert.IsFalse(r.ReadyToThrow);
            Assert.IsFalse(r.Fire());
            Assert.AreEqual(1, r.ThrowsMade);
        }

        [Test]
        public void BurstReadyAgainAfterThePause()
        {
            var r = NewBurstRules();
            r.Fire();
            RunUntil(r, () => r.Phase == DartsPhase.Aiming, 0.5f, () => 0f, 10f);
            Assert.IsTrue(r.ReadyToThrow);
            Assert.IsTrue(r.Fire());
        }

        [Test]
        public void BurstModeIgnoresMuscleLevel()
        {
            var r = NewBurstRules();
            RunUntil(r, () => false, 0.5f, () => 0f, 0.1f);
            RunUntil(r, () => false, 0.5f, () => 0.95f, 1f);
            Assert.AreEqual(DartsPhase.Aiming, r.Phase);
        }

        [Test]
        public void BurstEventDoesNothingOnOldBridge()
        {
            var r = NewRules();
            Assert.IsFalse(r.Fire());
            Assert.AreEqual(DartsPhase.Aiming, r.Phase);
        }

        [Test]
        public void OldBridgeStillThrowsByLevel()
        {
            var r = NewRules();
            ThrowOnce(r);
            Assert.AreEqual(1, r.ThrowsMade);
        }

        [Test]
        public void BurstIsIgnoredAfterTheLastThrow()
        {
            var r = NewBurstRules();
            for (int i = 0; i < r.Tuning.Throws; i++)
            {
                RunUntil(r, () => r.ReadyToThrow, 0.5f, () => 0f, 10f);
                r.Fire();
            }
            RunUntil(r, () => r.Phase == DartsPhase.Over, 0.5f, () => 0f, 20f);
            Assert.IsFalse(r.Fire());
            Assert.AreEqual(r.Tuning.Throws, r.ThrowsMade);
        }
    }
}
