using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    public class DartsTutorialTests
    {
        const float Dt = 0.01f;

        // Шагает seconds секунд с постоянным сосредоточением; возвращает последний результат.
        static bool Run(DartsTutorial t, int step, float concentration, float seconds)
        {
            bool result = false;
            for (float time = 0f; time < seconds; time += Dt) result = t.Update(step, Dt, concentration);
            return result;
        }

        [Test]
        public void StepsGoInOrderFocusThrowThenAim()
        {
            Assert.AreEqual(0, DartsTutorial.FocusStep);
            Assert.AreEqual(1, DartsTutorial.ThrowStep);
            Assert.AreEqual(2, DartsTutorial.AimStep);
            Assert.AreEqual(3, DartsTutorial.StepCount);
        }

        static void Land(DartsTutorial t, int points)
        {
            t.NoteEvent(new DartsEvent(DartsEventKind.Hit, points));
        }

        [Test]
        public void AimStepIsDoneByTwoHits()
        {
            var t = new DartsTutorial();
            Land(t, 1);
            Assert.IsFalse(t.Update(DartsTutorial.AimStep, Dt, 0f));
            Land(t, 2);
            Assert.IsTrue(t.Update(DartsTutorial.AimStep, Dt, 0f));
        }

        [Test]
        public void AimStepIgnoresMisses()
        {
            var t = new DartsTutorial();
            Land(t, 0);
            Land(t, 0);
            Land(t, 0);
            Assert.AreEqual(0, t.Counter.Hits);
            Assert.IsFalse(t.Update(DartsTutorial.AimStep, Dt, 0f));
        }

        [Test]
        public void AimStepIsNotDoneByAThrowEventAlone()
        {
            var t = new DartsTutorial();
            t.NoteEvent(new DartsEvent(DartsEventKind.Throw, 0));
            Assert.IsFalse(t.Update(DartsTutorial.AimStep, Dt, 1f));
        }

        [Test]
        public void ResetClearsTheAimCounter()
        {
            var t = new DartsTutorial();
            Land(t, 2);
            Land(t, 0);
            t.Reset();
            Assert.AreEqual(0, t.Counter.Hits);
            Assert.IsFalse(t.Update(DartsTutorial.AimStep, Dt, 0f));
        }

        [Test]
        public void CounterCheckpointIsTwoHitsOutOfFiveThrows()
        {
            Assert.AreEqual(2, DartsHitCounter.Needed);
            Assert.AreEqual(5, DartsHitCounter.Throws);
            var c = new DartsHitCounter();
            c.NoteThrow(1);
            Assert.IsFalse(c.Passed);
            c.NoteThrow(2);
            Assert.IsTrue(c.Passed, "два попадания засчитывают шаг");
            Assert.AreEqual(2, c.Hits);
        }

        [Test]
        public void AMissIsAThrowButNotAHit()
        {
            var c = new DartsHitCounter();
            c.NoteThrow(0);
            Assert.AreEqual(0, c.Hits);
            Assert.AreEqual(1, c.Thrown, "промах тратит бросок");
        }

        [Test]
        public void FiveThrowsWithoutTwoHitsMustRestart()
        {
            var c = new DartsHitCounter();
            c.NoteThrow(2);
            for (int i = 0; i < 4; i++) c.NoteThrow(0);
            Assert.IsTrue(c.MustRestart);
            Assert.IsFalse(c.Passed);
            c.NoteThrow(2);
            Assert.AreEqual(1, c.Hits, "после пятого броска новые не учитываются");
        }

        [Test]
        public void TheSecondHitOnTheFifthThrowStillPasses()
        {
            var c = new DartsHitCounter();
            for (int i = 0; i < 3; i++) c.NoteThrow(0);
            c.NoteThrow(2);
            c.NoteThrow(1);
            Assert.IsTrue(c.Passed);
            Assert.IsFalse(c.MustRestart, "второе попадание на пятом броске засчитывает шаг, перезапуска нет");
        }

        [Test]
        public void CounterStopsCountingOncePassed()
        {
            var c = new DartsHitCounter();
            c.NoteThrow(2);
            c.NoteThrow(2);
            c.NoteThrow(1);
            Assert.AreEqual(2, c.Hits);
            Assert.AreEqual(2, c.Thrown);
        }

        [Test]
        public void CounterResetStartsOver()
        {
            var c = new DartsHitCounter();
            c.NoteThrow(2);
            c.NoteThrow(0);
            c.Reset();
            Assert.AreEqual(0, c.Hits);
            Assert.AreEqual(0, c.Thrown);
            Assert.IsFalse(c.Passed);
            Assert.IsFalse(c.MustRestart);
        }

        [Test]
        public void CounterLabelShowsHitsOfTwo()
        {
            Assert.AreEqual("Попаданий: 0 из 2", DartsHitCounter.Label(0));
            Assert.AreEqual("Попаданий: 1 из 2", DartsHitCounter.Label(1));
        }

        [Test]
        public void CounterUsesTheSameRingsAsScoring()
        {
            var tuning = new DartsTuning();
            var c = new DartsHitCounter();
            c.NoteThrow(DartsRules.PointsFor(tuning, 0f, 0f));
            c.NoteThrow(DartsRules.PointsFor(tuning, tuning.OnePointRadius - 0.001f, 0f));
            Assert.IsTrue(c.Passed);
            var miss = new DartsHitCounter();
            miss.NoteThrow(DartsRules.PointsFor(tuning, tuning.OnePointRadius + 0.001f, 0f));
            Assert.AreEqual(0, miss.Hits);
        }

        [Test]
        public void FocusIsNotDoneWhileConcentrationIsLow()
        {
            var t = new DartsTutorial();
            Assert.IsFalse(Run(t, DartsTutorial.FocusStep, 0.59f, 5f));
            Assert.AreEqual(0f, t.FocusHeld, 1e-6f);
        }

        [Test]
        public void FocusIsDoneAfterHalfASecondAtOrAboveTheLevel()
        {
            var t = new DartsTutorial();
            Assert.IsFalse(Run(t, DartsTutorial.FocusStep, 0.6f, 0.4f));
            Assert.IsTrue(Run(t, DartsTutorial.FocusStep, 0.6f, 0.2f));
        }

        [Test]
        public void FocusResetsWhenConcentrationDropsBelowTheLevel()
        {
            var t = new DartsTutorial();
            Run(t, DartsTutorial.FocusStep, 0.9f, 0.4f);
            t.Update(DartsTutorial.FocusStep, Dt, 0.3f);
            Assert.AreEqual(0f, t.FocusHeld, 1e-6f);
            Assert.IsFalse(Run(t, DartsTutorial.FocusStep, 0.9f, 0.4f));        // накопление началось заново
            Assert.IsTrue(Run(t, DartsTutorial.FocusStep, 0.9f, 0.2f));
        }

        [Test]
        public void FocusStaysDoneOnceCounted()
        {
            var t = new DartsTutorial();
            Assert.IsTrue(Run(t, DartsTutorial.FocusStep, 0.9f, 0.7f));
            Assert.IsTrue(t.Update(DartsTutorial.FocusStep, Dt, 0f));
        }

        [Test]
        public void ThrowIsNotDoneWithoutAThrowEvent()
        {
            var t = new DartsTutorial();
            Assert.IsFalse(Run(t, DartsTutorial.ThrowStep, 1f, 3f));
        }

        [Test]
        public void ThrowIsDoneByTheThrowEvent()
        {
            var t = new DartsTutorial();
            t.NoteEvent(new DartsEvent(DartsEventKind.Throw, 0));
            Assert.IsTrue(t.Update(DartsTutorial.ThrowStep, Dt, 0f));
        }

        [Test]
        public void HitAndGameOverEventsDoNotCountAsAThrow()
        {
            var t = new DartsTutorial();
            t.NoteEvent(new DartsEvent(DartsEventKind.Hit, 2));
            t.NoteEvent(new DartsEvent(DartsEventKind.GameOver, 5));
            Assert.IsFalse(t.Update(DartsTutorial.ThrowStep, Dt, 0f));
        }

        [Test]
        public void ResetClearsTheStep()
        {
            var t = new DartsTutorial();
            t.NoteEvent(new DartsEvent(DartsEventKind.Throw, 0));
            t.Update(DartsTutorial.ThrowStep, Dt, 0f);
            t.Reset();
            Assert.IsFalse(t.Done);
            Assert.IsFalse(t.Update(DartsTutorial.ThrowStep, Dt, 0f));
        }

        [Test]
        public void RealRulesRaiseThrowEventThatCompletesTheStep()
        {
            var rules = new DartsRules(new DartsTuning { Throws = 99 }, () => 0.3f);
            var t = new DartsTutorial();
            rules.Raised += t.NoteEvent;
            for (float time = 0f; time < 0.2f; time += Dt) rules.Step(Dt, 0.5f, 0.0f);        // мышца расслаблена
            Assert.IsFalse(t.Update(DartsTutorial.ThrowStep, Dt, 0f));
            for (float time = 0f; time < 1f && !t.Done; time += Dt)
            {
                rules.Step(Dt, 0.5f, 0.9f);
                t.Update(DartsTutorial.ThrowStep, Dt, 0f);
            }
            Assert.IsTrue(t.Done);
        }

        [Test]
        public void FocusStepWithoutMuscleSignalNeverThrows()
        {
            var rules = new DartsRules(new DartsTuning { Throws = 99 }, () => 0.3f);
            int throws = 0;
            rules.Raised += e => { if (e.Kind == DartsEventKind.Throw) throws++; };
            for (float time = 0f; time < 5f; time += Dt) rules.Step(Dt, 1f, null);
            Assert.AreEqual(0, throws);
        }

        [Test]
        public void DebugScoreArgumentIsParsed()
        {
            Assert.AreEqual(100, DartsArgs.IntValue(new[] { "game.exe", "--debug-score", "100" }, DartsArgs.DebugScore));
            Assert.AreEqual(25, DartsArgs.IntValue(new[] { "--debug-score=25" }, DartsArgs.DebugScore));
            Assert.IsNull(DartsArgs.IntValue(new[] { "--launch", "x.json" }, DartsArgs.DebugScore));
            Assert.IsNull(DartsArgs.IntValue(new[] { "--debug-score", "abc" }, DartsArgs.DebugScore));
        }

        [TestCase(0)]
        [TestCase(9)]
        [TestCase(10)]
        [TestCase(25)]
        [TestCase(100)]
        public void ScoreLabelFitsItsFieldAndKeepsTheRightEdge(int score)
        {
            string text = NeurotlonHud.ScoreText(score);
            float fontSize = 52f;
            float width = NeurotlonHud.TextWidth(text, fontSize);
            var rect = NeurotlonHud.RightAligned(1000f, 0f, 90f, text, fontSize, 200f);
            Assert.AreEqual(1000f, rect.xMax, 1e-3f);
            Assert.GreaterOrEqual(rect.width, width);
        }
    }
}
