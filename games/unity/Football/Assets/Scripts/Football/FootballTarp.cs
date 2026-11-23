using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Мягкий чехол ворот: пока мяч давит на ткань, она прогибается в месте касания, потом колеблется и затухает.
    // Сетка чехла подробная (GoalTarp.fbx), поэтому прогиб плавный. Мяч на ткань действует игра (пружина), здесь только вид.
    public sealed class FootballTarp : MonoBehaviour
    {
        const float Sigma = 0.26f;                 // ширина вмятины, м
        const float RingDownRate = 5.5f;           // 1/с: как быстро затухают колебания
        const float RingDownFrequency = 19f;       // рад/с
        const float RingDownSeconds = 1.4f;
        const float EdgePin = 0.28f;               // у края ткань закреплена на раме: прогиб гасится на этой ширине

        [SerializeField] MeshFilter filter;

        Mesh mesh;
        Vector3[] baseVertices;
        Vector3[] vertices;
        Vector2 min, max;
        float inward = -1f;                        // знак оси Z меши «внутрь ворот»
        bool dirty;
        readonly Dictionary<int, Contact> contacts = new Dictionary<int, Contact>();
        readonly List<int> finished = new List<int>();
        readonly List<KeyValuePair<Vector2, float>> depths = new List<KeyValuePair<Vector2, float>>();

        sealed class Contact
        {
            public Vector2 at;
            public float depth;
            public bool released;
            public float releasedAt;
            public float releasedDepth;
        }

        void Awake()
        {
            if (filter == null) filter = GetComponent<MeshFilter>();
            if (filter == null || filter.sharedMesh == null) return;
            mesh = Instantiate(filter.sharedMesh);
            mesh.name = "ЧехолПрогиб";
            filter.sharedMesh = mesh;
            baseVertices = mesh.vertices;
            vertices = new Vector3[baseVertices.Length];
            min = new Vector2(float.MaxValue, float.MaxValue);
            max = new Vector2(float.MinValue, float.MinValue);
            foreach (var v in baseVertices)
            {
                min = Vector2.Min(min, v);
                max = Vector2.Max(max, v);
            }
            // внутрь ворот — по направлению от игрока: оси +X мира (проём смотрит в −X)
            inward = Mathf.Sign(transform.InverseTransformDirection(Vector3.right).z);
            if (inward == 0f) inward = -1f;
        }

        // Мяч давит на чехол в точке world на глубину depth, м. Вызывается каждый кадр, пока есть касание.
        public void Press(int id, Vector3 world, float depth)
        {
            if (mesh == null) return;
            Vector3 local = transform.InverseTransformPoint(world);
            Contact c;
            if (!contacts.TryGetValue(id, out c)) { c = new Contact(); contacts[id] = c; }
            c.at = new Vector2(local.x, local.y);
            c.depth = depth;
            c.released = false;
        }

        // Мяч оторвался от ткани: дальше она колеблется сама.
        public void Release(int id)
        {
            Contact c;
            if (!contacts.TryGetValue(id, out c) || c.released) return;
            c.released = true;
            c.releasedAt = Time.time;
            c.releasedDepth = c.depth;
        }

        void LateUpdate()
        {
            if (mesh == null) return;
            if (contacts.Count == 0)
            {
                if (dirty) { mesh.vertices = baseVertices; mesh.RecalculateNormals(); dirty = false; }
                return;
            }
            finished.Clear();
            float twoSigmaSq = 2f * Sigma * Sigma;
            depths.Clear();
            foreach (var pair in contacts)
            {
                var c = pair.Value;
                float d = c.depth;
                if (c.released)
                {
                    float t = Time.time - c.releasedAt;
                    d = c.releasedDepth * Mathf.Exp(-RingDownRate * t) * Mathf.Cos(RingDownFrequency * t);
                    if (t > RingDownSeconds) finished.Add(pair.Key);
                }
                depths.Add(new KeyValuePair<Vector2, float>(c.at, d));
            }
            for (int i = 0; i < baseVertices.Length; i++)
            {
                Vector3 b = baseVertices[i];
                float push = 0f;
                for (int k = 0; k < depths.Count; k++)
                {
                    Vector2 d2 = new Vector2(b.x, b.y) - depths[k].Key;
                    push += depths[k].Value * Mathf.Exp(-d2.sqrMagnitude / twoSigmaSq);
                }
                float edge = Mathf.Min(Mathf.Min(b.x - min.x, max.x - b.x), Mathf.Min(b.y - min.y, max.y - b.y));
                push *= Mathf.SmoothStep(0f, 1f, edge / EdgePin);
                vertices[i] = new Vector3(b.x, b.y, b.z + inward * push);
            }
            mesh.vertices = vertices;
            mesh.RecalculateNormals();
            dirty = true;
            foreach (int id in finished) contacts.Remove(id);
        }
    }
}
