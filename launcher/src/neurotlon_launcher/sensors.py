"""Датчики стенда: поиск через мост, серийные номера в `bridge.toml`, запуск и надзор за мостом.

Мост (`neurotlon-bridge`) отдельная программа: игры берут сигналы у неё. Лаунчер запускает её
сам, подставляет профиль по дисциплине станции и перезапускает, если она упала.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

BRIDGE_TOML = "bridge.toml"
SCAN_TIMEOUT_S = 45.0
SCAN_SECONDS = 15  # столько ищет мост; окно показывает отсчёт
SCAN_JSON_MARK = "NEUROTLON_SCAN_JSON="  # строка со списком среди сообщений SDK
RESTART_DELAYS_S = (3.0, 6.0, 12.0, 30.0)  # пауза перед перезапуском моста растёт до 30 с

# Какие сигналы нужны дисциплине и каким датчиком каждый снимается.
ROLES: dict[str, tuple[str, ...]] = {
    "darts": ("eeg", "emg"),
    "football": ("eeg", "emg"),
    "pong": ("emg_left", "emg_right"),
}
ROLE_KIND = {"eeg": "brainbit", "emg": "callibri", "emg_left": "callibri", "emg_right": "callibri"}
MODES = ("external", "hardware", "emulate")

NO_BRIDGE = "Мост датчиков не входит в эту установку"
SCAN_FAILED = "Не удалось найти датчики"
SCAN_TIMEOUT = "Поиск датчиков не завершился вовремя"


@dataclass(frozen=True)
class SensorDevice:
    kind: str  # brainbit | callibri
    name: str
    serial: str
    address: str

    def view(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "name": self.name,
            "serial": self.serial,
            "address": self.address,
        }


def roles_for(discipline: str | None) -> tuple[str, ...]:
    return ROLES.get(discipline or "", ())


def missing_roles(discipline: str, devices: dict[str, str]) -> list[str]:
    """Сигналы дисциплины, для которых не задан серийный номер."""
    return [role for role in roles_for(discipline) if not devices.get(role, "").strip()]


def duplicate_serials(discipline: str, devices: dict[str, str]) -> bool:
    values = [
        devices[r].strip().lower() for r in roles_for(discipline) if devices.get(r, "").strip()
    ]
    return len(values) != len(set(values))


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], *, timeout: float
    ) -> subprocess.CompletedProcess[str]: ...


def _run(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        stdin=subprocess.DEVNULL,  # см. _popen
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # русский текст без кракозябр
    )


class SensorService:
    """Поиск датчиков и файл `bridge.toml` рядом с настройками лаунчера."""

    def __init__(self, config_dir: Path, bridge_exe: str = "", runner: Runner = _run) -> None:
        self._dir = config_dir
        self._exe = bridge_exe
        self._runner = runner

    @property
    def available(self) -> bool:
        return bool(self._exe)

    @property
    def toml_path(self) -> Path:
        return self._dir / BRIDGE_TOML

    def saved_devices(self) -> dict[str, str]:
        try:
            data = tomllib.loads(self.toml_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
        raw = data.get("devices", {})
        return {k: str(v) for k, v in raw.items() if isinstance(v, str | int) and str(v).strip()}

    def save_devices(self, devices: dict[str, str]) -> None:
        lines = ["# Записано экраном настройки стенда. Серийные номера датчиков.", "[devices]"]
        for role in ("eeg", "emg", "emg_left", "emg_right"):
            serial = devices.get(role, "").strip()
            if serial:
                lines.append(f"{role} = {json.dumps(serial, ensure_ascii=False)}")
        temp = self.toml_path.with_suffix(".toml.tmp")
        self._dir.mkdir(parents=True, exist_ok=True)
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp.replace(self.toml_path)

    def scan(self) -> tuple[list[SensorDevice], str | None]:
        """Найденные датчики и ошибка (по-русски) или `None`."""
        if not self._exe:
            return [], NO_BRIDGE
        try:
            done = self._runner([self._exe, "--scan", "--json"], timeout=SCAN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return [], SCAN_TIMEOUT
        except OSError as exc:
            return [], f"{SCAN_FAILED}: {exc}"
        if done.returncode != 0:
            reason = (done.stderr or "").strip().splitlines()
            return [], reason[-1] if reason else SCAN_FAILED
        for line in done.stdout.splitlines():
            log.info("bridge scan: %s", line.strip())
        marked = [line for line in done.stdout.splitlines() if line.startswith(SCAN_JSON_MARK)]
        if not marked:
            return [], SCAN_FAILED
        try:
            items: list[dict[str, Any]] = json.loads(marked[-1][len(SCAN_JSON_MARK) :])
            return [
                SensorDevice(
                    str(i["kind"]), str(i["name"]), str(i.get("serial") or ""), str(i["address"])
                )
                for i in items
            ], None
        except (ValueError, KeyError, TypeError):
            return [], SCAN_FAILED


class Popener(Protocol):
    def __call__(self, args: Sequence[str]) -> subprocess.Popen[str]: ...


def _popen(args: Sequence[str]) -> subprocess.Popen[str]:
    # stdin обязательно DEVNULL: Electron даёт ядру канал, на котором ядро ждёт закрытия окна
    # (чтение в потоке). Унаследовавший его мост на Windows зависал бы при старте Python.
    return subprocess.Popen(
        list(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@dataclass(frozen=True)
class BridgeStatus:
    mode: str
    ok: bool
    error: str | None = None


class BridgeProcess:
    """Запускает мост и держит его живым: упавший перезапускается с растущей паузой."""

    def __init__(
        self,
        args: Sequence[str],
        mode: str,
        popen: Popener = _popen,
        sleep: Callable[[float], bool] | None = None,
    ) -> None:
        self._args = list(args)
        self._mode = mode
        self._popen = popen
        self._stop = threading.Event()
        self._wait = sleep or self._stop.wait
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    def status(self) -> BridgeStatus:
        with self._lock:
            proc, error = self._proc, self._error
        running = proc is not None and proc.poll() is None
        return BridgeStatus(self._mode, running, None if running else error)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._supervise, name="bridge-supervisor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _supervise(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                proc = self._popen(self._args)
            except OSError as exc:
                self._set(None, f"Мост не запустился: {exc}")
                proc = None
            if proc is not None:
                self._set(proc, None)
                log.info("bridge started, pid %s", getattr(proc, "pid", "?"))
                lines: list[str] = []
                if proc.stderr:
                    for raw in proc.stderr:  # вывод моста сразу в журнал: видно, что он делает
                        line = raw.strip()
                        if line:
                            lines.append(line)
                            log.info("bridge: %s", line)
                code = proc.wait()
                if self._stop.is_set():
                    return
                self._set(proc, lines[-1] if lines else f"Мост завершился (код {code})")
                log.warning("bridge exited with code %s: %s", code, self._error)
            delay = RESTART_DELAYS_S[min(failures, len(RESTART_DELAYS_S) - 1)]
            failures += 1
            if self._wait(delay):
                return

    def _set(self, proc: subprocess.Popen[str] | None, error: str | None) -> None:
        with self._lock:
            self._proc, self._error = proc, error
