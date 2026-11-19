using System.Collections.Generic;
using Neurotlon.Games.Darts;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace Neurotlon.Games.Darts.Editor
{
    // Собирает сцену дартса одной командой: Neurotlon → Build Darts Scene.
    // Модели мишени и дротика, материалы, арена (из понга), свет, камера, звуки и игровые компоненты.
    // Повторный запуск пересоздаёт сцену заново, поэтому её удобно настраивать правкой этого файла.
    public static class DartsSceneBuilder
    {
        const string ArtDir = "Assets/Art/Darts/";
        const string SceneDir = "Assets/Scenes/";

        // Положение в сцене: игрок в начале координат смотрит вдоль +Z; арена та же, что в понге.
        static readonly Vector3 EyePosition = new Vector3(0f, 1.66f, -0.25f);
        static readonly Vector3 BoardCenter = new Vector3(0f, 1.70f, 1.50f);

        [MenuItem("Neurotlon/Build Darts Scene")]
        public static void Build()
        {
            ImportTextures();
            var mats = BuildMaterials();
            ImportModels(mats);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            Transform board = BuildBoard();
            Transform held = BuildDart("HeldDart", true);
            Transform template = BuildDart("DartTemplate", false);
            Camera camera = BuildCamera();
            BuildLights();
            BuildPostProcessing();
            BuildGame(camera, board, held, template, mats);
            if (!AssetDatabase.IsValidFolder("Assets/Scenes")) AssetDatabase.CreateFolder("Assets", "Scenes");
            EditorSceneManager.SaveScene(scene, SceneDir + "Darts.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(SceneDir + "Darts.unity", true) };
            Debug.Log("Neurotlon: сцена дартса собрана: " + SceneDir + "Darts.unity");
        }

        // --- текстуры и материалы ---

        static void ImportTextures()
        {
            var sisal = (TextureImporter)AssetImporter.GetAtPath(ArtDir + "sisal.png");
            if (sisal != null)
            {
                sisal.wrapMode = TextureWrapMode.Repeat;
                sisal.mipmapEnabled = true;
                sisal.anisoLevel = 8;
                sisal.SaveAndReimport();
            }
            var wood = (TextureImporter)AssetImporter.GetAtPath(ArtDir + "wood.png");
            if (wood != null)
            {
                wood.wrapMode = TextureWrapMode.Repeat;
                wood.mipmapEnabled = true;
                wood.anisoLevel = 8;
                wood.SaveAndReimport();
            }
            var normal = (TextureImporter)AssetImporter.GetAtPath(ArtDir + "sisal_normal.png");
            if (normal != null)
            {
                normal.textureType = TextureImporterType.NormalMap;
                normal.wrapMode = TextureWrapMode.Repeat;
                normal.SaveAndReimport();
            }
        }

        struct MatDef
        {
            public Color Color;
            public float Smoothness;
            public float Metallic;
            public bool Sisal;

            public MatDef(Color color, float smoothness, float metallic, bool sisal)
            {
                Color = color;
                Smoothness = smoothness;
                Metallic = metallic;
                Sisal = sisal;
            }
        }

        // Цвета как в Blender (линейные) пересчитываются в гамму материала.
        static Color Lin(float r, float g, float b)
        {
            return new Color(Mathf.LinearToGammaSpace(r), Mathf.LinearToGammaSpace(g), Mathf.LinearToGammaSpace(b), 1f);
        }

        static Dictionary<string, Material> BuildMaterials()
        {
            var defs = new Dictionary<string, MatDef>
            {
                { "DB_Black", new MatDef(Lin(0.025f, 0.025f, 0.028f), 0.10f, 0f, true) },
                { "DB_Cream", new MatDef(Lin(0.86f, 0.78f, 0.58f), 0.10f, 0f, true) },
                { "DB_Red", new MatDef(Lin(0.70f, 0.04f, 0.05f), 0.15f, 0f, true) },
                { "DB_Green", new MatDef(Lin(0.03f, 0.40f, 0.15f), 0.15f, 0f, true) },
                { "DB_Surround", new MatDef(Lin(0.02f, 0.02f, 0.022f), 0.15f, 0f, true) },
                { "DB_Wire", new MatDef(Lin(0.72f, 0.73f, 0.76f), 0.75f, 0.9f, false) },
                { "DB_Body", new MatDef(Lin(0.16f, 0.10f, 0.05f), 0.2f, 0f, false) },
                { "DB_Number", new MatDef(Lin(0.92f, 0.92f, 0.90f), 0.45f, 0f, false) },
                { "DB_CatchRing", new MatDef(Lin(0.035f, 0.035f, 0.04f), 0.3f, 0f, false) },
                { "DT_Tungsten", new MatDef(Lin(0.42f, 0.43f, 0.47f), 0.75f, 0.95f, false) },
                { "DT_Brass", new MatDef(Lin(0.80f, 0.56f, 0.16f), 0.7f, 0.95f, false) },
                { "DT_Steel", new MatDef(Lin(0.78f, 0.79f, 0.83f), 0.8f, 0.95f, false) },
                { "DT_Shaft", new MatDef(Lin(0.05f, 0.05f, 0.06f), 0.5f, 0f, false) },
                { "DT_FlightRed", new MatDef(Lin(0.78f, 0.04f, 0.05f), 0.45f, 0f, false) },
                { "DT_FlightWhite", new MatDef(Lin(0.93f, 0.93f, 0.95f), 0.45f, 0f, false) },
                { "DT_FlightDark", new MatDef(Lin(0.05f, 0.05f, 0.07f), 0.45f, 0f, false) },
            };
            if (!AssetDatabase.IsValidFolder(ArtDir + "Materials")) AssetDatabase.CreateFolder("Assets/Art/Darts", "Materials");
            var sisalTex = AssetDatabase.LoadAssetAtPath<Texture2D>(ArtDir + "sisal.png");
            var sisalNormal = AssetDatabase.LoadAssetAtPath<Texture2D>(ArtDir + "sisal_normal.png");
            var result = new Dictionary<string, Material>();
            foreach (var kv in defs)
            {
                string path = ArtDir + "Materials/" + kv.Key + ".mat";
                var m = AssetDatabase.LoadAssetAtPath<Material>(path);
                bool isNew = m == null;
                if (isNew) m = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                m.SetColor("_BaseColor", kv.Value.Color);
                m.SetFloat("_Smoothness", kv.Value.Smoothness);
                m.SetFloat("_Metallic", kv.Value.Metallic);
                if (kv.Value.Sisal)
                {
                    m.SetTexture("_BaseMap", sisalTex);
                    m.SetTextureScale("_BaseMap", Vector2.one);
                    m.SetTexture("_BumpMap", sisalNormal);
                    m.SetFloat("_BumpScale", 0.45f);
                    m.EnableKeyword("_NORMALMAP");
                }
                if (isNew) AssetDatabase.CreateAsset(m, path); else EditorUtility.SetDirty(m);
                result[kv.Key] = m;
            }
            // материал прицела: светящийся, без освещения, с прозрачностью (вершинный цвет задаёт игра)
            string reticlePath = ArtDir + "Materials/Reticle.mat";
            var reticle = AssetDatabase.LoadAssetAtPath<Material>(reticlePath);
            if (reticle == null)
            {
                reticle = new Material(Shader.Find("Universal Render Pipeline/Particles/Unlit"));
                AssetDatabase.CreateAsset(reticle, reticlePath);
            }
            reticle.SetFloat("_Surface", 1f);
            reticle.SetFloat("_Blend", 0f);
            reticle.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
            reticle.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            reticle.SetFloat("_ZWrite", 0f);
            reticle.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            reticle.renderQueue = 3100;
            EditorUtility.SetDirty(reticle);
            result["Reticle"] = reticle;
            // материал прожектора: свой шейдер Neurotlon/DartsSpotlight
            string spotPath = ArtDir + "Materials/Spotlight.mat";
            var spot = AssetDatabase.LoadAssetAtPath<Material>(spotPath);
            if (spot == null)
            {
                spot = new Material(Shader.Find("Neurotlon/DartsSpotlight"));
                AssetDatabase.CreateAsset(spot, spotPath);
            }
            EditorUtility.SetDirty(spot);
            result["Spotlight"] = spot;
            AssetDatabase.SaveAssets();
            return result;
        }

        static void ImportModels(Dictionary<string, Material> mats)
        {
            foreach (string model in new[] { "Dartboard", "Dart" })
            {
                string path = ArtDir + model + ".fbx";
                var importer = (ModelImporter)AssetImporter.GetAtPath(path);
                if (importer == null) continue;
                importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
                importer.SaveAndReimport();
                var go = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                var names = new HashSet<string>();
                foreach (var r in go.GetComponentsInChildren<Renderer>())
                    foreach (var sm in r.sharedMaterials)
                        if (sm != null) names.Add(sm.name);
                foreach (string n in names)
                {
                    Material m;
                    if (mats.TryGetValue(n, out m))
                        importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), n), m);
                    else
                        Debug.LogWarning("Neurotlon: для материала модели нет замены: " + n);
                }
                importer.SaveAndReimport();
            }
        }

        // --- сцена ---

        static Transform BuildBoard()
        {
            // корень без поворота: x вправо, y вверх, z от игрока в мишень; игра работает в этих осях
            var root = new GameObject("Dartboard");
            root.transform.position = BoardCenter;
            var model = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(ArtDir + "Dartboard.fbx"));
            model.name = "Model";
            model.transform.SetParent(root.transform, false);
            // лицо мишени должно смотреть на игрока (-Z): тело мишени лежит за лицом, то есть центр модели дальше от камеры
            var renderer = model.GetComponentInChildren<Renderer>();
            if (renderer != null && renderer.bounds.center.z < root.transform.position.z) model.transform.Rotate(0f, 180f, 0f);
            // деревянная стена паба за мишенью (текстура ArtSource/Darts/make_wood.py)
            var wall = GameObject.CreatePrimitive(PrimitiveType.Cube);
            wall.name = "WoodWall";
            wall.transform.SetParent(root.transform, false);
            wall.transform.localPosition = new Vector3(0f, 0.0f, 0.10f);
            wall.transform.localScale = new Vector3(4.2f, 2.8f, 0.06f);
            wall.GetComponent<Renderer>().sharedMaterial = WoodMaterial();
            Object.DestroyImmediate(wall.GetComponent<Collider>());
            return root.transform;
        }

        static Material WoodMaterial()
        {
            string path = ArtDir + "Materials/Wood.mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (m == null)
            {
                m = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                AssetDatabase.CreateAsset(m, path);
            }
            m.SetColor("_BaseColor", Color.white);
            m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(ArtDir + "wood.png"));
            m.SetTextureScale("_BaseMap", new Vector2(3.5f, 1f));      // доски ~0,3 м шириной
            m.SetFloat("_Smoothness", 0.28f);
            m.SetFloat("_Metallic", 0f);
            EditorUtility.SetDirty(m);
            return m;
        }

        static Material SolidMaterial(string name, Color color, float smoothness)
        {
            string path = ArtDir + "Materials/" + name + ".mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (m == null)
            {
                m = new Material(Shader.Find("Universal Render Pipeline/Lit"));
                AssetDatabase.CreateAsset(m, path);
            }
            m.SetColor("_BaseColor", color);
            m.SetFloat("_Smoothness", smoothness);
            EditorUtility.SetDirty(m);
            return m;
        }

        // Дротик: корень, +Z — куда смотрит острие. Поворот модели подбирается по её границам, а не на глаз.
        static Transform BuildDart(string name, bool visible)
        {
            var root = new GameObject(name);
            var model = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>(ArtDir + "Dart.fbx"));
            model.name = "Model";
            model.transform.SetParent(root.transform, false);
            // начало модели в острие, хвост уходит назад: центр модели должен оказаться позади корня (по -Z)
            var renderer = model.GetComponentInChildren<Renderer>();
            if (renderer != null && renderer.bounds.center.z > root.transform.position.z) model.transform.Rotate(0f, 180f, 0f);
            root.SetActive(visible);
            return root.transform;
        }

        static Camera BuildCamera()
        {
            var go = new GameObject("Main Camera");
            go.tag = "MainCamera";
            var cam = go.AddComponent<Camera>();
            go.AddComponent<AudioListener>();
            go.transform.position = EyePosition;
            go.transform.LookAt(BoardCenter + new Vector3(0f, -0.04f, 0f));
            cam.fieldOfView = 40f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 80f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.05f, 0.03f, 0.02f);
            var data = go.AddComponent<UniversalAdditionalCameraData>();
            data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            data.antialiasingQuality = AntialiasingQuality.High;
            data.renderPostProcessing = true;
            return cam;
        }

        static void BuildLights()
        {
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.17f, 0.12f, 0.08f);
            var dir = new GameObject("Directional Light");
            dir.transform.rotation = Quaternion.Euler(60f, -20f, 0f);
            var dl = dir.AddComponent<Light>();
            dl.type = LightType.Directional;
            dl.intensity = 0.18f;
            dl.color = new Color(1f, 0.78f, 0.55f);
            // два прожектора на мишень, как на турнире
            float[] xs = { -0.9f, 0.9f };
            for (int i = 0; i < 2; i++)
            {
                var go = new GameObject(i == 0 ? "SpotLeft" : "SpotRight");
                go.transform.position = new Vector3(xs[i], 3.4f, 0.6f);
                go.transform.rotation = Quaternion.LookRotation((BoardCenter - go.transform.position).normalized);
                var l = go.AddComponent<Light>();
                l.type = LightType.Spot;
                l.spotAngle = 38f;
                l.innerSpotAngle = 20f;
                l.range = 9f;
                l.intensity = 30f;
                l.color = new Color(1f, 0.84f, 0.62f);
                l.shadows = LightShadows.Soft;
            }
        }

        // Глубина резкости (арена позади размыта), свечение и виньетка: картинка собранная, а не плоская.
        static void BuildPostProcessing()
        {
            string path = ArtDir + "DartsVolume.asset";
            AssetDatabase.DeleteAsset(path);
            var profile = ScriptableObject.CreateInstance<UnityEngine.Rendering.VolumeProfile>();
            AssetDatabase.CreateAsset(profile, path);
            var dof = profile.Add<UnityEngine.Rendering.Universal.DepthOfField>(true);
            dof.mode.Override(UnityEngine.Rendering.Universal.DepthOfFieldMode.Gaussian);
            dof.gaussianStart.Override(1.9f);
            dof.gaussianEnd.Override(5.5f);
            dof.gaussianMaxRadius.Override(1.5f);
            var bloom = profile.Add<UnityEngine.Rendering.Universal.Bloom>(true);
            bloom.threshold.Override(0.9f);
            bloom.intensity.Override(0.5f);
            bloom.scatter.Override(0.6f);
            var vignette = profile.Add<UnityEngine.Rendering.Universal.Vignette>(true);
            vignette.intensity.Override(0.38f);
            vignette.smoothness.Override(0.5f);
            var tone = profile.Add<UnityEngine.Rendering.Universal.Tonemapping>(true);
            tone.mode.Override(UnityEngine.Rendering.Universal.TonemappingMode.ACES);
            EditorUtility.SetDirty(profile);
            AssetDatabase.SaveAssets();
            var go = new GameObject("PostProcessing");
            var volume = go.AddComponent<UnityEngine.Rendering.Volume>();
            volume.isGlobal = true;
            volume.sharedProfile = profile;
        }

        static void BuildGame(Camera camera, Transform board, Transform held, Transform template, Dictionary<string, Material> mats)
        {
            var go = new GameObject("DartsGame");
            var source = go.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.spatialBlend = 0f;
            source.volume = 0.85f;
            var sounds = go.AddComponent<DartsSounds>();
            var game = go.AddComponent<DartsGame>();
            var recorder = go.AddComponent<DartsRecorder>();

            Set(sounds, "source", source);
            Set(sounds, "throwClip", Clip("throw"));
            Set(sounds, "hit", Clip("hit"));
            Set(sounds, "bull", Clip("bull"));
            Set(sounds, "miss", Clip("miss"));
            Set(sounds, "finish", Clip("finish"));
            Set(game, "board", board);
            Set(game, "heldDart", held);
            Set(game, "dartTemplate", template);
            Set(game, "viewCamera", camera);
            Set(game, "sounds", sounds);
            Set(game, "reticleMaterial", mats["Reticle"]);
            Set(game, "spotlightMaterial", mats["Spotlight"]);
            Set(recorder, "game", game);
        }

        static AudioClip Clip(string name)
        {
            return AssetDatabase.LoadAssetAtPath<AudioClip>("Assets/Audio/" + name + ".wav");
        }

        static void Set(Object target, string field, Object value)
        {
            var so = new SerializedObject(target);
            var p = so.FindProperty(field);
            if (p == null)
            {
                Debug.LogWarning("Neurotlon: у " + target.GetType().Name + " нет поля " + field);
                return;
            }
            p.objectReferenceValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
