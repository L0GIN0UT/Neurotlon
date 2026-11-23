"""Точка входа: `neurotlon-launcher --config launcher.toml [--no-camera] [--windowed]`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigError, LauncherConfig, load_config
from .qr import create_scanner
from .runtime import StationRuntime
from .web_bridge import BridgeServer, Station

EXIT_OK = 0
EXIT_CONFIG = 2
DEFAULT_CONFIG = Path("launcher.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurotlon-launcher", description="Лаунчер стенда")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="путь к launcher.toml")
    parser.add_argument("--no-camera", action="store_true", help="без вебки: только ввод ID")
    parser.add_argument("--windowed", action="store_true", help="окно вместо полного экрана")
    parser.add_argument(
        "--ui",
        choices=("pygame", "web"),
        default="pygame",
        help="web: отдавать состояние окну Electron по локальному HTTP",
    )
    parser.add_argument("--ui-token", default="", help="токен запуска для --ui web")
    parser.add_argument("--ui-port", type=int, default=0, help="порт моста (0 — любой свободный)")
    parser.add_argument(
        "--ui-detached",
        action="store_true",
        help="для разработки: не следить за stdin, работать до Ctrl+C",
    )
    return parser


def setup_logging(config: LauncherConfig) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.data_dir / "launcher.log", encoding="utf-8"),
        ],
    )


def run(config: LauncherConfig, token: str, *, camera: bool, windowed: bool) -> None:
    """Интерфейс на pygame (запасной): окно рисует сам лаунчер."""
    from .ui import Ui  # pygame подключаем только здесь

    with StationRuntime(config, token, fullscreen=not windowed) as station:
        scanner = create_scanner(config.camera_index, enabled=camera)
        try:
            Ui(station.machine, scanner, station.status, windowed=windowed).run()
        finally:
            scanner.stop()


def run_web(
    config: LauncherConfig, token: str, *, ui_token: str, ui_port: int, detached: bool = False
) -> None:
    """Веб-интерфейс: лаунчер отдаёт состояние по локальному HTTP, окно рисует Electron.

    После запуска печатает в stdout строку `{"ready": true, "port": N}` и работает, пока не
    закроется stdin (так Electron сообщает, что окно закрыто) или не придёт прерывание.
    """
    with StationRuntime(config, token, fullscreen=True) as runtime:
        station = Station(runtime.machine, runtime.status)
        server = BridgeServer(station, ui_token, ui_port)
        station.start()
        thread = threading.Thread(target=server.serve_forever, name="web-bridge", daemon=True)
        thread.start()
        print(json.dumps({"ready": True, "port": server.port}), flush=True)
        try:
            if detached:
                threading.Event().wait()
            else:
                sys.stdin.read()  # возвращается, когда родитель закрыл канал
        except KeyboardInterrupt:
            pass
        finally:
            server.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        token = config.read_token()
    except ConfigError as exc:
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    setup_logging(config)
    if args.ui == "web":
        if len(args.ui_token) < 16:
            print(
                "Ошибка настроек: для --ui web нужен --ui-token (от 16 символов)", file=sys.stderr
            )
            return EXIT_CONFIG
        run_web(
            config,
            token,
            ui_token=args.ui_token,
            ui_port=args.ui_port,
            detached=args.ui_detached,
        )
    else:
        run(config, token, camera=not args.no_camera, windowed=args.windowed)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
