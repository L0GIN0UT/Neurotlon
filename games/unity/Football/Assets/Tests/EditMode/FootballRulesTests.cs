using System;
using NUnit.Framework;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballRulesTests
    {
        const float Dt = 0.01f;

        static FootballTuning Tuning(DribbleMode mode)
        {
            var t = new FootballTuning();
            t.Dribble = mode;
            return t;
        }

        static void Run(IElement e, Func<float> eeg, Func<float, float?> emg, float maxSeconds = 90f)
        {
            float time = 0f;
            while (!e.Finished && time < maxSeconds)
            {
                e.Step(Dt, eeg(), emg(time));
                time += Dt;
            }
        }

        // ---------- змейка ----------

        [Test]
        public void LevelDribbleWeavingThroughTheConesIsClean()
        {
            var t = Tuning(DribbleMode.Level);
            var snake = new SnakeElement(t);
            // нужный X в каждый момент берём из пути: напряжение, дающее это положение
            Run(snake, () => 0.5f, time =>
            {
                float y = t.StartY + t.ForwardSpeed * time;
                float x = SnakePath.DesiredX(t, y);
                return x / (2f * t.LateralMax) + 0.5f;
            });
            Assert.IsTrue(snake.Finished);
            Assert.LessOrEqual(snake.Touches, 1);
            Assert.AreEqual(2, snake.Points);
        }

        [Test]
        public void LevelDribbleStraightThroughTheMiddleTouchesEveryCone()
        {
            var snake = new SnakeElement(Tuning(DribbleMode.Level));
            Run(snake, () => 0.5f, time => 0.5f);                  // мышца в середине диапазона: мяч по линии конусов
            Assert.IsTrue(snake.Finished);
            Assert.AreEqual(5, snake.Touches);
            Assert.AreEqual(1, snake.Points);
        }

        [Test]
        public void ThrottleDribbleSlowIsCleanAndFastTouchesCones()
        {
            var slow = new SnakeElement(Tuning(DribbleMode.Throttle));
            Run(slow, () => 0.5f, time => 0.0f);
            Assert.IsTrue(slow.Finished);
            Assert.LessOrEqual(slow.Touches, 1, "медленно мяч идёт по змейке");
            var fast = new SnakeElement(Tuning(DribbleMode.Throttle));
            Run(fast, () => 0.5f, time => 1.0f);
            Assert.IsTrue(fast.Finished);
            Assert.GreaterOrEqual(fast.Touches, 2, "на полной скорости мяч уходит к конусам");
        }

        [Test]
        public void RhythmDribbleOnTheBeatFinishesAndWithoutTapsDoesNot()
        {
            var t = Tuning(DribbleMode.Rhythm);
            var good = new SnakeElement(t);
            Run(good, () => 0.5f, time =>
            {
                float phase = time % t.RhythmBeatSeconds;
                return phase < 0.2f ? 0.9f : 0.05f;               // короткий импульс в начале каждого такта
            });
            Assert.IsTrue(good.Finished);
            Assert.Greater(good.Points, 0);
            var idle = new SnakeElement(t);
            Run(idle, () => 0.5f, time => 0.05f, t.ElementSeconds + 5f);
            Assert.IsTrue(idle.Finished);
            Assert.AreEqual(0, idle.Points, "без касаний мяч стоит: элемент не выполнен");
        }

        // ---------- передача и удар: три попытки ----------

        // Мышца: полторы секунды расслаблена, полторы напряжена — ровно одна попытка за период.
        static float? Pulse(float time)
        {
            return time % 3f < 1.5f ? 0f : 0.9f;
        }

        [Test]
        public void PassWithFullConcentrationHitsEveryHoleAndScoresTwo()
        {
            var pass = new PassElement(new FootballTuning(), () => 0.3f);
            Run(pass, () => 1f, Pulse);
            Assert.IsTrue(pass.Finished);
            Assert.AreEqual(3, pass.AttemptCount);
            for (int i = 0; i < 3; i++) Assert.AreEqual(2, pass.AttemptResult(i), "попытка " + i);
            Assert.AreEqual(2, pass.Points);
            Assert.Greater(pass.Accuracy, 0.6f);
        }

        [Test]
        public void PassWithoutConcentrationOftenMissesButNeverBreaks()
        {
            int total = 0;
            for (int i = 0; i < 20; i++)
            {
                float seed = 0.05f * i;
                var pass = new PassElement(new FootballTuning(), () => seed);
                Run(pass, () => 0f, Pulse);
                Assert.IsTrue(pass.Finished);
                Assert.That(pass.Points, Is.InRange(0, 2));
                total += pass.Points;
            }
            Assert.Less(total, 20 * 2, "без сосредоточения идеально попасть каждый раз нельзя");
        }

        [Test]
        public void PassHolesAreThreeDifferentPlacesOnADiagonal()
        {
            var t = new FootballTuning();
            var seen = new System.Collections.Generic.HashSet<string>();
            for (int i = 0; i < t.Attempts; i++) seen.Add(Math.Sign(t.PassX(i)) + ":" + Math.Sign(t.PassZ(i)));
            Assert.AreEqual(3, seen.Count);
            for (int i = 0; i < t.Attempts; i++)
            {
                Assert.Less(Math.Abs(t.PassX(i)) + t.TarpHoleRadius, t.GoalHalfWidth, "отверстие внутри ворот по ширине");
                Assert.Less(Math.Abs(t.PassZ(i)) + t.TarpHoleRadius, t.GoalHeight * 0.5f, "отверстие внутри ворот по высоте");
            }
        }

        [Test]
        public void ElementDoesNotFinishAfterTheFirstAttemptAndNeedsARelaxedLegForTheNext()
        {
            var pass = new PassElement(new FootballTuning(), () => 0.3f);
            for (float time = 0f; time < 0.3f; time += Dt) pass.Step(Dt, 1f, 0f);
            for (float time = 0f; time < 0.2f; time += Dt) pass.Step(Dt, 1f, 0.9f);
            Assert.AreEqual(AimedElement.PhaseKind.Flying, pass.Phase);
            for (float time = 0f; time < 1.0f; time += Dt) pass.Step(Dt, 1f, 0.9f);        // полёт кончился, мышца всё ещё напряжена
            Assert.IsFalse(pass.Finished);
            Assert.AreEqual(1, pass.Attempt);
            for (float time = 0f; time < 2f; time += Dt) pass.Step(Dt, 1f, 0.9f);
            Assert.AreEqual(AimedElement.PhaseKind.Aiming, pass.Phase, "новая попытка только после расслабления мышцы");
        }

        [Test]
        public void ElementPointsFollowTheSumOfThreeAttempts()
        {
            Assert.AreEqual(2, AimedElement.PointsFromSum(6, 3));
            Assert.AreEqual(2, AimedElement.PointsFromSum(5, 3));
            Assert.AreEqual(1, AimedElement.PointsFromSum(4, 3));
            Assert.AreEqual(1, AimedElement.PointsFromSum(2, 3));
            Assert.AreEqual(0, AimedElement.PointsFromSum(1, 3));
            Assert.AreEqual(0, AimedElement.PointsFromSum(0, 3));
        }

        [Test]
        public void PassScoresTwoInsideTheHoleOneInTheGoalAndZeroOutside()
        {
            var t = new FootballTuning();
            float tx = t.PassX(0), tz = t.PassZ(0);
            Assert.AreEqual(2, PassElement.PointsAt(t, tx, tz, tx, tz));
            Assert.AreEqual(2, PassElement.PointsAt(t, tx + t.PassHoleRadius * 0.9f, tz, tx, tz));
            Assert.AreEqual(1, PassElement.PointsAt(t, 0.80f, 0.33f, tx, tz), "в ворота, но мимо отверстия");
            Assert.AreEqual(0, PassElement.PointsAt(t, t.GoalHalfWidth + 0.3f, 0f, tx, tz));
            Assert.AreEqual(0, PassElement.PointsAt(t, 0f, t.GoalHeight, tx, tz));
        }

        [Test]
        public void AnyHoleOfTheTarpLetsTheBallThrough()
        {
            var t = new FootballTuning();
            for (int i = 0; i < t.TarpHoleX.Length; i++) Assert.IsTrue(t.InAnyHole(t.TarpHoleX[i], t.TarpHoleZ[i]));
            Assert.IsFalse(t.InAnyHole(0.80f, 0.33f), "в верхнем правом углу отверстия нет");
            Assert.IsFalse(t.InAnyHole(-0.80f, -0.33f), "в нижнем левом углу отверстия нет");
        }

        [Test]
        public void HittingThePostOrTheCrossbarScoresNothingAndIsTold()
        {
            var t = new FootballTuning();
            float tx = t.PassX(0), tz = t.PassZ(0);
            Assert.AreEqual(FootballTuning.FrameContact.Post, t.FrameAt(t.GoalHalfWidth, 0f));
            Assert.AreEqual(FootballTuning.FrameContact.Post, t.FrameAt(-t.GoalHalfWidth - 0.1f, 0.2f));
            Assert.AreEqual(FootballTuning.FrameContact.Crossbar, t.FrameAt(0.3f, t.GoalHeight * 0.5f));
            Assert.AreEqual(FootballTuning.FrameContact.None, t.FrameAt(0f, 0f), "чехол — не рама");
            Assert.AreEqual(FootballTuning.FrameContact.None, t.FrameAt(t.GoalHalfWidth + 0.6f, 0f), "далеко от штанги — чистый промах");
            Assert.AreEqual(0, PassElement.PointsAt(t, t.GoalHalfWidth, 0f, tx, tz), "по штанге — ноль");
            Assert.AreEqual(0, PassElement.PointsAt(t, 0.3f, t.GoalHeight * 0.5f, tx, tz), "по перекладине — ноль");
        }

        [Test]
        public void TheNetHasARoofAndASlopingBackSoBallsFromAboveStayOutside()
        {
            var t = new FootballTuning();
            Assert.AreEqual(-1f, t.NetTopHeight(-0.1f), "перед воротами сетки нет");
            Assert.AreEqual(t.GoalHeight, t.NetTopHeight(t.GoalDepthTop * 0.5f), 1e-4f, "над проёмом крыша на высоте перекладины");
            Assert.AreEqual(t.GoalHeight * 0.5f, t.NetTopHeight((t.GoalDepthTop + t.GoalDepthBottom) * 0.5f), 1e-4f, "задняя стенка наклонная");
            Assert.AreEqual(0f, t.NetTopHeight(t.GoalDepthBottom + 0.5f), 1e-4f, "за воротами сетки нет");
            Assert.AreEqual(t.GoalDepthBottom, t.NetBackDepth(0f), 1e-4f);
            Assert.AreEqual(t.GoalDepthTop, t.NetBackDepth(t.GoalHeight), 1e-4f);
        }

        [Test]
        public void KickIsOnlyFiredAfterTheLegWasRelaxed()
        {
            var kick = new KickElement(new FootballTuning(), () => 0.3f);
            for (float time = 0f; time < 2f; time += Dt) kick.Step(Dt, 1f, 0.9f);     // мышца напряжена с самого начала
            Assert.AreEqual(AimedElement.PhaseKind.Aiming, kick.Phase);
            for (float time = 0f; time < 0.2f; time += Dt) kick.Step(Dt, 1f, 0.0f);
            for (float time = 0f; time < 0.2f; time += Dt) kick.Step(Dt, 1f, 0.9f);
            Assert.AreEqual(AimedElement.PhaseKind.Flying, kick.Phase);
        }

        [Test]
        public void KickRingsGiveTwoInTheCentreOneOnTheBoardAndZeroOutside()
        {
            var t = new FootballTuning();
            Assert.AreEqual(2, KickElement.PointsAt(t, 0f, 0f));
            Assert.AreEqual(2, KickElement.PointsAt(t, t.TargetInnerRadius * 0.9f, 0f));
            Assert.AreEqual(1, KickElement.PointsAt(t, t.TargetInnerRadius * 1.1f, 0f));
            Assert.AreEqual(1, KickElement.PointsAt(t, 0f, -t.TargetRadius * 0.95f));
            Assert.AreEqual(0, KickElement.PointsAt(t, t.TargetRadius * 1.05f, 0f));
        }

        [Test]
        public void KickWithFullConcentrationHitsTheCentreThreeTimes()
        {
            var kick = new KickElement(new FootballTuning(), () => 0.3f);
            Run(kick, () => 1f, Pulse);
            Assert.IsTrue(kick.Finished);
            for (int i = 0; i < 3; i++) Assert.AreEqual(2, kick.AttemptResult(i), "попытка " + i);
            Assert.AreEqual(2, kick.Points);
        }

        // ---------- остановка ----------

        [Test]
        public void StopWithModerateBrakingEndsInsideTheZone()
        {
            var stop = new StopElement(new FootballTuning());
            Run(stop, () => 0.5f, time => 0.30f);                 // нужное торможение подобрано по параметрам
            Assert.IsTrue(stop.Finished);
            Assert.AreEqual(2, stop.Points);
        }

        [Test]
        public void StopWithoutBrakingOvershootsAndFullBrakingFallsShort()
        {
            var free = new StopElement(new FootballTuning());
            Run(free, () => 0.5f, time => 0.0f);
            Assert.AreEqual(0, free.Points);
            var hard = new StopElement(new FootballTuning());
            Run(hard, () => 0.5f, time => 1.0f);
            Assert.AreEqual(0, hard.Points);
        }

        [Test]
        public void AnUnbrakedBallStopsInTheNetBehindTheZoneInsteadOfRollingOnForever()
        {
            var t = new FootballTuning();
            var stop = new StopElement(t);
            float time = 0f;
            while (!stop.Finished && time < 30f)
            {
                stop.Step(Dt, 0.5f, 0f);
                time += Dt;
            }
            Assert.IsTrue(stop.Finished);
            Assert.IsTrue(stop.HitNet);
            Assert.Greater(stop.ImpactSpeed, 1f, "скорость удара о сетку запоминается для анимации прогиба");
            Assert.AreEqual(0, stop.Points);
            Assert.AreEqual(t.StopNetDistance - t.BallRadius, stop.Distance, 1e-3f);
            Assert.Less(time, 4f, "раньше мяч катился около 9 секунд");
            Assert.Greater(t.StopNetDistance, t.StopZoneDistance + t.StopZoneHalf * 2f, "сетка стоит за зоной, а не в ней");
        }

        [Test]
        public void StopPredictionMatchesWhereTheBallRealiyStops()
        {
            var t = new FootballTuning();
            var stop = new StopElement(t);
            stop.Step(Dt, 0.5f, 0.3f);
            float predicted = stop.PredictedStop;
            Run(stop, () => 0.5f, time => 0.30f);
            Assert.AreEqual(predicted, stop.Distance, 0.15f);
        }

        // ---------- вся игра ----------

        [Test]
        public void ATutorialSandboxRunsASnakeToTheFirstConeAndOneKick()
        {
            var tuning = new FootballTuning().CopyForTutorial(1, 1);
            var rules = new FootballRules(tuning, () => 0.3f, new[] { 0, 3 });
            var demo = new FootballDemo(true, tuning);
            for (float time = 0f; !rules.Over && time < 120f; time += 0.01f)
            {
                float eeg, emg;
                demo.Step(0.01f);
                demo.Signals(rules, out eeg, out emg);
                rules.Step(0.01f, eeg, emg);
            }
            Assert.IsTrue(rules.Over, "песочница заканчивается");
            Assert.AreEqual(2, rules.Count);
            Assert.GreaterOrEqual(rules.PointsOf(1), 1, "удар по мишени засчитан");
            Assert.AreEqual(1, tuning.ConeY.Length, "в песочнице один конус");
            Assert.AreEqual(1, tuning.Attempts, "в песочнице одна попытка");
        }

        [Test]
        public void TutorialCopyKeepsTheFirstConesOfTheRealFieldAndLeavesTheOriginal()
        {
            var real = new FootballTuning();
            var copy = real.CopyForTutorial(2, 5);
            CollectionAssert.AreEqual(new[] { real.ConeY[0], real.ConeY[1] }, copy.ConeY);
            Assert.AreEqual(5, copy.Attempts);
            Assert.AreEqual(5, real.ConeY.Length, "настоящее поле не тронуто");
            Assert.AreEqual(3, real.Attempts);
            Assert.GreaterOrEqual(copy.ElementSeconds, FootballTutorial.CheckTimeoutSeconds, "элемент не кончается раньше таймаута шага");
        }

        [Test]
        public void ATutorialKickThatMissesTheBoardDoesNotPass()
        {
            var tuning = new FootballTuning().CopyForTutorial(1, 1);
            var rules = new FootballRules(tuning, () => 0.3f, new[] { 3 });
            var demo = new FootballDemo(false, tuning);
            for (float time = 0f; !rules.Over && time < 60f; time += 0.01f)
            {
                float eeg, emg;
                demo.Step(0.01f);
                demo.Signals(rules, out eeg, out emg);
                rules.Step(0.01f, eeg, 0.9f);               // мышца напряжена сразу, без концентрации
            }
            Assert.LessOrEqual(rules.PointsOf(0), 2);
        }

        [Test]
        public void FullRunScoresAtMostTenAndEndsAfterFourElements()
        {
            var t = Tuning(DribbleMode.Level);
            var rules = new FootballRules(t, () => 0.3f);
            int started = 1, finished = 0;                     // первый элемент стартует в конструкторе, до подписки
            bool over = false;
            rules.Raised += e =>
            {
                if (e.Kind == FootballEventKind.ElementStarted) started++;
                if (e.Kind == FootballEventKind.ElementFinished) finished++;
                if (e.Kind == FootballEventKind.GameOver) over = true;
            };
            float time = 0f, elementTime = 0f;
            int lastIndex = 0;
            while (!rules.Over && time < 400f)
            {
                if (rules.CurrentIndex != lastIndex) { lastIndex = rules.CurrentIndex; elementTime = 0f; }
                float? emg;
                switch (rules.CurrentIndex)
                {
                    case 0: emg = SnakePath.DesiredX(t, t.StartY + t.ForwardSpeed * elementTime) / (2f * t.LateralMax) + 0.5f; break;
                    case 2: emg = 0.30f; break;
                    default: emg = Pulse(elementTime); break;                // передача и удар: расслабить, потом напрячь, три раза
                }
                rules.Step(Dt, 1f, emg);
                time += Dt;
                elementTime += Dt;
            }
            Assert.IsTrue(rules.Over);
            Assert.IsTrue(over);
            Assert.AreEqual(4, started);
            Assert.AreEqual(4, finished);
            Assert.AreEqual(8, rules.ElementPoints, "все четыре элемента выполнены чисто");
            Assert.LessOrEqual(rules.Score, 10);
            Assert.GreaterOrEqual(rules.Score, 9);
        }

        [Test]
        public void ScoreIsNeverAboveTheLimit()
        {
            var rules = new FootballRules(new FootballTuning(), () => 0.3f);
            rules.MaxPoints = 7;
            Assert.LessOrEqual(rules.Score, 7);
        }
    }
}
