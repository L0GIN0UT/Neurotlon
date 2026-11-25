"""Хранилище калибровки: формат файла, проверка записи, атомарность."""

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from neurotlon_bridge.calibration_store import (
    FILE_NAME,
    SCHEMA_VERSION,
    CalibrationRecord,
    EegScale,
    EmgScale,
    FileCalibrationStore,
    MemoryStore,
    Stamped,
    dump_record,
    parse_record,
    record_problem,
)
from neurotlon_bridge.source import EegMethod

NOW = 1_000_000.0
TTL_S = 4 * 3600.0
EMG = EmgScale(rest=3.0, peak=40.0, fs=1000.0)
EEG = EegScale(low=0.1, high=0.4, fs=250.0)


def record(
    *, method: EegMethod | None = "alpha", at: float = NOW - 60, **signals: Any
) -> CalibrationRecord:
    return CalibrationRecord(method, {n: Stamped(s, at) for n, s in signals.items()})


def problem(
    rec: CalibrationRecord, method: EegMethod | None = "alpha", **kwargs: object
) -> str | None:
    args: dict[str, object] = {
        "now": NOW,
        "ttl_s": TTL_S,
        "signals": ("eeg", "emg"),
        "eeg_method": method,
        "eeg_fs": 250.0,
        "emg_fs": 1000.0,
    }
    args.update(kwargs)
    return record_problem(rec, **args)  # type: ignore[arg-type]


def test_roundtrip_through_file(tmp_path: Path) -> None:
    store = FileCalibrationStore(tmp_path)
    rec = record(emg=EMG, eeg=EEG)
    store.save(rec)
    assert store.load() == rec
    data = json.loads((tmp_path / FILE_NAME).read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["eeg_method"] == "alpha"
    assert data["signals"]["emg"]["rest"] == 3.0
    assert data["signals"]["eeg"]["high"] == 0.4


def test_no_file_means_no_record(tmp_path: Path) -> None:
    assert FileCalibrationStore(tmp_path / "missing").load() is None


def test_save_creates_the_directory(tmp_path: Path) -> None:
    store = FileCalibrationStore(tmp_path / "a" / "b")
    store.save(record(emg=EMG))
    assert store.load() is not None


def test_clear_is_idempotent(tmp_path: Path) -> None:
    store = FileCalibrationStore(tmp_path)
    store.clear()
    store.save(record(emg=EMG))
    store.clear()
    store.clear()
    assert store.load() is None
    assert not (tmp_path / FILE_NAME).exists()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{not json",
        "[]",
        '{"schema_version": 99, "signals": {}}',
        '{"schema_version": 1, "eeg_method": "fft", "signals": {}}',
        '{"schema_version": 1, "signals": []}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": "1", "peak": 2, '
        '"fs": 1000, "calibrated_at": 5}}}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": true, "peak": 2, '
        '"fs": 1000, "calibrated_at": 5}}}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "gsr"}}}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": 1, "peak": 2}}}',
    ],
)
def test_corrupt_file_is_ignored_and_erased(tmp_path: Path, text: str) -> None:
    (tmp_path / FILE_NAME).write_text(text, encoding="utf-8")
    store = FileCalibrationStore(tmp_path)
    assert store.load() is None
    assert not (tmp_path / FILE_NAME).exists()


