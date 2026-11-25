using System.Collections.Generic;
using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    // Тесты общего хода обучения из NeurotlonKit (кит лежит в пакете без своих тестов, поэтому тесты здесь).
    public class NeurotlonTutorialTests
    {
        static NeurotlonTutorial Start(int steps, List<int> started)
        {
            var tutorial = new NeurotlonTutorial(steps);
            tutorial.StepStarted += started.Add;
            tutorial.Begin();
            Read(tutorial);
            return tutorial;
        }

        // Пройти фазу чтения подсказки: механика в ней не считается.
        static void Read(NeurotlonTutorial tutorial)
        {
            tutorial.Update(NeurotlonTutorial.ReadSeconds + 0.01f, false);
        }

        [Test]
        public void StepsGoOneByOneInOrderAndFinish()
        {
            var started = new List<int>();
            var tutorial = Start(3, started);
            for (int i = 0; i < 3; i++)
            {
                Assert.AreEqual(i, tutorial.Index);
                tutorial.Update(0.1f, true);                              // механика сработала
                Assert.AreEqual(NeurotlonTutorial.Phase.Done, tutorial.State);
                tutorial.Update(NeurotlonTutorial.DoneShowSeconds + 0.1f, false);
                if (i < 2) Read(tutorial);
            }
            Assert.AreEqual(NeurotlonTutorial.Phase.Finished, tutorial.State);
            CollectionAssert.AreEqual(new[] { 0, 1, 2 }, started, "каждый шаг начинается ровно один раз и по порядку");
        }

        [Test]
        public void AStepIsCountedByTheEventNotByTheClock()
        {
            var tutorial = Start(2, new List<int>());
            tutorial.Update(NeurotlonTutorial.StepSeconds * 0.5f, false);
            Assert.AreEqual(0, tutorial.Index, "без события шаг не засчитан");
            tutorial.Update(0.1f, true);
            Assert.AreEqual(NeurotlonTutorial.Phase.Done, tutorial.State);
        }

        [Test]
        public void ATimedOutStepStartsAgainAndAsksForAVolunteerAfterTwoFailures()
        {
            var started = new List<int>();
            var tutorial = Start(2, started);
            tutorial.Update(NeurotlonTutorial.StepSeconds + 0.1f, false);
            Assert.AreEqual(0, tutorial.Index, "шаг повторяется, а не засчитывается по таймеру");
            Assert.AreEqual(1, tutorial.Timeouts);
            Assert.IsFalse(tutorial.NeedsHelp);
            tutorial.Update(NeurotlonTutorial.StepSeconds + 0.1f, false);
            Assert.IsTrue(tutorial.NeedsHelp);
            CollectionAssert.AreEqual(new[] { 0, 0, 0 }, started, "песочница шага сбрасывается при каждой попытке");
        }

        [Test]
        public void SkipMovesToTheNextStepAndClearsTheFailures()
        {
            var started = new List<int>();
            var tutorial = Start(3, started);
            tutorial.Update(NeurotlonTutorial.StepSeconds + 0.1f, false);
            tutorial.Skip();
            Assert.AreEqual(1, tutorial.Index);
            Assert.AreEqual(0, tutorial.Timeouts);
            Assert.AreEqual(NeurotlonTutorial.Phase.Reading, tutorial.State, "новый шаг начинается с чтения подсказки");
            tutorial.Skip();
            tutorial.Skip();
            Assert.AreEqual(NeurotlonTutorial.Phase.Finished, tutorial.State);
        }

        [Test]
        public void TheHintIsReadFirstAndTheMechanicDoesNotCountWhileReading()
        {
            var tutorial = new NeurotlonTutorial(1);
            tutorial.Begin();
            Assert.AreEqual(NeurotlonTutorial.Phase.Reading, tutorial.State);
            Assert.IsFalse(tutorial.InPlay);
            tutorial.Update(NeurotlonTutorial.ReadSeconds * 0.5f, true);
            Assert.AreEqual(NeurotlonTutorial.Phase.Reading, tutorial.State, "механика во время чтения не засчитывается");
            tutorial.Update(NeurotlonTutorial.ReadSeconds, false);
            Assert.AreEqual(NeurotlonTutorial.Phase.Trying, tutorial.State);
            Assert.IsTrue(tutorial.InPlay);
        }

        [Test]
        public void ARepeatedStepSkipsTheReading()
        {
            var tutorial = Start(1, new List<int>());
            tutorial.Update(NeurotlonTutorial.StepSeconds + 0.1f, false);
            Assert.AreEqual(NeurotlonTutorial.Phase.Trying, tutorial.State, "после неудачи сразу попытка, подсказку уже читали");
        }

        [Test]
        public void AStepThatIsATestCannotBeSkippedAndKeepsItsOwnTimeout()
        {
            var tutorial = new NeurotlonTutorial(2, i => i == 0, i => i == 1 ? 60f : 20f);
            tutorial.Begin();
            Read(tutorial);
            Assert.IsTrue(tutorial.Skip(), "первый шаг пропустить можно");
            Read(tutorial);
            Assert.IsFalse(tutorial.CanSkipNow);
            Assert.IsFalse(tutorial.Skip(), "шаг-проверку пропустить нельзя");
            Assert.AreEqual(1, tutorial.Index);
            Assert.AreEqual(60f, tutorial.TimeLeft, 0.01f, "у шага своё время на попытку");
        }

        [Test]
        public void TryStartedFiresWhenReadingEndsAndOnEveryRepeat()
        {
            var tries = new List<int>();
            var tutorial = new NeurotlonTutorial(1);
            tutorial.TryStarted += tries.Add;
            tutorial.Begin();
            Assert.AreEqual(0, tries.Count, "пока читают, попытки нет");
            Read(tutorial);
            CollectionAssert.AreEqual(new[] { 0 }, tries);
            tutorial.Update(NeurotlonTutorial.StepSeconds + 0.1f, false);
            CollectionAssert.AreEqual(new[] { 0, 0 }, tries, "повтор после неудачи начинает новую попытку");
        }

        [Test]
        public void NoStepsMeansFinishedAtOnce()
        {
            var tutorial = new NeurotlonTutorial(0);
            Assert.AreEqual(NeurotlonTutorial.Phase.Finished, tutorial.State);
        }

        [Test]
        public void TheWordingNeverMentionsAHand()
        {
            foreach (string text in new[] { NeurotlonTexts.Tense, NeurotlonTexts.Relax, NeurotlonTexts.TenseThenRelax, NeurotlonTexts.RelaxBeforeNext,
                NeurotlonCalibration.TextRest, NeurotlonCalibration.TextSqueeze, NeurotlonCalibration.TextRelease })
            {
                StringAssert.DoesNotContain("рук", text.ToLowerInvariant());
                StringAssert.DoesNotContain("кулак", text.ToLowerInvariant());
            }
        }
    }
}
