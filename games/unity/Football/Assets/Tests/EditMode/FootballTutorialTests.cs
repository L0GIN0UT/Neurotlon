using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEngine;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballTutorialTests
    {
        static readonly FootballTuning Tuning = new FootballTuning();

        static FootballTutorial Begin(TutorialStep step)
        {
            var tutorial = new FootballTutorial(Tuning);
            tutorial.Begin(step);
            return tutorial;
        }

        static FootballEvent Event(FootballEventKind kind, FootballElement element, int points = 0)
        {
            return new FootballEvent(kind, element, points);
        }

        static FootballEvent Landed(int points)
        {
            return Event(FootballEventKind.Landed, FootballElement.Kick, points);
        }

        static readonly TutorialStep[] ExpectedOrder =
        {
            TutorialStep.Cones, TutorialStep.Focus, TutorialStep.Shot, TutorialStep.Hits,
            TutorialStep.Gate, TutorialStep.Slow, TutorialStep.StopZone,
        };

        // ---------- порядок шагов и тексты ----------

        [TestCase(DribbleMode.Throttle)]
        [TestCase(DribbleMode.Level)]
        [TestCase(DribbleMode.Rhythm)]
        public void EveryModeHasSevenStepsInTheSameOrder(DribbleMode mode)
        {
            CollectionAssert.AreEqual(ExpectedOrder, FootballTutorial.StepsFor(mode));
        }

        [Test]
        public void OnlyTheHitsStepIsACheckAndCannotBeSkipped()
        {
            foreach (var step in ExpectedOrder)
                Assert.AreEqual(step != TutorialStep.Hits, FootballTutorial.IsSkippable(step), step.ToString());
            Assert.AreEqual(90f, FootballTutorial.TimeoutFor(TutorialStep.Hits));
            Assert.AreEqual(NeurotlonTutorial.StepSeconds, FootballTutorial.TimeoutFor(TutorialStep.Cones));
        }

        [Test]
        public void TheFirstStepTextFollowsTheDribbleModeAndOthersDoNot()
        {
            string throttle = FootballTutorial.TextFor(TutorialStep.Cones, DribbleMode.Throttle);
            string level = FootballTutorial.TextFor(TutorialStep.Cones, DribbleMode.Level);
            string rhythm = FootballTutorial.TextFor(TutorialStep.Cones, DribbleMode.Rhythm);
            Assert.AreNotEqual(throttle, level);
            Assert.AreNotEqual(throttle, rhythm);
            Assert.AreNotEqual(level, rhythm);
            foreach (var text in new[] { throttle, level, rhythm }) StringAssert.EndsWith("Обведите два конуса, не задев их", text);
            StringAssert.StartsWith(NeurotlonTexts.Tense, throttle);
            StringAssert.Contains("быстрее", throttle);
            StringAssert.Contains("тормозит", throttle);
            StringAssert.Contains("в такт", rhythm);
            for (int i = 1; i < ExpectedOrder.Length; i++)
                Assert.AreEqual(FootballTutorial.TextFor(ExpectedOrder[i], DribbleMode.Throttle), FootballTutorial.TextFor(ExpectedOrder[i], DribbleMode.Rhythm));
        }

        [Test]
        public void EveryStepHasItsOwnShortText()
        {
            var seen = new System.Collections.Generic.HashSet<string>();
            foreach (var step in ExpectedOrder)
            {
                string text = FootballTutorial.TextFor(step, DribbleMode.Throttle);
                Assert.IsFalse(string.IsNullOrEmpty(text), step.ToString());
                Assert.Less(text.Length, 120, "подсказка короткая: " + step);
                Assert.LessOrEqual(text.Split('\n').Length, 2, "не больше двух строк: " + step);
                seen.Add(text);
            }
            Assert.AreEqual(ExpectedOrder.Length, seen.Count, "у каждой механики своя подсказка");
        }

        [Test]
        public void TextsUseSensorMuscleWordingOnly()
        {
            var banned = new Regex("рук|кист|кулак|сжат|сжим|сожм|нога|ногу|ногой|ноги|ног\\b", RegexOptions.IgnoreCase);
            foreach (DribbleMode mode in new[] { DribbleMode.Throttle, DribbleMode.Level, DribbleMode.Rhythm })
                foreach (var step in ExpectedOrder)
                    Assert.IsFalse(banned.IsMatch(FootballTutorial.TextFor(step, mode)), step + " " + mode);
            Assert.IsFalse(banned.IsMatch(FootballTutorial.HitsText(1)));
            StringAssert.StartsWith(NeurotlonTexts.Tense, FootballTutorial.TextFor(TutorialStep.Shot, DribbleMode.Throttle));
        }

        [Test]
        public void HitsCaptionShowsHitsOutOfTwo()
        {
            Assert.AreEqual("Попаданий: 0 из 2", FootballTutorial.HitsText(0));
            Assert.AreEqual("Попаданий: 2 из 2", FootballTutorial.HitsText(2));
        }

        [Test]
        public void OnlyTheHitsStepGetsFiveAttemptsLikeTheDotsInTheGame()
        {
            Assert.AreEqual(5, FootballTutorial.AttemptsFor(TutorialStep.Hits));
            foreach (var step in ExpectedOrder)
                if (step != TutorialStep.Hits) Assert.AreEqual(1, FootballTutorial.AttemptsFor(step), step.ToString());
        }

        // ---------- два конуса ----------

        [Test]
        public void ConeTouchMeansRetryAndNeverDone()
        {
            var t = Begin(TutorialStep.Cones);
            t.ObserveEvent(Event(FootballEventKind.Touch, FootballElement.Snake));
            Assert.IsTrue(t.Retry);
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Snake, 1));
            Assert.IsFalse(t.Done);
        }

        [Test]
        public void TwoConesPassedWithoutTouchesIsDone()
        {
            var t = Begin(TutorialStep.Cones);
            Assert.IsFalse(t.Done);
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Snake, 2));
            Assert.IsTrue(t.Done);
            Assert.IsFalse(t.Retry);
        }

        [Test]
        public void SandboxWithTwoConesHasTwoConesOfTheRealField()
        {
            var sandbox = Tuning.CopyForTutorial(FootballTutorial.SandboxCones, 1);
            Assert.AreEqual(2, sandbox.ConeY.Length);
            Assert.AreEqual(Tuning.ConeY[0], sandbox.ConeY[0]);
            Assert.AreEqual(Tuning.ConeY[1], sandbox.ConeY[1]);
        }

        [Test]
        public void SnakeThroughTheMiddleTouchesAConeAndRestartsTheStep()
        {
            // тот же путь, что в игре: правила песочницы, события идут в условие шага
            var tuning = new FootballTuning { Dribble = DribbleMode.Level }.CopyForTutorial(2, 1);
            var t = Begin(TutorialStep.Cones);
            var rules = new FootballRules(tuning, () => 0.5f, new[] { 0 });
            rules.Raised += t.ObserveEvent;
            for (int i = 0; i < 9000 && !rules.Over && !t.Retry; i++) rules.Step(0.01f, 0.5f, 0.5f);      // ровно по центру: конус задет
            Assert.IsTrue(t.Retry);
            Assert.IsFalse(t.Done);
        }

        [Test]
        public void SnakeWithDemoPlayerFinishesTheTwoConeSandbox()
        {
            var tuning = new FootballTuning().CopyForTutorial(2, 1);
            var t = Begin(TutorialStep.Cones);
            var rules = new FootballRules(tuning, () => 0.5f, new[] { 0 });
            var demo = new FootballDemo(true, tuning);
            rules.Raised += t.ObserveEvent;
            for (int i = 0; i < 9000 && !rules.Over && !t.Retry; i++)
            {
                float eeg, emg;
                demo.Step(0.01f);
                demo.Signals(rules, out eeg, out emg);
                rules.Step(0.01f, eeg, emg);
            }
            Assert.IsTrue(rules.Over || t.Retry, "песочница завершилась исходом");
            Assert.AreNotEqual(t.Done, t.Retry, "ровно один исход: засчитано или повтор");
        }

        // ---------- сосредоточение ----------

        [Test]
        public void FocusNeedsHalfSecondHeldWithoutBreak()
        {
            var t = Begin(TutorialStep.Focus);
            for (int i = 0; i < 4; i++) t.ObserveConcentration(0.7f, 0.1f);       // 0,4 с
            Assert.IsFalse(t.Done);
            t.ObserveConcentration(0.5f, 0.1f);                                    // упала ниже 0,6: отсчёт заново
            Assert.AreEqual(0f, t.FocusProgress);
            for (int i = 0; i < 4; i++) t.ObserveConcentration(0.7f, 0.1f);
            Assert.IsFalse(t.Done, "после сброса снова нужно полсекунды");
            t.ObserveConcentration(0.6f, 0.1f);
            Assert.IsTrue(t.Done);
        }

        [Test]
        public void FocusIgnoresConcentrationInOtherSteps()
        {
            var t = Begin(TutorialStep.Shot);
            for (int i = 0; i < 20; i++) t.ObserveConcentration(1f, 0.1f);
            Assert.IsFalse(t.Done);
        }

        // ---------- удар по мишени и ворота ----------

        [Test]
        public void ShotIsCountedByKickEventOnTheTarget()
        {
            var t = Begin(TutorialStep.Shot);
            t.ObserveEvent(Event(FootballEventKind.ElementStarted, FootballElement.Kick));
            Assert.IsFalse(t.Done);
            t.ObserveEvent(Event(FootballEventKind.Kick, FootballElement.Pass));
            Assert.IsFalse(t.Done, "удар в ворота не засчитывает шаг мишени");
            t.ObserveEvent(Event(FootballEventKind.Kick, FootballElement.Kick));
            Assert.IsTrue(t.Done);
        }

        [Test]
        public void GateIsCountedByKickEventOnThePass()
        {
            var t = Begin(TutorialStep.Gate);
            t.ObserveEvent(Event(FootballEventKind.ElementStarted, FootballElement.Pass));
            Assert.IsFalse(t.Done);
            t.ObserveEvent(Event(FootballEventKind.Kick, FootballElement.Pass));
            Assert.IsTrue(t.Done);
        }

        // ---------- два самостоятельных удара ----------

        [Test]
        public void HitsCheckpointIsTwoHitsOutOfFiveKicks()
        {
            Assert.AreEqual(2, TutorialHits.Needed);
            Assert.AreEqual(5, TutorialHits.MaxAttempts);
            var hits = new TutorialHits();
            hits.Register(1);
            Assert.IsFalse(hits.Passed);
            hits.Register(2);
            Assert.IsTrue(hits.Passed, "два попадания засчитывают шаг");
            Assert.AreEqual(2, hits.Hits);
        }

        [Test]
        public void AMissTakesAnAttemptButIsNotAHit()
        {
            var hits = new TutorialHits();
            hits.Register(0);
            Assert.AreEqual(0, hits.Hits);
            Assert.AreEqual(1, hits.Used, "промах занимает точку попытки");
            Assert.AreEqual(0, hits.ResultOf(0));
            Assert.AreEqual(-1, hits.ResultOf(1), "следующий удар ещё не сделан");
        }

        [Test]
        public void FiveKicksWithoutTwoHitsExhaustTheCounter()
        {
            var hits = new TutorialHits();
            hits.Register(2);
            for (int i = 0; i < 4; i++) hits.Register(0);
            Assert.AreEqual(5, hits.Used);
            Assert.IsTrue(hits.Exhausted);
            Assert.IsFalse(hits.Passed);
            hits.Register(2);
            Assert.AreEqual(1, hits.Hits, "после пятого удара новые не учитываются");
        }

        [Test]
        public void TheSecondHitOnTheFifthKickStillPasses()
        {
            var hits = new TutorialHits();
            for (int i = 0; i < 4; i++) hits.Register(0);
            hits.Register(1);
            Assert.IsFalse(hits.Passed);
            Assert.IsFalse(hits.Exhausted == false && hits.Used < 5, "четыре промаха и одно попадание: пять ударов");
            var ok = new TutorialHits();
            ok.Register(0);
            ok.Register(0);
            ok.Register(0);
            ok.Register(2);
            ok.Register(2);
            Assert.IsTrue(ok.Passed, "второе попадание на пятом ударе засчитывает шаг");
            Assert.IsFalse(ok.Exhausted);
        }

        [Test]
        public void DotsKeepTheirOwnPoints()
        {
            var hits = new TutorialHits();
            hits.Register(1);
            hits.Register(0);
            hits.Register(2);
            Assert.AreEqual(1, hits.ResultOf(0));
            Assert.AreEqual(0, hits.ResultOf(1));
            Assert.AreEqual(2, hits.ResultOf(2));
            Assert.AreEqual(-1, hits.ResultOf(3));
        }

        [Test]
        public void HitsCounterResetsClean()
        {
            var hits = new TutorialHits();
            hits.Register(2);
            hits.Register(0);
            hits.Reset();
            Assert.AreEqual(0, hits.Hits);
            Assert.AreEqual(0, hits.Used);
            Assert.IsFalse(hits.Passed);
            Assert.AreEqual(-1, hits.ResultOf(0));
        }

        [Test]
        public void HitsStepIsDoneByTwoLandedHitsOnTheTarget()
        {
            var t = Begin(TutorialStep.Hits);
            t.ObserveEvent(Landed(0));
            t.ObserveEvent(Landed(1));
            Assert.IsFalse(t.Done);
            Assert.AreEqual(1, t.Hits.Hits);
            t.ObserveEvent(Event(FootballEventKind.Landed, FootballElement.Pass, 2));
            Assert.AreEqual(1, t.Hits.Hits, "посадка мяча в воротах не считается ударом в мишень");
            t.ObserveEvent(Landed(2));
            Assert.IsTrue(t.Done);
            Assert.IsFalse(t.Retry);
        }

        [Test]
        public void HitsStepRestartsAtOnceAfterFiveKicksWithoutTwoHits()
        {
            var t = Begin(TutorialStep.Hits);
            t.ObserveEvent(Landed(2));
            for (int i = 0; i < 4; i++) t.ObserveEvent(Landed(0));
            Assert.IsTrue(t.Retry, "пять ударов, а попаданий меньше двух: новая попытка");
            Assert.IsFalse(t.Done);
        }

        [Test]
        public void BeginOnANewTryClearsHitsAndOutcome()
        {
            var t = Begin(TutorialStep.Hits);
            t.ObserveEvent(Landed(2));
            t.ObserveEvent(Landed(1));
            Assert.IsTrue(t.Done);
            t.Begin(TutorialStep.Hits);
            Assert.IsFalse(t.Retry);
            Assert.IsFalse(t.Done);
            Assert.AreEqual(0, t.Hits.Hits);
            Assert.AreEqual(0, t.Hits.Used);
            t.ObserveEvent(Landed(2));
            Assert.AreEqual(1, t.Hits.Hits);
        }

        [Test]
        public void HitsAreNotCountedInOtherSteps()
        {
            var t = Begin(TutorialStep.Shot);
            t.ObserveEvent(Landed(2));
            Assert.AreEqual(0, t.Hits.Hits);
        }

        [Test]
        public void RealTargetSandboxWithDemoPlayerPassesTheHitsStep()
        {
            var tuning = new FootballTuning().CopyForTutorial(FootballTutorial.SandboxCones, FootballTutorial.AttemptsFor(TutorialStep.Hits));
            var t = Begin(TutorialStep.Hits);
            var rules = new FootballRules(tuning, () => 0.3f, new[] { 3 });
            var demo = new FootballDemo(true, tuning);
            rules.Raised += t.ObserveEvent;
            for (float time = 0f; !rules.Over && !t.Done && time < 120f; time += 0.01f)
            {
                float eeg, emg;
                demo.Step(0.01f);
                demo.Signals(rules, out eeg, out emg);
                rules.Step(0.01f, eeg, emg);
            }
            Assert.IsTrue(t.Done, "автоигрок попадает в мишень дважды");
            Assert.GreaterOrEqual(t.Hits.Hits, 2);
        }

        // ---------- торможение ----------

        [Test]
        public void SlowCountsBelowHalfOfTheStartSpeed()
        {
            var t = Begin(TutorialStep.Slow);
            t.ObserveStopSpeed(Tuning.StopStartSpeed, false);
            t.ObserveStopSpeed(Tuning.StopStartSpeed * 0.5f, false);
            Assert.IsFalse(t.Done, "ровно половина ещё не ниже половины");
            t.ObserveStopSpeed(Tuning.StopStartSpeed * 0.5f - 0.01f, false);
            Assert.IsTrue(t.Done);
        }

        [Test]
        public void SlowIsNotCountedWhenTheNetStoppedTheBall()
        {
            var t = Begin(TutorialStep.Slow);
            t.ObserveStopSpeed(0f, true);
            Assert.IsFalse(t.Done, "мяч встал в сетке, а не от торможения");
        }

        [Test]
        public void SlowIsIgnoredInOtherSteps()
        {
            var t = Begin(TutorialStep.StopZone);
            t.ObserveStopSpeed(0.1f, false);
            Assert.IsFalse(t.Done);
        }

        [Test]
        public void RealStopSandboxWithBrakeSlowsTheBallAndWithoutBrakeDoesNot()
        {
            var braked = Begin(TutorialStep.Slow);
            RunStop(braked, 0.30f);
            Assert.IsTrue(braked.Done, "напряжённая мышца тормозит мяч");
            var idle = Begin(TutorialStep.Slow);
            RunStop(idle, 0f);
            Assert.IsFalse(idle.Done, "без торможения мяч доезжает до сетки на высокой скорости");
        }

        static void RunStop(FootballTutorial t, float emg)
        {
            var rules = new FootballRules(Tuning.CopyForTutorial(FootballTutorial.SandboxCones, 1), () => 0.5f, new[] { 2 });
            rules.Raised += t.ObserveEvent;
            for (int i = 0; i < 9000 && !rules.Over && !t.Done; i++)
            {
                rules.Step(0.01f, 0.5f, emg);
                var stop = rules.Current as StopElement;
                if (stop != null) t.ObserveStopSpeed(stop.Speed, stop.HitNet);
            }
        }

        // ---------- остановка в зоне ----------

        [Test]
        public void StopZoneIsDoneOnlyWhenTheBallStopsInsideTheYellowSquare()
        {
            var t = Begin(TutorialStep.StopZone);
            t.ObserveEvent(Event(FootballEventKind.Landed, FootballElement.Stop, 0));
            Assert.IsFalse(t.Done, "посадка мяча сама по себе не конец элемента");
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Snake, 2));
            Assert.IsFalse(t.Done);
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Stop, 2));
            Assert.IsTrue(t.Done, "внутри жёлтого квадрата: два очка");
            Assert.IsFalse(t.Retry);
        }

        [Test]
        public void StopZoneNearTheSquareDoesNotCount()
        {
            var t = Begin(TutorialStep.StopZone);
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Stop, 1));
            Assert.IsFalse(t.Done, "рядом с квадратом (1 очко) не засчитывается");
            Assert.IsTrue(t.Retry, "новая попытка сразу");
        }

        [Test]
        public void StopZoneRestartsAtOnceWhenTheBallMissedTheZone()
        {
            var t = Begin(TutorialStep.StopZone);
            t.ObserveEvent(Event(FootballEventKind.ElementFinished, FootballElement.Stop, 0));
            Assert.IsTrue(t.Retry);
            Assert.IsFalse(t.Done);
        }

        [Test]
        public void RealStopSandboxIsCountedOnlyWhenTheBallStopsInTheZone()
        {
            var good = Begin(TutorialStep.StopZone);
            var goodRules = new FootballRules(Tuning.CopyForTutorial(FootballTutorial.SandboxCones, 1), () => 0.5f, new[] { 2 });
            goodRules.Raised += good.ObserveEvent;
            for (int i = 0; i < 9000 && !goodRules.Over; i++) goodRules.Step(0.01f, 0.5f, 0.30f);
            Assert.IsTrue(good.Done, "с подходящим торможением мяч встаёт в зоне");

            var bad = Begin(TutorialStep.StopZone);
            var badRules = new FootballRules(Tuning.CopyForTutorial(FootballTutorial.SandboxCones, 1), () => 0.5f, new[] { 2 });
            badRules.Raised += bad.ObserveEvent;
            for (int i = 0; i < 9000 && !badRules.Over; i++) badRules.Step(0.01f, 0.5f, 0f);              // без торможения мяч уходит в сетку
            Assert.IsTrue(bad.Retry);
            Assert.IsFalse(bad.Done);
        }

        // ---------- повтор ----------

        [Test]
        public void MarkRetryDoesNotUndoADoneStep()
        {
            var t = Begin(TutorialStep.Gate);
            t.ObserveEvent(Event(FootballEventKind.Kick, FootballElement.Pass));
            t.MarkRetry();
            Assert.IsTrue(t.Done);
            Assert.IsFalse(t.Retry);
        }

        [Test]
        public void MarkRetryRestartsAnUnfinishedStepAndBeginClearsIt()
        {
            var t = Begin(TutorialStep.Slow);
            t.MarkRetry();
            Assert.IsTrue(t.Retry);
            t.Begin(TutorialStep.Slow);
            Assert.IsFalse(t.Retry);
        }

        // ---------- подпись очков ----------

        [Test]
        public void ScoreGrowsLeftAndNeverReachesTheTimer()
        {
            var top = new Rect(130f, 20f, 1180f, 88f);
            const float s = 1f;
            var timer = FootballHud.TimerRect(top, s);
            float edge = FootballHud.ScoreRightEdge(top, s);
            float previousLeft = float.MaxValue;
            foreach (int score in new[] { 0, 9, 10, 25, 100 })
            {
                var rect = FootballHud.ScoreRect(top, s, score, 48f * s);
                Assert.AreEqual(edge, rect.xMax, 0.01f, "правый край неподвижен при счёте " + score);
                Assert.LessOrEqual(rect.xMin, previousLeft + 0.01f, "число растёт влево");
                Assert.GreaterOrEqual(rect.xMin, timer.xMax, "не наезжает на таймер при счёте " + score);
                previousLeft = rect.xMin;
            }
        }
    }
}
