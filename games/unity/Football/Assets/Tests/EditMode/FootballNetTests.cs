using System.Reflection;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballNetTests
    {
        GameObject goal;
        MeshFilter filter;
        FootballNet net;

        [SetUp]
        public void SetUp()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Art/Football/GoalNet.fbx");
            Assert.IsNotNull(prefab, "нет модели сетки");
            goal = (GameObject)Object.Instantiate(prefab);
            goal.transform.SetPositionAndRotation(FootballLayout.GoalMouth, Quaternion.Euler(0f, -90f, 0f));
            filter = goal.GetComponentInChildren<MeshFilter>();
            net = filter.gameObject.AddComponent<FootballNet>();
            Call("Awake");                                   // в режиме редактора Unity сам Awake не вызывает
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(goal);
        }

        void Call(string method)
        {
            typeof(FootballNet).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(net, null);
        }

        [Test]
        public void PressedNetBulgesOutwardNearTheBallAndStaysPinnedAtTheFrame()
        {
            var mesh = filter.sharedMesh;
            var before = mesh.vertices;
            // середина задней стенки: берём вершину, ближайшую к центру задней части ворот
            Vector3 centreWorld = FootballLayout.GoalMouth + Vector3.right * 0.8f + Vector3.up * 0.55f;
            net.Press(1, centreWorld, 0.2f, Vector3.right);
            Call("LateUpdate");
            var after = mesh.vertices;
            float biggest = 0f;
            for (int i = 0; i < before.Length; i++) biggest = Mathf.Max(biggest, (after[i] - before[i]).magnitude);
            Assert.That(biggest, Is.InRange(0.1f, 0.21f), "в месте касания сетка уходит почти на глубину нажатия");
            // вершины на краях сетки (пристёгнуты к раме) не двигаются
            var freedom = FootballNet.ComputeFreedom(mesh.triangles, before.Length);
            for (int i = 0; i < before.Length; i++)
                if (freedom[i] < 1e-4f) Assert.AreEqual(0f, (after[i] - before[i]).magnitude, 1e-5f, "край сетки закреплён");
        }

        [Test]
        public void AFreeBottomEdgeLetsTheNetMoveNearTheGround()
        {
            // сетка 3 × 3 вершины, y растёт вверх; нижняя строка — y = 0
            var positions = new[] { new Vector3(0, 0, 0), new Vector3(1, 0, 0), new Vector3(2, 0, 0), new Vector3(0, 1, 0), new Vector3(1, 1, 0), new Vector3(2, 1, 0), new Vector3(0, 2, 0), new Vector3(1, 2, 0), new Vector3(2, 2, 0) };
            var triangles = new[] { 0, 1, 4, 0, 4, 3, 1, 2, 5, 1, 5, 4, 3, 4, 7, 3, 7, 6, 4, 5, 8, 4, 8, 7 };
            var pinned = FootballNet.ComputeFreedom(triangles, positions, false);
            var freeBottom = FootballNet.ComputeFreedom(triangles, positions, true);
            Assert.AreEqual(0f, pinned[1], 1e-5f, "обычная сетка: нижний край пристёгнут");
            Assert.Greater(freeBottom[1], pinned[1], "занавес: нижний край свободен");
            Assert.AreEqual(0f, freeBottom[7], 1e-5f, "верхний край по-прежнему закреплён");
        }

        [Test]
        public void MoreHopsFromTheEdgeMeansMoreFreedom()
        {
            // две клетки: прямоугольник 3 × 3 вершины, центр дальше всего от края
            var triangles = new[] { 0, 1, 4, 0, 4, 3, 1, 2, 5, 1, 5, 4, 3, 4, 7, 3, 7, 6, 4, 5, 8, 4, 8, 7 };
            var freedom = FootballNet.ComputeFreedom(triangles, 9);
            Assert.AreEqual(0f, freedom[0], 1e-5f);
            Assert.AreEqual(0f, freedom[8], 1e-5f);
            Assert.Greater(freedom[4], freedom[1] - 1e-5f, "центр свободнее края");
        }
    }
}
