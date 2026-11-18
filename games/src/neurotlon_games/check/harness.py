"""Эмулированный мост для проверки: источник, который запоминает, что с ним делала игра."""

from __future__ import annotations

import time
from types import TracebackType

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.server import BridgeServer, BridgeThread
from neurotlon_bridge.source import CalibrationStep, Reading

from .scripted import ScriptedInput


class RecordingSource(EmulatedSource):
    """`EmulatedSource` + журнал: сколько раз сервер брал значения и какие были шаги калибровки."""

    def __init__(self, profile: str, speed: float) -> None:
        super().__init__(profile, time.monotonic, speed)
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

    def start_calibration(self, signal: str, step: CalibrationStep) -> None:
        self.calibrations.append((signal, step))
        self.last_calibration_at = time.monotonic()
        super().start_calibration(signal, step)


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
