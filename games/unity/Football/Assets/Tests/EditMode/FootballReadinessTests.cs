using NUnit.Framework;

namespace Neurotlon.Games.Football.Tests
{
    // Football требует откалиброванными сигналы своей дисциплины (eeg, emg); общая логика проверена в Darts.Tests.
    public class FootballReadinessTests
    {
        static NeurotlonBridge BridgeWith(string calibrated)
        {
            var bridge = new NeurotlonBridge("127.0.0.1", 0, () => 0.0);
            bridge.ApplyLine("{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"eeg\",\"state\":\"connected\"},{\"name\":\"emg\",\"state\":\"connected\"}],"
                + "\"features\":[\"burst\",\"emg_cycle\",\"calibration_state\"],\"calibrated\":" + calibrated + "}");
            return bridge;
        }

        static string[] Signals { get { return NeurotlonProtocol.SignalsFor(NeurotlonProtocol.DisciplineFootball); } }

        [Test]
        public void TheGameNeedsItsOwnSignals()
        {
            CollectionAssert.AreEqual(new[] { "eeg", "emg" }, Signals);
        }

        [Test]
        public void CalibratedSensorsStartTheGame()
        {
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(BridgeWith("[\"eeg\",\"emg\"]"), Signals));
        }

        [Test]
        public void WithoutCalibrationTheGameStopsWithTheLauncherHint()
        {
            var missing = NeurotlonReadiness.Uncalibrated(BridgeWith("[]"), Signals);
            CollectionAssert.AreEqual(Signals, missing);
            StringAssert.Contains("калибровку в лаунчере", NeurotlonReadiness.NotCalibratedReason);
        }

        [Test]
        public void AnyMissingSignalStopsTheGame()
        {
            var missing = NeurotlonReadiness.Uncalibrated(BridgeWith("[\"eeg\"]"), Signals);
            CollectionAssert.DoesNotContain(missing, "eeg");
            Assert.AreEqual(Signals.Length - 1, missing.Count);
        }
    }
}
