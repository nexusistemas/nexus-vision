"""
Aba 4 — Conta, Licença Anti-Fraude & Atualizações (vision.nexusistemas.app.br).
Exibe HWID físico real do Windows (SHA-256), ativação online via Supabase RPC,
status de contingência offline 72h / Anti-Clock Tampering e Auto-Updater GitHub.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import (
    APP_NAME,
    APP_VERSION,
    BRAND_ASSETS,
    COMPANY_NAME,
    DATA_DIR,
    PORTAL_DOMAIN,
    PORTAL_URL,
)
from core.database import DatabaseManager
from core.license_manager import (
    LICENSE_KEY_REGEX,
    LicenseHeartbeatWorker,
    LicenseManager,
    LicenseStatus,
)
from core.updater import UpdateCheckWorker, UpdateDownloadWorker
from supabase_config import GITHUB_REPO, is_supabase_configured


class LicenseTab(QWidget):
    """Aba de licenciamento Node-Locked (HWID), status anti-fraude e Auto-Updater."""

    def __init__(
        self,
        db: DatabaseManager,
        license_manager: LicenseManager,
        heartbeat_worker: LicenseHeartbeatWorker,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.license_manager = license_manager
        self.heartbeat_worker = heartbeat_worker
        self.hw_info = license_manager.hw_info

        self._update_check_worker: Optional[UpdateCheckWorker] = None
        self._update_download_worker: Optional[UpdateDownloadWorker] = None
        self._pending_update_info: Optional[dict[str, Any]] = None

        self._build_ui()
        self._load_initial_key()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # --- Banner Institucional ---
        hero = QFrame()
        hero.setProperty("card", "elevated")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(18)

        logo_box = QLabel()
        logo_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_box.setFixedSize(150, 90)
        logo_box.setStyleSheet(
            "background-color: #E2E8F0; border: 2px solid #06B6D4; border-radius: 12px; padding: 6px;"
        )
        logo_path = BRAND_ASSETS.logo_full or BRAND_ASSETS.logo_mark
        if logo_path and logo_path.exists():
            pix = QPixmap(str(logo_path))
            if not pix.isNull():
                logo_box.setPixmap(
                    pix.scaled(
                        136,
                        76,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        else:
            logo_box.setText("NEXUS\nVISION")
            logo_box.setStyleSheet(
                "background-color: #0E2A3F; color: #22D3EE; border: 2px solid #06B6D4; "
                "border-radius: 12px; font-weight: 900; font-size: 16px;"
            )

        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        lbl_name = QLabel(f"{APP_NAME} v{APP_VERSION}  •  {COMPANY_NAME}")
        lbl_name.setStyleSheet("color: #F8FAFC; font-size: 18px; font-weight: 800; background: transparent;")
        lbl_desc = QLabel(
            f"Portal Comercial & Gestão de Licenças: {PORTAL_DOMAIN}  •  Proteção Node-Locked HWID"
        )
        lbl_desc.setProperty("muted", "true")

        self.lbl_license_badge = QLabel("● VERIFICANDO LICENÇA...")
        self.lbl_license_badge.setStyleSheet(
            "color: #38BDF8; background-color: #0E2A3F; border: 1px solid #0891B2; "
            "border-radius: 10px; padding: 4px 12px; font-size: 11px; font-weight: 800;"
        )
        self.lbl_license_badge.setFixedHeight(26)

        info_col.addWidget(lbl_name)
        info_col.addWidget(lbl_desc)
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.lbl_license_badge)
        badge_row.addStretch()
        info_col.addLayout(badge_row)

        btn_portal = QPushButton(f"🌐  Abrir {PORTAL_DOMAIN}")
        btn_portal.setProperty("variant", "primary")
        btn_portal.setMinimumHeight(38)
        btn_portal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PORTAL_URL)))

        hl.addWidget(logo_box)
        hl.addLayout(info_col, 1)
        hl.addWidget(btn_portal)
        root.addWidget(hero)

        # --- Card 1: Ativação de Chave & Status em Tempo Real ---
        act_card = QFrame()
        act_card.setProperty("card", "true")
        al = QVBoxLayout(act_card)
        al.setContentsMargins(18, 16, 18, 16)
        al.setSpacing(12)

        lbl_act_title = QLabel("ATIVAÇÃO DE LICENÇA COMERCIAL (NODE-LOCKED)")
        lbl_act_title.setProperty("sectionTitle", "true")

        self.lbl_status_message = QLabel("Consultando servidor de licenciamento...")
        self.lbl_status_message.setWordWrap(True)
        self.lbl_status_message.setStyleSheet(
            "background-color: #0B1324; border: 1px solid #1E293B; border-radius: 8px; "
            "padding: 10px 12px; color: #CBD5E1; font-size: 13px;"
        )

        key_row = QHBoxLayout()
        key_row.setSpacing(10)

        self.in_license_key = QLineEdit()
        self.in_license_key.setPlaceholderText("NV-XXXX-XXXX-XXXX")
        self.in_license_key.setMaxLength(17)
        self.in_license_key.setStyleSheet(
            "font-family: Consolas, 'Cascadia Code', monospace; font-size: 16px; "
            "font-weight: 800; letter-spacing: 2px; padding: 10px;"
        )
        self.in_license_key.textEdited.connect(self._format_license_input)

        self.btn_activate = QPushButton("🔑  Ativar / Validar Online")
        self.btn_activate.setProperty("variant", "success")
        self.btn_activate.setMinimumHeight(42)
        self.btn_activate.clicked.connect(self._trigger_activation)

        key_row.addWidget(self.in_license_key, 1)
        key_row.addWidget(self.btn_activate)

        # Metadados da licença ativa
        lic_grid = QGridLayout()
        lic_grid.setHorizontalSpacing(18)
        lic_grid.setVerticalSpacing(6)
        self.lbl_val_condo = QLabel("—")
        self.lbl_val_plano = QLabel("—")
        self.lbl_val_expira = QLabel("—")
        self.lbl_val_grace = QLabel("72h após validação online")
        for lbl in (self.lbl_val_condo, self.lbl_val_plano, self.lbl_val_expira, self.lbl_val_grace):
            lbl.setStyleSheet("color: #F8FAFC; font-weight: 700; background: transparent;")

        for idx, (k, widget) in enumerate(
            [
                ("Condomínio / Cliente:", self.lbl_val_condo),
                ("Plano:", self.lbl_val_plano),
                ("Validade da Licença:", self.lbl_val_expira),
                ("Contingência Offline:", self.lbl_val_grace),
            ]
        ):
            r, c = divmod(idx, 2)
            lk = QLabel(k)
            lk.setProperty("muted", "true")
            lic_grid.addWidget(lk, r, c * 2)
            lic_grid.addWidget(widget, r, c * 2 + 1)

        al.addWidget(lbl_act_title)
        al.addWidget(self.lbl_status_message)
        al.addLayout(key_row)
        al.addLayout(lic_grid)
        root.addWidget(act_card)

        # --- Card 2: Identificação Física da Máquina (HWID SHA-256) ---
        hw_card = QFrame()
        hw_card.setProperty("card", "true")
        hwl = QVBoxLayout(hw_card)
        hwl.setContentsMargins(18, 16, 18, 16)
        hwl.setSpacing(10)

        lbl_hw_title = QLabel("IDENTIFICAÇÃO FÍSICA DA ESTAÇÃO (HWID WINDOWS — SHA-256)")
        lbl_hw_title.setProperty("sectionTitle", "true")
        lbl_hw_sub = QLabel(
            "Combina MachineGuid do Registro + UUID da Placa-Mãe + Serial do Volume do Sistema."
        )
        lbl_hw_sub.setProperty("muted", "true")

        hwid_row = QHBoxLayout()
        hwid_row.setSpacing(10)
        self.in_hwid = QLineEdit(self.hw_info.hwid_sha256)
        self.in_hwid.setReadOnly(True)
        self.in_hwid.setStyleSheet(
            "font-family: Consolas, 'Cascadia Code', monospace; font-size: 13px; "
            "font-weight: 700; color: #22D3EE; padding: 9px;"
        )

        self.btn_copy_hwid = QPushButton("📋  Copiar HWID")
        self.btn_copy_hwid.setMinimumHeight(38)
        self.btn_copy_hwid.setFixedWidth(150)
        self.btn_copy_hwid.clicked.connect(self._copy_hwid)

        hwid_row.addWidget(self.in_hwid, 1)
        hwid_row.addWidget(self.btn_copy_hwid)

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(18)
        meta_grid.setVerticalSpacing(6)
        meta_items = [
            ("Fingerprint Curto:", self.hw_info.hwid_short),
            ("Hostname / Volume:", f"{self.hw_info.hostname}  •  Vol {self.hw_info.volume_serial}"),
            ("Sistema Operacional:", self.hw_info.os_summary),
            ("Pasta de Dados Local:", str(DATA_DIR)),
            ("Banco Local SQLite:", f"Modo {self.db.get_journal_mode()} (Offline-First)"),
            ("Servidor Supabase:", "Configurado (Produção)" if is_supabase_configured() else "DEMO_LOCAL (Configure supabase_config.py)"),
        ]
        for idx, (k, v) in enumerate(meta_items):
            r, c = divmod(idx, 2)
            lk = QLabel(k)
            lk.setProperty("muted", "true")
            lv = QLabel(v)
            lv.setStyleSheet("color: #E2E8F0; font-weight: 600; background: transparent;")
            meta_grid.addWidget(lk, r, c * 2)
            meta_grid.addWidget(lv, r, c * 2 + 1)

        hwl.addWidget(lbl_hw_title)
        hwl.addWidget(lbl_hw_sub)
        hwl.addLayout(hwid_row)
        hwl.addLayout(meta_grid)
        root.addWidget(hw_card)

        # --- Card 3: Auto-Updater via GitHub Releases ---
        upd_card = QFrame()
        upd_card.setProperty("card", "true")
        ul = QVBoxLayout(upd_card)
        ul.setContentsMargins(18, 16, 18, 16)
        ul.setSpacing(10)

        upd_hdr = QHBoxLayout()
        lbl_upd_title = QLabel(f"ATUALIZAÇÕES DO APLICATIVO (v{APP_VERSION})")
        lbl_upd_title.setProperty("sectionTitle", "true")
        lbl_repo = QLabel(f"Origem: github.com/{GITHUB_REPO}")
        lbl_repo.setProperty("muted", "true")
        upd_hdr.addWidget(lbl_upd_title)
        upd_hdr.addStretch()
        upd_hdr.addWidget(lbl_repo)

        self.lbl_update_status = QLabel("Clique em 'Verificar Atualizações' para consultar novas versões.")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setProperty("muted", "true")

        self.progress_update = QProgressBar()
        self.progress_update.setObjectName("MotionBar")
        self.progress_update.setRange(0, 100)
        self.progress_update.setValue(0)
        self.progress_update.setVisible(False)

        upd_btns = QHBoxLayout()
        upd_btns.setSpacing(10)
        self.btn_check_update = QPushButton("↻  Verificar Atualizações")
        self.btn_check_update.setProperty("variant", "primary")
        self.btn_check_update.setMinimumHeight(36)
        self.btn_check_update.clicked.connect(self._check_for_updates)

        self.btn_download_update = QPushButton("⬇  Baixar e Instalar Atualização")
        self.btn_download_update.setProperty("variant", "success")
        self.btn_download_update.setMinimumHeight(36)
        self.btn_download_update.setVisible(False)
        self.btn_download_update.clicked.connect(self._download_update)

        upd_btns.addWidget(self.btn_check_update)
        upd_btns.addWidget(self.btn_download_update)
        upd_btns.addStretch()

        ul.addLayout(upd_hdr)
        ul.addWidget(self.lbl_update_status)
        ul.addWidget(self.progress_update)
        ul.addLayout(upd_btns)
        root.addWidget(upd_card)

        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    # =========================================================================
    # AÇÕES DE LICENCIAMENTO
    # =========================================================================

    def _load_initial_key(self) -> None:
        saved_code = self.license_manager.get_saved_license_code()
        if saved_code:
            self.in_license_key.setText(saved_code)

    def _copy_hwid(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.hw_info.hwid_sha256)
        self.btn_copy_hwid.setText("✓  HWID Copiado!")
        QTimer.singleShot(1800, lambda: self.btn_copy_hwid.setText("📋  Copiar HWID"))

    def _format_license_input(self, raw: str) -> None:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", raw.upper())
        if cleaned.startswith("NV"):
            body = cleaned[2:14]
            parts = ["NV"] + [body[i : i + 4] for i in range(0, len(body), 4) if body[i : i + 4]]
            formatted = "-".join(parts)
        else:
            formatted = "-".join(
                cleaned[i : i + 4] for i in range(0, min(len(cleaned), 16), 4)
            )
        self.in_license_key.blockSignals(True)
        self.in_license_key.setText(formatted)
        self.in_license_key.setCursorPosition(len(formatted))
        self.in_license_key.blockSignals(False)

    def _trigger_activation(self) -> None:
        key = self.in_license_key.text().strip().upper()
        if not LICENSE_KEY_REGEX.match(key):
            QMessageBox.warning(
                self,
                "Formato de Chave Inválido",
                "Informe a chave exatamente no formato:\nNV-XXXX-XXXX-XXXX\n\n"
                "Exemplo: NV-8F2A-9C10-4D7E",
            )
            return

        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("⏳  Validando...")
        self.heartbeat_worker.trigger_validation(key)

    def apply_license_status(self, status: LicenseStatus) -> None:
        self.btn_activate.setEnabled(True)
        self.btn_activate.setText("🔑  Ativar / Validar Online")

        if status.code and not self.in_license_key.text().strip():
            self.in_license_key.setText(status.code)

        self.lbl_status_message.setText(status.message)
        self.lbl_val_condo.setText(status.condominio_nome or "—")
        self.lbl_val_plano.setText(status.plano or "—")
        self.lbl_val_expira.setText((status.validade_ate or "—")[:10] if status.validade_ate else "—")
        self.lbl_val_grace.setText(
            f"Até {status.offline_grace_until}" if status.offline_grace_until else "72h após validação online"
        )

        badge_styles = {
            "ONLINE_VALID": ("● LICENÇA ATIVA (ONLINE)", "#6EE7B7", "#064E3B", "#10B981"),
            "OFFLINE_GRACE": ("● CONTINGÊNCIA OFFLINE (72H)", "#38BDF8", "#0E2A3F", "#0891B2"),
            "DEMO_LOCAL": ("● MODO DEMO LOCAL (SEM SUPABASE)", "#FCD34D", "#3A2208", "#F59E0B"),
            "BLOCKED": ("● LICENÇA BLOQUEADA", "#FCA5A5", "#450A0A", "#EF4444"),
            "EXPIRED": ("● LICENÇA EXPIRADA", "#FDBA74", "#431407", "#F97316"),
            "HWID_MISMATCH": ("● HWID DE OUTRO COMPUTADOR", "#FCA5A5", "#450A0A", "#EF4444"),
            "CLOCK_TAMPERED": ("● RELÓGIO DO WINDOWS ADULTERADO", "#FCA5A5", "#450A0A", "#EF4444"),
            "UNLICENSED": ("● AGUARDANDO ATIVAÇÃO", "#CBD5E1", "#1E293B", "#475569"),
        }
        txt, fg, bg, border = badge_styles.get(
            status.mode, ("● " + status.mode, "#CBD5E1", "#1E293B", "#475569")
        )
        self.lbl_license_badge.setText(txt)
        self.lbl_license_badge.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border: 1px solid {border}; "
            "border-radius: 10px; padding: 4px 12px; font-size: 11px; font-weight: 800;"
        )

    # =========================================================================
    # AUTO-UPDATER (GITHUB RELEASES)
    # =========================================================================

    def _check_for_updates(self) -> None:
        if self._update_check_worker and self._update_check_worker.isRunning():
            return
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("⏳  Verificando...")
        self.lbl_update_status.setText("Consultando GitHub Releases...")
        self.btn_download_update.setVisible(False)

        self._update_check_worker = UpdateCheckWorker(parent=self)
        self._update_check_worker.check_finished.connect(self._on_update_check_finished)
        self._update_check_worker.start()

    def _on_update_check_finished(self, info: dict[str, Any]) -> None:
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText("↻  Verificar Atualizações")
        self._pending_update_info = info

        if info.get("error"):
            self.lbl_update_status.setText(str(info["error"]))
            return

        if info.get("available"):
            latest = info.get("latest_version")
            self.lbl_update_status.setText(
                f"Nova versão disponível: v{latest} (atual: v{APP_VERSION}). "
                "Clique abaixo para baixar o novo instalador."
            )
            if info.get("download_url"):
                self.btn_download_update.setVisible(True)
        else:
            self.lbl_update_status.setText(
                f"Você já está na versão mais recente do Nexus Vision (v{APP_VERSION})."
            )

    def _download_update(self) -> None:
        if not self._pending_update_info or not self._pending_update_info.get("download_url"):
            return
        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self.btn_download_update.setEnabled(False)
        self.btn_check_update.setEnabled(False)
        self.progress_update.setValue(0)
        self.progress_update.setVisible(True)
        self.lbl_update_status.setText("Baixando novo instalador NexusVision_Setup.exe...")

        self._update_download_worker = UpdateDownloadWorker(
            download_url=self._pending_update_info["download_url"],
            asset_name=self._pending_update_info.get("asset_name") or "NexusVision_Setup.exe",
            parent=self,
        )
        self._update_download_worker.progress_changed.connect(self.progress_update.setValue)
        self._update_download_worker.download_finished.connect(self._on_download_finished)
        self._update_download_worker.start()

    def _on_download_finished(self, file_path: str, error: str) -> None:
        self.btn_download_update.setEnabled(True)
        self.btn_check_update.setEnabled(True)
        if error or not file_path:
            self.lbl_update_status.setText(error or "Falha no download.")
            return

        self.lbl_update_status.setText(f"Download concluído: {file_path}")
        reply = QMessageBox.question(
            self,
            "Atualização Pronta",
            "O novo instalador do Nexus Vision foi baixado com sucesso.\n\n"
            "Deseja iniciar a instalação agora?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.startfile(file_path)  # type: ignore[attr-defined]
            except Exception as exc:
                QMessageBox.warning(self, "Erro ao Abrir Instalador", str(exc))
