using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Neurotlon
{
    // Запись результата участника (shared/game-launch.schema.json, Entry).
    // points и wins не всегда нужны, поэтому JSON собирается вручную (JsonUtility пишет все поля).
    public class ResultEntryData
    {
        public string participant_code;
        public string outcome;
        public float points;
        public int wins = -1; // -1: поле не пишется
        public string reason;

        public bool HasPoints { get { return outcome == NeurotlonProtocol.OutcomeCompleted; } }
        public bool HasWins { get { return wins >= 0; } }
    }

    public class NeurotlonResultException : Exception
    {
        public NeurotlonResultException(string message) : base(message) { }
    }

    // Запись result.json: проверка правил лаунчера и сервера, затем временный файл и переименование.
    public static class NeurotlonResult
    {
        // Участник доиграл. wins только в понге: 1 у победителя, 0 у проигравшего.
        public static ResultEntryData Completed(string code, float points, int wins = -1)
        {
            return new ResultEntryData
            {
                participant_code = code,
                outcome = NeurotlonProtocol.OutcomeCompleted,
                points = points,
                wins = wins,
            };
        }

        public static ResultEntryData NotCompleted(string code, string reason = NeurotlonProtocol.NotDoneEquipment)
        {
            return new ResultEntryData
            {
                participant_code = code,
                outcome = NeurotlonProtocol.OutcomeNotCompleted,
                reason = reason,
            };
        }

        public static void WriteFinished(NeurotlonLaunch launch, IList<ResultEntryData> entries)
        {
            string problem = EntriesProblem(launch, entries);
            if (problem != null) throw new NeurotlonResultException(problem);
            var sb = new StringBuilder();
            sb.Append("{\"protocol\":").Append(NeurotlonProtocol.ProtocolVersion);
            sb.Append(",\"session_id\":").Append(Quote(launch.SessionId));
            sb.Append(",\"status\":").Append(Quote(NeurotlonProtocol.ResultStatusFinished));
            sb.Append(",\"entries\":[");
            for (int i = 0; i < entries.Count; i++)
            {
                if (i > 0) sb.Append(',');
                AppendEntry(sb, entries[i]);
            }
            sb.Append("]}");
            WriteAtomic(launch.ResultPath, sb.ToString());
        }

        public static void WriteAborted(NeurotlonLaunch launch, string reason)
        {
            if (string.IsNullOrEmpty(reason)) reason = "прервано";
            if (reason.Length > NeurotlonProtocol.ResultReasonMaxLength)
            {
                reason = reason.Substring(0, NeurotlonProtocol.ResultReasonMaxLength);
            }
            var sb = new StringBuilder();
            sb.Append("{\"protocol\":").Append(NeurotlonProtocol.ProtocolVersion);
            sb.Append(",\"session_id\":").Append(Quote(launch.SessionId));
            sb.Append(",\"status\":").Append(Quote(NeurotlonProtocol.ResultStatusAborted));
            sb.Append(",\"entries\":[],\"reason\":").Append(Quote(reason)).Append('}');
            WriteAtomic(launch.ResultPath, sb.ToString());
        }

        // Правила как в neurotlon_games.contract; null, если всё в порядке.
        public static string EntriesProblem(NeurotlonLaunch launch, IList<ResultEntryData> entries)
        {
            int expected = launch.IsPong ? 2 : 1;
            if (entries == null || entries.Count != expected)
                return launch.Discipline + ": нужно ровно " + expected + " участник(ов) в результате";
            var seen = new HashSet<string>();
            foreach (var e in entries)
            {
                if (!seen.Add(e.participant_code)) return "участник " + e.participant_code + " повторяется";
            }
            foreach (var p in launch.Participants)
            {
                if (!seen.Contains(p.code)) return "в результате нет участника " + p.code;
            }
            foreach (var e in entries)
            {
                string problem = EntryProblem(launch, e);
                if (problem != null) return problem;
            }
            return launch.IsPong ? PongWinnerProblem(entries) : null;
        }

        static string EntryProblem(NeurotlonLaunch launch, ResultEntryData e)
        {
            if (e.outcome == NeurotlonProtocol.OutcomeCompleted)
            {
                if (float.IsNaN(e.points) || e.points < 0f || e.points > NeurotlonProtocol.ResultPointsMax)
                    return e.participant_code + ": points должно быть от 0 до 1000";
                if (e.HasWins && !launch.IsPong) return "wins допустимы только в понге, а не в " + launch.Discipline;
                if (e.HasWins && e.wins > 1) return e.participant_code + ": wins только 0 или 1";
                return null;
            }
            if (e.outcome != NeurotlonProtocol.OutcomeNotCompleted)
                return e.participant_code + ": неизвестный outcome " + e.outcome;
            if (e.HasWins) return e.participant_code + ": wins при not_completed не пишется";
            if (e.reason != NeurotlonProtocol.NotDoneParticipantRefused
                && e.reason != NeurotlonProtocol.NotDoneHealth
                && e.reason != NeurotlonProtocol.NotDoneEquipment
                && e.reason != NeurotlonProtocol.NotDoneNoShow
                && e.reason != NeurotlonProtocol.NotDoneOther)
                return e.participant_code + ": неизвестная причина " + e.reason;
            return null;
        }

        // Понг: если завершили оба, wins есть у обоих и ровно у одного равно 1.
        static string PongWinnerProblem(IList<ResultEntryData> entries)
        {
            int sum = 0;
            foreach (var e in entries)
            {
                if (e.outcome != NeurotlonProtocol.OutcomeCompleted) return null;
                if (!e.HasWins) return "понг: при двух завершивших wins есть у обоих, ровно у одного 1";
                sum += e.wins;
            }
            return sum == 1 ? null : "понг: при двух завершивших wins есть у обоих, ровно у одного 1";
        }

        static void AppendEntry(StringBuilder sb, ResultEntryData e)
        {
            sb.Append("{\"participant_code\":").Append(Quote(e.participant_code));
            sb.Append(",\"outcome\":").Append(Quote(e.outcome));
            if (e.HasPoints)
            {
                sb.Append(",\"points\":").Append(e.points.ToString("0.###", CultureInfo.InvariantCulture));
            }
            if (e.HasWins) sb.Append(",\"wins\":").Append(e.wins.ToString(CultureInfo.InvariantCulture));
            if (!string.IsNullOrEmpty(e.reason)) sb.Append(",\"reason\":").Append(Quote(e.reason));
            sb.Append('}');
        }

        public static string Quote(string value)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in value ?? "")
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }

        // Сначала временный файл рядом, потом переименование: лаунчер не прочитает недописанное.
        static void WriteAtomic(string path, string json)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, json, new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
        }
    }
}
