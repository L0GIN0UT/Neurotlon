using System;

namespace Neurotlon.Games.Football
{
    // Запуск удара по событию `burst` (резкое сокращение). Событие только запускает удар: сила, скорость и точность от него
    // не зависят. Чистый класс без Unity: мост подаётся тремя делегатами (BurstSupported, TryTakeBurst, DiscardBursts).
    public sealed class KickTrigger
    {
        readonly Func<bool> supported;
        readonly Func<bool> take;
        readonly Action discard;

        public KickTrigger(Func<bool> supported, Func<bool> take, Action discard)
        {
            this.supported = supported;
            this.take = take;
            this.discard = discard;
        }

        // Мост умеет `burst`: удар по событию. Иначе работает старый порог уровня emg.
        public bool BurstMode { get { return supported(); } }

        // Звать каждый кадр. ready: игра готова к удару сейчас. Не готова: накопленные события выбрасываются, чтобы удар
        // не сработал позже по старому событию. Готова и событие есть: true (ровно один удар), остальные события выброшены.
        public bool Poll(bool ready)
        {
            if (!supported()) return false;
            if (!ready)
            {
                discard();
                return false;
            }
            if (!take()) return false;
            discard();
            return true;
        }
    }
}
