using NUnit.Framework;

namespace Neurotlon.Games.Darts.Tests
{
    // Разбор hello.features и очередь событий burst в клиенте моста: строки JSON подаются прямо в разбор, без сокета.
    public class NeurotlonBridgeBurstTests
    {
        const string Emg = NeurotlonProtocol.SignalEmg;

        double now;

        NeurotlonBridge NewBridge()
        {
            now = 0;
            return new NeurotlonBridge("127.0.0.1", 0, () => now);
        }

        static string Hello(string features)
        {
            return "{\"type\":\"hello\",\"protocol\":1,\"signals\":[{\"name\":\"emg\",\"state\":\"emulated\"}]"
                + features + "}";
        }

        static string Burst(int seq, long tMs, string signal = Emg)
        {
            return "{\"type\":\"burst\",\"signal\":\"" + signal + "\",\"t_ms\":" + tMs + ",\"seq\":" + seq + ",\"rise\":0.8}";
        }

        NeurotlonBridge WithBurstSupport()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello(",\"features\":[\"burst\",\"emg_cycle\"],\"eeg_method\":\"alpha\""));
            return bridge;
        }

        [Test]
        public void EventIsQueuedAndTakenExactlyOnce()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void EachCallTakesOneOfSeveralEvents()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            bridge.ApplyLine(Burst(2, 1200));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void DuplicateSeqIsIgnored()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            bridge.ApplyLine(Burst(1, 1000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void OldSeqIsIgnored()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(5, 1000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            bridge.ApplyLine(Burst(4, 1100));
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void EventWithEarlierTimeIsIgnored()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 2000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
            bridge.ApplyLine(Burst(2, 1500));
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
            bridge.ApplyLine(Burst(3, 2000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg), "равное t_ms допустимо, важен seq");
        }

        [Test]
        public void SignalsKeepSeparateCounters()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000, NeurotlonProtocol.SignalEmgLeft));
            bridge.ApplyLine(Burst(1, 1000, NeurotlonProtocol.SignalEmgRight));
            Assert.IsTrue(bridge.TryTakeBurst(NeurotlonProtocol.SignalEmgLeft));
            Assert.IsTrue(bridge.TryTakeBurst(NeurotlonProtocol.SignalEmgRight));
        }

        [Test]
        public void DiscardClearsAccumulatedEvents()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            bridge.ApplyLine(Burst(2, 1200));
            bridge.DiscardBursts(Emg);
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
            bridge.ApplyLine(Burst(3, 1400));
            Assert.IsTrue(bridge.TryTakeBurst(Emg), "после выброса новые события принимаются");
        }

        [Test]
        public void StaleEventIsDroppedOnTake()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            now += NeurotlonBridge.StaleSeconds + 0.1;
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void FreshEventSurvivesBelowStaleLimit()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(1, 1000));
            now += NeurotlonBridge.StaleSeconds - 0.1;
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void QueueIsBounded()
        {
            var bridge = WithBurstSupport();
            for (int i = 1; i <= NeurotlonBridge.MaxBursts + 5; i++) bridge.ApplyLine(Burst(i, 1000 + i));
            int taken = 0;
            while (bridge.TryTakeBurst(Emg)) taken++;
            Assert.AreEqual(NeurotlonBridge.MaxBursts, taken);
        }

        [Test]
        public void HelloWithoutBurstMeansNotSupported()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello(",\"features\":[\"emg_cycle\"]"));
            Assert.IsFalse(bridge.BurstSupported);
            Assert.IsTrue(bridge.Supports(NeurotlonProtocol.FeatureEmgCycle));
        }

        [Test]
        public void OldBridgeWithoutFeaturesSupportsNothing()
        {
            var bridge = NewBridge();
            bridge.ApplyLine(Hello(""));
            Assert.IsFalse(bridge.BurstSupported);
            Assert.IsFalse(bridge.Supports(NeurotlonProtocol.FeatureEmgCycle));
            Assert.IsFalse(bridge.Supports(NeurotlonProtocol.FeatureBaselineDuration));
            Assert.IsNull(bridge.EegMethod);
        }

        [Test]
        public void HelloReportsFeaturesAndEegMethod()
        {
            var bridge = WithBurstSupport();
            Assert.IsTrue(bridge.BurstSupported);
            Assert.IsTrue(bridge.Supports(NeurotlonProtocol.FeatureEmgCycle));
            Assert.IsFalse(bridge.Supports(NeurotlonProtocol.FeatureBaselineDuration));
            Assert.AreEqual(NeurotlonProtocol.EegMethodAlpha, bridge.EegMethod);
        }

        [Test]
        public void NewHelloResetsSeqAndQueue()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(7, 5000));
            bridge.ApplyLine(Burst(8, 5200));
            bridge.ApplyLine(Hello(",\"features\":[\"burst\"]"));
            Assert.IsFalse(bridge.TryTakeBurst(Emg), "очередь прежнего подключения сброшена");
            bridge.ApplyLine(Burst(1, 100));
            Assert.IsTrue(bridge.TryTakeBurst(Emg), "seq и t_ms начались заново");
        }

        [Test]
        public void ConnectionLossResetsEverything()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine(Burst(3, 3000));
            bridge.ApplyLine(NeurotlonBridge.DisconnectedMarker);
            Assert.IsFalse(bridge.TryTakeBurst(Emg));
            Assert.IsFalse(bridge.BurstSupported);
            Assert.IsNull(bridge.EegMethod);
            bridge.ApplyLine(Hello(",\"features\":[\"burst\"]"));
            bridge.ApplyLine(Burst(1, 50));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
        }

        [Test]
        public void BrokenLinesAreSkipped()
        {
            var bridge = WithBurstSupport();
            bridge.ApplyLine("{not json");
            bridge.ApplyLine(Burst(1, 1000));
            Assert.IsTrue(bridge.TryTakeBurst(Emg));
        }
    }
}
