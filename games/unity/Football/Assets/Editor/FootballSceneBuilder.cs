using System.Collections.Generic;
using Neurotlon.Games.Football;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace Neurotlon.Games.Football.Editor
{
    // Собирает сцену футбола одной командой: Neurotlon → Build Football Scene. Повторный запуск пересоздаёт сцену.
    // Модели и текстуры — Assets/Art/Football, поле с объёмной травой — шейдер ShellGrass (слои рисуются только вблизи камеры).
    public static class FootballSceneBuilder
    {
        const string ArtDir = "Assets/Art/Football/";
        const string MatDir = "Assets/Art/Football/Materials/";
        const float FieldPlaneW = 62f, FieldPlaneD = 42f;       // поле вместе с полями вокруг линий
        const float LineY = 0.052f;                              // линии лежат на уровне кончиков травы
        const int GrassLayers = 20;

        [MenuItem("Neurotlon/Build Football Scene")]
        public static void Build()
        {
            ImportTextures();
            var mats = BuildMaterials();
            ImportModels(mats);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            BuildField(mats);
            BuildGround();
            BuildLines(mats);
            Transform ball = Place("FootBall", "FootBall.fbx", FootballLayout.SnakeBall + Vector3.up * FootballLayout.BallRadius, Quaternion.identity);
            var tuning = new FootballTuning();
            var cones = new List<Transform>();
            for (int i = 0; i < tuning.ConeY.Length; i++)
                cones.Add(Place("Cone" + (i + 1), "TrainingCone.fbx", new Vector3(0f, FootballLayout.GrassSurface, tuning.ConeY[i]), Quaternion.Euler(0f, 37f * i, 0f)));
            var conePhysics = MakePhysicsMaterial("ConePhysics", FootballCone.GrassFriction, FootballCone.ConeBounciness);
            foreach (var cone in cones) AddConePhysics(cone, conePhysics);
            Place("Goal", "MiniGoal.fbx", FootballLayout.GoalMouth, Quaternion.Euler(0f, -90f, 0f));      // проём смотрит в −X
            Transform tarpTransform = Place("GoalTarp", "GoalTarp.fbx", FootballLayout.GoalMouth, Quaternion.Euler(0f, -90f, 0f));
            var tarp = tarpTransform.gameObject.AddComponent<FootballTarp>();
            Transform netTransform = Place("GoalNet", "GoalNet.fbx", FootballLayout.GoalMouth, Quaternion.Euler(0f, -90f, 0f));
            var goalNet = netTransform.gameObject.AddComponent<FootballNet>();
            Transform stopNetTransform = Place("StopNet", "StopNet.fbx", FootballLayout.StopNet, Quaternion.Euler(0f, 90f, 0f));    // ловит мяч за зоной остановки: мяч катится в −X, сетка лицом к +X
            var stopNet = stopNetTransform.gameObject.AddComponent<FootballNet>();
            var stopNetSettings = new SerializedObject(stopNet);
            stopNetSettings.FindProperty("bottomEdgeFree").boolValue = true;
            stopNetSettings.ApplyModifiedPropertiesWithoutUndo();
            Place("Target", "TargetPanel.fbx", FootballLayout.TargetBase, Quaternion.Euler(0f, 180f, 0f)); // лицо смотрит в −Z
            BuildDecor(mats);
            BuildSky(mats);
            Camera camera = BuildCamera();
            BuildLight();
            BuildPostProcessing();
            BuildGame(camera, ball, cones, mats, tarp, goalNet, stopNet);

            if (!AssetDatabase.IsValidFolder("Assets/Scenes")) AssetDatabase.CreateFolder("Assets", "Scenes");
            EditorSceneManager.SaveScene(scene, "Assets/Scenes/Football.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene("Assets/Scenes/Football.unity", true) };
            Debug.Log("Neurotlon: сцена футбола собрана: Assets/Scenes/Football.unity");
        }

        // ---------- текстуры ----------

        static void ImportTextures()
        {
            Tex("grass_albedo.png", false, TextureWrapMode.Repeat, 8, true);
            Tex("grass_normal.png", true, TextureWrapMode.Repeat, 8, false);
            Tex("stripes.png", false, TextureWrapMode.Clamp, 4, false);
            Tex("ball_albedo.png", false, TextureWrapMode.Repeat, 8, true);
            Tex("ball_normal.png", true, TextureWrapMode.Repeat, 8, false);
            Tex("cone_albedo.png", false, TextureWrapMode.Repeat, 8, true);
            Tex("cone_normal.png", true, TextureWrapMode.Repeat, 8, false);
            Tex("net.png", false, TextureWrapMode.Repeat, 4, true);
            Tex("target_rings.png", false, TextureWrapMode.Clamp, 8, true);
            Tex("goal_tarp.png", false, TextureWrapMode.Clamp, 8, true);
            Tex("stop_net.png", false, TextureWrapMode.Repeat, 8, true);
            Tex("logo.png", false, TextureWrapMode.Clamp, 8, true);
            var hdr = AssetImporter.GetAtPath(ArtDir + "orlando_stadium_2k.hdr") as TextureImporter;
            if (hdr != null)
            {
                hdr.textureShape = TextureImporterShape.Texture2D;
                hdr.wrapMode = TextureWrapMode.Repeat;
                hdr.mipmapEnabled = true;
                hdr.sRGBTexture = false;
                hdr.SaveAndReimport();
            }
        }

        static void Tex(string file, bool normal, TextureWrapMode wrap, int aniso, bool alphaTransparency)
        {
            var imp = AssetImporter.GetAtPath(ArtDir + file) as TextureImporter;
            if (imp == null) return;
            imp.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            imp.wrapMode = wrap;
            imp.mipmapEnabled = true;
            imp.anisoLevel = aniso;
            imp.alphaIsTransparency = alphaTransparency;
            imp.SaveAndReimport();
        }

        static Texture2D T(string file)
        {
            return AssetDatabase.LoadAssetAtPath<Texture2D>(ArtDir + file);
        }

        // ---------- материалы ----------

        static Color Lin(float r, float g, float b)
        {
            return new Color(Mathf.LinearToGammaSpace(r), Mathf.LinearToGammaSpace(g), Mathf.LinearToGammaSpace(b), 1f);
        }

        static Material Lit(string name, Color color, float smooth, float metal, Texture2D map = null, Texture2D normal = null, float normalScale = 1f, Vector2? tiling = null)
        {
            string path = MatDir + name + ".mat";
            var m = AssetDatabase.LoadAssetAtPath<Material>(path);
            bool isNew = m == null;
            if (isNew) m = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            m.SetColor("_BaseColor", color);
            m.SetFloat("_Smoothness", smooth);
            m.SetFloat("_Metallic", metal);
            if (map != null)
            {
                m.SetTexture("_BaseMap", map);
                if (tiling.HasValue) m.SetTextureScale("_BaseMap", tiling.Value);
            }
            if (normal != null)
            {
                m.SetTexture("_BumpMap", normal);
                m.SetFloat("_BumpScale", normalScale);
                m.EnableKeyword("_NORMALMAP");
            }
            if (isNew) AssetDatabase.CreateAsset(m, path); else EditorUtility.SetDirty(m);
            return m;
        }

        // Материал с вырезом по альфе: отверстия чехла и круг мишени.
        static Material Cutout(string name, Texture2D map, float smooth, bool doubleSided, Color? tint = null)
        {
            var m = Lit(name, tint.HasValue ? tint.Value : Color.white, smooth, 0f, map);
            m.SetFloat("_AlphaClip", 1f);
            m.SetFloat("_Cutoff", 0.5f);
            m.SetFloat("_Cull", doubleSided ? 0f : 2f);
            m.EnableKeyword("_ALPHATEST_ON");
            m.renderQueue = 2450;
            EditorUtility.SetDirty(m);
            return m;
        }

        static Dictionary<string, Material> BuildMaterials()
        {
            if (!AssetDatabase.IsValidFolder("Assets/Art/Football/Materials")) AssetDatabase.CreateFolder("Assets/Art/Football", "Materials");
            var d = new Dictionary<string, Material>();
            d["FB_Ball"] = Lit("FB_Ball", Color.white, 0.55f, 0f, T("ball_albedo.png"), T("ball_normal.png"), 1f);
            d["FB_Cone"] = Lit("FB_Cone", Color.white, 0.45f, 0f, T("cone_albedo.png"), T("cone_normal.png"), 0.8f);
            d["FB_ConeBase"] = Lit("FB_ConeBase", Lin(0.93f, 0.21f, 0.02f), 0.4f, 0f);
            d["FB_GoalTube"] = Lit("FB_GoalTube", Lin(0.93f, 0.93f, 0.94f), 0.6f, 0.15f);
            d["FB_Rubber"] = Lit("FB_Rubber", Lin(0.03f, 0.03f, 0.03f), 0.2f, 0f);
            d["FB_Rubber2"] = d["FB_Rubber"];
            var net = Lit("FB_Net", Color.white, 0.2f, 0f, T("net.png"));
            net.SetFloat("_Cull", 0f);                                           // сетка видна с обеих сторон
            net.SetFloat("_AlphaClip", 1f);
            net.SetFloat("_Cutoff", 0.35f);
            net.EnableKeyword("_ALPHATEST_ON");
            net.renderQueue = 2450;
            EditorUtility.SetDirty(net);
            d["FB_Net"] = net;
            d["FB_TargetFace"] = Cutout("FB_TargetFace", T("target_rings.png"), 0.4f, false);
            d["FB_GoalTarp"] = Cutout("FB_GoalTarp", T("goal_tarp.png"), 0.45f, true);
            d["FB_StopPole"] = Lit("FB_StopPole", Lin(0.10f, 0.11f, 0.12f), 0.5f, 0.7f);
            d["FB_StopNet"] = Cutout("FB_StopNet", T("stop_net.png"), 0.2f, true, Lin(0.95f, 0.50f, 0.08f));
            d["FB_TargetBoard"] = Lit("FB_TargetBoard", Lin(0.08f, 0.08f, 0.09f), 0.2f, 0f);
            d["FB_TargetMetal"] = Lit("FB_TargetMetal", Lin(0.16f, 0.17f, 0.19f), 0.55f, 0.7f);
            d["FB_Bolt"] = Lit("FB_Bolt", Lin(0.55f, 0.56f, 0.58f), 0.65f, 0.9f);
            d["Line"] = Lit("Line", Lin(0.93f, 0.93f, 0.92f), 0.1f, 0f);
            d["LineYellow"] = Lit("LineYellow", Lin(1.0f, 0.78f, 0.08f), 0.1f, 0f);
            d["Flag"] = Lit("Flag", Lin(1.0f, 0.78f, 0.05f), 0.2f, 0f);
            d["FB_BoardText"] = Cutout("FB_BoardText", T("logo.png"), 0.1f, true);
            d["FlagPole"] = Lit("FlagPole", Lin(0.95f, 0.95f, 0.95f), 0.5f, 0f);
            d["BoardBlue"] = Lit("BoardBlue", Lin(0.05f, 0.20f, 0.58f), 0.35f, 0f);
            d["BoardWhite"] = Lit("BoardWhite", Lin(0.92f, 0.92f, 0.94f), 0.35f, 0f);
            d["BoardPost"] = Lit("BoardPost", Lin(0.12f, 0.13f, 0.15f), 0.5f, 0.5f);
            // материал прицела: прозрачный, без освещения
            string rp = MatDir + "Reticle.mat";
            var reticle = AssetDatabase.LoadAssetAtPath<Material>(rp);
            if (reticle == null)
            {
                reticle = new Material(Shader.Find("Universal Render Pipeline/Particles/Unlit"));
                AssetDatabase.CreateAsset(reticle, rp);
            }
            reticle.SetFloat("_Surface", 1f);
            reticle.SetFloat("_Blend", 0f);
            reticle.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
            reticle.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
            reticle.SetFloat("_ZWrite", 0f);
            reticle.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            reticle.renderQueue = 3100;
            EditorUtility.SetDirty(reticle);
            d["Reticle"] = reticle;
            // трава
            string gp = MatDir + "ShellGrass.mat";
            var grass = AssetDatabase.LoadAssetAtPath<Material>(gp);
            if (grass == null)
            {
                grass = new Material(Shader.Find("Neurotlon/ShellGrass"));
                AssetDatabase.CreateAsset(grass, gp);
            }
            grass.SetTexture("_BaseMap", T("grass_albedo.png"));
            grass.SetTexture("_StripeMap", T("stripes.png"));
            grass.SetFloat("_TileSize", 1.8f);
            grass.SetFloat("_Height", 0.04f);
            grass.SetFloat("_Density", 70f);
            grass.SetColor("_Root", new Color(0.40f, 0.55f, 0.23f, 1f));
            grass.SetColor("_Tip", new Color(1.18f, 1.18f, 1.02f, 1f));
            grass.SetFloat("_Near", 5f);
            grass.SetFloat("_Far", 12f);
            grass.SetVector("_FieldCenter", Vector4.zero);
            grass.SetVector("_FieldSize", new Vector4(FieldPlaneW, FieldPlaneD, 0f, 0f));
            EditorUtility.SetDirty(grass);
            d["Grass"] = grass;
            AssetDatabase.SaveAssets();
            return d;
        }

        static void ImportModels(Dictionary<string, Material> mats)
        {
            foreach (string model in new[] { "FootBall", "TrainingCone", "MiniGoal", "GoalTarp", "GoalNet", "StopNet", "TargetPanel" })
            {
                string path = ArtDir + model + ".fbx";
                var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null) continue;
                importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
                importer.isReadable = model == "GoalTarp" || model == "GoalNet" || model == "StopNet" || model == "TrainingCone";                    // чехол прогибается в игре: вершины должны быть доступны
                importer.SaveAndReimport();
                var go = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                var names = new HashSet<string>();
                foreach (var r in go.GetComponentsInChildren<Renderer>())
                    foreach (var sm in r.sharedMaterials)
                        if (sm != null) names.Add(sm.name);
                foreach (string n in names)
                {
                    Material m;
                    if (mats.TryGetValue(n, out m)) importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), n), m);
                    else Debug.LogWarning("Neurotlon: для материала модели нет замены: " + n);
                }
                importer.SaveAndReimport();
            }
        }

        // ---------- физика ----------

        static PhysicsMaterial MakePhysicsMaterial(string name, float friction, float bounciness)
        {
            string path = MatDir + name + ".asset";
            var m = AssetDatabase.LoadAssetAtPath<PhysicsMaterial>(path);
            if (m == null)
            {
                m = new PhysicsMaterial(name);
                AssetDatabase.CreateAsset(m, path);
            }
            FootballCone.Configure(m, friction, bounciness);
            EditorUtility.SetDirty(m);
            return m;
        }

        static void AddConePhysics(Transform cone, PhysicsMaterial material)
        {
            FootballCone.Attach(cone.gameObject, material);
        }

        // Земля под полем: твёрдая плоскость на уровне травы (конусы и другие тела ложатся на неё).
        static void BuildGround()
        {
            var ground = new GameObject("Ground");
            var box = ground.AddComponent<BoxCollider>();
            box.center = new Vector3(0f, FootballLayout.GrassSurface - 0.5f, 0f);
            box.size = new Vector3(90f, 1f, 70f);
            box.sharedMaterial = MakePhysicsMaterial("GroundPhysics", FootballCone.GrassFriction, FootballCone.GroundBounciness);
        }

        // ---------- поле ----------

        static void BuildField(Dictionary<string, Material> mats)
        {
            // сетка поля, повторённая GrassLayers раз; слой лежит во второй UV-координате (x от 0 до 1)
            const float cell = 1.5f;
            int nx = Mathf.CeilToInt(FieldPlaneW / cell), nz = Mathf.CeilToInt(FieldPlaneD / cell);
            var verts = new List<Vector3>();
            var uv0 = new List<Vector2>();
            var uv1 = new List<Vector2>();
            var norms = new List<Vector3>();
            var tris = new List<int>();
            for (int layer = 0; layer < GrassLayers; layer++)
            {
                int baseIndex = verts.Count;
                float l = layer / (float)(GrassLayers - 1);
                for (int z = 0; z <= nz; z++)
                    for (int x = 0; x <= nx; x++)
                    {
                        float px = -FieldPlaneW / 2f + x * FieldPlaneW / nx, pz = -FieldPlaneD / 2f + z * FieldPlaneD / nz;
                        verts.Add(new Vector3(px, 0f, pz));
                        uv0.Add(new Vector2(x / (float)nx, z / (float)nz));
                        uv1.Add(new Vector2(l, 0f));
                        norms.Add(Vector3.up);
                    }
                for (int z = 0; z < nz; z++)
                    for (int x = 0; x < nx; x++)
                    {
                        int a = baseIndex + z * (nx + 1) + x, b = a + 1, c = a + nx + 1, d = c + 1;
                        tris.AddRange(new[] { a, c, b, b, c, d });
                    }
            }
            var mesh = new Mesh { name = "FieldShells", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetUVs(0, uv0);
            mesh.SetUVs(1, uv1);
            mesh.SetNormals(norms);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            string meshPath = ArtDir + "FieldShells.asset";
            AssetDatabase.DeleteAsset(meshPath);
            AssetDatabase.CreateAsset(mesh, meshPath);
            var go = new GameObject("Field");
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var r = go.AddComponent<MeshRenderer>();
            r.sharedMaterial = mats["Grass"];
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            r.receiveShadows = true;
            go.isStatic = true;
        }

        static void BuildLines(Dictionary<string, Material> mats)
        {
            float hw = FootballLayout.FieldWidth / 2f - 1.5f, hh = FootballLayout.FieldDepth / 2f - 1.5f;
            var root = new GameObject("Lines").transform;
            Line(root, "Низ", -hw, -hh, hw, -hh, 0.14f, mats["Line"]);
            Line(root, "Право", hw, -hh, hw, hh, 0.14f, mats["Line"]);
            Line(root, "Верх", hw, hh, -hw, hh, 0.14f, mats["Line"]);
            Line(root, "Лево", -hw, hh, -hw, -hh, 0.14f, mats["Line"]);
            var z = FootballLayout.ZoneCentre;
            float s = FootballLayout.ZoneSize / 2f;
            Line(root, "Зона1", z.x - s, z.z - s, z.x + s, z.z - s, 0.14f, mats["LineYellow"]);
            Line(root, "Зона2", z.x + s, z.z - s, z.x + s, z.z + s, 0.14f, mats["LineYellow"]);
            Line(root, "Зона3", z.x + s, z.z + s, z.x - s, z.z + s, 0.14f, mats["LineYellow"]);
            Line(root, "Зона4", z.x - s, z.z + s, z.x - s, z.z - s, 0.14f, mats["LineYellow"]);
            foreach (var p in new[] { FootballLayout.SnakeBall, FootballLayout.PassBall, FootballLayout.StopBall, FootballLayout.KickBall })
            {
                Line(root, "Метка", p.x - 0.3f, p.z - 0.3f, p.x + 0.3f, p.z + 0.3f, 0.07f, mats["Line"]);
                Line(root, "Метка", p.x - 0.3f, p.z + 0.3f, p.x + 0.3f, p.z - 0.3f, 0.07f, mats["Line"]);
            }
        }

        static void Line(Transform parent, string name, float x0, float z0, float x1, float z1, float width, Material m)
        {
            var q = GameObject.CreatePrimitive(PrimitiveType.Quad);
            q.name = name;
            q.transform.SetParent(parent, false);
            Object.DestroyImmediate(q.GetComponent<Collider>());
            float len = Mathf.Sqrt((x1 - x0) * (x1 - x0) + (z1 - z0) * (z1 - z0));
            q.transform.position = new Vector3((x0 + x1) / 2f, LineY, (z0 + z1) / 2f);
            float angle = Mathf.Atan2(x1 - x0, z1 - z0) * Mathf.Rad2Deg;
            q.transform.rotation = Quaternion.Euler(90f, angle - 90f, 0f);
            q.transform.localScale = new Vector3(len, width, 1f);
            var r = q.GetComponent<MeshRenderer>();
            r.sharedMaterial = m;
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        }

        static Transform Place(string name, string model, Vector3 position, Quaternion rotation)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(ArtDir + model);
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            go.name = name;
            go.transform.SetPositionAndRotation(position, rotation);
            return go.transform;
        }

        // ---------- борта, флажки ----------

        static void BuildDecor(Dictionary<string, Material> mats)
        {
            var root = new GameObject("Decor").transform;
            float hw = FootballLayout.FieldWidth / 2f - 1.5f, hh = FootballLayout.FieldDepth / 2f - 1.5f;
            foreach (var c in new[] { new Vector2(-hw, -hh), new Vector2(hw, -hh), new Vector2(hw, hh), new Vector2(-hw, hh) })
            {
                var pole = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                pole.name = "ФлажокСтойка";
                pole.transform.SetParent(root, false);
                pole.transform.position = new Vector3(c.x, 0.77f, c.y);
                pole.transform.localScale = new Vector3(0.04f, 0.77f, 0.04f);
                pole.GetComponent<MeshRenderer>().sharedMaterial = mats["FlagPole"];
                Object.DestroyImmediate(pole.GetComponent<Collider>());
                var flag = GameObject.CreatePrimitive(PrimitiveType.Cube);
                flag.name = "Флажок";
                flag.transform.SetParent(root, false);
                float dir = c.x < 0f ? 1f : -1f;
                flag.transform.position = new Vector3(c.x + dir * 0.17f, 1.37f, c.y);
                flag.transform.localScale = new Vector3(0.34f, 0.2f, 0.012f);
                flag.GetComponent<MeshRenderer>().sharedMaterial = mats["Flag"];
                Object.DestroyImmediate(flag.GetComponent<Collider>());
            }
            float z = FootballLayout.FieldDepth / 2f + 1.2f;
            for (int i = 0; i < 14; i++)
            {
                float x = -22f + 3.2f * i;
                bool blue = i % 2 == 0;
                var board = GameObject.CreatePrimitive(PrimitiveType.Cube);
                board.name = "Борт";
                board.transform.SetParent(root, false);
                board.transform.position = new Vector3(x, 0.55f, z);
                board.transform.localScale = new Vector3(3f, 0.9f, 0.08f);
                board.GetComponent<MeshRenderer>().sharedMaterial = blue ? mats["BoardBlue"] : mats["BoardWhite"];
                Object.DestroyImmediate(board.GetComponent<Collider>());
                if (blue)
                {
                    // логотип проекта — плоскость с прозрачной текстурой и проверкой глубины: мяч перед щитком её закрывает
                    var label = GameObject.CreatePrimitive(PrimitiveType.Quad);
                    label.name = "Логотип";
                    label.transform.SetParent(root, false);
                    label.transform.position = new Vector3(x, 0.55f, z - 0.045f);
                    label.transform.localScale = new Vector3(1.6f, 0.496f, 1f);       // пропорции логотипа 1000:310
                    label.GetComponent<MeshRenderer>().sharedMaterial = mats["FB_BoardText"];
                    Object.DestroyImmediate(label.GetComponent<Collider>());
                }
                var post = GameObject.CreatePrimitive(PrimitiveType.Cube);
                post.name = "БортСтойка";
                post.transform.SetParent(root, false);
                post.transform.position = new Vector3(x - 1.6f, 0.5f, z + 0.05f);
                post.transform.localScale = new Vector3(0.08f, 1.0f, 0.08f);
                post.GetComponent<MeshRenderer>().sharedMaterial = mats["BoardPost"];
                Object.DestroyImmediate(post.GetComponent<Collider>());
            }
            foreach (float sx in new[] { -24f, 24f })
            {
                for (int j = 0; j < 8; j++)
                {
                    var board = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    board.name = "БортБок";
                    board.transform.SetParent(root, false);
                    board.transform.position = new Vector3(sx, 0.55f, -13.5f + 3.4f * j);
                    board.transform.localScale = new Vector3(0.08f, 0.9f, 3.2f);
                    board.GetComponent<MeshRenderer>().sharedMaterial = j % 2 == 0 ? mats["BoardBlue"] : mats["BoardWhite"];
                    Object.DestroyImmediate(board.GetComponent<Collider>());
                }
            }
        }

        // ---------- небо, камера, свет ----------

        static void BuildSky(Dictionary<string, Material> mats)
        {
            string path = MatDir + "StadiumSky.mat";
            var sky = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (sky == null)
            {
                sky = new Material(Shader.Find("Skybox/Panoramic"));
                AssetDatabase.CreateAsset(sky, path);
            }
            sky.SetTexture("_MainTex", AssetDatabase.LoadAssetAtPath<Texture2D>(ArtDir + "orlando_stadium_2k.hdr"));
            sky.SetFloat("_Exposure", 1.0f);
            sky.SetFloat("_Rotation", 0f);
            EditorUtility.SetDirty(sky);
            RenderSettings.skybox = sky;
            RenderSettings.ambientMode = AmbientMode.Skybox;
            RenderSettings.ambientIntensity = 1.0f;
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
            DynamicGI.UpdateEnvironment();
        }

        static Camera BuildCamera()
        {
            var go = new GameObject("Main Camera");
            go.tag = "MainCamera";
            var cam = go.AddComponent<Camera>();
            go.AddComponent<AudioListener>();
            cam.fieldOfView = 55f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 300f;
            cam.clearFlags = CameraClearFlags.Skybox;
            go.transform.position = new Vector3(0f, 1.55f, -12.6f);
            go.transform.rotation = Quaternion.LookRotation(new Vector3(0f, 0.35f, -5f) - go.transform.position);
            var data = go.AddComponent<UniversalAdditionalCameraData>();
            data.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            data.antialiasingQuality = AntialiasingQuality.High;
            data.renderPostProcessing = true;
            return cam;
        }

        static void BuildLight()
        {
            var go = new GameObject("Sun");
            go.transform.rotation = Quaternion.Euler(48f, -38f, 0f);
            var l = go.AddComponent<Light>();
            l.type = LightType.Directional;
            l.intensity = 1.5f;
            l.color = new Color(1f, 0.95f, 0.86f);
            l.shadows = LightShadows.Soft;
            l.shadowStrength = 0.85f;
            RenderSettings.sun = l;
        }

        static void BuildPostProcessing()
        {
            string path = ArtDir + "FootballVolume.asset";
            AssetDatabase.DeleteAsset(path);
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            AssetDatabase.CreateAsset(profile, path);
            var bloom = profile.Add<Bloom>(true);
            bloom.threshold.Override(1.0f);
            bloom.intensity.Override(0.35f);
            var vignette = profile.Add<Vignette>(true);
            vignette.intensity.Override(0.22f);
            vignette.smoothness.Override(0.5f);
            var tone = profile.Add<Tonemapping>(true);
            tone.mode.Override(TonemappingMode.ACES);
            EditorUtility.SetDirty(profile);
            AssetDatabase.SaveAssets();
            var go = new GameObject("PostProcessing");
            var volume = go.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.sharedProfile = profile;
        }

        // ---------- игра ----------

        static void BuildGame(Camera camera, Transform ball, List<Transform> cones, Dictionary<string, Material> mats, FootballTarp tarp, FootballNet goalNet, FootballNet stopNet)
        {
            var go = new GameObject("FootballGame");
            var source = go.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.spatialBlend = 0f;
            source.volume = 0.9f;
            var sounds = go.AddComponent<FootballSounds>();
            var game = go.AddComponent<FootballGame>();
            var recorder = go.AddComponent<FootballRecorder>();
            Set(sounds, "source", source);
            foreach (var n in new[] { "kick", "touch", "good", "soft", "miss", "tick", "end", "tarp", "net", "ground", "post", "target" })
                Set(sounds, n, AssetDatabase.LoadAssetAtPath<AudioClip>("Assets/Audio/" + n + ".wav"));
            Set(game, "ball", ball);
            Set(game, "viewCamera", camera);
            Set(game, "sounds", sounds);
            Set(game, "tarp", tarp);
            Set(game, "goalNet", goalNet);
            Set(game, "stopNet", stopNet);
            Set(game, "reticleMaterial", mats["Reticle"]);
            var so = new SerializedObject(game);
            var arr = so.FindProperty("cones");
            arr.arraySize = cones.Count;
            for (int i = 0; i < cones.Count; i++) arr.GetArrayElementAtIndex(i).objectReferenceValue = cones[i];
            so.ApplyModifiedPropertiesWithoutUndo();
            Set(recorder, "game", game);
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
