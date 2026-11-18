using System;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;

namespace Neurotlon
{
    // Поля называются так же, как в shared/game-launch.schema.json (snake_case): так работает JsonUtility.
    [Serializable]
    public class LaunchParticipant
    {
        public string code;
        public string display_name;
        public string side;
    }

    [Serializable]
    public class LaunchBridge
    {
        public string host;
        public int port;
    }

    [Serializable]
    public class LaunchFile
    {
        public int protocol;
        public string session_id;
        public string discipline;
        public int duration_s;
        public LaunchParticipant[] participants;
        public LaunchBridge bridge;
        public string result_path;
        public string language;
        public bool fullscreen;
    }

    public class NeurotlonLaunchException : Exception
    {
        public NeurotlonLaunchException(string message) : base(message) { }
    }

    // launch.json, разобранный и проверенный. Путь лаунчер передаёт как `--launch <путь>`.
    public class NeurotlonLaunch
    {
        public const string LaunchEnv = "NEUROTLON_LAUNCH";

        static readonly Regex CodePattern = new Regex("^NT(0[1-9]|[1-9][0-9])$");

        public LaunchFile Data { get; private set; }

        public string SessionId { get { return Data.session_id; } }
        public string Discipline { get { return Data.discipline; } }
        public int DurationSeconds { get { return Data.duration_s; } }
        public LaunchParticipant[] Participants { get { return Data.participants; } }
        public string BridgeHost { get { return Data.bridge.host; } }
        public int BridgePort { get { return Data.bridge.port; } }
        public string ResultPath { get { return Data.result_path; } }
        public bool Fullscreen { get { return Data.fullscreen; } }
        public bool IsPong { get { return Data.discipline == NeurotlonProtocol.DisciplinePong; } }
        public string[] Signals { get { return NeurotlonProtocol.SignalsFor(Data.discipline); } }

        // Участник стороны (понг): "left" или "right".
        public LaunchParticipant BySide(string side)
        {
            foreach (var p in Data.participants)
            {
                if (p.side == side) return p;
            }
            throw new NeurotlonLaunchException("нет участника со стороной " + side);
        }

        // Сигнал игрока в понге: emg_left или emg_right.
        public string SignalOf(LaunchParticipant participant)
        {
            if (string.IsNullOrEmpty(participant.side))
            {
                throw new NeurotlonLaunchException("у " + participant.code + " нет стороны");
            }
            return "emg_" + participant.side;
        }

        // Значение после `--launch` (или `--launch=<путь>`) или null.
        public static string FindLaunchPath(string[] args)
        {
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--launch" && i + 1 < args.Length) return args[i + 1];
                if (args[i].StartsWith("--launch=", StringComparison.Ordinal))
                {
                    return args[i].Substring("--launch=".Length);
                }
            }
            return null;
        }

        public static NeurotlonLaunch FromCommandLine()
        {
            return FromArgs(Environment.GetCommandLineArgs());
        }

        public static NeurotlonLaunch FromArgs(string[] args)
        {
            string path = FindLaunchPath(args);
            if (path == null) path = Environment.GetEnvironmentVariable(LaunchEnv); // для запуска из редактора
            if (path == null)
            {
                throw new NeurotlonLaunchException("не передан аргумент --launch <путь к launch.json>");
            }
            string json;
            try
            {
                json = File.ReadAllText(path);
            }
            catch (Exception e)
            {
                throw new NeurotlonLaunchException("launch.json не читается: " + e.Message);
            }
            return Parse(json);
        }

        public static NeurotlonLaunch Parse(string json)
        {
            LaunchFile data;
            try
            {
                data = JsonUtility.FromJson<LaunchFile>(json);
            }
            catch (Exception e)
            {
                throw new NeurotlonLaunchException("launch.json не разобран: " + e.Message);
            }
            if (data == null) throw new NeurotlonLaunchException("launch.json пустой");
            Validate(data);
            return new NeurotlonLaunch { Data = data };
        }

        static void Validate(LaunchFile d)
        {
            if (d.protocol != NeurotlonProtocol.ProtocolVersion)
                throw new NeurotlonLaunchException("protocol должен быть 1");
            if (string.IsNullOrEmpty(d.session_id))
                throw new NeurotlonLaunchException("нет session_id");
            if (d.discipline != NeurotlonProtocol.DisciplineDarts
                && d.discipline != NeurotlonProtocol.DisciplineFootball
                && d.discipline != NeurotlonProtocol.DisciplinePong)
                throw new NeurotlonLaunchException("неизвестная дисциплина: " + d.discipline);
            if (d.duration_s < NeurotlonProtocol.DurationMinSeconds
                || d.duration_s > NeurotlonProtocol.DurationMaxSeconds)
                throw new NeurotlonLaunchException("duration_s вне диапазона 10..3600");
            if (d.bridge == null || string.IsNullOrEmpty(d.bridge.host) || d.bridge.port < 1
                || d.bridge.port > 65535)
                throw new NeurotlonLaunchException("bridge.host / bridge.port заданы неверно");
            if (string.IsNullOrEmpty(d.result_path))
                throw new NeurotlonLaunchException("нет result_path");
            ValidateParticipants(d);
        }

        static void ValidateParticipants(LaunchFile d)
        {
            int expected = d.discipline == NeurotlonProtocol.DisciplinePong ? 2 : 1;
            if (d.participants == null || d.participants.Length != expected)
                throw new NeurotlonLaunchException(d.discipline + ": нужно участников: " + expected);
            foreach (var p in d.participants)
            {
                if (p.code == null || !CodePattern.IsMatch(p.code))
                    throw new NeurotlonLaunchException("неверный ID участника: " + p.code);
            }
            if (expected == 2)
            {
                string a = d.participants[0].side, b = d.participants[1].side;
                bool ok = (a == NeurotlonProtocol.SideLeft && b == NeurotlonProtocol.SideRight)
                    || (a == NeurotlonProtocol.SideRight && b == NeurotlonProtocol.SideLeft);
                if (!ok) throw new NeurotlonLaunchException("pong: нужны стороны left и right");
            }
        }
    }
}
