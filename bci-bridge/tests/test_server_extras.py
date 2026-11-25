"""Сервер: заряд в `sensor`, сбои калибровки, блокирующие вызовы вне цикла событий."""

import asyncio
import json
import threading
import time
from collections.abc import Callable
from typing import Any

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.server import BridgeServer
from neurotlon_bridge.source import CalibrationStep, Segment


class Source(EmulatedSource):
    def __init__(self) -> None:
        super().__init__("darts", time.monotonic)
        self.level: int | None = None
        self.fail_calibration = False
        self.fail_reset = False
        self.threads: list[threading.Thread] = []

    def battery(self, signal: str) -> int | None:
        return self.level if signal == "emg" else None

    def start_calibration(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.threads.append(threading.current_thread())
        if self.fail_calibration:
            raise RuntimeError("замок завис")
        super().start_calibration(signal, step, segments, duration_s)

    def reset(self) -> None:
        self.threads.append(threading.current_thread())
        if self.fail_reset:
            raise RuntimeError("очистка не удалась")
        super().reset()


class Conn:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, **fields: Any) -> None:
        self.writer.write(json.dumps(fields).encode() + b"\n")
        await self.writer.drain()

    async def until(self, pred: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        async def loop() -> dict[str, Any]:
            while True:
                msg: dict[str, Any] = json.loads(await self.reader.readline())
                if pred(msg):
                    return msg

        return await asyncio.wait_for(loop(), 5)


async def connect(server: BridgeServer) -> Conn:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    return Conn(reader, writer)


def run(scenario: Callable[[Source, BridgeServer], Any]) -> Source:
    source = Source()

    async def main() -> None:
        server = BridgeServer(source, port=0, rate_hz=100)
        await server.start()
        try:
            await scenario(source, server)
        finally:
            await server.stop()

    asyncio.run(main())
    return source


def is_sensor(msg: dict[str, Any]) -> bool:
    return bool(msg["type"] == "sensor")


def test_sensor_message_sent_when_battery_changes() -> None:
    async def scenario(source: Source, server: BridgeServer) -> None:
        conn = await connect(server)
        await conn.until(lambda m: m["type"] == "sample")
        source.level = 80
        first = await conn.until(is_sensor)
        assert (first["signal"], first["state"], first["battery"]) == ("emg", "emulated", 80)
        source.level = 70
        assert (await conn.until(is_sensor))["battery"] == 70

    run(scenario)


def test_no_sensor_message_without_changes() -> None:
    async def scenario(source: Source, server: BridgeServer) -> None:
        conn = await connect(server)
        seen = 0
        for _ in range(20):
            msg = await conn.until(lambda m: True)
            seen += is_sensor(msg)
        assert seen == 0

    run(scenario)


def test_calibration_failure_is_reported_and_connection_survives() -> None:
    async def scenario(source: Source, server: BridgeServer) -> None:
        source.fail_calibration = True
        conn = await connect(server)
        await conn.send(type="calibrate", signal="emg", step="rest")
        failed = await conn.until(lambda m: m["type"] == "calibration")
        assert (failed["signal"], failed["step"], failed["status"]) == ("emg", "rest", "failed")
        assert "замок завис" in failed["reason"]
        await conn.until(lambda m: m["type"] == "sample")

    run(scenario)


def test_reset_failure_is_reported_for_every_signal() -> None:
    async def scenario(source: Source, server: BridgeServer) -> None:
        source.fail_reset = True
        conn = await connect(server)
        await conn.send(type="reset")
        got: dict[str, dict[str, Any]] = {}
        while len(got) < 2:
            msg = await conn.until(lambda m: m["type"] == "calibration")
            got[msg["signal"]] = msg
        assert {m["status"] for m in got.values()} == {"failed"}
        assert got["eeg"]["step"] == "baseline"
        assert got["emg"]["step"] == "rest"

    run(scenario)


def test_blocking_calls_run_outside_event_loop_thread() -> None:
    async def scenario(source: Source, server: BridgeServer) -> None:
        conn = await connect(server)
        await conn.send(type="calibrate", signal="emg", step="rest")
        await conn.until(lambda m: m["type"] == "calibration")
        await conn.send(type="reset")
        deadline = time.monotonic() + 5
        while len(source.threads) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)

    source = run(scenario)
    assert len(source.threads) == 2
    assert all(t is not threading.main_thread() for t in source.threads)
