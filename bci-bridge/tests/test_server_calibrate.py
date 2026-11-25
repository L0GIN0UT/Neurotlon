"""Сервер: параметры шага калибровки (`segments`, `duration_s`) и ответ на недопустимые значения."""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import pytest

from neurotlon_bridge.emulator import EmulatedSource
from neurotlon_bridge.server import BridgeServer
from neurotlon_bridge.source import CalibrationStep, Segment

TENSE = {"phase": "tense", "s": 4}
RELAX = {"phase": "relax", "s": 3}


class Recording(EmulatedSource):
    def __init__(self, profile: str = "darts", speed: float = 1.0) -> None:
        super().__init__(profile, time.monotonic, speed)
        self.calls: list[tuple[str, CalibrationStep, tuple[Segment, ...] | None, float | None]] = []

    def start_calibration(
        self,
        signal: str,
        step: CalibrationStep,
        segments: tuple[Segment, ...] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.calls.append((signal, step, segments, duration_s))
        super().start_calibration(signal, step, segments, duration_s)


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


def scenario(
    body: Callable[[Recording, Conn], Any], profile: str = "darts", speed: float = 1.0
) -> Recording:
    source = Recording(profile, speed)

    async def main() -> None:
        server = BridgeServer(source, port=0, rate_hz=100, calibration_interval_s=0.01)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            conn = Conn(reader, writer)
            await conn.until(lambda m: m["type"] == "hello")
            await body(source, conn)
            writer.close()
        finally:
            await server.stop()

    asyncio.run(main())
    return source


def test_cycle_segments_reach_the_source_and_progress_has_phases() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="cycle", segments=[TENSE, RELAX])
        running = await conn.until(
            lambda m: m["type"] == "calibration" and m.get("status") == "running"
        )
        assert (running["step"], running["segment"], running["phase"]) == ("cycle", 1, "tense")
        assert 0.0 < running["phase_left_s"] <= 4.0

    source = scenario(body)
    assert source.calls == [("emg", "cycle", (Segment("tense", 4.0), Segment("relax", 3.0)), None)]


def test_cycle_without_segments_uses_the_default_rhythm() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="cycle")
        running = await conn.until(lambda m: m["type"] == "calibration")
        assert running["status"] == "running"
        assert running["phase"] == "tense"

    assert scenario(body).calls == [("emg", "cycle", None, None)]


def test_baseline_duration_is_passed_and_drives_the_step() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="eeg", step="baseline", duration_s=10)
        done = await conn.until(lambda m: m["type"] == "calibration" and m.get("status") == "done")
        assert done["step"] == "baseline"

    source = scenario(body, speed=20.0)
    assert source.calls == [("eeg", "baseline", None, 10.0)]


def test_unrelated_fields_are_not_forwarded() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(
            type="calibrate",
            signal="emg",
            step="rest",
            segments=[TENSE, RELAX],
            duration_s=7,
        )
        await conn.until(lambda m: m["type"] == "calibration")

    assert scenario(body).calls == [("emg", "rest", None, None)]


BAD_SEGMENTS: list[list[dict[str, Any]]] = [
    [TENSE] * 5 + [RELAX] * 5,  # больше 8
    [{"phase": "tense", "s": 15}, {"phase": "relax", "s": 15}] * 2 + [TENSE],  # сумма больше 60
    [TENSE, TENSE],  # нет расслабления
    [RELAX, RELAX],  # нет напряжения
    [{"phase": "tense", "s": 1.5}, RELAX],  # короче 2 с
    [{"phase": "tense", "s": 16}, RELAX],  # длиннее 15 с
    [TENSE],  # один сегмент
]


@pytest.mark.parametrize("segments", BAD_SEGMENTS)
def test_bad_segments_get_failed_answer_and_never_reach_the_source(
    segments: list[dict[str, Any]],
) -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="cycle", segments=segments)
        failed = await conn.until(
            lambda m: m["type"] == "calibration" and m.get("status") == "failed"
        )
        assert (failed["signal"], failed["step"]) == ("emg", "cycle")
        assert failed["reason"]

    assert scenario(body).calls == []


@pytest.mark.parametrize("duration", [4.9, 30.1, 1, 100])
def test_bad_baseline_duration_gets_failed_answer(duration: float) -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="eeg", step="baseline", duration_s=duration)
        failed = await conn.until(
            lambda m: m["type"] == "calibration" and m.get("status") == "failed"
        )
        assert failed["step"] == "baseline"
        assert "duration_s" in failed["reason"]

    assert scenario(body).calls == []


def test_server_keeps_working_after_a_rejected_request() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="cycle", segments=[TENSE])
        await conn.until(lambda m: m.get("status") == "failed")
        await conn.send(type="calibrate", signal="emg", step="rest")
        await conn.until(lambda m: m["type"] == "calibration" and m.get("status") == "running")

    assert [c[1] for c in scenario(body).calls] == ["rest"]


def test_pong_cycle_for_both_hands() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        for signal in ("emg_left", "emg_right"):
            await conn.send(type="calibrate", signal=signal, step="cycle")
        seen: set[str] = set()
        while seen != {"emg_left", "emg_right"}:
            msg = await conn.until(lambda m: m["type"] == "calibration")
            seen.add(msg["signal"])

    assert [c[0] for c in scenario(body, profile="pong").calls] == ["emg_left", "emg_right"]


def test_cycle_for_eeg_is_answered_with_failed_and_not_started() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="eeg", step="cycle")
        failed = await conn.until(lambda m: m.get("status") == "failed")
        assert (failed["signal"], failed["step"]) == ("eeg", "cycle")
        assert "не подходит" in failed["reason"]

    assert scenario(body).calls == []


def test_baseline_for_emg_and_unknown_signal_are_rejected() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="baseline")
        await conn.until(lambda m: m.get("status") == "failed")
        await conn.send(type="calibrate", signal="emg_left", step="rest")
        failed = await conn.until(lambda m: m.get("status") == "failed")
        assert failed["signal"] == "emg_left"

    assert scenario(body).calls == []


def test_rejected_request_does_not_stop_a_running_calibration() -> None:
    async def body(source: Recording, conn: Conn) -> None:
        await conn.send(type="calibrate", signal="emg", step="cycle")
        await conn.until(lambda m: m.get("status") == "running")
        await conn.send(type="calibrate", signal="emg", step="cycle", segments=[TENSE])
        await conn.until(lambda m: m.get("status") == "failed")
        later = await conn.until(lambda m: m.get("status") == "running")
        assert later["step"] == "cycle"
        assert source.calibration_status("emg") is not None
        assert source.calibration_status("emg").status == "running"  # type: ignore[union-attr]

    assert len(scenario(body).calls) == 1
