from pathlib import Path

import numpy as np
import pytest

from neurotlon_bridge.config import ConfigError, DebugConfig, load_config
from neurotlon_bridge.processing.alpha import AlphaConfig, AlphaEngine
from neurotlon_bridge.processing.trace import HEADER, CsvTraceWriter, TraceRow

FS = 250


class ListSink:
    def __init__(self) -> None:
        self.rows: list[TraceRow] = []

    def write(self, row: TraceRow) -> None:
        self.rows.append(row)


def row(t: float = 1.0, reason: str = "ok") -> TraceRow:
    nan = float("nan")
    return (
        TraceRow(t, "live", 0.21, 0.5, True, reason, 0.1, 0.3)
        if reason == "ok"
        else TraceRow(t, "live", nan, nan, False, reason, nan, nan)
    )


def signal(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(2)
    t = np.arange(round(seconds * FS)) / FS
    amp = 5 + 15 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 4.0))
    wave = amp * np.sin(2 * np.pi * 10 * t) + 8 * np.sin(2 * np.pi * 20 * t)
    return np.asarray((wave[:, None] + rng.normal(0, 1.5, (t.size, 4))) * 1e-6)


def test_engine_reports_phases_and_concentration_to_the_sink() -> None:
    sink = ListSink()
    now = [0.0]
    engine = AlphaEngine(AlphaConfig(), FS, lambda: now[0], sink)
    engine.start_calibration(8)
    data = signal(12)
    for i in range(0, len(data), 50):
        now[0] += 0.2
        engine.push(data[i : i + 50])
    phases = [r.phase for r in sink.rows]
    assert phases[0] == "calibrating" and phases[-1] == "live"
    live = [r for r in sink.rows if r.phase == "live"]
    assert all(r.valid and 0.0 <= r.concentration <= 1.0 and r.low < r.high for r in live)
    calibrating = [r for r in sink.rows if r.phase == "calibrating"]
    assert all(np.isnan(r.concentration) and not r.valid for r in calibrating)
    assert all(np.isfinite(r.rel_alpha) for r in calibrating)


def test_artifact_window_is_traced_with_reason() -> None:
    sink = ListSink()
    now = [0.0]
    engine = AlphaEngine(AlphaConfig(), FS, lambda: now[0], sink)
    engine.start_calibration(8)
    data = signal(4)
    data[300:, :] += 400e-6 * np.sign(np.sin(np.arange(len(data) - 300) / 5.0))[:, None]
    for i in range(0, len(data), 50):
        now[0] += 0.2
        engine.push(data[i : i + 50])
    bad = [r for r in sink.rows if r.reason in ("ptp", "jump")]
    assert bad and all(np.isnan(r.rel_alpha) and not r.valid for r in bad)


def test_csv_writer_header_and_rows_without_personal_data(tmp_path: Path) -> None:
    path = tmp_path / "eeg-trace.csv"
    writer = CsvTraceWriter(path, wall_clock=lambda: 0.0)
    writer.write(row())
    writer.write(row(2.0, "ptp"))
    writer.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == HEADER
    assert len(lines) == 3
    assert lines[1].split(",")[1:] == ["1.000", "live", "0.21", "0.5", "1", "ok", "0.1", "0.3"]
    assert lines[2].split(",")[1:] == ["2.000", "live", "", "", "0", "ptp", "", ""]


def test_csv_writer_rotates_at_the_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "eeg-trace.csv"
    writer = CsvTraceWriter(path, max_bytes=1024)
    for i in range(200):
        writer.write(row(float(i)))
    writer.close()
    assert path.stat().st_size <= 1024 + 100
    old = tmp_path / "eeg-trace.old.csv"
    assert old.exists() and old.stat().st_size <= 1024 + 100
    assert path.read_text(encoding="utf-8").startswith(HEADER)


def test_csv_writer_restart_appends_without_second_header(tmp_path: Path) -> None:
    path = tmp_path / "eeg-trace.csv"
    for _ in range(2):
        writer = CsvTraceWriter(path)
        writer.write(row())
        writer.close()
    assert path.read_text(encoding="utf-8").count(HEADER) == 1


def test_csv_writer_survives_unwritable_path(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    writer = CsvTraceWriter(blocker / "eeg-trace.csv")  # родитель - файл
    writer.write(row())  # не падает
    writer.write(row())


def test_csv_writer_rejects_tiny_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CsvTraceWriter(tmp_path / "x.csv", max_bytes=10)


def test_debug_section_defaults_off(tmp_path: Path) -> None:
    cfg = tmp_path / "bridge.toml"
    cfg.write_text("", encoding="utf-8")
    assert load_config(cfg).debug == DebugConfig(eeg_trace=False, eeg_trace_max_kb=2048)


def test_debug_section_parsed(tmp_path: Path) -> None:
    cfg = tmp_path / "bridge.toml"
    cfg.write_text("[debug]\neeg_trace = true\neeg_trace_max_kb = 64\n", encoding="utf-8")
    assert load_config(cfg).debug == DebugConfig(eeg_trace=True, eeg_trace_max_kb=64)


@pytest.mark.parametrize(
    "body",
    ["eeg_trace = 1", "eeg_trace = true\neeg_trace_max_kb = 0", "eeg_trace_max_kb = 1.5", "x = 1"],
)
def test_debug_section_rejects_bad_values(tmp_path: Path, body: str) -> None:
    cfg = tmp_path / "bridge.toml"
    cfg.write_text(f"[debug]\n{body}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg)
