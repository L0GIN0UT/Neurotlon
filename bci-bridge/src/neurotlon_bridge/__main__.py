"""Точка входа: `neurotlon-bridge --emulate`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import Sequence

from .emulator import EmulatedSource
from .server import BridgeServer, BridgeThread
from .source import PROFILES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurotlon-bridge", description="BCI-мост Нейротлона")
    parser.add_argument("--emulate", action="store_true", help="эмулятор датчиков (клавиши)")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="darts")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--headless", action="store_true", help="без окна (значения не меняются)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.emulate:
        print("реальные датчики — следующий шаг M2")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source = EmulatedSource(args.profile, time.monotonic)
    server = BridgeServer(source, port=args.port)
    if args.headless:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(server.serve_forever())
        return 0
    from .window import run_window

    thread = BridgeThread(server)
    thread.start()
    try:
        run_window(source, args.profile)
    finally:
        thread.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
