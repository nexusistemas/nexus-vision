"""
Janela Principal (MainWindow) do Nexus Vision — NexuSistemas Tecnologia.
Sidebar corporativa Dark 24h com detecção automática da logo na raiz,
ícone nativo da janela (QIcon), relógio digital 24h e navegação entre as 4 abas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import (
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    BRAND_ASSETS,
    CAPTURES_RETENTION_HOURS,
    COMPANY_NAME,
    HISTORY_RETENTION_HOURS,
    cleanup_old_captures,
)
from core.cloud_backup import CloudBackupWorker
from core.database import DatabaseManager
from core.license_manager import LicenseHeartbeatWorker, LicenseManager, LicenseStatus
from ui.tab_history import HistoryTab
from ui.tab_license import LicenseTab
from ui.tab_monitor import MonitorTab
from ui.tab_vehicles import VehiclesTab


class MainWindow(QMainWindow):
    """Shell principal do aplicativo desktop Nexus Vision."""

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.license_manager = LicenseManager(self.db)
        self.license_heartbeat = LicenseHeartbeatWorker(self.license_manager, parent=self)
        self._cloud_worker: Optional[CloudBackupWorker] = None
        self._auto_restore_checked: bool = False
        self._cloud_sync_timer = QTimer(self)
        self._cloud_sync_timer.setSingleShot(True)
        self._cloud_sync_timer.setInterval(3000)
        self._cloud_sync_timer.timeout.connect(lambda: self._run_cloud_operation("backup", silent=True))
        self._nav_buttons: list[QPushButton] = []

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — {COMPANY_NAME}")
        self.resize(1340, 840)
        self.setMinimumSize(1100, 700)

        # Ícone da janela detectado automaticamente (nexus_vision.ico / nexus.ico / fallback png)
        if BRAND_ASSETS.app_icon and BRAND_ASSETS.app_icon.exists():
            self.setWindowIcon(QIcon(str(BRAND_ASSETS.app_icon)))

        self._build_ui()
        self._connect_signals()
        self._start_clock()
        self._switch_tab(0)
        self._run_24h_cleanup()
        # Limpeza automática contínua a cada 1 hora (mantém apenas últimas 24h mesmo rodando sem fechar)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(60 * 60 * 1000)
        self._cleanup_timer.timeout.connect(self._run_24h_cleanup)
        self._cleanup_timer.start()
        self.license_heartbeat.start()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # =====================================================================
        # SIDEBAR ESQUERDA
        # =====================================================================
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(252)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        # Cabeçalho da marca com logo detectada na raiz
        brand_frame = QFrame()
        brand_frame.setObjectName("BrandContainer")
        bf_layout = QHBoxLayout(brand_frame)
        bf_layout.setContentsMargins(16, 18, 16, 18)
        bf_layout.setSpacing(12)

        logo_label = QLabel()
        logo_label.setObjectName("LogoBadge")
        logo_label.setFixedSize(52, 52)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_path = BRAND_ASSETS.logo_mark or BRAND_ASSETS.logo_full or BRAND_ASSETS.app_icon
        if logo_path and logo_path.exists():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                logo_label.setPixmap(
                    pix.scaled(
                        42,
                        42,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        else:
            logo_label.setText("NV")
            logo_label.setStyleSheet(
                "background-color: #0891B2; color: #FFFFFF; border-radius: 12px; "
                "font-size: 18px; font-weight: 900;"
            )

        brand_text_col = QVBoxLayout()
        brand_text_col.setSpacing(2)
        lbl_title = QLabel("NEXUS VISION")
        lbl_title.setObjectName("BrandTitle")
        lbl_sub = QLabel("NexuSistemas")
        lbl_sub.setObjectName("BrandSubtitle")
        brand_text_col.addWidget(lbl_title)
        brand_text_col.addWidget(lbl_sub)

        bf_layout.addWidget(logo_label)
        bf_layout.addLayout(brand_text_col, 1)
        sb_layout.addWidget(brand_frame)

        # Menu de Navegação
        nav_container = QWidget()
        nav_container.setStyleSheet("background: transparent;")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(12, 18, 12, 12)
        nav_layout.setSpacing(6)

        nav_items = [
            ("📹   Monitoramento Ao Vivo", "Monitoramento Ao Vivo", "Captura ROI em tempo real e gatilho de movimento"),
            ("🚗   Moradores && Veículos", "Cadastro de Moradores e Veículos", "Base local offline-first e importação CSV"),
            ("🕒   Histórico de Acessos", "Histórico de Acessos", "Auditoria por data, placa e miniatura capturada"),
            ("🔐   Conta && Licença", "Conta & Licença", "Identificação HWID Windows e ativação vision.nexusistemas.app.br"),
        ]
        self._page_meta: list[tuple[str, str]] = []

        for idx, (btn_label, title, subtitle) in enumerate(nav_items):
            self._page_meta.append((title, subtitle))
            btn = QPushButton(btn_label)
            btn.setProperty("nav", "true")
            btn.setProperty("active", "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self._switch_tab(i))
            self._nav_buttons.append(btn)
            nav_layout.addWidget(btn)

        nav_layout.addStretch(1)
        sb_layout.addWidget(nav_container, 1)

        # Rodapé da Sidebar (Status do Sistema 24h)
        footer = QFrame()
        footer.setObjectName("SidebarFooter")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(14, 12, 14, 14)
        fl.setSpacing(4)

        self.lbl_sb_capture = QLabel("● Captura: Aguardando")
        self.lbl_sb_capture.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 700; background: transparent;")
        self.lbl_sb_alpr = QLabel("● IA ALPR: Carregando...")
        self.lbl_sb_alpr.setStyleSheet("color: #FBBF24; font-size: 11px; font-weight: 700; background: transparent;")
        self.lbl_sb_license = QLabel("● Licença: Verificando...")
        self.lbl_sb_license.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 700; background: transparent;")
        lbl_db = QLabel(f"● SQLite {self.db.get_journal_mode()} Offline-First")
        lbl_db.setStyleSheet("color: #10B981; font-size: 11px; font-weight: 600; background: transparent;")
        lbl_ver = QLabel(f"v{APP_VERSION}")
        lbl_ver.setStyleSheet("color: #64748B; font-size: 11px; background: transparent;")

        fl.addWidget(self.lbl_sb_capture)
        fl.addWidget(self.lbl_sb_alpr)
        fl.addWidget(self.lbl_sb_license)
        fl.addWidget(lbl_db)
        fl.addWidget(lbl_ver)
        sb_layout.addWidget(footer)

        # =====================================================================
        # ÁREA DIREITA (TOPBAR + STACK DE ABAS)
        # =====================================================================
        right_shell = QWidget()
        right_layout = QVBoxLayout(right_shell)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("TopBar")
        topbar.setFixedHeight(68)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 10, 20, 10)
        tb.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.lbl_page_title = QLabel(APP_NAME)
        self.lbl_page_title.setObjectName("PageTitle")
        self.lbl_page_subtitle = QLabel(APP_SUBTITLE)
        self.lbl_page_subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(self.lbl_page_title)
        title_col.addWidget(self.lbl_page_subtitle)

        self.lbl_vehicle_pill = QLabel("0 veículos cadastrados")
        self.lbl_vehicle_pill.setObjectName("PillBadge")

        self.lbl_clock = QLabel("--:--:--")
        self.lbl_clock.setObjectName("ClockLabel")

        tb.addLayout(title_col, 1)
        tb.addWidget(self.lbl_vehicle_pill)
        tb.addWidget(self.lbl_clock)

        # Stack com as 4 abas
        self.stack = QStackedWidget()
        self.tab_monitor = MonitorTab(self.db, self)
        self.tab_vehicles = VehiclesTab(self.db, self)
        self.tab_history = HistoryTab(self.db, self)
        self.tab_license = LicenseTab(
            self.db, self.license_manager, self.license_heartbeat, self
        )

        self.stack.addWidget(self.tab_monitor)
        self.stack.addWidget(self.tab_vehicles)
        self.stack.addWidget(self.tab_history)
        self.stack.addWidget(self.tab_license)

        right_layout.addWidget(topbar)
        right_layout.addWidget(self.stack, 1)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(right_shell, 1)

        self._update_vehicle_counter()

    def _connect_signals(self) -> None:
        self.tab_monitor.access_logged.connect(self.tab_history.refresh_history)
        self.tab_monitor.capture_state_changed.connect(self._on_capture_state_changed)
        self.tab_monitor.alpr_status_changed.connect(self._on_alpr_status_changed)
        self.tab_monitor.quick_register_requested.connect(self._on_quick_register_requested)
        self.tab_monitor.open_license_tab_requested.connect(lambda: self._switch_tab(3))
        self.tab_vehicles.vehicles_changed.connect(self._update_vehicle_counter)
        self.tab_vehicles.vehicles_changed.connect(self.tab_monitor.refresh_recent_passages)
        self.tab_vehicles.vehicles_changed.connect(self._schedule_auto_cloud_backup)
        self.tab_vehicles.cloud_backup_requested.connect(lambda: self._run_cloud_operation("backup", silent=False))
        self.tab_vehicles.cloud_restore_requested.connect(self._confirm_and_restore_cloud)
        self.license_heartbeat.license_updated.connect(self._on_license_updated)

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        title, subtitle = self._page_meta[index]
        self.lbl_page_title.setText(title)
        self.lbl_page_subtitle.setText(subtitle)

        for idx, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if index == 2:
            self.tab_history.refresh_history()
        elif index == 0:
            self.tab_monitor.refresh_recent_passages()

    def _start_clock(self) -> None:
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

    def _tick_clock(self) -> None:
        self.lbl_clock.setText(datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))

    def _update_vehicle_counter(self) -> None:
        total = self.db.count_vehicles()
        self.lbl_vehicle_pill.setText(f"🚗  {total} veículo(s) na base")

    def _on_capture_state_changed(self, state: str) -> None:
        if state == "ATIVA":
            self.lbl_sb_capture.setText("● Captura: ATIVA (~15 FPS)")
            self.lbl_sb_capture.setStyleSheet(
                "color: #22D3EE; font-size: 11px; font-weight: 700; background: transparent;"
            )
        elif state == "PAUSADA":
            self.lbl_sb_capture.setText("● Captura: PAUSADA")
            self.lbl_sb_capture.setStyleSheet(
                "color: #FBBF24; font-size: 11px; font-weight: 700; background: transparent;"
            )
        else:
            self.lbl_sb_capture.setText("● Captura: Parada")
            self.lbl_sb_capture.setStyleSheet(
                "color: #94A3B8; font-size: 11px; font-weight: 700; background: transparent;"
            )

    def _on_alpr_status_changed(self, message: str, ready: bool) -> None:
        if ready:
            self.lbl_sb_alpr.setText("● IA ALPR: ONNX CPU")
            self.lbl_sb_alpr.setStyleSheet(
                "color: #10B981; font-size: 11px; font-weight: 700; background: transparent;"
            )
        elif "Erro" in message:
            self.lbl_sb_alpr.setText("● IA ALPR: ERRO")
            self.lbl_sb_alpr.setStyleSheet(
                "color: #F87171; font-size: 11px; font-weight: 700; background: transparent;"
            )
            self.lbl_sb_alpr.setToolTip(message)
        else:
            self.lbl_sb_alpr.setText("● IA ALPR: Carregando...")
            self.lbl_sb_alpr.setStyleSheet(
                "color: #FBBF24; font-size: 11px; font-weight: 700; background: transparent;"
            )

    def _on_quick_register_requested(self, plate: str) -> None:
        self._switch_tab(1)
        self.tab_vehicles.prefill_new_vehicle(plate)

    def _on_license_updated(self, status: LicenseStatus) -> None:
        self.tab_monitor.apply_license_status(status)
        self.tab_license.apply_license_status(status)

        if status.mode == "ONLINE_VALID":
            self.lbl_sb_license.setText("● Licença: ATIVA")
            self.lbl_sb_license.setStyleSheet("color: #10B981; font-size: 11px; font-weight: 700; background: transparent;")
            # Se for PC recém-formatado/novo (base local vazia), tenta restaurar backup da nuvem automaticamente!
            if not self._auto_restore_checked and self.db.count_vehicles() == 0:
                self._auto_restore_checked = True
                self._run_cloud_operation("restore", silent=True)
        elif status.mode == "OFFLINE_GRACE":
            self.lbl_sb_license.setText("● Licença: OFFLINE 72h")
            self.lbl_sb_license.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 700; background: transparent;")
        elif status.mode == "DEMO_LOCAL":
            self.lbl_sb_license.setText("● Licença: DEMO LOCAL")
            self.lbl_sb_license.setStyleSheet("color: #FBBF24; font-size: 11px; font-weight: 700; background: transparent;")
        else:
            self.lbl_sb_license.setText(f"● Licença: {status.mode}")
            self.lbl_sb_license.setStyleSheet("color: #F87171; font-size: 11px; font-weight: 700; background: transparent;")

    def _schedule_auto_cloud_backup(self) -> None:
        st = self.license_manager.current_status
        if st.allowed and st.code and not st.is_demo:
            self.tab_vehicles.set_cloud_status("Sincronizando alterações na nuvem em instantes...", ok=True)
            self._cloud_sync_timer.start()

    def _confirm_and_restore_cloud(self) -> None:
        reply = QMessageBox.question(
            self,
            "Restaurar Backup da Nuvem",
            "Deseja baixar e restaurar todos os veículos salvos na nuvem para a licença atual?\n\n"
            "Placas já cadastradas localmente serão atualizadas e novas placas da nuvem serão adicionadas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_cloud_operation("restore", silent=False)

    def _run_cloud_operation(self, mode: str, silent: bool = False) -> None:
        if self._cloud_worker is not None and self._cloud_worker.isRunning():
            return
        code = self.license_manager.get_saved_license_code()
        if not code:
            if not silent:
                QMessageBox.information(
                    self,
                    "Licença Necessária",
                    "Ative sua chave de licença na Aba 4 (Conta & Licença) para utilizar o backup na nuvem.",
                )
            return

        self.tab_vehicles.set_cloud_status(
            "Enviando backup para a nuvem..." if mode == "backup" else "Buscando backup na nuvem...",
            ok=True,
        )
        self._cloud_worker = CloudBackupWorker(
            mode=mode,
            db=self.db,
            license_code=code,
            hwid=self.license_manager.hwid,
            silent=silent,
            parent=self,
        )
        self._cloud_worker.finished_operation.connect(self._on_cloud_operation_finished)
        self._cloud_worker.start()

    def _on_cloud_operation_finished(
        self, ok: bool, mode: str, message: str, extra: dict
    ) -> None:
        silent = bool(extra.get("silent", False))
        now_hm = datetime.now().strftime("%H:%M:%S")
        self.tab_vehicles.set_cloud_status(f"{message} ({now_hm})", ok=ok)

        if mode == "restore" and ok and int(extra.get("total") or 0) > 0:
            self.tab_vehicles.refresh_table()
            self._update_vehicle_counter()
            self.tab_monitor.refresh_recent_passages()
            QMessageBox.information(
                self,
                "Backup Restaurado da Nuvem",
                f"{message}\n\nSeus moradores e veículos já estão prontos para leitura offline.",
            )
            return

        if not silent:
            if ok:
                QMessageBox.information(self, "Nuvem Nexus Vision", message)
            else:
                QMessageBox.warning(self, "Nuvem Nexus Vision", message)

    def _run_24h_cleanup(self) -> None:
        """Apaga automaticamente fotos e histórico com mais de 24 horas."""
        cleanup_old_captures(max_hours=CAPTURES_RETENTION_HOURS)
        deleted = self.db.prune_old_history(max_hours=HISTORY_RETENTION_HOURS)
        if deleted > 0:
            self.tab_monitor.refresh_recent_passages()
            self.tab_history.refresh_history()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cleanup_timer.stop()
        self._cloud_sync_timer.stop()
        if self._cloud_worker is not None and self._cloud_worker.isRunning():
            self._cloud_worker.wait(2500)
        self.license_heartbeat.stop()
        self.tab_monitor.shutdown()
        self.db.close()
        super().closeEvent(event)
