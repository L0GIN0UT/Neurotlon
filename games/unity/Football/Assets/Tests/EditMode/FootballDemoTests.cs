using NUnit.Framework;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballDemoTests
    {
        const float Dt = 0.01f;

        static int Play(bool right, DribbleMode mode = DribbleMode.Throttle)
        {
            var tuning = new FootballTuning { Dribble = mode };
            var rules = new FootballRules(tuning, () => 0.3f);
            var demo = new FootballDemo(right, tuning);
            float time = 0f;
            while (!rules.Over && time < 600f)
            {
                float eeg, emg;
                demo.Step(Dt);
                demo.Signals(rules, out eeg, out emg);
                rules.Step(Dt, eeg, emg);
                time += Dt;
            }
            Assert.IsTrue(rules.Over, "автоигрок доводит игру до конца");
            return rules.Score;
        }

        [Test]
        public void TheRightDemoScoresAlmostEverything()
        {
            Assert.GreaterOrEqual(Play(true), 9);
        }

        [TestCase(DribbleMode.Level)]
        [TestCase(DribbleMode.Throttle)]
        [TestCase(DribbleMode.Rhythm)]
        public void TheRightDemoWorksWithEveryDribbleMode(DribbleMode mode)
        {
            Assert.GreaterOrEqual(Play(true, mode), 9);
        }

        [TestCase(DribbleMode.Level)]
        [TestCase(DribbleMode.Throttle)]
        [TestCase(DribbleMode.Rhythm)]
        public void TheWrongDemoLosesWithEveryDribbleMode(DribbleMode mode)
        {
            Assert.LessOrEqual(Play(false, mode), 4);
        }

        [Test]
        public void ThrottleIsTheDefaultDribble()
        {
            Assert.AreEqual(DribbleMode.Throttle, new FootballTuning().Dribble);
        }

        [Test]
        public void TheWrongDemoScoresAlmostNothing()
        {
            Assert.LessOrEqual(Play(false), 4);
        }
    }
}
