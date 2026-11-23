using NUnit.Framework;
using UnityEngine;

namespace Neurotlon.Games.Football.Tests
{
    public class BallCollisionsTests
    {
        const float R = 0.11f;
        float impact;

        [Test]
        public void MovingBallHitsALyingOneAndPushesItAway()
        {
            Vector3 pa = new Vector3(0f, R, 0f), va = new Vector3(3f, 0f, 0f);
            Vector3 pb = new Vector3(0.2f, R, 0f), vb = Vector3.zero;                  // центры ближе 2R: мячи касаются
            Assert.IsTrue(BallCollisions.Resolve(ref pa, ref va, ref pb, ref vb, R, 0.6f, out impact));
            Assert.AreEqual(3f, impact, 1e-3f, "скорость сближения для звука удара");
            Assert.Greater(vb.x, 1.5f, "лежавший мяч покатился вперёд");
            Assert.Less(va.x, 1.5f, "налетевший мяч потерял скорость");
            Assert.GreaterOrEqual(pb.x - pa.x, 2f * R - 1e-4f, "мячи больше не пересекаются");
        }

        [Test]
        public void SeparatedBallsDoNotInteract()
        {
            Vector3 pa = Vector3.zero, va = Vector3.right, pb = new Vector3(1f, 0f, 0f), vb = Vector3.zero;
            Assert.IsFalse(BallCollisions.Resolve(ref pa, ref va, ref pb, ref vb, R, 0.6f, out impact));
            Assert.AreEqual(Vector3.right, va);
            Assert.AreEqual(Vector3.zero, vb);
        }

        [Test]
        public void BallsMovingApartAreOnlySeparated()
        {
            Vector3 pa = Vector3.zero, va = -Vector3.right, pb = new Vector3(0.15f, 0f, 0f), vb = Vector3.right;
            BallCollisions.Resolve(ref pa, ref va, ref pb, ref vb, R, 0.6f, out impact);
            Assert.AreEqual(-Vector3.right, va);
            Assert.AreEqual(Vector3.right, vb);
        }

        [Test]
        public void EqualBallsExchangeMostOfTheSpeedHeadOn()
        {
            Vector3 pa = new Vector3(0f, R, 0f), va = new Vector3(2f, 0f, 0f);
            Vector3 pb = new Vector3(0.21f, R, 0f), vb = Vector3.zero;
            BallCollisions.Resolve(ref pa, ref va, ref pb, ref vb, R, 1f, out impact);              // идеально упругий удар
            Assert.AreEqual(0f, va.x, 1e-3f);
            Assert.AreEqual(2f, vb.x, 1e-3f);
        }
    }
}
