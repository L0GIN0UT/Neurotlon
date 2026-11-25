using NUnit.Framework;
using UnityEngine;

namespace Neurotlon.Games.Darts.Tests
{
    // Подпись счёта (0, 9, 10, 25, 100) помещается в поле и держит правый край на месте.
    public class NeurotlonHudTests
    {
        [TestCase(0)]
        [TestCase(9)]
        [TestCase(10)]
        [TestCase(25)]
        [TestCase(100)]
        public void TheScoreFieldFitsAndKeepsItsRightEdge(int score)
        {
            const float fontSize = 52f;
            string text = NeurotlonHud.ScoreText(score);
            Rect field = NeurotlonHud.RightAligned(1000f, 20f, 90f, text, fontSize, 200f);
            Assert.AreEqual(1000f, field.xMax, 1e-3f, "правый край не двигается");
            Assert.GreaterOrEqual(field.width, NeurotlonHud.TextWidth(text, fontSize), "поле не уже текста");
            Assert.GreaterOrEqual(field.width, 200f);
        }

        [Test]
        public void MoreDigitsGrowTheFieldToTheLeftOnly()
        {
            Rect small = NeurotlonHud.RightAligned(1000f, 0f, 90f, NeurotlonHud.ScoreText(9), 52f, 0f);
            Rect big = NeurotlonHud.RightAligned(1000f, 0f, 90f, NeurotlonHud.ScoreText(100), 52f, 0f);
            Assert.Greater(big.width, small.width);
            Assert.AreEqual(small.xMax, big.xMax, 1e-3f);
        }

        [Test]
        public void ADebugScoreListIsParsedAndCycles()
        {
            int[] values = NeurotlonHud.ParseValues("0, 9,10 ,25,100,abc");
            CollectionAssert.AreEqual(new[] { 0, 9, 10, 25, 100 }, values);
            Assert.AreEqual(0, NeurotlonHud.Cycle(values, 0f, 3f));
            Assert.AreEqual(9, NeurotlonHud.Cycle(values, 3.1f, 3f));
            Assert.AreEqual(100, NeurotlonHud.Cycle(values, 12.5f, 3f));
            Assert.AreEqual(0, NeurotlonHud.Cycle(values, 15.2f, 3f), "после последнего снова первое");
            Assert.AreEqual(0, NeurotlonHud.ParseValues("").Length);
            Assert.AreEqual(0, NeurotlonHud.Cycle(new int[0], 5f, 3f));
        }

        [Test]
        public void AScoreStyleNeverWrapsOrClips()
        {
            var style = new GUIStyle { wordWrap = true, clipping = TextClipping.Clip };
            NeurotlonHud.SingleLine(style);
            Assert.IsFalse(style.wordWrap);
            Assert.AreEqual(TextClipping.Overflow, style.clipping);
        }
    }
}
