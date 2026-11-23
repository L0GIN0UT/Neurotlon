"""Точка входа для сборки моста датчиков в .exe (PyInstaller).

Сборку запускает `deploy/scripts/build-station-installer.ps1`.
"""

import sys

from neurotlon_bridge.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
