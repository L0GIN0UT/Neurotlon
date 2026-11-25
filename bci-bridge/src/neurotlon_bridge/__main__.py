"""Точка входа: `neurotlon-bridge --emulate | --scan | --discover | --profile X`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import queue
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from neurotlon_contracts.discovery import encode_message

from .calibration_store import FileCalibrationStore
from .config import ConfigError, default_config_path, load_config, required_devices
from .devices.base import DeviceBackend, DeviceError, ScannerPort
from .devices.discovery import DiscoveryService
from .devices.scan import format_devices, scan_devices
from .discover_session import DiscoverySession, Inbox, start_reader
from .emulator import EmulatedSource
from .processing.trace import TRACE_NAME, CsvTraceWriter
from .server import BridgeServer, BridgeThread
from .source import EEG_METHODS, PROFILES, EegMethod

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_DEVICES = 3
SCAN_SECONDS = 15.0  # BLE находит датчики не сразу: 10 секунд бывало мало
SCAN_JSON_MARK = "NEUROTLON_SCAN_JSON="

DEFAULT_EEG_METHOD: EegMethod = "alpha"

BackendFactory = Callable[[float], DeviceBackend]
ScannerFactory = Callable[[], ScannerPort]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurotlon-bridge", description="BCI-мост Нейротлона")
    parser.add_argument("--emulate", action="store_true", help="эмулятор датчиков (клавиши)")
    parser.add_argument("--scan", action="store_true", help="найти датчики, вывести и выйти")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="фоновый поиск датчиков для лаунчера: команды в stdin, сообщения в stdout (JSONL)",
    )
    parser.add_argument(
        "--fake", action="store_true", help="с --discover: устройства по сценарию, без Bluetooth"
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="darts")
    parser.add_argument(
        "--eeg-method",
        choices=EEG_METHODS,
        default=DEFAULT_EEG_METHOD,
        help="метод ЭЭГ: alpha (относительная альфа) или emotions (NeuroSDK Emotions)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, help="путь к bridge.toml (по умолчанию рядом)")
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="каталог для calibration.json (по умолчанию рядом с bridge.toml)",
    )
    parser.add_argument("--headless", action="store_true", help="без окна")
    parser.add_argument(
        "--json", action="store_true", help="с --scan: список датчиков в JSON (для лаунчера)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="с --emulate: сигналы подаются сами по сценарию, клавиши не нужны",
    )
    return parser


def default_backend_factory(scan_s: float) -> DeviceBackend:
    from .devices.neurosdk_backend import NeuroSdkBackend

    return NeuroSdkBackend(scan_s)


def default_scanner_factory() -> ScannerPort:
    from .devices.neurosdk_backend import NeuroSdkBackend

    return NeuroSdkBackend()


def fake_scanner_factory() -> ScannerPort:
    from .devices.fakes import FakeScanner, demo_devices

    started = time.monotonic()
    return FakeScanner(
        demo_devices(), lambda: time.monotonic() - started, stream_samples=True, rssi_wobble_db=6
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: BackendFactory | None = None,
    scanner_factory: ScannerFactory | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger(__name__).info("bridge started: %s", " ".join(sys.argv[1:]))
    factory = backend_factory or default_backend_factory
    if args.discover:
        make = scanner_factory or (fake_scanner_factory if args.fake else default_scanner_factory)
        return _discover(make, stdin or sys.stdin, stdout or sys.stdout)
    if args.scan:
        return _scan(args, factory)
    if args.emulate:
        return _emulate(args)
    return _hardware(args, factory)


def _scan(args: argparse.Namespace, factory: BackendFactory) -> int:
    try:
        backend = factory(SCAN_SECONDS)
        try:
            backend.check()
            if args.json:
                found = scan_devices(backend, SCAN_SECONDS)
                # SDK пишет свои сообщения в тот же stdout: список — на строке с меткой
                # (список для лаунчера без rssi: формат `--scan --json` не меняется)
                payload = json.dumps(
                    [
                        {"kind": d.kind, "name": d.name, "serial": d.serial, "address": d.address}
                        for d in found
                    ],
                    ensure_ascii=False,
                )
                print(f"{SCAN_JSON_MARK}{payload}", flush=True)
            else:
                print(f"Поиск датчиков, {SCAN_SECONDS:g} с...", flush=True)
                print(format_devices(scan_devices(backend, SCAN_SECONDS)))
        finally:
            backend.close()
    except DeviceError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_DEVICES
    return EXIT_OK


def _discover(make_scanner: ScannerFactory, stdin: TextIO, stdout: TextIO) -> int:
    """Долгоживущий поиск для экрана настройки (`shared/sensor-discovery.md`)."""
    if hasattr(stdout, "reconfigure"):
        stdout.reconfigure(encoding="utf-8")  # русские сообщения не должны ломаться
    lock = threading.Lock()

    def write(line: str) -> None:
        with lock:  # одним куском: SDK пишет в тот же stdout
            stdout.write(f"{line}\n")
            stdout.flush()

    try:
        service = DiscoveryService(make_scanner())
    except DeviceError as exc:
        write(encode_message({"type": "error", "message": str(exc)}))
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_DEVICES
    inbox: Inbox = queue.Queue()
    start_reader(stdin, inbox)
    DiscoverySession(service, write).run(inbox)
    return EXIT_OK


def _emulate(args: argparse.Namespace) -> int:
    source = EmulatedSource(args.profile, time.monotonic)
    server = BridgeServer(source, port=args.port, eeg_method=args.eeg_method)
    if args.auto:
        from .scripted import ScriptedInput

        ScriptedInput(source, args.profile).start()
    if args.headless:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(server.serve_forever())
        return EXIT_OK
    from .window import run_window

    thread = BridgeThread(server)
    thread.start()
    try:
        run_window(source, args.profile)
    finally:
        thread.stop()
    return EXIT_OK


def _state_dir(args: argparse.Namespace) -> Path:
    """Каталог данных моста: `--state-dir`, иначе папка с `bridge.toml`."""
    if args.state_dir is not None:
        return Path(args.state_dir)
    config_file = args.config or default_config_path()
    return config_file.parent if config_file is not None else Path.cwd()


def _hardware(args: argparse.Namespace, factory: BackendFactory) -> int:
    from .hardware_source import HardwareSource

    try:
        config = load_config(args.config)
        required_devices(args.profile, config)
    except ConfigError as exc:
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        backend = factory(config.scan_s)
        try:
            backend.check()
        except DeviceError:
            backend.close()
            raise
        state_dir = _state_dir(args)
        store = FileCalibrationStore(state_dir)
        trace = None
        if config.debug.eeg_trace:
            trace = CsvTraceWriter(state_dir / TRACE_NAME, config.debug.eeg_trace_max_kb * 1024)
        source = HardwareSource(
            args.profile, config, backend, eeg_method=args.eeg_method, store=store, eeg_trace=trace
        )
    except DeviceError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_DEVICES
    server = BridgeServer(source, port=args.port, eeg_method=args.eeg_method)
    source.start()
    try:
        if args.headless:
            with contextlib.suppress(KeyboardInterrupt):
                asyncio.run(server.serve_forever())
        else:
            from .window import run_window

            thread = BridgeThread(server)
            thread.start()
            try:
                run_window(source, args.profile, keyboard=False)
            finally:
                thread.stop()
    finally:
        source.close()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
