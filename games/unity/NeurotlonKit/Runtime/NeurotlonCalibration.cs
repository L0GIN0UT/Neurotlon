using System.Collections.Generic;

namespace Neurotlon
{
    // Калибровка по протоколу моста. Те же шаги и тексты, что в Python-SDK (neurotlon_games.sdk.calibration):
    //   ЭМГ: rest 5 с покоя, затем contract 12 с = 3 x (3 с сжать + 1 с пауза);
    //   ЭЭГ: baseline 8 с с закрытыми глазами.
    // В понге emg_left и emg_right калибруются одновременно.
    // Сбой шага: один повтор, потом State == Failed (игра пишет aborted с FailureReason).
    public class NeurotlonCalibration
    {
        public const float RestSeconds = 5f;
        public const float ContractSeconds = 12f;
        public const float BaselineSeconds = 8f;
        public const float SqueezeSeconds = 3f;
        public const float PauseSeconds = 1f;
        public const int Retries = 1;
        public const float TimeoutFactor = 2f;
        public const float TimeoutExtraSeconds = 5f;

        public const string TextRest = "Расслабьте руку";
        public const string TextSqueeze = "Сожмите кулак";
        public const string TextRelease = "Отпустите";
        public const string TextBaseline = "Закройте глаза и расслабьтесь";
        public const string TextRetry = "Не получилось, повторяем шаг";

        public enum CalibrationState { Idle, Running, Done, Failed }

        public class Phase
        {
            public readonly string Step;
            public readonly string[] Signals;

            public Phase(string step, params string[] signals)
            {
                Step = step;
                Signals = signals;
            }
        }

        readonly NeurotlonBridge bridge;
        readonly Phase[] phases;
        readonly Dictionary<string, CalibrationProgress> stale = new Dictionary<string, CalibrationProgress>();
        readonly HashSet<string> fresh = new HashSet<string>();
        int index;
        int attempt;
        bool sent;
        float elapsed;

        public NeurotlonCalibration(NeurotlonBridge bridge, string discipline)
        {
            this.bridge = bridge;
            phases = PhasesFor(discipline);
        }

        public CalibrationState State { get; private set; }
        public string FailureReason { get; private set; }
        public float Progress { get; private set; }
        public int PhaseCount { get { return phases.Length; } }
        public int PhaseNumber { get { return System.Math.Min(index + 1, phases.Length); } }
        public bool Finished { get { return State == CalibrationState.Done || State == CalibrationState.Failed; } }
        public bool Retrying { get { return State == CalibrationState.Running && attempt > 0; } }
        public Phase Current { get { return State == CalibrationState.Running ? phases[index] : null; } }

        // Инструкция сейчас; пусто, если калибровка не идёт.
        public string Text
        {
            get { return Current == null ? "" : Instruction(Current.Step, Progress); }
        }

        public static Phase[] PhasesFor(string discipline)
        {
            if (discipline == NeurotlonProtocol.DisciplinePong)
            {
                var both = new[] { NeurotlonProtocol.SignalEmgLeft, NeurotlonProtocol.SignalEmgRight };
                return new[]
                {
                    new Phase(NeurotlonProtocol.StepRest, both),
                    new Phase(NeurotlonProtocol.StepContract, both),
                };
            }
            return new[]
            {
                new Phase(NeurotlonProtocol.StepRest, NeurotlonProtocol.SignalEmg),
                new Phase(NeurotlonProtocol.StepContract, NeurotlonProtocol.SignalEmg),
                new Phase(NeurotlonProtocol.StepBaseline, NeurotlonProtocol.SignalEeg),
            };
        }

        // Текст для игрока; ритм «сжать / отпустить» выводится из прогресса шага contract.
        public static string Instruction(string step, float progress)
        {
            if (step == NeurotlonProtocol.StepBaseline) return TextBaseline;
            if (step == NeurotlonProtocol.StepRest) return TextRest;
            float position = (progress * ContractSeconds) % (SqueezeSeconds + PauseSeconds);
            return position < SqueezeSeconds ? TextSqueeze : TextRelease;
        }

        public void Start()
        {
            index = 0;
            FailureReason = null;
            State = phases.Length == 0 ? CalibrationState.Done : CalibrationState.Running;
            attempt = 0;
            Restart();
        }

        // Каждый кадр, dt — реальное время кадра в секундах.
        public void Update(float dt)
        {
            if (State != CalibrationState.Running) return;
            elapsed += dt;
            var phase = phases[index];
            if (!sent)
            {
                sent = Send(phase);
                if (!sent)
                {
                    CheckTimeout(phase);
                    return;
                }
            }
            string failure = Poll(phase);
            if (failure != null) OnFailure(failure);
            else if (Progress >= 1f) NextPhase();
            else CheckTimeout(phase);
        }

        void Restart()
        {
            sent = false;
            elapsed = 0f;
            Progress = 0f;
        }

        bool Send(Phase phase)
        {
            // прогресс, который мост держит от прошлого запуска, за новый не считаем
            var before = new Dictionary<string, CalibrationProgress>();
            foreach (var s in phase.Signals) before[s] = bridge.Calibration(s);
            foreach (var s in phase.Signals)
            {
                if (!bridge.Calibrate(s, phase.Step)) return false;
            }
            stale.Clear();
            foreach (var pair in before) stale[pair.Key] = pair.Value;
            fresh.Clear();
            return true;
        }

        // Причина сбоя или null; обновляет Progress.
        string Poll(Phase phase)
        {
            float min = 1f;
            foreach (var name in phase.Signals)
            {
                var current = bridge.Calibration(name);
                CalibrationProgress old;
                stale.TryGetValue(name, out old);
                if (current != null && !current.SameAs(old)) fresh.Add(name); // мост ответил на новый запуск
                if (current == null || current.Step != phase.Step || !fresh.Contains(name))
                {
                    min = 0f;
                }
                else if (current.Status == NeurotlonProtocol.CalibStatusFailed)
                {
                    return string.IsNullOrEmpty(current.Reason)
                        ? name + ": калибровка не удалась"
                        : current.Reason;
                }
                else if (current.Status != NeurotlonProtocol.CalibStatusDone)
                {
                    min = System.Math.Min(min, current.Progress);
                }
            }
            Progress = min;
            return null;
        }

        void CheckTimeout(Phase phase)
        {
            float limit = StepSeconds(phase.Step) * TimeoutFactor + TimeoutExtraSeconds;
            if (elapsed > limit) OnFailure("мост не отвечает на калибровку");
        }

        static float StepSeconds(string step)
        {
            if (step == NeurotlonProtocol.StepContract) return ContractSeconds;
            if (step == NeurotlonProtocol.StepBaseline) return BaselineSeconds;
            return RestSeconds;
        }

        void OnFailure(string reason)
        {
            if (attempt < Retries)
            {
                attempt++;
                Restart();
                return;
            }
            FailureReason = reason;
            State = CalibrationState.Failed;
        }

        void NextPhase()
        {
            if (index + 1 >= phases.Length)
            {
                Progress = 1f;
                State = CalibrationState.Done;
                return;
            }
            index++;
            attempt = 0;
            Restart();
        }
    }
}
