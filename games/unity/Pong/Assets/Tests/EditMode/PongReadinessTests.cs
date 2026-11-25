using NUnit.Framework;

namespace Neurotlon.Games.Pong.Tests
{
    // Pong требует откалиброванными сигналы своей дисциплины (emg_left, emg_right); общая логика проверена в Darts.Tests.
    public class PongReadinessTests
    {
        static NeurotlonBridge BridgeWith(string calibrated)
        {
            var bridge = new NeurotlonBridge("127.0.0.1", 0, () => 0.0);
            bridge.ApplyLine("{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"emg_left\",\"state\":\"connected\"},{\"name\":\"emg_right\",\"state\":\"connected\"}],"
                + "\"features\":[\"burst\",\"emg_cycle\",\"calibration_state\"],\"calibrated\":" + calibrated + "}");
            return bridge;
        }

        static string[] Signals { get { return NeurotlonProtocol.SignalsFor(NeurotlonProtocol.DisciplinePong); } }

        [Test]
        public void TheGameNeedsItsOwnSignals()
        {
            CollectionAssert.AreEqual(new[] { "emg_left", "emg_right" }, Signals);
        }

        [Test]
        public void CalibratedSensorsStartTheGame()
        {
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(BridgeWith("[\"emg_left\",\"emg_right\"]"), Signals));
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
            var missing = NeurotlonReadiness.Uncalibrated(BridgeWith("[\"emg_left\"]"), Signals);
            CollectionAssert.DoesNotContain(missing, "emg_left");
            Assert.AreEqual(Signals.Length - 1, missing.Count);
        }
    }
}
