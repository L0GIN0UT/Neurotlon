"""Эмулированный мост для проверки: источник, который запоминает, что с ним делала игра."""

from __future__ import annotations

import time
from types import TracebackType

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.scripted import ScriptedInput
from neurotlon_bridge.server import FEATURES, BridgeServer, BridgeThread
from neurotlon_bridge.source import BurstEvent, CalibrationStep, Reading, Segment


class RecordingSource(EmulatedSource):
    """`EmulatedSource` + журнал: сколько раз сервер брал значения, какие были шаги калибровки
    и когда мост отправлял события `burst`."""

    def __init__(self, profile: str, speed: float) -> None:
        super().__init__(profile, time.monotonic, speed)
        self.speed = speed
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
        return super().read(now_ms)

    def drain_bursts(self, signal: str) -> list[BurstEvent]:
        events = super().drain_bursts(signal)
        now = time.monotonic()
        self.burst_times.extend(now for _ in events)
        return events

    def bursts_between(self, start: float, end: float) -> int:
        """Сколько событий `burst` мост отдал серверу за промежуток (монотонные секунды)."""
        return sum(start <= t <= end for t in list(self.burst_times))

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
    """Мост на свободном порту + сценарий ввода; контекстный менеджер."""

    def __init__(self, profile: str, speed: float) -> None:
        self.source = RecordingSource(profile, speed)
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
        self._input.start()
        return self

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
