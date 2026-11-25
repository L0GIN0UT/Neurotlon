using NUnit.Framework;

namespace Neurotlon.Games.Pong.Tests
{
    public class PongScoreLayoutTests
    {
        [TestCase(0, 0)]
        [TestCase(9, 9)]
        [TestCase(10, 9)]
        [TestCase(11, 10)]
        [TestCase(25, 20)]
        [TestCase(100, 99)]
        public void NamesStayClearOfTheScore(int left, int right)
        {
            string text = PongScoreLayout.Text(left, right);
            float width = PongScoreLayout.Width(text);
            float offset = PongScoreLayout.NameOffset(text);
            Assert.GreaterOrEqual(offset, width * 0.5f + PongScoreLayout.NameGap - 0.001f, "имя не должно заходить на счёт");
            Assert.GreaterOrEqual(width, text.Length * PongScoreLayout.FontSize * 0.5f, "поле не уже самого текста");
        }

        [Test]
        public void WiderScoreMovesNamesFurther()
        {
            float narrow = PongScoreLayout.NameOffset(PongScoreLayout.Text(0, 0));
            float wide = PongScoreLayout.NameOffset(PongScoreLayout.Text(100, 99));
            Assert.Greater(wide, narrow);
        }

        [Test]
        public void DebugScoreParsesPair()
        {
            int l, r;
            Assert.IsTrue(PongScoreLayout.TryParseDebugScore(new[] { "game.exe", "--debug-score", "11:10" }, out l, out r));
            Assert.AreEqual(11, l);
            Assert.AreEqual(10, r);
        }

        [Test]
        public void DebugScoreSingleNumberMeansBothSides()
        {
            int l, r;
            Assert.IsTrue(PongScoreLayout.TryParseDebugScore(new[] { "--debug-score=25" }, out l, out r));
            Assert.AreEqual(25, l);
            Assert.AreEqual(25, r);
        }

        [TestCase("abc")]
        [TestCase("-1:3")]
        [TestCase("1:2:3")]
        [TestCase("")]
        public void BadDebugScoreIsIgnored(string value)
        {
            int l, r;
            Assert.IsFalse(PongScoreLayout.TryParseDebugScore(new[] { "--debug-score", value }, out l, out r));
        }

        [Test]
        public void NoArgumentMeansRealScore()
        {
            int l, r;
            Assert.IsFalse(PongScoreLayout.TryParseDebugScore(new[] { "game.exe", "--launch", "x.json" }, out l, out r));
            Assert.IsFalse(PongScoreLayout.TryParseDebugScore(null, out l, out r));
        }
    }
}
