using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace Neurotlon.Games.Football.Tests
{
    // Конус — настоящее твёрдое тело; мяч-«поршень» (кинематический шар) идёт по траектории игры и толкает его.
    // Проверяем на физике Unity, прогоняя её вручную (SimulationMode.Script).
    public class FootballConeTests
    {
        GameObject ground, cone, ball;
        FootballCone body;
        Rigidbody ballBody;
        SimulationMode previousMode;
        float previousThreshold;
        Vector3 coneStart;

        [SetUp]
        public void SetUp()
        {
            previousMode = Physics.simulationMode;
            previousThreshold = Physics.bounceThreshold;
            Physics.simulationMode = SimulationMode.Script;
            Physics.bounceThreshold = FootballCone.BounceThreshold;
            ground = new GameObject("Ground");
            var box = ground.AddComponent<BoxCollider>();
            box.center = new Vector3(0f, -0.5f, 0f);
            box.size = new Vector3(50f, 1f, 50f);
            box.sharedMaterial = FootballCone.MakeMaterial("g", FootballCone.GrassFriction, FootballCone.GroundBounciness);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Art/Football/TrainingCone.fbx");
            Assert.IsNotNull(prefab, "нет модели конуса");
            cone = (GameObject)Object.Instantiate(prefab);
            coneStart = new Vector3(0f, 0f, 2f);
            cone.transform.position = coneStart;
            body = FootballCone.Attach(cone, FootballCone.MakeMaterial("c", FootballCone.GrassFriction, FootballCone.ConeBounciness));
            ball = new GameObject("Ball");
            ballBody = ball.AddComponent<Rigidbody>();
            ballBody.isKinematic = true;
            var sphere = ball.AddComponent<SphereCollider>();
            sphere.radius = FootballLayout.BallRadius;
            sphere.sharedMaterial = FootballCone.MakeMaterial("b", 0.4f, FootballCone.BallBounciness);
            Physics.SyncTransforms();
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(ball);
            Object.DestroyImmediate(cone);
            Object.DestroyImmediate(ground);
            Physics.simulationMode = previousMode;
            Physics.bounceThreshold = previousThreshold;
        }

        // Мяч идёт вдоль +Z со смещением offset по X и скоростью speed, потом физика ещё 1,5 с.
        void BallPasses(float offset, float speed)
        {
            float z = coneStart.z - 1.0f;
            ballBody.position = new Vector3(offset, FootballLayout.BallRadius, z);
            ball.transform.position = ballBody.position;
            Physics.SyncTransforms();
            int steps = Mathf.RoundToInt(2.0f / speed / 0.01f);
            for (int i = 0; i < steps; i++)
            {
                z += speed * 0.01f;
                ballBody.MovePosition(new Vector3(offset, FootballLayout.BallRadius, z));
                Physics.Simulate(0.01f);
            }
            for (int i = 0; i < 150; i++) Physics.Simulate(0.01f);
        }

        float LowestPoint()
        {
            float lowest = float.MaxValue;
            foreach (var c in cone.GetComponentsInChildren<MeshCollider>()) lowest = Mathf.Min(lowest, c.bounds.min.y);
            return lowest;
        }

        [Test]
        public void ABallHittingTheConeHeadOnPushesItAway()
        {
            BallPasses(0f, 1.7f);
            Assert.Greater(cone.transform.position.z - coneStart.z, 0.5f, "мяч толкает конус вперёд, а не проезжает сквозь него");
        }

        [Test]
        public void ABallPassingBesideTheConeDoesNotTouchIt()
        {
            BallPasses(0.26f, 1.7f);
            Assert.AreEqual(0f, (cone.transform.position - coneStart).magnitude, 0.03f);
            Assert.Less(body.TiltDegrees, 3f);
        }

        [Test]
        public void WhateverTheHitTheConeEndsOnTheGroundNotInItNorAboveIt()
        {
            foreach (float offset in new[] { 0f, 0.08f, 0.16f, 0.2f })
            {
                foreach (float speed in new[] { 1.0f, 1.7f, 3.0f })
                {
                    body.ResetPose();
                    Physics.SyncTransforms();
                    BallPasses(offset, speed);
                    Assert.AreEqual(0f, LowestPoint(), 0.03f, "конус лежит или стоит на земле (смещение " + offset + ", скорость " + speed + ")");
                }
            }
        }

        [Test]
        public void ASideHitCanKnockTheConeOverAndItStaysDown()
        {
            bool fell = false;
            foreach (float offset in new[] { 0.12f, 0.16f, 0.2f })
            {
                body.ResetPose();
                Physics.SyncTransforms();
                BallPasses(offset, 1.7f);
                if (body.TiltDegrees > 80f) fell = true;
            }
            Assert.IsTrue(fell, "при боковом ударе конус кувыркается и остаётся лежать");
        }

        [Test]
        public void ResetPutsTheKnockedConeBackWhereItStood()
        {
            BallPasses(0f, 3f);
            body.ResetPose();
            Assert.AreEqual(0f, (cone.transform.position - coneStart).magnitude, 1e-3f);
            Assert.AreEqual(0f, body.TiltDegrees, 0.5f);
        }
    }
}
