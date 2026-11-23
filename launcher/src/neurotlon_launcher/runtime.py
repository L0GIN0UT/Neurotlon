"""Сборка и остановка всего, что нужно станции: API, буфер, досылка, игра, машина, heartbeat.

Всё, что нужно рабочему режиму станции; окно (Electron) получает состояние через `web_bridge`.
"""

from __future__ import annotations

import logging
from types import TracebackType

from . import texts
from .api import HttpStationApi, StationApiError, Unauthorized
from .config import ConfigError, LauncherConfig
from .game import SubprocessGameRunner
from .heartbeat import HeartbeatLoop
from .machine import StationMachine
from .outbox import Outbox
from .recovery import recover_active
from .sender import Sender
from .sensors import BridgeProcess, BridgeStatus
from .startup import check_discipline
from .status import StationStatus

log = logging.getLogger(__name__)


class StationRuntime:
    def __init__(
        self, config: LauncherConfig, token: str, *, fullscreen: bool, bridge_exe: str = ""
    ) -> None:
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
        discipline = config.discipline or self._discover_discipline()
        self.machine = StationMachine(
            discipline,
            self.api,
            self.outbox,
            runner,
            on_enqueue=self.sender.kick,
            fallback_duration_s=config.fallback_duration_s,
        )
        self.heartbeat = HeartbeatLoop(
            self.api, self.machine.heartbeat_view, self.outbox.pending_count
        )
        self.bridge = self._make_bridge(config, discipline, bridge_exe)
        recover_active(self.machine, self.outbox, data_dir)
        problem = check_discipline(self.api, config.discipline) if config.discipline else None
        if problem:
            self.machine.block(problem)

    @staticmethod
    def _make_bridge(config: LauncherConfig, discipline: str, exe: str) -> BridgeProcess | None:
        """Мост датчиков: запускается самим лаунчером, если в настройках не «external»."""
        if config.bridge_mode == "external" or not exe:
            return None
        args = [exe, "--profile", discipline, "--port", str(config.bridge_port)]
        if config.bridge_mode == "emulate":
            args.append("--emulate")  # окно эмулятора: значения задаются клавишами
        else:
            args += ["--headless", "--config", str(config.token_file.parent / "bridge.toml")]
        return BridgeProcess(args, config.bridge_mode)

    def bridge_status(self) -> BridgeStatus | None:
        return self.bridge.status() if self.bridge else None

    def _discover_discipline(self) -> str:
        """Дисциплина станции с сервера (без связи — из кэша прошлого запуска)."""
        try:
            return self.api.get_config().discipline
        except Unauthorized as exc:
            raise ConfigError(texts.UNAUTHORIZED) from exc
        except StationApiError as exc:
            raise ConfigError(texts.DISCIPLINE_UNKNOWN) from exc

    def status(self) -> StationStatus:
        return StationStatus(
            self.outbox.pending_count(), self.outbox.rejected_count(), self.heartbeat.online
        )

    def __enter__(self) -> StationRuntime:
        self.sender.start()
        self.heartbeat.start()
        if self.bridge:
            self.bridge.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.machine.close()
        if self.bridge:
            self.bridge.stop()
        self.heartbeat.stop()
        sender_stopped = self.sender.stop()
        self.api.close()
        if sender_stopped:
            self.outbox.close()  # пока поток досылки жив, базу не закрываем
        else:
            log.warning("sender thread did not stop, outbox left open")
