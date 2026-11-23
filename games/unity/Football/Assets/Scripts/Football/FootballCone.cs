using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Тренировочный конус как настоящее твёрдое тело (PhysX). Мяч (физическое тело FootballGame) толкает его при встрече,
    // дальше конус сам скользит, кренится, падает, подпрыгивает, катится и ложится. Упадёт он или только качнётся, решает физика.
    // Тело, коллайдер и материалы создаёт сборщик сцены.
    [RequireComponent(typeof(Rigidbody))]
    public sealed class FootballCone : MonoBehaviour
    {
        const float ConeMass = 0.45f;              // кг, лёгкий пластиковый конус
        // Трение и упругость подобраны опытом: цепкая трава заставляет конус то валиться, то уезжать стоймя; упругий удар мяча
        // отбрасывает конус, а не тащит его перед собой.
        public const float GrassFriction = 1.8f;
        public const float ConeBounciness = 0.5f;
        public const float GroundBounciness = 0.1f;
        public const float BallBounciness = 0.6f;
        public const float BounceThreshold = 0.2f;  // м/с: упругость работает и при медленных столкновениях (по умолчанию в Unity — от 2 м/с)

        Rigidbody body;
        Vector3 startPosition;
        Quaternion startRotation;

        public float TiltDegrees { get { return Vector3.Angle(transform.up, Vector3.up); } }

        bool prepared;

        void Awake()
        {
            Prepare();
        }

        // Запоминает исходное место конуса; вызывается и из Awake, и лениво (в режиме редактора Awake сам не вызывается).
        void Prepare()
        {
            if (prepared) return;
            prepared = true;
            body = GetComponent<Rigidbody>();
            startPosition = transform.position;
            startRotation = transform.rotation;
        }

        // Материал физики с общими для конусов, земли и мяча настройками трения (берётся наибольшее трение пары).
        public static PhysicsMaterial MakeMaterial(string name, float friction, float bounciness)
        {
            return Configure(new PhysicsMaterial(name), friction, bounciness);
        }

        public static PhysicsMaterial Configure(PhysicsMaterial m, float friction, float bounciness)
        {
            m.dynamicFriction = friction;
            m.staticFriction = friction;
            m.bounciness = bounciness;
            m.frictionCombine = PhysicsMaterialCombine.Maximum;
            m.bounceCombine = PhysicsMaterialCombine.Maximum;
            return m;
        }

        // Делает из модели конуса твёрдое тело: масса, выпуклый коллайдер по меши, трение травы. Вызывает сборщик сцены и тест.
        public static FootballCone Attach(GameObject root, PhysicsMaterial material)
        {
            var body = root.AddComponent<Rigidbody>();
            body.mass = ConeMass;
            body.linearDamping = 0.05f;
            body.angularDamping = 0.25f;
            body.interpolation = RigidbodyInterpolation.Interpolate;
            body.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            foreach (var filter in root.GetComponentsInChildren<MeshFilter>())
            {
                var collider = filter.gameObject.AddComponent<MeshCollider>();
                collider.sharedMesh = filter.sharedMesh;
                collider.convex = true;
                collider.sharedMaterial = material;
            }
            var cone = root.AddComponent<FootballCone>();
            cone.Prepare();                                      // исходное место запоминается сразу, до любых толчков
            return cone;
        }

        // Поставить конус на исходное место (новый заход на змейку).
        public void ResetPose()
        {
            Prepare();
            body.linearVelocity = Vector3.zero;
            body.angularVelocity = Vector3.zero;
            body.position = startPosition;
            body.rotation = startRotation;
            transform.SetPositionAndRotation(startPosition, startRotation);
            body.Sleep();
        }
    }
}