def test_binary_garbage_is_ignored_and_erased(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_bytes(b"\xff\xfe\x00garbage")
    store = FileCalibrationStore(tmp_path)
    assert store.load() is None
    assert not (tmp_path / FILE_NAME).exists()


def test_parse_record_rejects_other_version() -> None:
    with pytest.raises(ValueError):
        parse_record('{"schema_version": 2, "signals": {}}')


def test_nan_cannot_be_written() -> None:
    bad = record(emg=EmgScale(float("nan"), 2.0, 1000.0))
    with pytest.raises(ValueError):
        dump_record(bad)


def test_failed_replace_keeps_the_old_file_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileCalibrationStore(tmp_path)
    old = record(emg=EMG)
    store.save(old)

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("диск отвалился на переименовании")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        store.save(record(emg=EmgScale(5.0, 90.0, 1000.0)))
    monkeypatch.undo()
    assert store.load() == old
    assert [p.name for p in tmp_path.iterdir()] == [FILE_NAME]


def test_failure_while_writing_keeps_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileCalibrationStore(tmp_path)
    old = record(emg=EMG)
    store.save(old)

    def broken_fsync(fd: int) -> None:
        raise OSError("нет места")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        store.save(record(eeg=EEG))
    monkeypatch.undo()
    assert store.load() == old
    assert [p.name for p in tmp_path.iterdir()] == [FILE_NAME]


@pytest.mark.skipif(os.name == "nt", reason="права POSIX")
def test_file_is_readable_only_by_the_owner(tmp_path: Path) -> None:
    store = FileCalibrationStore(tmp_path)
    store.save(record(emg=EMG))
    assert stat.S_IMODE((tmp_path / FILE_NAME).stat().st_mode) == 0o600


def test_memory_store_is_a_store() -> None:
    store = MemoryStore()
    assert store.load() is None
    rec = record(emg=EMG)
    store.save(rec)
    assert store.load() == rec
    store.clear()
    assert store.load() is None


# --- record_problem ---


def test_good_record_has_no_problem() -> None:
    assert problem(record(emg=EMG, eeg=EEG)) is None


def test_record_without_eeg_is_fine_for_pong_style_profile() -> None:
    rec = record(method=None, emg_left=EMG, emg_right=EMG)
    assert problem(rec, None, signals=("emg_left", "emg_right")) is None


def test_expired_record() -> None:
    assert problem(record(emg=EMG, at=NOW - TTL_S - 1)) is not None
    assert problem(record(emg=EMG, at=NOW - TTL_S + 1)) is None


def test_record_from_the_future() -> None:
    assert problem(record(emg=EMG, at=NOW + 3600)) is not None


def test_other_eeg_method() -> None:
    assert problem(record(method="emotions", emg=EMG), "alpha") is not None
    assert problem(record(method="alpha", emg=EMG), "emotions") is not None
    assert problem(record(method=None, emg=EMG), "alpha") is not None


def test_signal_outside_the_profile() -> None:
    assert problem(record(emg_left=EMG), signals=("eeg", "emg")) is not None


def test_scale_kind_must_match_the_signal() -> None:
    assert problem(record(eeg=EMG)) is not None
    assert problem(record(emg=EEG)) is not None


@pytest.mark.parametrize(
    "scale",
    [
        EmgScale(5.0, 5.0, 1000.0),
        EmgScale(9.0, 5.0, 1000.0),
        EmgScale(-1.0, 5.0, 1000.0),
        EmgScale(float("nan"), 5.0, 1000.0),
        EmgScale(1.0, float("inf"), 1000.0),
        EmgScale(1.0, 5.0, 0.0),
        EegScale(0.5, 0.5, 250.0),
        EegScale(0.6, 0.2, 250.0),
        EegScale(float("nan"), 0.2, 250.0),
        EegScale(0.1, float("inf"), 250.0),
    ],
)
def test_bad_numbers(scale: EmgScale | EegScale) -> None:
    rec = record(eeg=scale) if isinstance(scale, EegScale) else record(emg=scale)
    assert problem(rec) is not None


def test_eeg_sampling_rate_must_match() -> None:
    assert problem(record(eeg=EegScale(0.1, 0.4, 500.0))) is not None


def test_empty_record_is_a_problem() -> None:
    assert problem(CalibrationRecord("alpha", {})) is not None


@pytest.mark.parametrize(
    "text",
    [
        "[" * 100_000,
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": 1, "peak": '
        + "9" * 400
        + ', "fs": 1000, "calibrated_at": 5}}}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": NaN, "peak": 2, '
        '"fs": 1000, "calibrated_at": 5}}}',
        '{"schema_version": 1, "signals": {"emg": {"kind": "emg", "rest": 1, "peak": Infinity, '
        '"fs": 1000, "calibrated_at": 5}}}',
        '"just a string"',
        "42",
        "x" * 70_000,
    ],
    ids=["deep", "huge-int", "nan", "infinity", "string", "number", "oversized"],
)
def test_hostile_file_is_ignored_and_erased(tmp_path: Path, text: str) -> None:
    (tmp_path / FILE_NAME).write_text(text, encoding="utf-8")
    assert FileCalibrationStore(tmp_path).load() is None
    assert not (tmp_path / FILE_NAME).exists()


def test_emg_sampling_rate_must_be_near_nominal() -> None:
    assert problem(record(emg=EmgScale(3.0, 40.0, 1050.0))) is None
    assert problem(record(emg=EmgScale(3.0, 40.0, 500.0))) is not None
