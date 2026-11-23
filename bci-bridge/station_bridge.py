"""Точка входа для сборки моста датчиков в .exe (PyInstaller).

Сборку запускает `deploy/scripts/build-station-installer.ps1`.
"""

import sys

from neurotlon_bridge.__main__ import main

for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(
            encoding="utf-8"
        )  # русские сообщения не должны превращаться в кракозябры

if __name__ == "__main__":
    sys.exit(main())
