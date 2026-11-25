// Константы контрактов shared/game-launch.* и shared/bridge-protocol.*.
// Значения проверяет тест games/tests/test_unity_kit.py: менять только вместе со схемами.
namespace Neurotlon
{
    public static class NeurotlonProtocol
    {
        public const int ProtocolVersion = 1;

        // Сигналы моста (SignalName)
        public const string SignalEeg = "eeg";
        public const string SignalEmg = "emg";
        public const string SignalEmgLeft = "emg_left";
        public const string SignalEmgRight = "emg_right";

        // Шаги калибровки (CalibrationStep)
        public const string StepRest = "rest";
        public const string StepContract = "contract";
        public const string StepCycle = "cycle";
        public const string StepBaseline = "baseline";

        // Фазы шага cycle (Phase)
        public const string PhaseTense = "tense";
        public const string PhaseRelax = "relax";

        // Возможности моста (Feature, hello.features)
        public const string FeatureBurst = "burst";
        public const string FeatureEmgCycle = "emg_cycle";
        public const string FeatureBaselineDuration = "baseline_duration";

        // Метод обработки ЭЭГ (EegMethod)
        public const string EegMethodEmotions = "emotions";
        public const string EegMethodAlpha = "alpha";

        // Состояние датчика (SensorState)
        public const string SensorStateConnecting = "connecting";
        public const string SensorStateConnected = "connected";
        public const string SensorStateDisconnected = "disconnected";
        public const string SensorStateEmulated = "emulated";

        // Почему значение нельзя использовать (InvalidReason)
        public const string InvalidArtifact = "artifact";
        public const string InvalidNoContact = "no_contact";
        public const string InvalidDisconnected = "disconnected";
        public const string InvalidStale = "stale";
        public const string InvalidNotCalibrated = "not_calibrated";

        // Ход калибровки (Calibration.status)
        public const string CalibStatusRunning = "running";
        public const string CalibStatusDone = "done";
        public const string CalibStatusFailed = "failed";

        // Дисциплины (Discipline)
        public const string DisciplineDarts = "darts";
        public const string DisciplineFootball = "football";
        public const string DisciplinePong = "pong";

        // Стороны в понге (Participant.side)
        public const string SideLeft = "left";
        public const string SideRight = "right";

        // Результат (Result.status, Entry.outcome, Entry.reason)
        public const string ResultStatusFinished = "finished";
        public const string ResultStatusAborted = "aborted";
        public const string OutcomeCompleted = "completed";
        public const string OutcomeNotCompleted = "not_completed";
        public const string NotDoneParticipantRefused = "participant_refused";
        public const string NotDoneHealth = "health";
        public const string NotDoneEquipment = "equipment";
        public const string NotDoneNoShow = "no_show";
        public const string NotDoneOther = "other";

        // Типы сообщений
        public const string MessageHello = "hello";
        public const string MessageSample = "sample";
        public const string MessageSensor = "sensor";
        public const string MessageCalibration = "calibration";
        public const string MessageBurst = "burst";
        public const string MessageCalibrate = "calibrate";
        public const string MessageReset = "reset";

        // Лимиты схемы Result
        public const int ResultReasonMaxLength = 200;
        public const int ResultPointsMax = 1000;
        public const int MaxPointsMax = 1000;
        public const int DurationMinSeconds = 10;
        public const int DurationMaxSeconds = 3600;

        public static string[] SignalsFor(string discipline)
        {
            if (discipline == DisciplinePong)
            {
                return new[] { SignalEmgLeft, SignalEmgRight };
            }
            return new[] { SignalEeg, SignalEmg };
        }
    }
}
