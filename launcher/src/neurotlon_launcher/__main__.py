"""Точка входа: `neurotlon-launcher --config launcher.toml [--no-camera] [--windowed]`."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from .api import HttpStationApi
from .config import ConfigError, LauncherConfig, load_config
from .game import SubprocessGameRunner
from .heartbeat import HeartbeatLoop
from .machine import StationMachine
from .outbox import Outbox
from .qr import create_scanner
from .recovery import recover_active
from .sender import Sender
from .startup import check_discipline

EXIT_OK = 0
EXIT_CONFIG = 2
DEFAULT_CONFIG = Path("launcher.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neurotlon-launcher", description="Лаунчер стенда")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="путь к launcher.toml")
    parser.add_argument("--no-camera", action="store_true", help="без вебки: только ввод ID")
    parser.add_argument("--windowed", action="store_true", help="окно вместо полного экрана")
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
    from .ui import Ui  # pygame подключаем только здесь

    data_dir = config.data_dir
    api = HttpStationApi(
        config.server_url,
        token,
        cache_path=data_dir / "config-cache.json",
        ca_file=config.ca_file,
    )
    outbox = Outbox(data_dir / "outbox.db")
    sender = Sender(outbox, api)
    runner = SubprocessGameRunner(
        config.game_command,
        config.game_workdir,
        data_dir,
        config.bridge_host,
        config.bridge_port,
        fullscreen=not windowed,
    )
    machine = StationMachine(
        config.discipline,
        api,
        outbox,
        runner,
        on_enqueue=sender.kick,
        fallback_duration_s=config.fallback_duration_s,
    )
    heartbeat = HeartbeatLoop(api, machine.heartbeat_view, outbox.pending_count)
    recover_active(machine, outbox, data_dir)
    problem = check_discipline(api, config.discipline)
    if problem:
        machine.block(problem)
    scanner = create_scanner(config.camera_index, enabled=camera)
    sender.start()
    heartbeat.start()
    try:
        Ui(
            machine,
            scanner,
            lambda: (outbox.pending_count(), outbox.rejected_count()),
            windowed=windowed,
        ).run()
    finally:
        machine.close()
        scanner.stop()
        heartbeat.stop()
        sender_stopped = sender.stop()
        api.close()
        if sender_stopped:
            outbox.close()  # пока поток досылки жив, базу не закрываем
        else:
            logging.getLogger(__name__).warning("sender thread did not stop, outbox left open")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        token = config.read_token()
    except ConfigError as exc:
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    setup_logging(config)
    run(config, token, camera=not args.no_camera, windowed=args.windowed)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
