using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    // Готовность калибровки (общая логика кита для всех игр): строки hello и sample подаются прямо в разбор, без сокета.
    public class NeurotlonReadinessTests
    {
        const string Features = "\"features\":[\"burst\",\"emg_cycle\",\"calibration_state\"]";

        double now;

        NeurotlonBridge NewBridge()
        {
            now = 0;
            return new NeurotlonBridge("127.0.0.1", 0, () => now);
        }

        static string Hello(string state, string calibrated, string features = Features)
        {
            string text = "{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"eeg\",\"state\":\"" + state
                + "\"},{\"name\":\"emg\",\"state\":\"" + state + "\"}]";
            if (features != null) text += "," + features;
            if (calibrated != null) text += ",\"calibrated\":" + calibrated;
            return text + "}";
        }

        static string[] Signals { get { return NeurotlonProtocol.SignalsFor(NeurotlonProtocol.DisciplineDarts); } }

        [Test]
        public void CalibratedRealSensorsAreReady()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[\"eeg\",\"emg\"]"));
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void RealSensorsWithoutCalibrationAreNotReady()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[]"));
            CollectionAssert.AreEqual(new[] { "eeg", "emg" }, NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void ACalibratedListMissingFromHelloMeansNothingIsCalibrated()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", null));
            CollectionAssert.AreEqual(new[] { "eeg", "emg" }, NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void OneUncalibratedSensorIsEnoughToStop()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[\"emg\"]"));
            CollectionAssert.AreEqual(new[] { "eeg" }, NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void EmulatedSensorsNeedNoCalibration()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("emulated", "[]"));
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void AMixOfEmulatedAndRealChecksOnlyTheRealOne()
        {
            var bridge = NewBridge();
            bridge.ApplyLine("{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"eeg\",\"state\":\"emulated\"},"
                + "{\"name\":\"emg\",\"state\":\"connected\"}]," + Features + ",\"calibrated\":[]}");
            CollectionAssert.AreEqual(new[] { "emg" }, NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void AnOldBridgeWithoutCalibrationStateIsNotChecked()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", null, "\"features\":[\"burst\",\"emg_cycle\"]"));
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(bridge, Signals));
            bridge.ApplyLine(Hello("connected", null, null));
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(bridge, Signals));
        }

        [Test]
        public void ANewHelloAfterABridgeRestartReplacesTheCalibratedList()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[\"eeg\",\"emg\"]"));
            Assert.IsEmpty(NeurotlonReadiness.Uncalibrated(bridge, Signals));
            bridge.ApplyLine(NeurotlonBridge.DisconnectedMarker);
            bridge.ApplyLine(Hello("connected", "[]"));
            Assert.AreEqual(2, NeurotlonReadiness.Uncalibrated(bridge, Signals).Count);
        }

        [Test]
        public void NotCalibratedReadingsMeanTheCalibrationIsLost()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[\"eeg\",\"emg\"]"));
            bridge.ApplyLine("{\"type\":\"sample\",\"t_ms\":1000,\"signals\":{\"emg\":{\"value\":0,\"valid\":true}}}");
            Assert.IsFalse(NeurotlonReadiness.CalibrationLost(bridge, Signals));
            bridge.ApplyLine("{\"type\":\"sample\",\"t_ms\":1020,\"signals\":{\"emg\":{\"value\":0,\"valid\":false,\"reason\":\"not_calibrated\"}}}");
            Assert.IsTrue(NeurotlonReadiness.CalibrationLost(bridge, Signals));
            bridge.ApplyLine("{\"type\":\"sample\",\"t_ms\":1040,\"signals\":{\"emg\":{\"value\":0.4,\"valid\":true}}}");
            Assert.IsFalse(NeurotlonReadiness.CalibrationLost(bridge, Signals));
        }

        [Test]
        public void ArtifactAndStaleAreNotACalibrationLoss()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello("connected", "[\"eeg\",\"emg\"]"));
            bridge.ApplyLine("{\"type\":\"sample\",\"t_ms\":1000,\"signals\":{\"emg\":{\"value\":0,\"valid\":false,\"reason\":\"artifact\"}}}");
            Assert.IsFalse(NeurotlonReadiness.CalibrationLost(bridge, Signals));
            bridge.ApplyLine("{\"type\":\"sample\",\"t_ms\":1020,\"signals\":{\"emg\":{\"value\":0,\"valid\":false,\"reason\":\"not_calibrated\"}}}");
            now += NeurotlonBridge.StaleSeconds + 0.1;   // данные устарели: это потеря датчика (SensorLost), а не калибровки
            Assert.IsFalse(NeurotlonReadiness.CalibrationLost(bridge, Signals));
            CollectionAssert.Contains(bridge.LostSignals(Signals), "emg");
        }

        [Test]
        public void TheGameAbortsOnlyAfterMoreThanTwoSeconds()
        {
            var watch = new NeurotlonCalibrationWatch();
            Assert.IsFalse(watch.Update(1f, true));
            Assert.IsFalse(watch.Update(1f, true), "ровно две секунды ещё терпим");
            Assert.IsTrue(watch.Update(0.1f, true));
        }

        [Test]
        public void ARecoveredCalibrationResetsTheTimer()
        {
            var watch = new NeurotlonCalibrationWatch();
            Assert.IsFalse(watch.Update(1.9f, true));
            Assert.IsFalse(watch.Update(0.1f, false));
            Assert.AreEqual(0f, watch.LostSeconds);
            Assert.IsFalse(watch.Update(1.9f, true), "счёт пошёл заново");
            watch.Reset();
            Assert.AreEqual(0f, watch.LostSeconds);
        }

        [Test]
        public void TheReasonsAreWrittenForTheOperator()
        {
            Assert.AreEqual("датчики не откалиброваны: пройдите калибровку в лаунчере", NeurotlonReadiness.NotCalibratedReason);
            Assert.AreEqual("калибровка датчиков сброшена", NeurotlonReadiness.CalibrationResetReason);
            Assert.LessOrEqual(NeurotlonReadiness.NotCalibratedReason.Length, NeurotlonProtocol.ResultReasonMaxLength);
        }
    }
}
