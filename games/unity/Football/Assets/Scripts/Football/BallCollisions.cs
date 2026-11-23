using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Столкновение двух одинаковых мячей: расталкивание и упругий обмен скоростью вдоль линии центров.
    public static class BallCollisions
    {
        // true, если мячи касались друг друга и были сдвинуты/получили скорость; impactSpeed — скорость сближения в момент удара (0, если мячи расходились).
        public static bool Resolve(ref Vector3 positionA, ref Vector3 velocityA, ref Vector3 positionB, ref Vector3 velocityB, float radius, float restitution, out float impactSpeed)
        {
            impactSpeed = 0f;
            Vector3 between = positionB - positionA;
            float distance = between.magnitude;
            float minimum = radius * 2f;
            if (distance >= minimum) return false;
            Vector3 normal = distance > 1e-5f ? between / distance : Vector3.up;
            float overlap = minimum - distance;
            positionA -= normal * (overlap * 0.5f);
            positionB += normal * (overlap * 0.5f);
            float approach = Vector3.Dot(velocityA - velocityB, normal);          // > 0 — мячи сближаются
            if (approach > 0f)
            {
                impactSpeed = approach;
                float impulse = (1f + restitution) * approach * 0.5f;             // массы равны
                velocityA -= normal * impulse;
                velocityB += normal * impulse;
            }
            return true;
        }
    }
}
