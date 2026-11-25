using System.Collections.Generic;
using NUnit.Framework;

namespace Neurotlon.Games.Football.Tests
{
    public class KickTriggerTests
    {
        sealed class FakeBridge
        {
            public bool Supported = true;
            public int Pending;
            public int Discards;
            public bool Take()
            {
                if (Pending == 0) return false;
                Pending--;
                return true;
            }
            public void Discard() { Pending = 0; Discards++; }
            public KickTrigger Trigger() { return new KickTrigger(() => Supported, Take, Discard); }
        }

        static AimedElement NewKick(bool burst)
        {
            var e = new KickElement(new FootballTuning(), () => 0.5f);
            e.BurstMode = burst;
            return e;
        }

        [Test]
        public void EventLaunchesExactlyOneKick()
        {
            var bridge = new FakeBridge { Pending = 1 };
            var trigger = bridge.Trigger();
            var kick = NewKick(true);
            int kicks = 0;
            kick.Raised += ev => { if (ev.Kind == FootballEventKind.Kick) kicks++; };
            for (int i = 0; i < 5; i++)
            {
                if (trigger.Poll(kick.ReadyForKick)) kick.RequestKick();
                kick.Step(0.02f, 0.5f, 0.0f);
            }
            Assert.AreEqual(1, kicks);
            Assert.AreEqual(AimedElement.PhaseKind.Flying, kick.Phase);
        }

        [Test]
        public void EventWhileNotReadyIsIgnoredAndDiscarded()
        {
            var bridge = new FakeBridge { Pending = 1 };
            var trigger = bridge.Trigger();
            Assert.IsFalse(trigger.Poll(false));
            Assert.AreEqual(0, bridge.Pending);
            Assert.IsFalse(trigger.Poll(true), "старое событие не должно запустить удар позже");
        }

        [Test]
        public void TwoEventsInOneFrameGiveOneKick()
        {
            var bridge = new FakeBridge { Pending = 2 };
            var trigger = bridge.Trigger();
            Assert.IsTrue(trigger.Poll(true));
            Assert.IsFalse(trigger.Poll(true));
            var kick = NewKick(true);
            Assert.IsTrue(kick.RequestKick());
            Assert.IsFalse(kick.RequestKick(), "второй запрос в том же кадре");
        }

        [Test]
        public void RequestOutsideAimingIsRejected()
        {
            var kick = NewKick(true);
            kick.RequestKick();
            kick.Step(0.02f, 0.5f, 0f);
            Assert.AreEqual(AimedElement.PhaseKind.Flying, kick.Phase);
            Assert.IsFalse(kick.ReadyForKick);
            Assert.IsFalse(kick.RequestKick());
            Assert.IsFalse(NewKick(false).RequestKick(), "без burst-режима запрос не принимается");
        }

        [Test]
        public void StrongLevelDoesNotKickInBurstMode()
        {
            var kick = NewKick(true);
            for (int i = 0; i < 100; i++) kick.Step(0.02f, 0.5f, 1.0f);
            Assert.AreEqual(AimedElement.PhaseKind.Aiming, kick.Phase);
        }

        [Test]
        public void OldBridgeKicksByLevelAsBefore()
        {
            var bridge = new FakeBridge { Supported = false, Pending = 1 };
            var trigger = bridge.Trigger();
            Assert.IsFalse(trigger.BurstMode);
            Assert.IsFalse(trigger.Poll(true));
            Assert.AreEqual(1, bridge.Pending, "старый мост: события не трогаем");
            var kick = NewKick(false);
            var kicks = new List<FootballEventKind>();
            kick.Raised += ev => kicks.Add(ev.Kind);
            kick.Step(0.02f, 0.5f, 0.0f);
            kick.Step(0.02f, 0.5f, 0.9f);
            Assert.Contains(FootballEventKind.Kick, kicks);
        }

        [Test]
        public void ShotHintNamesTheBurstOnlyWhenSupported()
        {
            StringAssert.StartsWith(FootballTutorial.BurstHint, FootballTutorial.TextFor(TutorialStep.Shot, DribbleMode.Throttle, true));
            StringAssert.StartsWith(NeurotlonTexts.Tense, FootballTutorial.TextFor(TutorialStep.Shot, DribbleMode.Throttle));
        }
    }
}
