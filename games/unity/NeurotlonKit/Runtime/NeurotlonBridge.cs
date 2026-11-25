using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace Neurotlon
{
    // Сообщения протокола моста (shared/bridge-protocol.md). Поля — как в схеме.
    [Serializable]
    public class BridgeEnvelope
    {
        public string type;
    }

    [Serializable]
    public class HelloSignal
    {
        public string name;
        public string state;
    }

    [Serializable]
    public class HelloMessage
    {
        public string type;
        public int protocol;
        public HelloSignal[] signals;
        public string[] features;
        public string eeg_method;
    }

    [Serializable]
    public class ReadingData
    {
        public float value;
        public bool valid;
        public string reason;
    }

    // JsonUtility не читает словари, поэтому четыре известных сигнала — отдельные поля.
    // Сигнала нет в сообщении, если valid == false и reason пустой.
    [Serializable]
    public class SampleSignals
    {
        public ReadingData eeg;
        public ReadingData emg;
        public ReadingData emg_left;
        public ReadingData emg_right;
    }

    [Serializable]
    public class SampleMessage
    {
        public string type;
        public long t_ms;
        public SampleSignals signals;
    }

    [Serializable]
    public class SensorMessage
    {
        public string type;
        public string signal;
        public string state;
        public int battery;
    }

    [Serializable]
    public class CalibrationMessage
    {
        public string type;
        public string signal;
        public string step;
        public string status;
        public float progress;
        public string reason;
        public int segment;
        public string phase;
        public float phase_left_s;
    }

    [Serializable]
    public class BurstMessage
    {
        public string type;
        public string signal;
        public long t_ms;
        public int seq;
        public float rise;
    }

    [Serializable]
    public class CalibrateSegment
    {
        public string phase;
        public float s;
    }

    [Serializable]
    public class CalibrateMessage
    {
        public string type;
        public string signal;
        public string step;
        public CalibrateSegment[] segments;
        public float duration_s;
    }

    [Serializable]
    public class ResetMessage
    {
        public string type;
    }

    // Последнее значение сигнала. Использовать можно, только если Valid.
    public struct SignalReading
    {
        public float Value;
        public bool Valid;
        public string Reason;
    }

    public class CalibrationProgress
    {
        public string Step;
        public string Status;
        public float Progress;
        public string Reason;

        public bool SameAs(CalibrationProgress other)
        {
            return other != null && Step == other.Step && Status == other.Status
                && Mathf.Approximately(Progress, other.Progress) && Reason == other.Reason;
        }
    }

    // Клиент BCI-моста: TCP + NDJSON в фоновом потоке, разбор — в главном (Pump).
    // Вызывайте Pump() каждый кадр (NeurotlonGame делает это сам).
    public class NeurotlonBridge : IDisposable
    {
        public const float StaleSeconds = 0.5f;
        public const float ReconnectSeconds = 1f;
        public const int MaxLineBytes = 64 * 1024;
        const int MaxQueued = 2000;
        const string ConnectedMarker = "\u0001connected";
        const string DisconnectedMarker = "\u0001disconnected";

        readonly string host;
        readonly int port;
        readonly ConcurrentQueue<string> lines = new ConcurrentQueue<string>();
        readonly object sendLock = new object();
        readonly Stopwatch clock = Stopwatch.StartNew();
        readonly Dictionary<string, SignalReading> readings = new Dictionary<string, SignalReading>();
        readonly Dictionary<string, double> receivedAt = new Dictionary<string, double>();
        readonly Dictionary<string, string> states = new Dictionary<string, string>();
        readonly Dictionary<string, CalibrationProgress> calibrations =
            new Dictionary<string, CalibrationProgress>();
        TcpClient client;
        Thread thread;
        volatile bool stopping;
        volatile bool connected;

        public NeurotlonBridge(string host, int port)
        {
            this.host = host;
            this.port = port;
        }

        public bool Connected { get { return connected; } }

        double Now { get { return clock.Elapsed.TotalSeconds; } }

        public void Start()
        {
            if (thread != null) return;
            thread = new Thread(Run) { IsBackground = true, Name = "neurotlon-bridge" };
            thread.Start();
        }

        // Разобрать пришедшие строки. Только из главного потока.
        public void Pump()
        {
            string line;
            while (lines.TryDequeue(out line))
            {
                if (line == ConnectedMarker) continue;
                if (line == DisconnectedMarker)
                {
                    readings.Clear();
                    receivedAt.Clear();
                    states.Clear();
                    calibrations.Clear();
                    continue;
                }
                Apply(line);
            }
        }

        // --- чтение состояния ---

        public SignalReading? Reading(string signal)
        {
            SignalReading reading;
            double at;
            if (!readings.TryGetValue(signal, out reading) || !receivedAt.TryGetValue(signal, out at))
            {
                return null;
            }
            if (Now - at > StaleSeconds)
            {
                return new SignalReading { Value = 0f, Valid = false, Reason = NeurotlonProtocol.InvalidStale };
            }
            return reading;
        }

        // Значение 0..1 или null: артефакт, нет контакта, данные старше 500 мс, нет связи.
        public float? Value(string signal)
        {
            var reading = Reading(signal);
            if (reading == null || !reading.Value.Valid) return null;
            return reading.Value.Value;
        }

        public string State(string signal)
        {
            string state;
            return states.TryGetValue(signal, out state) ? state : null;
        }

        public CalibrationProgress Calibration(string signal)
        {
            CalibrationProgress progress;
            return calibrations.TryGetValue(signal, out progress) ? progress : null;
        }

        // Связь есть и пришли состояния всех нужных датчиков (сообщение hello).
        public bool IsReady(string[] signals)
        {
            if (!connected) return false;
            foreach (var name in signals)
            {
                if (State(name) == null) return false;
            }
            return true;
        }

        // Сигналы, которых нет: мост не отвечает, датчик отключён или данные устарели.
        public List<string> LostSignals(string[] signals)
        {
            var lost = new List<string>();
            foreach (var name in signals)
            {
                var reading = Reading(name);
                bool staleOrGone = reading != null && !reading.Value.Valid
                    && (reading.Value.Reason == NeurotlonProtocol.InvalidDisconnected
                        || reading.Value.Reason == NeurotlonProtocol.InvalidStale);
                if (!connected || State(name) == NeurotlonProtocol.SensorStateDisconnected || staleOrGone)
                {
                    lost.Add(name);
                }
            }
            return lost;
        }

        // --- команды ---

        public bool Calibrate(string signal, string step)
        {
            return Send(JsonUtility.ToJson(new CalibrateMessage
            {
                type = NeurotlonProtocol.MessageCalibrate,
                signal = signal,
                step = step,
            }));
        }

        public bool Reset()
        {
            calibrations.Clear();
            return Send(JsonUtility.ToJson(new ResetMessage { type = NeurotlonProtocol.MessageReset }));
        }

        public void Dispose()
        {
            stopping = true;
            lock (sendLock)
            {
                if (client != null) client.Close();
            }
            if (thread != null) thread.Join(2000);
        }

        // --- разбор ---

        void Apply(string line)
        {
            try
            {
                string type = JsonUtility.FromJson<BridgeEnvelope>(line).type;
                switch (type)
                {
                    case NeurotlonProtocol.MessageHello: ApplyHello(JsonUtility.FromJson<HelloMessage>(line)); break;
                    case NeurotlonProtocol.MessageSample: ApplySample(JsonUtility.FromJson<SampleMessage>(line)); break;
                    case NeurotlonProtocol.MessageSensor: ApplySensor(JsonUtility.FromJson<SensorMessage>(line)); break;
                    case NeurotlonProtocol.MessageCalibration:
                        ApplyCalibration(JsonUtility.FromJson<CalibrationMessage>(line));
                        break;
                    // неизвестные сообщения игра игнорирует
                }
            }
            catch (ArgumentException)
            {
                // битая строка: пропускаем, как и клиент на Python
            }
        }

        void ApplyHello(HelloMessage hello)
        {
            if (hello.signals == null) return;
            states.Clear();
            foreach (var s in hello.signals) states[s.name] = s.state;
        }

        void ApplySample(SampleMessage sample)
        {
            if (sample.signals == null) return;
            Store(NeurotlonProtocol.SignalEeg, sample.signals.eeg);
            Store(NeurotlonProtocol.SignalEmg, sample.signals.emg);
            Store(NeurotlonProtocol.SignalEmgLeft, sample.signals.emg_left);
            Store(NeurotlonProtocol.SignalEmgRight, sample.signals.emg_right);
        }

        void Store(string name, ReadingData data)
        {
            if (data == null) return;
            bool absent = !data.valid && string.IsNullOrEmpty(data.reason);
            if (absent) return;
            readings[name] = new SignalReading
            {
                Value = Mathf.Clamp01(data.value),
                Valid = data.valid,
                Reason = data.valid ? null : data.reason,
            };
            receivedAt[name] = Now;
        }

        void ApplySensor(SensorMessage sensor)
        {
            if (!string.IsNullOrEmpty(sensor.signal)) states[sensor.signal] = sensor.state;
        }

        void ApplyCalibration(CalibrationMessage msg)
        {
            if (string.IsNullOrEmpty(msg.signal)) return;
            float progress = msg.status == NeurotlonProtocol.CalibStatusDone ? 1f : msg.progress;
            calibrations[msg.signal] = new CalibrationProgress
            {
                Step = msg.step,
                Status = msg.status,
                Progress = Mathf.Clamp01(progress),
                Reason = string.IsNullOrEmpty(msg.reason) ? null : msg.reason,
            };
        }

        // --- фоновый поток ---

        bool Send(string json)
        {
            lock (sendLock)
            {
                if (client == null || !client.Connected) return false;
                try
                {
                    byte[] data = Encoding.UTF8.GetBytes(json + "\n");
                    client.GetStream().Write(data, 0, data.Length);
                    return true;
                }
                catch (Exception)
                {
                    return false;
                }
            }
        }

        void Run()
        {
            while (!stopping)
            {
                TcpClient current = null;
                try
                {
                    current = new TcpClient { NoDelay = true };
                    current.Connect(host, port);
                    lock (sendLock) { client = current; }
                    connected = true;
                    Enqueue(ConnectedMarker);
                    ReadLoop(current);
                }
                catch (Exception)
                {
                    // мост не запущен или связь оборвалась: ниже пауза и новая попытка
                }
                finally
                {
                    bool was = connected;
                    connected = false;
                    lock (sendLock) { client = null; }
                    if (current != null) current.Close();
                    if (was) Enqueue(DisconnectedMarker);
                }
                for (float waited = 0f; waited < ReconnectSeconds && !stopping; waited += 0.1f)
                {
                    Thread.Sleep(100);
                }
            }
        }

        void ReadLoop(TcpClient current)
        {
            var socket = current.Client;
            var stream = current.GetStream();
            var chunk = new byte[4096];
            var pending = new List<byte>();
            while (!stopping)
            {
                if (!socket.Poll(200000, SelectMode.SelectRead)) continue;
                int count = stream.Read(chunk, 0, chunk.Length);
                if (count == 0) return; // мост закрыл соединение
                for (int i = 0; i < count; i++)
                {
                    if (chunk[i] == (byte)'\n')
                    {
                        if (pending.Count > 0) Enqueue(Encoding.UTF8.GetString(pending.ToArray()));
                        pending.Clear();
                    }
                    else
                    {
                        pending.Add(chunk[i]);
                        if (pending.Count > MaxLineBytes) return; // защита от мусора
                    }
                }
            }
        }

        void Enqueue(string line)
        {
            lines.Enqueue(line);
            string dropped;
            while (lines.Count > MaxQueued) lines.TryDequeue(out dropped);
        }
    }
}
