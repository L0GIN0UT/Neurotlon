"""Точка входа для сборки моста датчиков в .exe (PyInstaller).

Сборку запускает `deploy/scripts/build-station-installer.ps1`.
"""

import os
import sys

if getattr(sys, "frozen", False):
    # Схема поиска датчиков кладётся рядом с программой, а не ищется по дереву репозитория.
    # присваиваем напрямую: чужое значение переменной не должно подменить схему
    os.environ["NEUROTLON_SHARED"] = os.path.join(sys._MEIPASS, "shared")  # type: ignore[attr-defined]

from neurotlon_bridge.__main__ import main

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(
            encoding="utf-8"
        )  # русские сообщения не должны превращаться в кракозябры

if __name__ == "__main__":
    sys.exit(main())
