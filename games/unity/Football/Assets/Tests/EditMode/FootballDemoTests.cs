using NUnit.Framework;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballDemoTests
    {
        const float Dt = 0.01f;

        static int Play(bool right)
        {
            var tuning = new FootballTuning();
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

        [Test]
        public void TheWrongDemoScoresAlmostNothing()
        {
            Assert.LessOrEqual(Play(false), 4);
        }
    }
}
