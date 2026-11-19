using UnityEngine;

namespace Neurotlon.Games.Pong
{
    // Камеры и экраны.
    //   Экран игроков: делится пополам, у каждого игрока вид от первого лица из-за своего края стола
    //   (слева красный, справа синий). Там же инструкции калибровки и отсчёт.
    //   Экран зрителей: вид со стороны стола, табло на стене.
    // Два экрана (монитор + телевизор): игроки на основном (1), зрители на втором (2);
    // `--audience-display 1|2` меняет номер экрана зрителей. `--view audience|players|all` на одном экране. Один экран: показаны игроки; клавиша F2 листает
    // виды (игроки / зрители / все сразу), F3 включает «все сразу». `--all-views` запускает сразу в этом режиме.
    public sealed class PongDisplays : MonoBehaviour
    {
        enum Mode { Players, Audience, All }

        [SerializeField] Camera leftPlayerCamera;
        [SerializeField] Camera rightPlayerCamera;
        [SerializeField] Camera audienceCamera;

        Mode mode = Mode.Players;
        bool twoDisplays;

        // Виден ли на этом окне экран игроков: если нет (только зрители), подсказки игроков рисовать не нужно.
        public bool ShowsPlayers { get { return twoDisplays || mode != Mode.Audience; } }

        // Где на окне (в координатах IMGUI, начало вверху слева) находится экран игроков: для счёта и подсказок.
        public Rect PlayerViewArea
        {
            get
            {
                if (mode == Mode.All) return new Rect(0f, Screen.height * 0.5f, Screen.width, Screen.height * 0.5f);
                return new Rect(0f, 0f, Screen.width, Screen.height);
            }
        }

        void Awake()
        {
            // В редакторе два экрана — это два окна Game (Display 1 и Display 2), второго монитора для этого не нужно.
            twoDisplays = (Display.displays.Length > 1 || Application.isEditor) && !HasArg("--all-views") && !HasArg("--split-view") && ReadArg("--view") == null;
            if (twoDisplays)
            {
                if (!Application.isEditor) Display.displays[1].Activate();
                int playersDisplay = ReadAudienceDisplay() == 2 ? 0 : 1;
                SetViewport(leftPlayerCamera, playersDisplay, new Rect(0f, 0f, 0.5f, 1f), true);
                SetViewport(rightPlayerCamera, playersDisplay, new Rect(0.5f, 0f, 0.5f, 1f), true);
                SetViewport(audienceCamera, 1 - playersDisplay, new Rect(0f, 0f, 1f, 1f), true);
                return;
            }
            mode = (HasArg("--all-views") || HasArg("--split-view")) ? Mode.All : Mode.Players;
            string view = ReadArg("--view");
            if (view == "audience") mode = Mode.Audience;
            else if (view == "players") mode = Mode.Players;
            else if (view == "all") mode = Mode.All;
            Apply();
        }

        void Update()
        {
            if (twoDisplays) return;
            if (Input.GetKeyDown(KeyCode.F3))
            {
                mode = mode == Mode.All ? Mode.Players : Mode.All;
                Apply();
            }
            else if (Input.GetKeyDown(KeyCode.F2))
            {
                mode = (Mode)(((int)mode + 1) % 3);
                Apply();
            }
        }

        // Один экран: игроки, зрители или все три вида в одном окне (зрители сверху, игроки снизу пополам).
        void Apply()
        {
            switch (mode)
            {
                case Mode.Players:
                    SetViewport(leftPlayerCamera, 0, new Rect(0f, 0f, 0.5f, 1f), true);
                    SetViewport(rightPlayerCamera, 0, new Rect(0.5f, 0f, 0.5f, 1f), true);
                    SetViewport(audienceCamera, 0, new Rect(0f, 0f, 1f, 1f), false);
                    break;
                case Mode.Audience:
                    SetViewport(leftPlayerCamera, 0, new Rect(0f, 0f, 0.5f, 1f), false);
                    SetViewport(rightPlayerCamera, 0, new Rect(0.5f, 0f, 0.5f, 1f), false);
                    SetViewport(audienceCamera, 0, new Rect(0f, 0f, 1f, 1f), true);
                    break;
                default:
                    SetViewport(leftPlayerCamera, 0, new Rect(0f, 0f, 0.5f, 0.5f), true);
                    SetViewport(rightPlayerCamera, 0, new Rect(0.5f, 0f, 0.5f, 0.5f), true);
                    SetViewport(audienceCamera, 0, new Rect(0f, 0.5f, 1f, 0.5f), true);
                    break;
            }
        }

        static void SetViewport(Camera camera, int display, Rect rect, bool enabled)
        {
            if (camera == null) return;
            camera.targetDisplay = display;
            camera.rect = rect;
            camera.enabled = enabled;
        }

        static int ReadAudienceDisplay()
        {
            string[] args = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "--audience-display") return args[i + 1] == "1" ? 1 : 2;
            }
            return 2;
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

        static bool HasArg(string name)
        {
            foreach (string arg in System.Environment.GetCommandLineArgs())
            {
                if (arg == name) return true;
            }
            return false;
        }
    }
}
