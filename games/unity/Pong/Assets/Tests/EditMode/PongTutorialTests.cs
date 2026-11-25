using NUnit.Framework;

namespace Neurotlon.Games.Pong.Tests
{
    public class PongTutorialTests
    {
        [Test]
        public void StepsGoInOrderPaddleHitScore()
        {
            string[] texts = PongTutorial.Texts(11);
            Assert.AreEqual(PongTutorial.StepCount, texts.Length);
            StringAssert.Contains("двигает вашу ракетку", texts[PongTutorial.PaddleStep]);
            StringAssert.Contains("Отбейте мяч", texts[PongTutorial.HitStep]);
            StringAssert.Contains("до 11 очков", texts[PongTutorial.ScoreStep]);
        }

        [Test]
        public void TextsDoNotMentionHandOrFist()
        {
            foreach (string text in PongTutorial.Texts(11))
            {
                foreach (string word in new[] { "рук", "кист", "кулак", "сжат", "сжим", "сожм" })
                    StringAssert.DoesNotContain(word, text.ToLowerInvariant());
            }
        }

        [Test]
        public void PaddleStepNeedsBothLowAndHighFromBothPlayers()
        {
            var t = new PongTutorial();
            t.StepSignals(0.1f, 0.1f);
            t.StepSignals(0.9f, 0.5f);
            Assert.IsTrue(t.PaddleDone(Side.Left));
            Assert.IsFalse(t.PaddleDone(Side.Right), "у правого не было верхнего значения");
            Assert.IsFalse(t.IsDone(PongTutorial.PaddleStep));
            t.StepSignals(0.5f, 0.75f);
            Assert.IsTrue(t.IsDone(PongTutorial.PaddleStep));
        }

        [Test]
        public void PaddleStepNeedsNoHoldAndIgnoresTheMiddle()
        {
            var t = new PongTutorial();
            t.StepSignals(0.31f, 0.69f);
            t.StepSignals(0.69f, 0.31f);
            Assert.IsFalse(t.IsDone(PongTutorial.PaddleStep), "0,31 и 0,69 не доходят до порогов 0,3 и 0,7");
            t.StepSignals(0.3f, 0.3f);
            t.StepSignals(0.7f, 0.7f);
            Assert.IsTrue(t.IsDone(PongTutorial.PaddleStep));
        }

        [Test]
        public void MissingSignalDoesNotAdvanceThePaddleStep()
        {
            var t = new PongTutorial();
            t.StepSignals(null, null);
            Assert.IsFalse(t.PaddleDone(Side.Left));
            Assert.IsFalse(t.PaddleDone(Side.Right));
        }

        [Test]
        public void HitStepIsDoneOnlyWhenBothHit()
        {
            var t = new PongTutorial();
            t.OnRulesEvent(PongEventKind.Serve, Side.Left);
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Left);      // подача: не в счёт
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Right);     // правый отбил
            Assert.IsTrue(t.HitDone(Side.Right));
            Assert.IsFalse(t.HitDone(Side.Left));
            Assert.IsFalse(t.IsDone(PongTutorial.HitStep), "левый ещё не отбивал");
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Left);
            Assert.IsTrue(t.IsDone(PongTutorial.HitStep));
        }

        [Test]
        public void ServeHitDoesNotCountAsAHit()
        {
            var t = new PongTutorial();
            t.OnRulesEvent(PongEventKind.Serve, Side.Right);
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Right);
            Assert.IsFalse(t.HitDone(Side.Right));
            t.OnRulesEvent(PongEventKind.Serve, Side.Right);
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Right);
            Assert.IsFalse(t.HitDone(Side.Right), "подача после очка тоже не отбитие");
        }

        [Test]
        public void ScoreStepIsDoneByTheFirstPoint()
        {
            var t = new PongTutorial();
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Left);
            Assert.IsFalse(t.IsDone(PongTutorial.ScoreStep));
            t.OnRulesEvent(PongEventKind.Point, Side.Right);
            Assert.IsTrue(t.IsDone(PongTutorial.ScoreStep));
        }

        [Test]
        public void ResetStartsTheAttemptOver()
        {
            var t = new PongTutorial();
            t.StepSignals(0.1f, 0.1f);
            t.StepSignals(0.9f, 0.9f);
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Left);
            t.OnRulesEvent(PongEventKind.PaddleHit, Side.Right);
            t.OnRulesEvent(PongEventKind.Point, Side.Left);
            Assert.IsTrue(t.IsDone(PongTutorial.PaddleStep));
            Assert.IsTrue(t.IsDone(PongTutorial.HitStep));
            Assert.IsTrue(t.IsDone(PongTutorial.ScoreStep));
            t.Reset();
            Assert.IsFalse(t.IsDone(PongTutorial.PaddleStep));
            Assert.IsFalse(t.IsDone(PongTutorial.HitStep));
            Assert.IsFalse(t.IsDone(PongTutorial.ScoreStep));
        }

        [Test]
        public void TutorialGoesThroughRealRulesSandbox()
        {
            // песочница на настоящих правилах: розыгрыш идёт, ракетки стоят так, что принимающий пропускает мяч, засчитывается очко
            var tuning = new PongTuning { TargetScore = 99 };
            var rules = new PongRules(tuning, () => 0.5f, Side.Left);
            var t = new PongTutorial();
            rules.Raised += e => t.OnRulesEvent(e.Kind, e.Side);
            t.OnRulesEvent(PongEventKind.Serve, rules.Server);
            for (int i = 0; i < 2000 && !t.IsDone(PongTutorial.ScoreStep); i++) rules.Step(0.02f, 0.6f, -0.6f);
            Assert.IsTrue(t.IsDone(PongTutorial.ScoreStep));
            Assert.AreEqual(1, rules.ScoreLeft + rules.ScoreRight);
            Assert.IsFalse(t.IsDone(PongTutorial.HitStep), "подача не засчитана как отбитие");
        }
    }
}
