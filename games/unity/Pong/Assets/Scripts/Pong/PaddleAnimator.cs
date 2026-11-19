using UnityEngine;

namespace Neurotlon.Games.Pong
{
    // Для какой камеры ракетка: у зрителей и у игрока (вид от первого лица) своя копия со своей позой и анимацией.
    public enum PaddleView { Audience, FirstPerson }

    // Движение ракетки. Положение по столу задаёт игра по сигналу ЭМГ; всё остальное от сигнала не зависит.
    //   Стойка: ракетка лицом к сопернику (чуть к залу), лопасть наклонена вперёд над столом; лёгкое покачивание.
    //   Подготовка: мяч приближается — ракетка отводится в замах в ту сторону, куда прилетит мяч.
    //   Удар (запускает отбитие): замах → контакт → выход вперёд по дуге → возврат.
    // Удар зеркален: мяч справа от игрока — форхенд (замах вправо, проход влево), слева — бэкхенд (наоборот).
    public sealed class PaddleAnimator
    {
        struct Pose
        {
            public float Pitch;      // < 0 верх ракетки вперёд (закрыта), > 0 назад (открыта)
            public float Yaw;        // > 0 поворот лица вправо (с точки зрения игрока), < 0 влево
            public float Roll;       // вращение кисти вокруг оси лица
            public float Lunge;      // вперёд по лицу, метры
            public float Lift;       // вверх, метры
            public float Side;       // вбок вправо (с точки зрения игрока), метры

            public Pose(float pitch, float yaw, float roll, float lunge, float lift, float side)
            {
                Pitch = pitch;
                Yaw = yaw;
                Roll = roll;
                Lunge = lunge;
                Lift = lift;
                Side = side;
            }

            public static Pose Lerp(Pose a, Pose b, float t)
            {
                return new Pose(
                    Mathf.Lerp(a.Pitch, b.Pitch, t), Mathf.Lerp(a.Yaw, b.Yaw, t), Mathf.Lerp(a.Roll, b.Roll, t),
                    Mathf.Lerp(a.Lunge, b.Lunge, t), Mathf.Lerp(a.Lift, b.Lift, t), Mathf.Lerp(a.Side, b.Side, t));
            }
        }

        // Набор поз и базовый угол для одного вида. Позы для форхенда; для бэкхенда Yaw, Roll и Side зеркалятся.
        sealed class Profile
        {
            public float FacingYaw;     // базовый поворот: ±90° — лицо ракетки/лопасть строго на соперника
            public float BaseRoll;      // поворот ракетки в её плоскости (ручка в сторону), одинаков для форхенда и бэкхенда
            public Pose Ready, WindUp, Contact, FollowThrough;
        }

        // Ракетка стоит почти вертикально, лопасть наклонена вперёд над столом, ручка назад к игроку;
        // удар виден как наклон и проход дугой. Модель повёрнута так, что лицо смотрит на соперника при ±90°;
        // чуть меньше, чтобы зал видел лицо ракетки.
        static readonly Profile ShotProfile = new Profile
        {
            FacingYaw = 76f,
            Ready = new Pose(-28f, 0f, 0f, 0f, 0f, 0f),
            WindUp = new Pose(-6f, 32f, 16f, -0.06f, -0.03f, 0.07f),
            Contact = new Pose(-42f, -6f, -14f, 0.12f, 0.02f, -0.02f),
            FollowThrough = new Pose(-78f, -44f, -30f, 0.15f, 0.08f, -0.08f),   // выход вперёд меньше 3 см после контакта: ракетка не догоняет мяч
        };

        // Первое лицо (камера сзади и выше, смотрит вдоль стола). Как в играх с таким видом: ракетка стоит вертикально
        // лицом на соперника, мы видим её сзади, а в своей плоскости она повёрнута так, что ручка смотрит влево
        // (для обоих игроков — влево с их точки зрения) и немного вниз, лопасть вправо-вверх.
        // Замах: ракетка чуть отходит к себе и приподнимается. Удар: проход вперёд к столу с наклоном лопасти вперёд.
        static readonly Profile FirstPersonProfile = new Profile
        {
            FacingYaw = 90f,
            BaseRoll = 68f,
            Ready = new Pose(-10f, 0f, 0f, 0f, 0f, 0f),
            WindUp = new Pose(8f, 24f, 12f, -0.10f, 0.04f, 0.10f),
            Contact = new Pose(-28f, -4f, -10f, 0.12f, 0.02f, -0.03f),
            FollowThrough = new Pose(-48f, -26f, -20f, 0.18f, 0.04f, -0.12f),   // после контакта вперёд ещё 6 см и медленнее мяча
        };

        // Доли длительности удара: до ContactFraction ракетка доходит до контакта с мячом (игра запускает этот ход заранее,
        // чтобы контакт пришёлся ровно на отбитие), дальше выход вперёд и возврат.
        public const float ContactFraction = 0.12f;
        const float FollowThroughEnd = 0.40f;   // контакт → выход вперёд; дальше возврат в стойку
        const float LateralSmoothSeconds = 0.08f;

