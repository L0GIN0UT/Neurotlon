"""Связь с процессом поиска датчиков `neurotlon-bridge --discover` (`shared/sensor-discovery.md`).

Процесс живёт, пока открыт экран настройки: лаунчер шлёт ему команды в stdin, читает сообщения
из stdout (строки с меткой; остальное, например мусор NeuroSDK, пропускается). Закрытие stdin
означает «отпустить датчики и выйти». Само устройство ввода-вывода спрятано за `DiscoveryProcess`:
тесты подставляют поток строк вместо настоящего процесса.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
from typing import IO, Any, Protocol

from neurotlon_contracts.discovery import (
    COMMANDS,
    decode_bridge_line,
    discovery_problem,
)

from .proc import close_job, create_kill_on_close_job

log = logging.getLogger(__name__)

QUIT_WAIT_S = 3.0  # столько ждём выхода после `quit`, потом завершаем принудительно
EXITED = "Поиск датчиков завершился (код {code})"
STDERR_KEEP = 20
MAX_LINE = 64 * 1024  # строка вывода длиннее отбрасывается, не доходя до JSON
ERROR_MAX = 300  # столько знаков stderr попадает в сообщение об ошибке


def bounded_lines(stream: IO[str], limit: int = MAX_LINE) -> Iterator[str]:
    """Строки потока; строка длиннее `limit` читается кусками и отдаётся пустой."""
    while True:
        chunk = stream.readline(limit + 1)
        if not chunk:
            return
        if len(chunk) <= limit or chunk.endswith("\n"):
            yield chunk
            continue
        while chunk and not chunk.endswith("\n"):  # пропускаем хвост слишком длинной строки
            chunk = stream.readline(limit)
        yield ""
        if not chunk:
            return


class DiscoveryProcess(Protocol):
    """Запущенный процесс поиска: строки в stdin, строки из stdout и stderr."""

    def write(self, line: str) -> None:
        """Записать строку в stdin процесса (`OSError`, если он закрыт)."""

    def close_input(self) -> None:
        """Закрыть stdin: так процессу сообщают «выходи»."""

    def stdout_lines(self) -> Iterator[str]:
        """Строки вывода до конца потока."""

    def stderr_lines(self) -> Iterator[str]: ...

    def returncode(self) -> int | None:
        """Код выхода, `None`, пока процесс жив."""

    def wait(self, timeout: float) -> bool:
        """Ждать выхода; `True`, если процесс вышел."""

    def kill(self) -> None:
        """Принудительно завершить и освободить всё, что с ним связано."""


class DiscoveryListener(Protocol):
    def on_message(self, message: dict[str, Any]) -> None:
        """Сообщение моста, прошедшее схему (из потока чтения)."""

    def on_exit(self, error: str | None) -> None:
        """Процесс закончился сам (не по `close()`); `error` — последняя строка его stderr."""


class DiscoveryClient:
    def __init__(self, process: DiscoveryProcess, listener: DiscoveryListener) -> None:
        self._process = process
        self._listener = listener
        self._closing = threading.Event()
        self._lock = threading.Lock()  # записи в stdin
        self._tail: list[str] = []
        self._threads: list[threading.Thread] = []
        self._errors: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return not self._closing.is_set() and self._process.returncode() is None

    def start(self) -> None:
        errors = threading.Thread(target=self._read_errors, name="discovery-err", daemon=True)
        output = threading.Thread(target=self._read, name="discovery-out", daemon=True)
        self._errors = errors
        for thread in (errors, output):
            thread.start()
            self._threads.append(thread)

    def send(self, command: Mapping[str, Any]) -> bool:
        """Отправить команду; `False`, если она не по схеме или процесс не принимает."""
        problem = discovery_problem(COMMANDS, command)
        if problem is not None:
            log.warning("команда не по схеме: %s (%s)", command, problem)
            return False
        line = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if not self.alive:
                return False
            try:
                self._process.write(line + "\n")
            except (OSError, ValueError):
                return False
        return True

    def close(self) -> None:
        """Отпустить датчики и дождаться выхода процесса; после этого `on_exit` не зовётся."""
        if self._closing.is_set():
            return
        quit_sent = self.send({"cmd": "quit"})
        self._closing.set()
        try:
            self._process.close_input()
        except (OSError, ValueError):
            log.debug("stdin уже закрыт")
        if not (self._process.wait(QUIT_WAIT_S if quit_sent else 0.5)):
            log.warning("поиск датчиков не вышел сам, завершаем принудительно")
        self._process.kill()  # освобождает Job Object; вышедшему процессу вреда не делает
        for thread in self._threads:
            if thread is not threading.current_thread():  # выход может закрывать свой же поток
                thread.join(timeout=1.0)

    # --- потоки чтения ---
    def _read(self) -> None:
        try:
            for line in self._process.stdout_lines():
                if len(line) > MAX_LINE:
                    log.debug("discovery: строка длиннее %d знаков отброшена", MAX_LINE)
                    continue
                try:
                    message = decode_bridge_line(line)
                except Exception:  # любой сбой разбора (в том числе RecursionError)
                    log.debug("discovery: строка не разобрана")
                    continue
                if message is None:
                    log.debug("discovery: %s", line.strip()[:200])
                    continue
                try:
                    self._listener.on_message(message)
                except Exception:
                    log.exception("обработка сообщения поиска")
        except (OSError, ValueError):
            log.debug("вывод поиска закрыт")
        except Exception:
            log.exception("чтение вывода поиска")
        if self._closing.is_set():
            return
        self._process.wait(1.0)
        if self._errors is not None:
            self._errors.join(timeout=1.0)  # последняя строка stderr приходит вместе с выходом
        code = self._process.returncode()
        with self._lock:
            error = self._tail[-1] if self._tail else None
        try:
            text = error or EXITED.format(code="?" if code is None else code)
            self._listener.on_exit(text[:ERROR_MAX])
        except Exception:
            log.exception("обработка выхода поиска")

    def _read_errors(self) -> None:
        try:
            for raw in self._process.stderr_lines():
                line = raw.strip()
                if not line:
                    continue
                log.info("bridge discover: %s", line)
                with self._lock:
                    self._tail = [*self._tail, line][-STDERR_KEEP:]
        except (OSError, ValueError):
            log.debug("stderr поиска закрыт")


class PopenDiscoveryProcess:
    """Настоящий процесс в Job Object «убить при закрытии»: умрёт вместе с лаунчером."""

    def __init__(self, args: Sequence[str]) -> None:
        self._proc = subprocess.Popen(
            list(args),
            stdin=subprocess.PIPE,  # свой канал, не унаследованный от Electron
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._job = create_kill_on_close_job(self._proc)
        log.info("bridge discover started, pid %s", self._proc.pid)

    def write(self, line: str) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise OSError("stdin закрыт")
        stdin.write(line)
        stdin.flush()

    def close_input(self) -> None:
        if self._proc.stdin is not None:
            self._proc.stdin.close()

    def stdout_lines(self) -> Iterator[str]:
        return bounded_lines(self._proc.stdout) if self._proc.stdout else iter(())

    def stderr_lines(self) -> Iterator[str]:
        return bounded_lines(self._proc.stderr) if self._proc.stderr else iter(())

    def returncode(self) -> int | None:
        return self._proc.poll()

    def wait(self, timeout: float) -> bool:
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    def kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=5)
        if self._job is not None:
            close_job(self._job)
            self._job = None
        for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            if stream is not None:
                try:
                    stream.close()  # ручки не копятся от перезапуска к перезапуску
                except (OSError, ValueError):
                    log.debug("поток уже закрыт")


def spawn_process(args: Sequence[str]) -> DiscoveryProcess:
    return PopenDiscoveryProcess(args)
