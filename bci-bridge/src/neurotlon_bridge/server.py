"""TCP-сервер моста: NDJSON по протоколу из shared/bridge-protocol.md."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field

from . import protocol
from .source import (
    CalibrationProgress,
    CalibrationStep,
    Clock,
    EegMethod,
    Feature,
    SensorState,
    SignalSource,
    steps_for,
)

log = logging.getLogger(__name__)

FEATURES: tuple[Feature, ...] = ("burst", "emg_cycle", "baseline_duration", "calibration_state")


@dataclass
class _Tracking:
    """Что уже отправлено текущему клиенту."""

    states: dict[str, SensorState]
    calibrations: dict[str, CalibrationProgress | None]
    batteries: dict[str, int | None] = field(default_factory=dict)
    calibration_sent_at: dict[str, float] = field(default_factory=dict)
    burst_seq: dict[str, int] = field(default_factory=dict)


def _default_step(signal: str) -> CalibrationStep:
    return "baseline" if signal == "eeg" else "rest"


class BridgeServer:
    def __init__(
        self,
        source: SignalSource,
        host: str = "127.0.0.1",
        port: int = 8765,
        rate_hz: float = 50,
        clock: Clock = time.monotonic,
        calibration_interval_s: float = 0.1,
        write_timeout_s: float = 1.0,
        eeg_method: EegMethod | None = None,
    ) -> None:
        self._source = source
        self._eeg_method = eeg_method
        self._host = host
        self._port = port
        self._rate_hz = rate_hz
        self._clock = clock
        self._calibration_interval_s = calibration_interval_s
        self._write_timeout_s = write_timeout_s
        self._t0 = clock()
        self._server: asyncio.Server | None = None
        self._current: asyncio.StreamWriter | None = None

    @property
    def port(self) -> int:
        """Фактический порт (после `start`, полезно при port=0)."""
        if self._server is None or not self._server.sockets:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        log.info("bridge listening on %s:%s", self._host, self.port)

    async def stop(self) -> None:
        if self._current is not None:
            self._current.transport.abort()
            self._current = None
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            self._server = None

    async def serve_forever(self) -> None:
        await self.start()
        try:
            assert self._server is not None
            await self._server.serve_forever()
        finally:
            await self.stop()

    async def _write(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        """Запись ограничена по времени: зависший клиент отключается."""
        writer.write(data)
        try:
            await asyncio.wait_for(writer.drain(), self._write_timeout_s)
        except TimeoutError:
            log.warning("клиент не читает данные, соединение сброшено")
            writer.transport.abort()
            raise ConnectionError("write timeout") from None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._current is not None:
            log.info("отказ: игра уже подключена, новое подключение закрыто")
            writer.transport.abort()
            return
        self._current = writer
        try:
            names = self._source.signals()
            for name in names:  # события до подключения этой игры ей не нужны
                await asyncio.to_thread(self._source.drain_bursts, name)
            hello = protocol.Hello(
                tuple((n, self._source.state(n)) for n in names),
                features=FEATURES,
                eeg_method=self._eeg_method if "eeg" in names else None,
                calibrated=await asyncio.to_thread(self._calibrated_signals, names),
            )
            await self._write(writer, protocol.encode(hello))
            tracking = _Tracking(
                states=dict(hello.signals),
                calibrations={n: self._source.calibration_status(n) for n in names},
            )
            tasks = {
                asyncio.create_task(self._send_loop(writer, tracking)),
                asyncio.create_task(self._receive_loop(reader, writer, tracking)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = None if task.cancelled() else task.exception()
                if exc is not None and not isinstance(exc, ConnectionError | OSError):
                    log.error("ошибка соединения", exc_info=exc)
        except (ConnectionError, OSError):
            pass
        finally:
            if self._current is writer:
                self._current = None
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    def _calibrated_signals(self, names: tuple[str, ...]) -> tuple[str, ...]:
        """Сигналы с готовой шкалой; блокирует (замки обработчиков): не в цикле событий."""
        return tuple(n for n in names if self._source.is_calibrated(n))

    async def _receive_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, tracking: _Tracking
    ) -> None:
        while True:
            try:
                line = await reader.readline()
            except ValueError:  # строка длиннее лимита буфера
                log.warning("слишком длинная строка, соединение закрыто")
                return
            if not line:
                return
            try:
                msg = protocol.decode(line)
            except ValueError as exc:
                log.warning("битое сообщение проигнорировано: %s", exc)
                continue
            match msg:
                case protocol.Calibrate():
                    problem = self._request_problem(msg)
                    if problem is not None:
                        log.warning("calibrate отклонён: %s", problem)
                        failed = protocol.Calibration(msg.signal, msg.step, "failed", None, problem)
                        await self._write(writer, protocol.encode(failed))
                        continue
                    segments = msg.segments if msg.step == "cycle" else None
                    duration_s = msg.duration_s if msg.step == "baseline" else None
                    try:
                        # вызов может блокировать (замки обработчиков): не в цикле событий
                        await asyncio.to_thread(
                            self._source.start_calibration,
                            msg.signal,
                            msg.step,
                            segments,
                            duration_s,
                        )
                    except ValueError as exc:
                        log.warning("calibrate проигнорирован: %s", exc)
                    except Exception as exc:
                        log.exception("ошибка запуска калибровки %s", msg.signal)
                        await self._report_failure(writer, msg.signal, msg.step, exc)
                case protocol.Reset():
                    try:
                        await asyncio.to_thread(self._source.reset)
                    except Exception as exc:
                        log.exception("ошибка очистки калибровки")
                        for name in self._source.signals():
                            await self._report_failure(writer, name, _default_step(name), exc)
                    for name in tracking.calibrations:
                        tracking.calibrations[name] = None
                case _:
                    pass

    def _request_problem(self, msg: protocol.Calibrate) -> str | None:
        """Почему запрос нельзя выполнить; ответ `failed` идущую калибровку не трогает."""
        if msg.signal not in self._source.signals():
            return f"сигнала {msg.signal} нет в профиле"
        if msg.step not in steps_for(msg.signal):
            return f"шаг {msg.step} не подходит для {msg.signal}"
        return protocol.calibrate_problem(msg)

    async def _report_failure(
        self, writer: asyncio.StreamWriter, signal: str, step: CalibrationStep, exc: Exception
    ) -> None:
        reason = f"внутренняя ошибка моста: {exc}"
        msg = protocol.Calibration(signal, step, "failed", None, reason)
        await self._write(writer, protocol.encode(msg))

    async def _send_loop(self, writer: asyncio.StreamWriter, tracking: _Tracking) -> None:
        period = 1.0 / self._rate_hz
        next_t = self._clock()
        while True:
            now = self._clock()
            t_ms = max(0, int((now - self._t0) * 1000))
            out = [protocol.encode(protocol.Sample(t_ms, self._source.read(t_ms)))]
            out.extend(self._burst_messages(tracking))
            out.extend(self._sensor_messages(tracking))
            out.extend(self._calibration_messages(tracking, now))
            await self._write(writer, b"".join(out))
            next_t += period
            now = self._clock()
            if now - next_t > period:  # отстали: не догоняем пачкой
                next_t = now
            await asyncio.sleep(max(0.0, next_t - now))

    def _burst_messages(self, tracking: _Tracking) -> list[bytes]:
        out: list[bytes] = []
        for name in self._source.signals():
            for event in self._source.drain_bursts(name):
                seq = tracking.burst_seq.get(name, 0) + 1
                tracking.burst_seq[name] = seq
                t_ms = max(0, int((event.t_s - self._t0) * 1000))
                out.append(protocol.encode(protocol.Burst(name, t_ms, seq, event.rise)))
        return out

    def _sensor_messages(self, tracking: _Tracking) -> list[bytes]:
        out: list[bytes] = []
        for name in self._source.signals():
            state = self._source.state(name)
            battery = self._source.battery(name)
            if state != tracking.states.get(name) or battery != tracking.batteries.get(name):
                tracking.states[name] = state
                tracking.batteries[name] = battery
                out.append(protocol.encode(protocol.Sensor(name, state, battery)))
        return out

    def _calibration_messages(self, tracking: _Tracking, now: float) -> list[bytes]:
        out: list[bytes] = []
        for name in self._source.signals():
            cur = self._source.calibration_status(name)
            prev = tracking.calibrations.get(name)
            if cur is None:
                tracking.calibrations[name] = None
                continue
            changed = prev is None or (prev.step, prev.status) != (cur.step, cur.status)
            due = now - tracking.calibration_sent_at.get(name, -1e9) >= self._calibration_interval_s
            if not (changed or (cur.status == "running" and due and cur != prev)):
                continue
            tracking.calibrations[name] = cur
            tracking.calibration_sent_at[name] = now
            running = cur.status == "running"
            message = protocol.Calibration(
                name,
                cur.step,
                cur.status,
                cur.progress if running else None,
                cur.reason,
                cur.segment if running else None,
                cur.phase if running else None,
                cur.phase_left_s if running else None,
            )
            out.append(protocol.encode(message))
        return out


class BridgeThread:
    """Фоновый поток, в котором работает цикл событий сервера моста."""

    def __init__(self, server: BridgeServer) -> None:
        self._server = server
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bridge-server", daemon=True)
        self._error: BaseException | None = None

    def start(self, timeout_s: float = 5.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout_s):
            raise TimeoutError("мост не запустился")
        if self._error is not None:
            raise self._error

    def stop(self) -> None:
        if self._thread.ident is None:
            return
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            log.warning("поток моста не остановился за 5 секунд")

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        await self._server.start()
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            await self._server.stop()
