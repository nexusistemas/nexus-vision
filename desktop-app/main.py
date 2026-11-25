"""
Ponto de entrada do aplicativo Desktop Nexus Vision — NexuSistemas Tecnologia.
Etapa 1: Captura Universal ROI Multi-Monitor, Detector de Movimento, SQLite WAL e UI 24h.
"""

from __future__ import annotations

import ctypes
import platform
import sys
from pathlib import Path

# Garante importações locais consistentes independente do diretório de execução
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from config import APP_NAME, BRAND_ASSETS, COMPANY_NAME, ensure_directories
from core.database import DatabaseManager
from ui.main_window import MainWindow
from ui.styles import DARK_STYLESHEET


def _configure_windows_taskbar_id() -> None:
    """Define AppUserModelID no Windows para exibir o ícone nexus.ico na barra de tarefas."""
    if platform.system() == "Windows":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NexuSistemas.NexusVision.Desktop.1"
            )
        except Exception:
            pass


def main() -> int:
    _configure_windows_taskbar_id()
    ensure_directories()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(COMPANY_NAME)
    app.setStyleSheet(DARK_STYLESHEET)

    if BRAND_ASSETS.app_icon and BRAND_ASSETS.app_icon.exists():
        app.setWindowIcon(QIcon(str(BRAND_ASSETS.app_icon)))

    db = DatabaseManager()
    window = MainWindow(db)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
