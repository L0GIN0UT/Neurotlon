using System.Collections.Generic;

namespace Neurotlon
{
    // Калибровка по протоколу моста. Те же шаги и тексты, что в Python-SDK (neurotlon_games.sdk.calibration):
    //   ЭМГ: если мост объявил emg_cycle, один шаг cycle (20 с, ритм по умолчанию 5/5/5/5 напрячь/расслабить),
    //        иначе rest 5 с покоя и contract 12 с = 3 x (3 с напрячь + 1 с пауза);
    //   ЭЭГ: baseline 12 с, глаза открыты, взгляд на точку.
    // В понге emg_left и emg_right калибруются одновременно.
    // Сбой шага: один повтор, потом State == Failed (игра пишет aborted с FailureReason).
    public class NeurotlonCalibration
    {
        public const float RestSeconds = 5f;
        public const float ContractSeconds = 12f;
        public const float CycleSeconds = 20f;
        public const float BaselineSeconds = 12f;
        public const float SqueezeSeconds = 3f;
        public const float PauseSeconds = 1f;
        public const int Retries = 1;
        public const float TimeoutFactor = 2f;
        public const float TimeoutExtraSeconds = 5f;

        public const string TextRest = NeurotlonTexts.Relax;
        public const string TextSqueeze = NeurotlonTexts.Tense;
        public const string TextRelease = NeurotlonTexts.RelaxShort;
        public const string TextBaseline = NeurotlonTexts.BaselineLook;
        public const string TextWeak = NeurotlonTexts.CycleWeak;
        public const string TextNoSignal = NeurotlonTexts.CycleNoSignal;
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
        readonly string discipline;
        Phase[] phases;
        readonly Dictionary<string, CalibrationProgress> stale = new Dictionary<string, CalibrationProgress>();
        readonly HashSet<string> fresh = new HashSet<string>();
        int index;
        int attempt;
        bool sent;
        float elapsed;

        public NeurotlonCalibration(NeurotlonBridge bridge, string discipline)
        {
            this.bridge = bridge;
            this.discipline = discipline;
            phases = PhasesFor(discipline, bridge.Supports(NeurotlonProtocol.FeatureEmgCycle));
        }

        public CalibrationState State { get; private set; }
        public string FailureReason { get; private set; }
        public float Progress { get; private set; }
        public int PhaseCount { get { return phases.Length; } }
        public int PhaseNumber { get { return System.Math.Min(index + 1, phases.Length); } }
        public bool Finished { get { return State == CalibrationState.Done || State == CalibrationState.Failed; } }
        public bool Retrying { get { return State == CalibrationState.Running && attempt > 0; } }
        public Phase Current { get { return State == CalibrationState.Running ? phases[index] : null; } }

        // Только у шага cycle, по последнему сообщению моста: фаза (tense / relax), номер отрезка с единицы
        // и сколько секунд фазе осталось. Вне cycle: null, 0, 0.
        public string CyclePhase { get; private set; }
        public int CycleSegment { get; private set; }
        public float PhaseLeftSeconds { get; private set; }

        // Причина последнего сбоя шага человеческим текстом, пока идёт повтор; иначе null.
        public string RetryReason { get; private set; }

        // Во время baseline на экране рисуется точка, на которую надо смотреть.
        public bool ShowsDot
        {
            get { return Current != null && Current.Step == NeurotlonProtocol.StepBaseline; }
        }

        // Инструкция сейчас; пусто, если калибровка не идёт.
        public string Text
        {
            get { return Current == null ? "" : Instruction(Current.Step, Progress, CyclePhase); }
        }

        public static Phase[] PhasesFor(string discipline)
        {
            return PhasesFor(discipline, false);
        }

        // emgCycle — мост объявил emg_cycle: ЭМГ калибруется одним шагом cycle вместо rest и contract.
        public static Phase[] PhasesFor(string discipline, bool emgCycle)
        {
            bool pong = discipline == NeurotlonProtocol.DisciplinePong;
            string[] emg = pong
                ? new[] { NeurotlonProtocol.SignalEmgLeft, NeurotlonProtocol.SignalEmgRight }
                : new[] { NeurotlonProtocol.SignalEmg };
            var list = new List<Phase>();
            if (emgCycle)
            {
                list.Add(new Phase(NeurotlonProtocol.StepCycle, emg));
            }
            else
            {
                list.Add(new Phase(NeurotlonProtocol.StepRest, emg));
                list.Add(new Phase(NeurotlonProtocol.StepContract, emg));
            }
            if (!pong) list.Add(new Phase(NeurotlonProtocol.StepBaseline, NeurotlonProtocol.SignalEeg));
            return list.ToArray();
        }

        // Текст для игрока; ритм шага contract выводится из прогресса, у cycle фазу сообщает мост.
        public static string Instruction(string step, float progress)
        {
            return Instruction(step, progress, null);
        }

        public static string Instruction(string step, float progress, string cyclePhase)
        {
            if (step == NeurotlonProtocol.StepBaseline) return TextBaseline;
            if (step == NeurotlonProtocol.StepRest) return TextRest;
            if (step == NeurotlonProtocol.StepCycle)
            {
                return cyclePhase == NeurotlonProtocol.PhaseRelax ? TextRest : TextSqueeze;
            }
            float position = (progress * ContractSeconds) % (SqueezeSeconds + PauseSeconds);
            return position < SqueezeSeconds ? TextSqueeze : TextRelease;
        }

        // Причина сбоя от моста для экрана: известные причины по-человечески, остальные как есть.
        public static string HumanReason(string reason)
        {
            switch (reason)
            {
                case "сокращение слабое, нет отличия от покоя": return TextWeak;
                case "нет данных в покое":
                case "нет данных при напряжении": return TextNoSignal;
                default: return reason;
            }
        }

        public void Start()
        {
            // hello уже пришёл (игра ждёт состояния датчиков), поэтому возможности моста известны
            phases = PhasesFor(discipline, bridge.Supports(NeurotlonProtocol.FeatureEmgCycle));
            index = 0;
            FailureReason = null;
            RetryReason = null;
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
            CyclePhase = null;
            CycleSegment = 0;
            PhaseLeftSeconds = 0f;
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
            bool first = true;
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
                    // у понга два датчика идут в одном ритме: показываем фазу первого
                    if (first && phase.Step == NeurotlonProtocol.StepCycle) TakeCyclePosition(current);
                }
                first = false;
            }
            Progress = min;
            return null;
        }

        void TakeCyclePosition(CalibrationProgress current)
        {
            CyclePhase = current.Phase;
            CycleSegment = current.Segment;
            PhaseLeftSeconds = current.PhaseLeftSeconds;
        }

        void CheckTimeout(Phase phase)
        {
            float limit = StepSeconds(phase.Step) * TimeoutFactor + TimeoutExtraSeconds;
            if (elapsed > limit) OnFailure("мост не отвечает на калибровку");
        }

        static float StepSeconds(string step)
        {
            if (step == NeurotlonProtocol.StepCycle) return CycleSeconds;
            if (step == NeurotlonProtocol.StepContract) return ContractSeconds;
            if (step == NeurotlonProtocol.StepBaseline) return BaselineSeconds;
            return RestSeconds;
        }

        void OnFailure(string reason)
        {
            if (attempt < Retries)
            {
                attempt++;
                RetryReason = HumanReason(reason);
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
            RetryReason = null;
            Restart();
        }
    }
}
