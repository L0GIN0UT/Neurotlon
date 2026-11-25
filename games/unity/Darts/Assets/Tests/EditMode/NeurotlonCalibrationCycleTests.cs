using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    // Шаги и тексты калибровки: cycle вместо rest + contract, если мост объявил emg_cycle; baseline 12 с с открытыми глазами.
    public class NeurotlonCalibrationCycleTests
    {
        static NeurotlonBridge BridgeWith(string features)
        {
            var bridge = new NeurotlonBridge("127.0.0.1", 0, () => 0.0);
            bridge.ApplyLine("{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"emg\",\"state\":\"emulated\"}]"
                + features + "}");
            return bridge;
        }

        static string[] StepNames(NeurotlonCalibration.Phase[] phases)
        {
            var names = new string[phases.Length];
            for (int i = 0; i < phases.Length; i++) names[i] = phases[i].Step;
            return names;
        }

        [Test]
        public void CycleIsChosenOnlyWhenBridgeAnnouncesIt()
        {
            var modern = new NeurotlonCalibration(BridgeWith(",\"features\":[\"burst\",\"emg_cycle\"]"), "darts");
            modern.Start();
            Assert.AreEqual(NeurotlonProtocol.StepCycle, modern.Current.Step);
            Assert.AreEqual(2, modern.PhaseCount);
            CollectionAssert.AreEqual(new[] { "cycle", "baseline" },
                StepNames(NeurotlonCalibration.PhasesFor("darts", true)));

            var old = new NeurotlonCalibration(BridgeWith(""), "darts");
            old.Start();
            Assert.AreEqual(NeurotlonProtocol.StepRest, old.Current.Step);
            Assert.AreEqual(3, old.PhaseCount);
            CollectionAssert.AreEqual(new[] { "rest", "contract", "baseline" },
                StepNames(NeurotlonCalibration.PhasesFor("darts", false)));
        }

        [Test]
        public void HelloBurstOnlyDoesNotSwitchToCycle()
        {
            var calibration = new NeurotlonCalibration(BridgeWith(",\"features\":[\"burst\"]"), "darts");
            calibration.Start();
            Assert.AreEqual(NeurotlonProtocol.StepRest, calibration.Current.Step);
        }

        [Test]
        public void PongRunsCycleOnBothSignals()
        {
            var phases = NeurotlonCalibration.PhasesFor(NeurotlonProtocol.DisciplinePong, true);
            Assert.AreEqual(1, phases.Length);
            Assert.AreEqual(NeurotlonProtocol.StepCycle, phases[0].Step);
            CollectionAssert.AreEqual(
                new[] { NeurotlonProtocol.SignalEmgLeft, NeurotlonProtocol.SignalEmgRight }, phases[0].Signals);
            var old = NeurotlonCalibration.PhasesFor(NeurotlonProtocol.DisciplinePong, false);
            CollectionAssert.AreEqual(new[] { "rest", "contract" }, StepNames(old));
        }

        [Test]
        public void CycleTextFollowsThePhase()
        {
            Assert.AreEqual(NeurotlonTexts.Tense,
                NeurotlonCalibration.Instruction(NeurotlonProtocol.StepCycle, 0.3f, NeurotlonProtocol.PhaseTense));
            Assert.AreEqual(NeurotlonTexts.Relax,
                NeurotlonCalibration.Instruction(NeurotlonProtocol.StepCycle, 0.3f, NeurotlonProtocol.PhaseRelax));
            Assert.AreEqual(NeurotlonTexts.Tense,
                NeurotlonCalibration.Instruction(NeurotlonProtocol.StepCycle, 0f, null), "до первого сообщения моста");
        }

        [Test]
        public void ProgressKeepsPhaseSegmentAndTimeLeft()
        {
            var bridge = BridgeWith(",\"features\":[\"emg_cycle\"]");
            bridge.ApplyLine("{\"type\":\"calibration\",\"signal\":\"emg\",\"step\":\"cycle\",\"status\":\"running\","
                + "\"progress\":0.3,\"segment\":2,\"phase\":\"relax\",\"phase_left_s\":3.5}");
            var progress = bridge.Calibration("emg");
            Assert.AreEqual(NeurotlonProtocol.PhaseRelax, progress.Phase);
            Assert.AreEqual(2, progress.Segment);
            Assert.AreEqual(3.5f, progress.PhaseLeftSeconds, 0.001f);
            Assert.AreEqual(0.3f, progress.Progress, 0.001f);
        }

        [Test]
        public void BaselineIsTwelveSecondsWithOpenEyes()
        {
            Assert.AreEqual(12f, NeurotlonCalibration.BaselineSeconds);
            Assert.AreEqual(NeurotlonTexts.BaselineLook, NeurotlonCalibration.TextBaseline);
            Assert.AreEqual("Расслабьтесь и смотрите на точку на экране", NeurotlonCalibration.TextBaseline);
            Assert.AreEqual(NeurotlonCalibration.TextBaseline,
                NeurotlonCalibration.Instruction(NeurotlonProtocol.StepBaseline, 0.5f));
            Assert.AreEqual(20f, NeurotlonCalibration.CycleSeconds);
        }

        [Test]
        public void KnownFailureReasonsAreHumanReadable()
        {
            Assert.AreEqual(NeurotlonTexts.CycleWeak,
                NeurotlonCalibration.HumanReason("сокращение слабое, нет отличия от покоя"));
            Assert.AreEqual(NeurotlonTexts.CycleNoSignal, NeurotlonCalibration.HumanReason("нет данных в покое"));
            Assert.AreEqual(NeurotlonTexts.CycleNoSignal, NeurotlonCalibration.HumanReason("нет данных при напряжении"));
            Assert.AreEqual("что-то новое", NeurotlonCalibration.HumanReason("что-то новое"));
        }

        [Test]
        public void PlayerTextsDoNotNameBodyParts()
        {
            string[] texts =
            {
                NeurotlonCalibration.TextRest, NeurotlonCalibration.TextSqueeze, NeurotlonCalibration.TextRelease,
                NeurotlonCalibration.TextBaseline, NeurotlonCalibration.TextWeak, NeurotlonCalibration.TextNoSignal,
            };
            foreach (var text in texts)
            {
                foreach (var word in new[] { "рук", "кулак", "ног" })
                {
                    StringAssert.DoesNotContain(word, text.ToLowerInvariant());
                }
            }
        }

        [Test]
        public void CalibrateMessageCarriesNoOwnSegments()
        {
            var json = NeurotlonBridge.CalibrateJson(NeurotlonProtocol.SignalEmg, NeurotlonProtocol.StepCycle);
            StringAssert.Contains("\"type\":\"calibrate\"", json);
            StringAssert.Contains("\"signal\":\"emg\"", json);
            StringAssert.Contains("\"step\":\"cycle\"", json);
            // JsonUtility пишет пустой массив и ноль; мост считает их отсутствующими (shared/bridge-protocol.md)
            StringAssert.Contains("\"segments\":[]", json);
            StringAssert.Contains("\"duration_s\":0", json);
        }
    }
}
