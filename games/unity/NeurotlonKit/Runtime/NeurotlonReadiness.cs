using System.Collections.Generic;

namespace Neurotlon
{
    // Готовность калибровки. Датчики калибрует лаунчер до запуска игры, игра калибровку не проводит и не просит:
    // она только проверяет, что мост объявил сигналы откалиброванными (hello.calibrated), и прерывается, если нет.
    // Какие сигналы нужны игре, определяет профиль дисциплины (NeurotlonProtocol.SignalsFor, Launch.Signals).
    // Те же правила и тексты у Python-SDK (neurotlon_games.sdk.app); значения сверяет games/tests/test_unity_kit.py.
    public static class NeurotlonReadiness
    {
        public const string NotCalibratedReason = "датчики не откалиброваны: пройдите калибровку в лаунчере";
        public const string CalibrationResetReason = "калибровка датчиков сброшена";

        // not_calibrated в sample дольше этого времени: мост перезапустился и потерял калибровку.
        public const float CalibrationLostSeconds = 2f;

        // Сигналы без калибровки. Пусто, если у моста нет функции calibration_state (старый мост: проверять нечем)
        // и если все сигналы либо в hello.calibrated, либо эмулируются (state emulated: калибровка не нужна).
        public static List<string> Uncalibrated(NeurotlonBridge bridge, string[] signals)
        {
            var missing = new List<string>();
            if (!bridge.Supports(NeurotlonProtocol.FeatureCalibrationState)) return missing;
            foreach (var name in signals)
            {
                if (bridge.Calibrated(name)) continue;
                if (bridge.State(name) == NeurotlonProtocol.SensorStateEmulated) continue;
                missing.Add(name);
            }
            return missing;
        }

        // Мост сейчас отдаёт хотя бы по одному из сигналов значение not_calibrated (калибровку стёрли).
        public static bool CalibrationLost(NeurotlonBridge bridge, string[] signals)
        {
            foreach (var name in signals)
            {
                var reading = bridge.Reading(name);
                if (reading != null && !reading.Value.Valid && reading.Value.Reason == NeurotlonProtocol.InvalidNotCalibrated)
                {
                    return true;
                }
            }
            return false;
        }
    }

    // Сколько секунд подряд калибровка потеряна. Update возвращает true, когда пора прерывать игру.
    public class NeurotlonCalibrationWatch
    {
        float lostFor;

        public float LostSeconds { get { return lostFor; } }

        public bool Update(float dt, bool lost)
        {
            if (!lost)
            {
                lostFor = 0f;
                return false;
            }
            lostFor += dt;
            return lostFor > NeurotlonReadiness.CalibrationLostSeconds;
        }

        public void Reset()
        {
            lostFor = 0f;
        }
    }
}
