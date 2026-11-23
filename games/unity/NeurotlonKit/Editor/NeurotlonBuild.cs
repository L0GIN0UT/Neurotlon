using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace Neurotlon.Kit.Editor
{
    /// <summary>
    /// Пакетная сборка игры в Windows .exe без открытия редактора:
    /// <c>Unity.exe -batchmode -quit -projectPath … -executeMethod Neurotlon.Kit.Editor.NeurotlonBuild.BuildWindows64 -neurotlonOut …</c>.
    /// Берёт включённые сцены из Build Settings, кладёт результат в папку <c>-neurotlonOut</c>
    /// как <c>&lt;productName&gt;.exe</c> и выходит с кодом 0 (успех) или 1.
    /// </summary>
    public static class NeurotlonBuild
    {
        private const string OutArg = "-neurotlonOut";

        public static void BuildWindows64()
        {
            try
            {
                string output = ArgValue(OutArg);
                if (string.IsNullOrEmpty(output))
                    throw new InvalidOperationException("Не задан аргумент " + OutArg + " <папка>");

                string[] scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
                if (scenes.Length == 0)
                    throw new InvalidOperationException("В Build Settings нет включённых сцен");

                Directory.CreateDirectory(output);
                var options = new BuildPlayerOptions
                {
                    scenes = scenes,
                    locationPathName = Path.Combine(output, PlayerSettings.productName + ".exe"),
                    target = BuildTarget.StandaloneWindows64,
                    options = BuildOptions.None,
                };

                BuildReport report = BuildPipeline.BuildPlayer(options);
                BuildSummary summary = report.summary;
                Debug.Log("Neurotlon build: " + summary.result + ", " + summary.totalSize / (1024 * 1024) + " MB -> " + options.locationPathName);
                EditorApplication.Exit(summary.result == BuildResult.Succeeded ? 0 : 1);
            }
            catch (Exception exception)
            {
                Debug.LogError("Neurotlon build failed: " + exception);
                EditorApplication.Exit(1);
            }
        }

        private static string ArgValue(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
        }
    }
}
