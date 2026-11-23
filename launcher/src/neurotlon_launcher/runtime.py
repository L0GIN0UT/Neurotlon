"""Сборка и остановка всего, что нужно станции: API, буфер, досылка, игра, машина, heartbeat.

Общая часть для обоих интерфейсов (pygame и веб): они различаются только тем, что рисуют.
"""

from __future__ import annotations

import logging
from types import TracebackType

from .api import HttpStationApi
from .config import LauncherConfig
from .game import SubprocessGameRunner
from .heartbeat import HeartbeatLoop
from .machine import StationMachine
from .outbox import Outbox
from .recovery import recover_active
from .sender import Sender
from .startup import check_discipline
from .status import StationStatus

log = logging.getLogger(__name__)


class StationRuntime:
    def __init__(self, config: LauncherConfig, token: str, *, fullscreen: bool) -> None:
        data_dir = config.data_dir
        self.api = HttpStationApi(
            config.server_url,
            token,
            cache_path=data_dir / "config-cache.json",
            ca_file=config.ca_file,
        )
        self.outbox = Outbox(data_dir / "outbox.db")
        self.sender = Sender(self.outbox, self.api)
        runner = SubprocessGameRunner(
            config.game_command,
            config.game_workdir,
            data_dir,
            config.bridge_host,
            config.bridge_port,
            fullscreen=fullscreen,
        )
        self.machine = StationMachine(
            config.discipline,
            self.api,
            self.outbox,
            runner,
            on_enqueue=self.sender.kick,
            fallback_duration_s=config.fallback_duration_s,
        )
        self.heartbeat = HeartbeatLoop(
            self.api, self.machine.heartbeat_view, self.outbox.pending_count
        )
        recover_active(self.machine, self.outbox, data_dir)
        problem = check_discipline(self.api, config.discipline)
        if problem:
            self.machine.block(problem)

    def status(self) -> StationStatus:
        return StationStatus(
            self.outbox.pending_count(), self.outbox.rejected_count(), self.heartbeat.online
        )

    def __enter__(self) -> StationRuntime:
        self.sender.start()
        self.heartbeat.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.machine.close()
        self.heartbeat.stop()
        sender_stopped = self.sender.stop()
        self.api.close()
        if sender_stopped:
            self.outbox.close()  # пока поток досылки жив, базу не закрываем
        else:
            log.warning("sender thread did not stop, outbox left open")
