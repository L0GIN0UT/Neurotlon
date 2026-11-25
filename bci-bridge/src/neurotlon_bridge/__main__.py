"""Точка входа: `neurotlon-bridge --emulate | --scan | --profile X`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .config import ConfigError, load_config, required_devices
from .devices.base import DeviceBackend, DeviceError
from .devices.scan import format_devices, scan_devices
from .emulator import EmulatedSource
from .server import BridgeServer, BridgeThread
from .source import EEG_METHODS, PROFILES, EegMethod

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_DEVICES = 3
SCAN_SECONDS = 15.0  # BLE находит датчики не сразу: 10 секунд бывало мало
SCAN_JSON_MARK = "NEUROTLON_SCAN_JSON="

DEFAULT_EEG_METHOD: EegMethod = "alpha"

BackendFactory = Callable[[float], DeviceBackend]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurotlon-bridge", description="BCI-мост Нейротлона")
    parser.add_argument("--emulate", action="store_true", help="эмулятор датчиков (клавиши)")
    parser.add_argument("--scan", action="store_true", help="найти датчики, вывести и выйти")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="darts")
    parser.add_argument(
        "--eeg-method",
        choices=EEG_METHODS,
        default=DEFAULT_EEG_METHOD,
        help="метод ЭЭГ: alpha (относительная альфа) или emotions (NeuroSDK Emotions)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, help="путь к bridge.toml (по умолчанию рядом)")
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


def main(
    argv: Sequence[str] | None = None, *, backend_factory: BackendFactory | None = None
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger(__name__).info("bridge started: %s", " ".join(sys.argv[1:]))
    factory = backend_factory or default_backend_factory
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
                payload = json.dumps([dataclasses.asdict(d) for d in found], ensure_ascii=False)
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
        source = HardwareSource(args.profile, config, backend, eeg_method=args.eeg_method)
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
