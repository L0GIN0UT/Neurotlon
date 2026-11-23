using System.Collections;
using System.IO;
using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Запись видео игры изнутри, для проверок и демонстраций. Включается только параметром запуска
    //   --record <папка> [--record-seconds N] [--record-all]
    // По умолчанию запись начинается, когда идёт игра; --record-all пишет и калибровку с отсчётом.
    // Игра работает с фиксированным шагом 30 кадров/с и сохраняет каждый кадр экрана в JPG; потом кадры собираются
    // в видео (ffmpeg). Запись начинается, когда идёт игра, и не зависит от окон на рабочем столе.
    public sealed class FootballRecorder : MonoBehaviour
    {
        const int Fps = 30;
        const int Quality = 92;

        [SerializeField] FootballGame game;

        string folder;
        int framesToRecord;
        int frame;

        void Awake()
        {
            folder = ReadArg("--record");
            if (string.IsNullOrEmpty(folder))
            {
                enabled = false;
                return;
            }
            int seconds;
            if (!int.TryParse(ReadArg("--record-seconds"), out seconds) || seconds < 1) seconds = 25;
            framesToRecord = seconds * Fps;
            Directory.CreateDirectory(folder);
            Time.captureFramerate = Fps;
        }

        IEnumerator Start()
        {
            bool all = System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "--record-all") >= 0;
            while (!all && (game == null || game.CurrentStage != NeurotlonGame.Stage.Playing)) yield return null;
            while (frame < framesToRecord)
            {
                yield return new WaitForEndOfFrame();
                if (frame == 0) Debug.Log("NTFRAME0 " + Time.time.ToString("F3", System.Globalization.CultureInfo.InvariantCulture));
                var texture = ScreenCapture.CaptureScreenshotAsTexture();
                File.WriteAllBytes(Path.Combine(folder, "f" + frame.ToString("D5") + ".jpg"), texture.EncodeToJPG(Quality));
                Destroy(texture);
                frame++;
            }
            File.WriteAllText(Path.Combine(folder, "done.txt"), frame.ToString());
            Application.Quit(0);
        }

        static string ReadArg(string name)
        {
            string[] args = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name) return args[i + 1];
            }
            return null;
        }
    }
}
