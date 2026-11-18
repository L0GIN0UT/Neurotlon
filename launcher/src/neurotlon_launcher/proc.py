"""Запуск игры вместе со всем деревом процессов и надёжное завершение.

Windows: процесс стартует в новой группе и кладётся в Job Object с флагом
KILL_ON_JOB_CLOSE, так что дети игры (Unity, python-потомки) умирают вместе с ней и даже
вместе с лаунчером. Не удалось создать Job — запасной путь `taskkill /T /F`.
POSIX: новая сессия и `killpg`.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _BasicLimits(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    )


class _IoCounters(ctypes.Structure):
    _fields_ = tuple(
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    )


class _ExtendedLimits(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


def _create_kill_on_close_job(process: subprocess.Popen[bytes]) -> int | None:
    """Job Object с процессом внутри или `None`, если не вышло."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    # _handle есть у Popen на Windows; приватный, но другого пути к HANDLE нет.
    handle = getattr(process, "_handle", None)
    if not ok or handle is None or not kernel32.AssignProcessToJobObject(job, int(handle)):
        kernel32.CloseHandle(job)
        return None
    return int(job)


def _terminate_job(job: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.TerminateJobObject(job, 1)
    kernel32.CloseHandle(job)


class ManagedProcess:
    """Процесс игры; `kill()` убивает всё дерево."""

    def __init__(
        self, args: Sequence[str], cwd: Path | None, output: IO[bytes] | int | None
    ) -> None:
        if sys.platform == "win32":
            self._proc = subprocess.Popen(
                list(args),
                cwd=cwd,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            self._job = _create_kill_on_close_job(self._proc)
            if self._job is None:
                log.warning("job object unavailable, falling back to taskkill /T")
        else:
            self._proc = subprocess.Popen(
                list(args),
                cwd=cwd,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._job = None

    @property
    def pid(self) -> int:
        return self._proc.pid

    def poll(self) -> int | None:
        return self._proc.poll()

    def kill(self) -> None:
        """Убить игру и всех её потомков, дождаться выхода."""
        if sys.platform == "win32":
            if self._job is not None:
                _terminate_job(self._job)
                self._job = None
            elif self._proc.poll() is None:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(self._proc.pid)],
                    capture_output=True,
                    check=False,
                )
        else:
            if self._proc.poll() is None:  # группа жива, пока жив её лидер
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(self._proc.pid, signal.SIGKILL)
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
