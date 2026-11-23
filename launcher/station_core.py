"""Точка входа для сборки ядра лаунчера в .exe (PyInstaller).

Сборку запускает `deploy/scripts/build-station-installer.ps1`.
"""

import os
import sys

if getattr(sys, "frozen", False):
    # Схемы контракта кладутся рядом с программой, а не ищутся по дереву репозитория.
    os.environ.setdefault("NEUROTLON_SHARED", os.path.join(sys._MEIPASS, "shared"))  # type: ignore[attr-defined]

from neurotlon_launcher.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
