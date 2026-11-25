"""Эмулированный мост для проверки: источник, который запоминает, что с ним делала игра.

Мост проверки ведёт себя как мост на реальных датчиках: состояние `connected`, а не `emulated`,
и значения `not_calibrated`, пока сигнал не откалиброван. Калибровку, как лаунчер перед игрой,
проводит сам `CheckBridge` до запуска игры; игра её не запускает.
"""

from __future__ import annotations

import threading
import time
from types import TracebackType

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.scripted import ScriptedInput
from neurotlon_bridge.server import FEATURES, BridgeServer, BridgeThread
from neurotlon_bridge.source import (
    PROFILES,
    BurstEvent,
    CalibrationProgress,
    CalibrationStep,
    Reading,
    Segment,
    SensorState,
)

CalibrationPlan = tuple[tuple[CalibrationStep, tuple[str, ...]], ...]
CALIBRATION_WAIT_S = 120.0  # на все шаги при скорости моста 1; дольше шаги не идут
CALIBRATION_POLL_S = 0.02


class CheckBridgeError(RuntimeError):
    """Мост проверки не смог подготовиться (например, калибровка не прошла)."""


def calibration_plan(profile: str) -> CalibrationPlan:
    """Шаги калибровки, как у лаунчера: ЭМГ шагом `cycle`, ЭЭГ шагом `baseline`.

    Ритм и длительность не задаём: берутся умолчания моста (`segments`, `duration_s` не передаются).
    """
    signals = PROFILES[profile]
    emg = tuple(s for s in signals if s != "eeg")
    plan: list[tuple[CalibrationStep, tuple[str, ...]]] = [("cycle", emg)]
    if "eeg" in signals:
        plan.append(("baseline", ("eeg",)))
    return tuple(plan)


class RecordingSource(EmulatedSource):
    """`EmulatedSource` + журнал: сколько раз сервер брал значения, какие шаги калибровки
    запускала игра и когда мост отправлял события `burst`.

    Шаги, которые проводит сам мост проверки (`calibrate_locally`), в журнал не попадают."""

    def __init__(self, profile: str, speed: float) -> None:
        super().__init__(profile, time.monotonic, speed)
        self.speed = speed
        self._calibrated: set[str] = set()
        self._calibrated_lock = threading.Lock()
        self.burst_times: list[float] = []
        self.reads = 0
        self.first_read_at: float | None = None
        self.calibrations: list[tuple[str, CalibrationStep]] = []
        self.last_calibration_at: float | None = None

    def read(self, now_ms: int) -> dict[str, Reading]:
        # сервер зовёт `read` только для подключённого клиента
        if self.first_read_at is None:
            self.first_read_at = time.monotonic()
        self.reads += 1
        readings = super().read(now_ms)
        with self._calibrated_lock:
            calibrated = set(self._calibrated)
        return {
            name: reading if name in calibrated else Reading(0.0, False, "not_calibrated")
            for name, reading in readings.items()
        }

    def state(self, signal: str) -> SensorState:
        super().state(signal)  # проверка имени
        return "connected"  # как реальный датчик: игра не получает поблажки `emulated`

    def is_calibrated(self, signal: str) -> bool:
        self._check(signal)
        with self._calibrated_lock:
            return signal in self._calibrated

    def calibration_status(self, signal: str) -> CalibrationProgress | None:
        status = super().calibration_status(signal)
        if status is not None and status.status == "done":
            with self._calibrated_lock:
                self._calibrated.add(signal)
        return status

    def reset(self) -> None:
        with self._calibrated_lock:
            self._calibrated.clear()
        super().reset()

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        events = super().drain_bursts(signal)
        now = time.monotonic()
        self.burst_times.extend(now for _ in events)
        return events

    def bursts_between(self, start: float, end: float) -> int:
        """Сколько событий `burst` мост отдал серверу за промежуток (монотонные секунды)."""
        return sum(start <= t <= end for t in list(self.burst_times))

    def calibrate_locally(self, signal: str, step: CalibrationStep) -> None:
        """Запустить шаг от имени «лаунчера»: игра его не видит в `calibrations`."""
        EmulatedSource.start_calibration(self, signal, step)

    def start_calibration(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.calibrations.append((signal, step))
        self.last_calibration_at = time.monotonic()
        super().start_calibration(signal, step, segments, duration_s)


BRIDGE_FEATURES = FEATURES
"""Что объявляет мост проверки в `hello.features`: те же функции, что у настоящего."""


class CheckBridge:
    """Мост на свободном порту + сценарий ввода; контекстный менеджер.

    `calibrate=True`: перед запуском игры мост калибрует сигналы (как лаунчер), игра видит их
    готовыми. `calibrate=False`: калибровки нет, как на стенде, где её пропустили."""

    def __init__(self, profile: str, speed: float, *, calibrate: bool = True) -> None:
        self.source = RecordingSource(profile, speed)
        self._profile = profile
        self._calibrate = calibrate
        self._server = BridgeServer(self.source, port=0)
        self._thread = BridgeThread(self._server)
        self._input = ScriptedInput(self.source, profile)
        self._serving = False
        self._port = 0

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return "127.0.0.1"

    def __enter__(self) -> CheckBridge:
        self._thread.start()
        self._port = self._server.port
        self._serving = True
        try:
            if self._calibrate:
                self._run_calibration()
        except BaseException:
            self.stop_serving()
            raise
        self._input.start()  # сценарий идёт от начала игры, а не от начала калибровки
        return self

    def _run_calibration(self) -> None:
        deadline = time.monotonic() + CALIBRATION_WAIT_S / self.source.speed + 10.0
        for step, signals in calibration_plan(self._profile):
            for signal in signals:
                self.source.calibrate_locally(signal, step)
            pending = set(signals)
            while pending:
                for signal in tuple(pending):
                    status = self.source.calibration_status(signal)
                    if status is not None and status.status == "failed":
                        raise CheckBridgeError(f"{signal}/{step}: {status.reason}")
                    if status is not None and status.status == "done":
                        pending.discard(signal)
                if pending and time.monotonic() > deadline:
                    raise CheckBridgeError(f"калибровка {step} не завершилась вовремя")
                if pending:
                    time.sleep(CALIBRATION_POLL_S)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._input.stop()
        self.stop_serving()

    def stop_serving(self) -> None:
        """Закрыть порт и оборвать соединение: для игры это потеря датчиков."""
        if self._serving:
            self._serving = False
            self._thread.stop()
