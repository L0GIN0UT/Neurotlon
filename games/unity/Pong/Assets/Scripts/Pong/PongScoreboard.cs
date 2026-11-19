using UnityEngine;
using UnityEngine.UI;

namespace Neurotlon.Games.Pong
{
    // Табло со счётом на стене арены. Собирается из UI в мировых координатах при старте:
    // имена игроков, счёт, время, подпись про золотой мяч. Шрифт встроенный (Liberation Sans, есть кириллица).
    public sealed class PongScoreboard : MonoBehaviour
    {
        static readonly Color PanelColor = new Color(0.03f, 0.05f, 0.10f, 1f);
        static readonly Color Cyan = new Color(0.30f, 0.90f, 1.0f);
        static readonly Color RedTeam = new Color(0.85f, 0.10f, 0.10f);
        static readonly Color BlueTeam = new Color(0.12f, 0.38f, 0.90f);

        // При масштабе 0,01: 10,4 x 2,2 м. Меньше рамки на стене (11 x 2,4 м), чтобы рамка обрамляла табло.
        [SerializeField] Vector2 sizePixels = new Vector2(1040f, 220f);

        Text leftName, rightName, leftScore, rightScore, caption, hint;
        Font font;

        void Awake()
        {
            font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            var rect = (RectTransform)transform;
            Vector3 position = rect.position;      // Canvas при создании может сбросить положение
            Quaternion rotation = rect.rotation;
            var canvas = gameObject.GetComponent<Canvas>();
            if (canvas == null) canvas = gameObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            rect.sizeDelta = sizePixels;
            rect.localScale = Vector3.one * 0.01f;
            rect.position = position;
            rect.rotation = rotation;
            Build(rect);
        }

        public void Show(string left, string right, int scoreLeft, int scoreRight, string captionText, string hintText)
        {
            leftName.text = left;
            rightName.text = right;
            leftScore.text = scoreLeft.ToString();
            rightScore.text = scoreRight.ToString();
            caption.text = captionText;
            hint.text = hintText;
        }

        void Build(RectTransform root)
        {
            Panel(root, "Фон", 0f, 0f, 1f, 1f, PanelColor);
            // цвет команды: широкая полоса у края и узкая линия под именем
            Panel(root, "ПолосаСлева", 0f, 0f, 0.025f, 1f, RedTeam);
            Panel(root, "ПолосаСправа", 0.975f, 0f, 1f, 1f, BlueTeam);
            Panel(root, "ЛинияСлева", 0.05f, 0.67f, 0.36f, 0.685f, RedTeam);
            Panel(root, "ЛинияСправа", 0.64f, 0.67f, 0.95f, 0.685f, BlueTeam);
            // игроки: имя сверху, счёт крупно под ним
            leftName = Label(root, "ИмяСлева", 0.05f, 0.70f, 0.36f, 0.97f, 56, TextAnchor.MiddleLeft, Color.white, FontStyle.Bold);
            rightName = Label(root, "ИмяСправа", 0.64f, 0.70f, 0.95f, 0.97f, 56, TextAnchor.MiddleRight, Color.white, FontStyle.Bold);
            // цифры счёта поменьше и с воздухом вокруг, чтобы не сливались с именем и линией под ним
            leftScore = Label(root, "СчётСлева", 0.08f, 0.08f, 0.33f, 0.60f, 120, TextAnchor.MiddleCenter, Color.white, FontStyle.Bold);
            rightScore = Label(root, "СчётСправа", 0.67f, 0.08f, 0.92f, 0.60f, 120, TextAnchor.MiddleCenter, Color.white, FontStyle.Bold);
            // центр: режим игры («ДО 11», «ЗОЛОТОЙ МЯЧ»…) и подсказка (чья подача)
            caption = Label(root, "Надпись", 0.37f, 0.42f, 0.63f, 0.97f, 72, TextAnchor.MiddleCenter, Cyan, FontStyle.Bold);
            hint = Label(root, "Подсказка", 0.37f, 0.05f, 0.63f, 0.42f, 40, TextAnchor.MiddleCenter, new Color(0.72f, 0.78f, 0.88f), FontStyle.Normal);
        }

        static Image Panel(RectTransform parent, string name, float x0, float y0, float x1, float y1, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.layer = parent.gameObject.layer;
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            rt.anchorMin = new Vector2(x0, y0);
            rt.anchorMax = new Vector2(x1, y1);
            rt.offsetMin = Vector2.zero;
            rt.offsetMax = Vector2.zero;
            var image = go.GetComponent<Image>();
            image.color = color;
            image.raycastTarget = false;
            return image;
        }

        Text Label(RectTransform parent, string name, float x0, float y0, float x1, float y1, int size,
            TextAnchor anchor, Color color, FontStyle style)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Text));
            go.layer = parent.gameObject.layer;
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            rt.anchorMin = new Vector2(x0, y0);
            rt.anchorMax = new Vector2(x1, y1);
            rt.offsetMin = Vector2.zero;
            rt.offsetMax = Vector2.zero;
            var text = go.GetComponent<Text>();
            text.font = font;
            text.fontSize = size;
            text.fontStyle = style;
            text.alignment = anchor;
            text.color = color;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.resizeTextForBestFit = true;
            text.resizeTextMinSize = 12;
            text.resizeTextMaxSize = size;
            text.raycastTarget = false;
            return text;
        }
    }
}
