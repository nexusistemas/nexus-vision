"""
Ponto de entrada do aplicativo Desktop Nexus Vision — NexuSistemas Tecnologia.
Inclui proteção Single-Instance (QLocalServer/QLocalSocket): clicar no atalho
com o app já aberto traz a janela existente para frente sem abrir duplicatas.
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

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from config import APP_NAME, BRAND_ASSETS, COMPANY_NAME, ensure_directories
from core.database import DatabaseManager
from ui.main_window import MainWindow
from ui.styles import DARK_STYLESHEET

SINGLE_INSTANCE_KEY = "NexuSistemas_NexusVision_SingleInstance_v1"


def _configure_windows_taskbar_id() -> None:
    """Define AppUserModelID no Windows para exibir o ícone nexus_vision.ico na barra de tarefas."""
    if platform.system() == "Windows":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NexuSistemas.NexusVision.Desktop.1"
            )
        except Exception:
            pass


def _notify_running_instance(server_key: str = SINGLE_INSTANCE_KEY) -> bool:
    """
    Tenta avisar uma instância já aberta do Nexus Vision para vir para frente.
    Retorna True se já existir outra instância ativa (neste caso devemos encerrar).
    """
    socket = QLocalSocket()
    socket.connectToServer(server_key)
    if socket.waitForConnected(400):
        socket.write(b"SHOW_WINDOW")
        socket.flush()
        socket.waitForBytesWritten(400)
        socket.disconnectFromServer()
        return True
    return False


def _bring_window_to_front(window: MainWindow) -> None:
    """Restaura (se minimizada) e traz a janela existente para o topo no Windows."""
    if window.isMinimized():
        window.showNormal()
    elif not window.isVisible():
        window.show()

    window.setWindowState(
        (window.windowState() & ~Qt.WindowState.WindowMinimized)
        | Qt.WindowState.WindowActive
    )
    window.raise_()
    window.activateWindow()

    if platform.system() == "Windows":
        try:
            hwnd = int(window.winId())
            user32 = ctypes.windll.user32
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def main() -> int:
    _configure_windows_taskbar_id()
    ensure_directories()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(COMPANY_NAME)

    # 1) Bloqueio Single-Instance ANTES de carregar banco ou modelos ONNX
    if _notify_running_instance(SINGLE_INSTANCE_KEY):
        return 0

    # 2) Inicia servidor local para escutar futuros cliques no atalho
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    instance_server = QLocalServer(app)
    instance_server.listen(SINGLE_INSTANCE_KEY)

    app.setStyleSheet(DARK_STYLESHEET)
    if BRAND_ASSETS.app_icon and BRAND_ASSETS.app_icon.exists():
        app.setWindowIcon(QIcon(str(BRAND_ASSETS.app_icon)))

    db = DatabaseManager()
    window = MainWindow(db)

    def _on_second_instance_connected() -> None:
        while instance_server.hasPendingConnections():
            conn = instance_server.nextPendingConnection()
            if conn is not None:
                conn.waitForReadyRead(200)
                conn.readAll()
                conn.disconnectFromServer()
                conn.deleteLater()
        _bring_window_to_front(window)

    instance_server.newConnection.connect(_on_second_instance_connected)
    app.aboutToQuit.connect(instance_server.close)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
