using System.Reflection;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace Neurotlon.Games.Football.Tests
{
    public class FootballTarpTests
    {
        GameObject goal;
        MeshFilter filter;
        FootballTarp tarp;

        [SetUp]
        public void SetUp()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Art/Football/GoalTarp.fbx");
            Assert.IsNotNull(prefab, "нет модели чехла");
            goal = (GameObject)Object.Instantiate(prefab);
            goal.transform.SetPositionAndRotation(FootballLayout.GoalMouth, Quaternion.Euler(0f, -90f, 0f));      // как в сцене
            filter = goal.GetComponentInChildren<MeshFilter>();
            tarp = filter.gameObject.AddComponent<FootballTarp>();
            Call("Awake");                                   // в режиме редактора Unity сам Awake не вызывает
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(goal);
        }

        float[] WorldX()
        {
            var vertices = filter.sharedMesh.vertices;
            var xs = new float[vertices.Length];
            for (int i = 0; i < vertices.Length; i++) xs[i] = filter.transform.TransformPoint(vertices[i]).x;
            return xs;
        }

        void Call(string method)
        {
            typeof(FootballTarp).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(tarp, null);
        }

        void LateUpdate()
        {
            Call("LateUpdate");
        }

        [Test]
        public void PressedFabricMovesAwayFromThePlayerAndOnlyNearTheBall()
        {
            var before = WorldX();
            Vector3 centre = filter.transform.TransformPoint(filter.sharedMesh.bounds.center);
            tarp.Press(1, centre, 0.10f);
            LateUpdate();
            var pressed = WorldX();
            float biggest = 0f, smallest = 0f;
            for (int i = 0; i < before.Length; i++)
            {
                float shift = pressed[i] - before[i];               // +X — внутрь ворот, прочь от игрока
                biggest = Mathf.Max(biggest, shift);
                smallest = Mathf.Min(smallest, shift);
            }
            Assert.Greater(biggest, 0.08f, "в месте касания ткань уходит почти на всю глубину нажатия (наибольший сдвиг " + biggest + ", наименьший " + smallest + ")");
            Assert.Less(biggest, 0.105f);
            Assert.GreaterOrEqual(smallest, -1e-4f, "ткань не выпячивается в сторону игрока");
        }

        [Test]
        public void FabricIsPinnedAtTheEdgesAndRecoversWhenTheBallLeaves()
        {
            var before = WorldX();
            var bounds = filter.sharedMesh.bounds;
            Vector3 corner = filter.transform.TransformPoint(new Vector3(bounds.min.x, bounds.min.y, 0f));
            tarp.Press(1, corner, 0.10f);
            LateUpdate();
            var pressed = WorldX();
            float edgeShift = 0f;
            for (int i = 0; i < before.Length; i++) edgeShift = Mathf.Max(edgeShift, pressed[i] - before[i]);
            Assert.Less(edgeShift, 0.06f, "у края ткань закреплена на раме, прогиб гасится");
        }
    }
}
