"""Точка входа: `neurotlon-launcher --config launcher.toml [--no-camera] [--windowed]`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigError, LauncherConfig, load_config
from .qr import create_scanner
from .runtime import StationRuntime
from .setup import SetupService
from .setup_station import SetupStation
from .web_bridge import BridgeServer, LiveState, Station

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_RESTART = 75  # настройки сохранены: окно перезапускает лаунчер в рабочем режиме
SAVED_LINGER_S = 1.5  # столько экран показывает «Сохранено», прежде чем лаунчер выйдет
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
        "--setup",
        action="store_true",
        help="открыть экран настройки, даже если настройки уже есть (для --ui web)",
    )
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


def serve_bridge(
    station: LiveState,
    *,
    ui_token: str,
    ui_port: int,
    detached: bool,
    done: threading.Event | None = None,
) -> bool:
    """Поднять мост и ждать конца работы; `True`, если завершились по событию `done`.

    После запуска печатает в stdout строку `{"ready": true, "port": N}`. Работает, пока родитель
    не закроет stdin (так Electron сообщает, что окно закрыто), не сработает `done` или Ctrl+C.
    """
    server = BridgeServer(station, ui_token, ui_port)
    station.start()
    threading.Thread(target=server.serve_forever, name="web-bridge", daemon=True).start()
    print(json.dumps({"ready": True, "port": server.port}), flush=True)
    closed = threading.Event()
    if not detached:

        def watch_stdin() -> None:
            sys.stdin.read()  # возвращается, когда родитель закрыл канал
            closed.set()

        threading.Thread(target=watch_stdin, name="stdin-watch", daemon=True).start()
    finished = False
    try:
        while not closed.is_set():
            if done is not None and done.wait(0.2):
                finished = True
                time.sleep(SAVED_LINGER_S)
                break
            if done is None:
                closed.wait(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return finished


def run_web(
    config: LauncherConfig, token: str, *, ui_token: str, ui_port: int, detached: bool = False
) -> None:
    """Веб-интерфейс: лаунчер отдаёт состояние по локальному HTTP, окно рисует Electron."""
    with StationRuntime(config, token, fullscreen=True) as runtime:
        serve_bridge(
            Station(runtime.machine, runtime.status, config.camera_name),
            ui_token=ui_token,
            ui_port=ui_port,
            detached=detached,
        )


def run_setup(
    config_path: Path, *, error: str | None, ui_token: str, ui_port: int, detached: bool
) -> int:
    """Экран первой настройки: `EXIT_RESTART`, если настройки сохранены."""
    station = SetupStation(SetupService(config_path), error)
    saved = serve_bridge(
        station, ui_token=ui_token, ui_port=ui_port, detached=detached, done=station.saved
    )
    return EXIT_RESTART if saved else EXIT_OK


def main_web(args: argparse.Namespace) -> int:
    if len(args.ui_token) < 16:
        print("Ошибка настроек: для --ui web нужен --ui-token (от 16 символов)", file=sys.stderr)
        return EXIT_CONFIG
    error: str | None = None
    if not args.setup:
        try:
            config = load_config(args.config)
            token = config.read_token()
            setup_logging(config)
            run_web(
                config,
                token,
                ui_token=args.ui_token,
                ui_port=args.ui_port,
                detached=args.ui_detached,
            )
            return EXIT_OK
        except ConfigError as exc:
            # Нет файла — обычная первая настройка; всё остальное показываем админу в форме.
            error = str(exc) if args.config.is_file() else None
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return run_setup(
        args.config,
        error=error,
        ui_token=args.ui_token,
        ui_port=args.ui_port,
        detached=args.ui_detached,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ui == "web":
        return main_web(args)
    try:
        config = load_config(args.config)
        token = config.read_token()
        setup_logging(config)
        run(config, token, camera=not args.no_camera, windowed=args.windowed)
    except ConfigError as exc:
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
