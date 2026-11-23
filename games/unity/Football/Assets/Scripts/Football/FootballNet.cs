using System.Collections.Generic;
using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Сетка ворот: мяч, влетевший внутрь, давит на заднюю стенку, боковины или крышу; сетка прогибается в месте касания
    // наружу, пружинит и колеблется, затухая. Края (где сетка пристёгнута к раме) неподвижны: чем дальше от края, тем она
    // свободнее. Мяч на сетку действует игра (пружина), здесь только вид.
    public sealed class FootballNet : MonoBehaviour
    {
        const float Sigma = 0.30f;                 // ширина вмятины, м
        const float RingDownRate = 4.5f;           // 1/с: затухание колебаний
        const float RingDownFrequency = 15f;       // рад/с
        const float RingDownSeconds = 1.6f;
        const int PinHops = 6;                     // на скольких шагах сетки от края она набирает полную подвижность

        [SerializeField] MeshFilter filter;
        [SerializeField] bool bottomEdgeFree;      // нижний край не пристёгнут (занавес с грузом): мяч у земли прогибает его свободно

        Mesh mesh;
        Vector3[] baseVertices;
        Vector3[] vertices;
        float[] free;                              // 0 — край (пристёгнут), 1 — полностью подвижна
        bool dirty;
        readonly Dictionary<int, Contact> contacts = new Dictionary<int, Contact>();
        readonly List<int> finished = new List<int>();
        readonly List<Contact> active = new List<Contact>();

        sealed class Contact
        {
            public Vector3 at;                     // точка касания, локально
            public Vector3 direction;              // куда прогибается сетка (наружу), локально
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
            mesh.name = "СеткаПрогиб";
            filter.sharedMesh = mesh;
            baseVertices = mesh.vertices;
            vertices = new Vector3[baseVertices.Length];
            free = ComputeFreedom(mesh.triangles, baseVertices, bottomEdgeFree);
        }

        public static float[] ComputeFreedom(int[] triangles, int vertexCount)
        {
            return ComputeFreedom(triangles, new Vector3[vertexCount], false);
        }

        // Подвижность вершин по числу шагов сетки до ближайшего пристёгнутого края (края — рёбра, которые есть только в одном треугольнике).
        // Если bottomEdgeFree, нижний край (вершины на высоте самой низкой точки) не считается пристёгнутым.
        public static float[] ComputeFreedom(int[] triangles, Vector3[] positions, bool bottomEdgeFree)
        {
            int vertexCount = positions.Length;
            float lowest = float.MaxValue;
            foreach (var v in positions) lowest = Mathf.Min(lowest, v.y);

            var neighbours = new List<int>[vertexCount];
            for (int i = 0; i < vertexCount; i++) neighbours[i] = new List<int>();
            var edgeUse = new Dictionary<long, int>();
            for (int t = 0; t < triangles.Length; t += 3)
            {
                for (int e = 0; e < 3; e++)
                {
                    int a = triangles[t + e], b = triangles[t + (e + 1) % 3];
                    if (!neighbours[a].Contains(b)) neighbours[a].Add(b);
                    if (!neighbours[b].Contains(a)) neighbours[b].Add(a);
                    long key = a < b ? ((long)a << 32) | (uint)b : ((long)b << 32) | (uint)a;
                    int uses;
                    edgeUse.TryGetValue(key, out uses);
                    edgeUse[key] = uses + 1;
                }
            }
            var hops = new int[vertexCount];
            for (int i = 0; i < vertexCount; i++) hops[i] = int.MaxValue;
            var queue = new Queue<int>();
            foreach (var pair in edgeUse)
            {
                if (pair.Value != 1) continue;
                int a = (int)(pair.Key >> 32), b = (int)(pair.Key & 0xffffffff);
                if (bottomEdgeFree && positions[a].y < lowest + 0.02f && positions[b].y < lowest + 0.02f) continue;     // ребро нижнего края свободно
                if (hops[a] != 0) { hops[a] = 0; queue.Enqueue(a); }
                if (hops[b] != 0) { hops[b] = 0; queue.Enqueue(b); }
            }
            while (queue.Count > 0)
            {
                int v = queue.Dequeue();
                foreach (int n in neighbours[v])
                {
                    if (hops[n] <= hops[v] + 1) continue;
                    hops[n] = hops[v] + 1;
                    queue.Enqueue(n);
                }
            }
            var result = new float[vertexCount];
            for (int i = 0; i < vertexCount; i++)
            {
                float k = hops[i] == int.MaxValue ? 1f : Mathf.Clamp01(hops[i] / (float)PinHops);
                result[i] = k * k * (3f - 2f * k);
            }
            return result;
        }

        // Мяч давит на сетку в точке world на глубину depth, м, прогиб — в сторону outward (мировой вектор). Вызывается каждый кадр касания.
        public void Press(int id, Vector3 world, float depth, Vector3 outward)
        {
            if (mesh == null) return;
            Contact c;
            if (!contacts.TryGetValue(id, out c)) { c = new Contact(); contacts[id] = c; }
            c.at = transform.InverseTransformPoint(world);
            c.direction = transform.InverseTransformDirection(outward).normalized;
            c.depth = depth;
            c.released = false;
        }

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
            active.Clear();
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
                active.Add(new Contact { at = c.at, direction = c.direction, depth = d });
            }
            float twoSigmaSq = 2f * Sigma * Sigma;
            for (int i = 0; i < baseVertices.Length; i++)
            {
                Vector3 b = baseVertices[i];
                Vector3 offset = Vector3.zero;
                for (int k = 0; k < active.Count; k++)
                {
                    float weight = Mathf.Exp(-(b - active[k].at).sqrMagnitude / twoSigmaSq);
                    offset += active[k].direction * (active[k].depth * weight);
                }
                vertices[i] = b + offset * free[i];
            }
            mesh.vertices = vertices;
            mesh.RecalculateNormals();
            dirty = true;
            foreach (int id in finished) contacts.Remove(id);
        }
    }
}