        readonly Side side;
        readonly Profile profile;
        readonly float phase;
        bool striking;
        float strikeFrom;
        float strikeMirror;
        float lateral;
        float lateralVelocity;

        public PaddleAnimator(Side side, PaddleView view)
        {
            this.side = side;
            profile = view == PaddleView.FirstPerson ? FirstPersonProfile : ShotProfile;
            phase = side == Side.Left ? 0f : 1.7f;      // стороны покачиваются не синхронно
        }

        // position — куда поставить ракетку; anticipation01 — насколько она отведена в замах (мяч приближается);
        // ballLateral — где прилетит мяч относительно игрока: +1 справа (форхенд), -1 слева (бэкхенд);
        // swing01 — ход удара от 0 до 1 (0 — не бьёт); time — игровое время; dt — шаг (0: без сглаживания).
        public void Apply(Transform paddle, Vector3 position, float anticipation01, float ballLateral, float swing01, float time, float dt)
        {
            float anticipation = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(anticipation01));
            Pose pose;
            float mirror;
            if (swing01 > 0f && swing01 < 1f)
            {
                if (!striking)
                {
                    striking = true;
                    strikeFrom = anticipation;                  // удар начинается с позы, в которой ракетка была к контакту
                    strikeMirror = MirrorFor(lateral);
                }
                mirror = strikeMirror;
                pose = Strike(swing01, Pose.Lerp(profile.Ready, profile.WindUp, strikeFrom));
            }
            else
            {
                striking = false;
                lateral = dt > 0f ? Mathf.SmoothDamp(lateral, Mathf.Clamp(ballLateral, -1f, 1f), ref lateralVelocity, LateralSmoothSeconds, 20f, dt)
                                  : Mathf.Clamp(ballLateral, -1f, 1f);
                mirror = MirrorFor(lateral);
                pose = Pose.Lerp(profile.Ready, profile.WindUp, anticipation);
                float calm = 1f - anticipation;                 // покачивание затихает, когда мяч рядом
                pose.Pitch += 2.5f * Mathf.Sin(time * 2.0f + phase) * calm;
                pose.Yaw += 3f * Mathf.Sin(time * 1.3f + phase) * calm;
                pose.Roll += 3f * Mathf.Sin(time * 1.7f + phase * 0.5f) * calm;
                pose.Lift += 0.008f * Mathf.Sin(time * 2.4f + phase) * calm;
            }
            // «вправо» для игрока слева — это -Z, для игрока справа — +Z; модель повёрнута так, что лицо смотрит
            // на соперника при углах -90° (слева) и +90° (справа)
            float rightZ = side == Side.Left ? -1f : 1f;
            float baseYaw = side == Side.Left ? -profile.FacingYaw : profile.FacingYaw;
            float yaw = baseYaw + mirror * pose.Yaw;
            float roll = profile.BaseRoll + (side == Side.Left ? 1f : -1f) * mirror * pose.Roll;
            float yawRad = yaw * Mathf.Deg2Rad;
            Vector3 forward = new Vector3(-Mathf.Sin(yawRad), 0f, -Mathf.Cos(yawRad));   // куда смотрит лицо ракетки
            Vector3 offset = forward * pose.Lunge + Vector3.up * pose.Lift + new Vector3(0f, 0f, rightZ * mirror * pose.Side);
            Quaternion rotation = Quaternion.Euler(0f, yaw, 0f) * Quaternion.Euler(pose.Pitch, 0f, roll);
            paddle.SetPositionAndRotation(position + offset, rotation);
        }

        // Зеркало удара: знак — форхенд/бэкхенд, величина — насколько мяч сбоку (по центру остаётся мягкий нейтральный блок).
        static float MirrorFor(float lat)
        {
            float magnitude = 0.4f + 0.6f * Mathf.Abs(lat);
            return Mathf.Abs(lat) < 0.05f ? 0.4f * magnitude : Mathf.Sign(lat) * magnitude;
        }

        Pose Strike(float t, Pose start)
        {
            if (t < ContactFraction)
            {
                float u = t / ContactFraction;
                return Pose.Lerp(start, profile.Contact, 1f - (1f - u) * (1f - u));            // резкий разгон к контакту
            }
            if (t < FollowThroughEnd)
            {
                float u = (t - ContactFraction) / (FollowThroughEnd - ContactFraction);
                return Pose.Lerp(profile.Contact, profile.FollowThrough, 1f - (1f - u) * (1f - u));    // выход вперёд, гасится к концу
            }
            float v = Mathf.SmoothStep(0f, 1f, (t - FollowThroughEnd) / (1f - FollowThroughEnd));
            return Pose.Lerp(profile.FollowThrough, profile.Ready, v);                                 // плавный возврат
        }
    }
}
