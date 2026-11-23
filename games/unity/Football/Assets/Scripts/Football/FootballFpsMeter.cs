using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Замер производительности: параметр запуска --fps снимает ограничение кадров и пишет в журнал средний и худший FPS.
    // Отдельный компонент, чтобы не перекрывать Update() базового класса NeurotlonGame (он опрашивает мост).
    public sealed class FootballFpsMeter : MonoBehaviour
    {
        float timer;
        int frames;
        float worst = float.MaxValue;

        void Awake()
        {
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;
        }

        void Update()
        {
            float dt = Time.unscaledDeltaTime;
            if (dt <= 0f) return;
            frames++;
            timer += dt;
            worst = Mathf.Min(worst, 1f / dt);
            if (timer >= 5f)
            {
                Debug.Log("Нейротлон FPS: среднее " + (frames / timer).ToString("F0") + ", худший кадр " + worst.ToString("F0"));
                timer = 0f;
                frames = 0;
                worst = float.MaxValue;
            }
        }
    }
}
