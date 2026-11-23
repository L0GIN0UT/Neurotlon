using NUnit.Framework;

namespace Neurotlon.Games.Pong.Tests
{
    public class PongCheckTests
    {
        static void Hold(PongCheck check, float? value, float seconds)
        {
            for (float t = 0f; t < seconds; t += 0.02f) check.Step(0.02f, value);
        }

        [Test]
        public void NotPassedUntilBothPositionsAreHeld()
        {
            var check = new PongCheck();
            Hold(check, 0.95f, 0.5f);
            Assert.IsTrue(check.HighDone);
            Assert.IsFalse(check.LowDone);
            Assert.IsFalse(check.Passed);
            Hold(check, 0.05f, 0.5f);
            Assert.IsTrue(check.Passed);
        }

        [Test]
        public void AShortTouchDoesNotCount()
        {
            var check = new PongCheck();
            Hold(check, 0.95f, 0.1f);
            Hold(check, 0.5f, 0.2f);
            Hold(check, 0.95f, 0.1f);
            Assert.IsFalse(check.HighDone, "удержание должно быть непрерывным");
        }

        [Test]
        public void LostSignalResetsTheHold()
        {
            var check = new PongCheck();
            Hold(check, 0.95f, 0.2f);
            Hold(check, null, 0.1f);
            Hold(check, 0.95f, 0.2f);
            Assert.IsFalse(check.HighDone);
        }

        [Test]
        public void AMiddleValueNeverPasses()
        {
            var check = new PongCheck();
            Hold(check, 0.5f, 5f);
            Assert.IsFalse(check.HighDone);
            Assert.IsFalse(check.LowDone);
        }

        // сценарий проверяющей программы: мышца сжата 0,8 с, потом 0,8 с расслаблена (эмулятор плавно нарастает и спадает)
        [Test]
        public void TheCheckerScriptedPatternPasses()
        {
            var check = new PongCheck();
            float value = 0f;
            for (float t = 0f; t < 6f && !check.Passed; t += 0.02f)
            {
                bool held = t % 1.6f < 0.8f;
                float tau = held ? 0.15f : 0.25f;
                value = (held ? 1f : 0f) + (value - (held ? 1f : 0f)) * (float)System.Math.Exp(-0.02f / tau);
                check.Step(0.02f, value);
            }
            Assert.IsTrue(check.Passed, "стандартный сценарий проверки проходит демо-проверку");
        }
    }
}
