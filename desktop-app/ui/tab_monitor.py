"""
Aba 1 — Monitoramento Ao Vivo do Nexus Vision (Produção 24h).
Integra captura ROI (~15 FPS), detector de movimento, filtro de distância/nitidez,
motor ALPR ONNX CPU, votação/cooldown, alertas sonoros Windows, Card Gigante de Status
limpo com destaque máximo para Morador/Casa/Veículo e lista lateral das últimas passagens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import (
    ACCESS_STATUS_BLOQUEADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_LIBERADO_MORADOR,
    ACCESS_STATUS_LIBERADO_VISITANTE,
    ACCESS_STATUS_NAO_CADASTRADO,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MOTION_SENSITIVITY,
    DEFAULT_SOUND_ENABLED,
    MAX_RECENT_PASSAGES,
)
from core.alpr_engine import (
    DEFAULT_QUALITY_PRESET,
    QUALITY_PRESETS,
    ALPREngineWorker,
    save_alpr_capture,
)
from core.database import DatabaseManager, format_plate_display, normalize_plate
from core.license_manager import LicenseStatus
from core.screen_capture import ScreenCaptureWorker
from core.sound_alerts import SoundAlertManager
from ui.roi_selector import ROISelectorOverlay


STATUS_THEME = {
    ACCESS_STATUS_LIBERADO_MORADOR: {
        "title": "MORADOR AUTORIZADO",
        "bg": "#052E1F",
        "border": "#10B981",
        "badge_bg": "#059669",
        "accent": "#34D399",
        "short": "AUTORIZADO",
        "bgr": (129, 185, 16),
    },
    ACCESS_STATUS_LIBERADO_VISITANTE: {
        "title": "VISITANTE AUTORIZADO",
        "bg": "#082840",
        "border": "#38BDF8",
        "badge_bg": "#0284C7",
        "accent": "#7DD3FC",
        "short": "VISITANTE",
        "bgr": (248, 189, 56),
    },
    ACCESS_STATUS_NAO_CADASTRADO: {
        "title": "NÃO CADASTRADO / VISITANTE",
        "bg": "#3A1E08",
        "border": "#F59E0B",
        "badge_bg": "#D97706",
        "accent": "#FCD34D",
        "short": "NÃO CADASTRADO",
        "bgr": (11, 158, 245),
    },
    ACCESS_STATUS_BLOQUEADO: {
        "title": "ALERTA: VEÍCULO BLOQUEADO",
        "bg": "#450A12",
        "bg_alt": "#7F1D1D",
        "border": "#EF4444",
        "badge_bg": "#DC2626",
        "accent": "#FCA5A5",
        "short": "BLOQUEADO",
        "bgr": (68, 68, 239),
    },
    ACCESS_STATUS_EXPIRADO: {
        "title": "VISITANTE EXPIRADO",
        "bg": "#3B1219",
        "border": "#F97316",
        "badge_bg": "#EA580C",
        "accent": "#FDBA74",
        "short": "EXPIRADO",
        "bgr": (22, 115, 249),
    },
}


class MonitorTab(QWidget):
    """Aba principal de monitoramento 24h com IA ALPR nativa offline."""

    access_logged = Signal()
    capture_state_changed = Signal(str)
    alpr_status_changed = Signal(str, bool)
    quick_register_requested = Signal(str)
    open_license_tab_requested = Signal()

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.sound = SoundAlertManager(enabled=DEFAULT_SOUND_ENABLED)

        self._worker: Optional[ScreenCaptureWorker] = None
        self._alpr_worker: Optional[ALPREngineWorker] = None
        self._overlay: Optional[ROISelectorOverlay] = None
        self._active_roi: Optional[dict[str, Any]] = None
        self._latest_qimage: Optional[QImage] = None
        self._last_unregistered_plate: str = ""
        self._license_allowed: bool = True
        self._alpr_ready: bool = False

        # Timer de alerta piscante para veículos BLOQUEADOS
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(420)
        self._blink_timer.timeout.connect(self._on_blocked_blink_tick)
        self._blink_state = False

        self._build_ui()
        self._load_saved_roi()
        self.refresh_recent_passages()
        self._start_alpr_engine()

    # =========================================================================
    # CONSTRUÇÃO DA INTERFACE
    # =========================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # --- Banner de Regularização de Licença (visível somente se bloqueada/expirada) ---
        self.license_banner = QFrame()
        self.license_banner.setVisible(False)
        self.license_banner.setStyleSheet(
            "QFrame { background-color: #450A12; border: 1px solid #EF4444; border-radius: 10px; }"
        )
        lb_lay = QHBoxLayout(self.license_banner)
        lb_lay.setContentsMargins(14, 10, 14, 10)
        lb_lay.setSpacing(12)
        self.lbl_license_banner_msg = QLabel(
            "⚠ Leitura automática IA ALPR pausada — regularize sua licença na aba Conta & Licença."
        )
        self.lbl_license_banner_msg.setWordWrap(True)
        self.lbl_license_banner_msg.setStyleSheet(
            "color: #FECACA; font-size: 13px; font-weight: 700; background: transparent;"
        )
        btn_go_license = QPushButton("🔐  Regularizar Licença")
        btn_go_license.setProperty("variant", "danger")
        btn_go_license.setFixedHeight(34)
        btn_go_license.clicked.connect(self.open_license_tab_requested.emit)
        lb_lay.addWidget(self.lbl_license_banner_msg, 1)
        lb_lay.addWidget(btn_go_license)
        root.addWidget(self.license_banner)

        # --- Barra de Controles da Câmera + IA (2 linhas compactas ou linha única limpa) ---
        toolbar_card = QFrame()
        toolbar_card.setProperty("card", "true")
        tb_layout = QHBoxLayout(toolbar_card)
        tb_layout.setContentsMargins(12, 9, 12, 9)
        tb_layout.setSpacing(9)

        self.btn_select_roi = QPushButton("⌖  Selecionar Câmera")
        self.btn_select_roi.setProperty("variant", "primary")
        self.btn_select_roi.setMinimumHeight(36)
        self.btn_select_roi.clicked.connect(self._open_roi_selector)

        self.btn_toggle_capture = QPushButton("▶  Iniciar")
        self.btn_toggle_capture.setProperty("variant", "success")
        self.btn_toggle_capture.setMinimumHeight(36)
        self.btn_toggle_capture.setMinimumWidth(112)
        self.btn_toggle_capture.clicked.connect(self._toggle_capture)

        self.btn_scan_now = QPushButton("🔍  Ler Agora")
        self.btn_scan_now.setMinimumHeight(36)
        self.btn_scan_now.setToolTip(
            "Envia o frame atual imediatamente para a IA ALPR (útil em imagem ou vídeo parado)"
        )
        self.btn_scan_now.clicked.connect(self._force_alpr_scan)

        # Controle de Distância / Nitidez da Placa (evita tentar ler carros longe/borrados!)
        lbl_qual = QLabel("Nitidez:")
        lbl_qual.setProperty("muted", "true")
        self.cmb_quality = QComboBox()
        self.cmb_quality.setMinimumHeight(34)
        self.cmb_quality.setFixedWidth(185)
        self.cmb_quality.setToolTip(
            "Controla o quão perto e nítida a placa precisa estar para a IA confirmar a leitura.\n"
            "Use 'Perto / Nítida' ou 'Muito Perto' para ignorar carros distantes na rua."
        )
        default_idx = 0
        for idx, (key, meta) in enumerate(QUALITY_PRESETS.items()):
            self.cmb_quality.addItem(meta["label"], key)
            if key == DEFAULT_QUALITY_PRESET:
                default_idx = idx
        self.cmb_quality.setCurrentIndex(default_idx)
        self.cmb_quality.currentIndexChanged.connect(self._on_quality_changed)

        # Sensibilidade de movimento (para acordar a IA)
        lbl_sens_title = QLabel("Mov.:")
        lbl_sens_title.setProperty("muted", "true")
        self.slider_sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.slider_sensitivity.setRange(1, 100)
        self.slider_sensitivity.setValue(DEFAULT_MOTION_SENSITIVITY)
        self.slider_sensitivity.setFixedWidth(74)
        self.slider_sensitivity.setToolTip(
            "Sensibilidade de movimento na tela para acordar o detector (não altera a distância da placa)"
        )
        self.slider_sensitivity.valueChanged.connect(self._on_sensitivity_changed)

        self.lbl_sens_val = QLabel(f"{DEFAULT_MOTION_SENSITIVITY}%")
        self.lbl_sens_val.setFixedWidth(30)
        self.lbl_sens_val.setStyleSheet("color: #38BDF8; font-weight: 700; background: transparent;")

        # Tempo de Cooldown (s)
        lbl_cd = QLabel("Espera:")
        lbl_cd.setProperty("muted", "true")
        self.spin_cooldown = QSpinBox()
        self.spin_cooldown.setRange(5, 300)
        self.spin_cooldown.setValue(DEFAULT_COOLDOWN_SECONDS)
        self.spin_cooldown.setSuffix(" s")
        self.spin_cooldown.setFixedWidth(72)
        self.spin_cooldown.setToolTip(
            "Cooldown (segundos) para não repetir a mesma placa enquanto o carro aguarda o portão abrir"
        )
        self.spin_cooldown.valueChanged.connect(self._on_cooldown_changed)

        # Toggle Som Ativado / Mudo
        self.btn_sound_toggle = QPushButton("🔊 Som")
        self.btn_sound_toggle.setCheckable(True)
        self.btn_sound_toggle.setChecked(DEFAULT_SOUND_ENABLED)
        self.btn_sound_toggle.setMinimumHeight(36)
        self.btn_sound_toggle.setFixedWidth(96)
        self.btn_sound_toggle.toggled.connect(self._on_sound_toggled)
        self._refresh_sound_button_style(DEFAULT_SOUND_ENABLED)

        self.lbl_fps = QLabel("0.0 FPS")
        self.lbl_fps.setStyleSheet(
            "color: #94A3B8; background-color: #0B1324; border: 1px solid #1E293B; "
            "border-radius: 6px; padding: 5px 8px; font-family: Consolas; font-weight: 700;"
        )

        tb_layout.addWidget(self.btn_select_roi)
        tb_layout.addWidget(self.btn_toggle_capture)
        tb_layout.addWidget(self.btn_scan_now)
        tb_layout.addStretch(1)
        tb_layout.addWidget(lbl_qual)
        tb_layout.addWidget(self.cmb_quality)
        tb_layout.addWidget(lbl_sens_title)
        tb_layout.addWidget(self.slider_sensitivity)
        tb_layout.addWidget(self.lbl_sens_val)
        tb_layout.addWidget(lbl_cd)
        tb_layout.addWidget(self.spin_cooldown)
        tb_layout.addWidget(self.btn_sound_toggle)
        tb_layout.addWidget(self.lbl_fps)
        root.addWidget(toolbar_card)

        # --- Corpo Principal ---
        body = QHBoxLayout()
        body.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        # 1) Card de Preview Ao Vivo + Status IA + Barra de Movimento
        preview_card = QFrame()
        preview_card.setProperty("card", "true")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 10, 14, 10)
        preview_layout.setSpacing(8)

        preview_header = QHBoxLayout()
        self.lbl_roi_info = QLabel("CAPTURA AO VIVO — Nenhuma área ROI selecionada")
        self.lbl_roi_info.setProperty("sectionTitle", "true")

        self.lbl_alpr_pill = QLabel("● IA ALPR: INICIANDO...")
        self.lbl_alpr_pill.setStyleSheet(
            "color: #FCD34D; background-color: #3A2208; border: 1px solid #F59E0B; "
            "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 700;"
        )

        self.lbl_motion_pill = QLabel("● AGUARDANDO INÍCIO")
        self.lbl_motion_pill.setStyleSheet(
            "color: #94A3B8; background-color: #131E34; border: 1px solid #26354D; "
            "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 700;"
        )
        preview_header.addWidget(self.lbl_roi_info, 1)
        preview_header.addWidget(self.lbl_alpr_pill)
        preview_header.addWidget(self.lbl_motion_pill)
        preview_layout.addLayout(preview_header)

        self.lbl_video = QLabel(
            "Nenhuma câmera capturando no momento.\n\n"
            "1. Abra o software das suas câmeras (Intelbras, Hikvision, navegador, etc.)\n"
            "2. Clique em 'Selecionar Câmera' e recorte o vídeo da entrada\n"
            "3. A IA lerá automaticamente assim que a placa aproximar e ficar nítida"
        )
        self.lbl_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_video.setMinimumHeight(270)
        self.lbl_video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl_video.setStyleSheet(
            "background-color: #070D19; border: 1px dashed #26354D; border-radius: 10px; "
            "color: #64748B; font-size: 13px; padding: 20px;"
        )
        preview_layout.addWidget(self.lbl_video, 1)

        # Barra de Nível de Movimento + Tempo de inferência IA
        motion_row = QHBoxLayout()
        motion_row.setSpacing(10)
        lbl_m = QLabel("Movimento:")
        lbl_m.setProperty("muted", "true")
        self.progress_motion = QProgressBar()
        self.progress_motion.setObjectName("MotionBar")
        self.progress_motion.setRange(0, 100)
        self.progress_motion.setValue(0)
        self.progress_motion.setFormat("%p%")

        self.lbl_last_trigger = QLabel("Última inferência IA: —")
        self.lbl_last_trigger.setProperty("muted", "true")

        motion_row.addWidget(lbl_m)
        motion_row.addWidget(self.progress_motion, 1)
        motion_row.addWidget(self.lbl_last_trigger)
        preview_layout.addLayout(motion_row)

        left_col.addWidget(preview_card, 3)

        # 2) Card Gigante de Status de Acesso (Limpo, sem botões de simulação, alta visibilidade!)
        self.status_card = QFrame()
        self.status_card.setObjectName("GiantStatusCard")
        self.status_card.setMinimumHeight(205)
        sc_layout = QVBoxLayout(self.status_card)
        sc_layout.setContentsMargins(20, 16, 20, 16)
        sc_layout.setSpacing(14)

        # Linha superior: Kicker + Título Gigante | Placa Mercosul Gigante
        sc_top = QHBoxLayout()
        sc_top.setSpacing(16)

        status_text_col = QVBoxLayout()
        status_text_col.setSpacing(4)
        self.lbl_status_kicker = QLabel("MONITORAMENTO VEICULAR EM TEMPO REAL • IA ONNX OFFLINE")
        self.lbl_status_kicker.setStyleSheet(
            "color: #94A3B8; font-size: 11px; font-weight: 700; letter-spacing: 1px; background: transparent;"
        )
        self.lbl_status_headline = QLabel("AGUARDANDO VEÍCULO NA PORTARIA")
        self.lbl_status_headline.setStyleSheet(
            "color: #F8FAFC; font-size: 27px; font-weight: 900; letter-spacing: 0.6px; background: transparent;"
        )
        status_text_col.addWidget(self.lbl_status_kicker)
        status_text_col.addWidget(self.lbl_status_headline)

        # Placa visual estilo Mercosul em destaque máximo
        self.lbl_plate_badge = QLabel("———-————")
        self.lbl_plate_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_plate_badge.setFixedSize(226, 74)
        self.lbl_plate_badge.setStyleSheet(
            "background-color: #0F172A; color: #F8FAFC; border: 2px solid #334155; "
            "border-top: 11px solid #1D4ED8; border-radius: 8px; "
            "font-family: Consolas, 'Segoe UI', monospace; font-size: 28px; font-weight: 900; letter-spacing: 2px;"
        )

        sc_top.addLayout(status_text_col, 1)
        sc_top.addWidget(self.lbl_plate_badge)
        sc_layout.addLayout(sc_top)

        # Linha inferior: 3 Blocos Grandes de Identificação (MORADOR | CASA / UNIDADE | VEÍCULO)
        self.info_blocks_container = QWidget()
        self.info_blocks_container.setStyleSheet("background: transparent;")
        blocks_row = QHBoxLayout(self.info_blocks_container)
        blocks_row.setContentsMargins(0, 0, 0, 0)
        blocks_row.setSpacing(12)

        self.box_resident, self.lbl_val_resident = self._make_resident_info_block(
            "👤  MORADOR / RESPONSÁVEL", "—", "#FFFFFF", 20
        )
        self.box_unit, self.lbl_val_unit = self._make_resident_info_block(
            "🏠  CASA / UNIDADE", "—", "#6EE7B7", 20
        )
        self.box_car, self.lbl_val_car = self._make_resident_info_block(
            "🚗  VEÍCULO / COR", "—", "#E2E8F0", 18
        )

        blocks_row.addWidget(self.box_resident, 4)
        blocks_row.addWidget(self.box_unit, 3)
        blocks_row.addWidget(self.box_car, 3)
        self.info_blocks_container.setVisible(False)
        sc_layout.addWidget(self.info_blocks_container)

        # Mensagem auxiliar + Botão rápido de cadastro (para estado inicial, bloqueado ou não cadastrado)
        self.footer_alert_row = QWidget()
        self.footer_alert_row.setStyleSheet("background: transparent;")
        fa_lay = QHBoxLayout(self.footer_alert_row)
        fa_lay.setContentsMargins(0, 0, 0, 0)
        fa_lay.setSpacing(12)

        self.lbl_status_details = QLabel(
            "Posicione a câmera sobre a entrada — os dados do morador, casa e carro aparecerão aqui em destaque."
        )
        self.lbl_status_details.setWordWrap(True)
        self.lbl_status_details.setStyleSheet(
            "color: #CBD5E1; font-size: 14px; font-weight: 600; background: transparent;"
        )

        self.btn_quick_register = QPushButton("➕  Cadastrar Esta Placa Agora")
        self.btn_quick_register.setProperty("variant", "primary")
        self.btn_quick_register.setMinimumHeight(40)
        self.btn_quick_register.setVisible(False)
        self.btn_quick_register.clicked.connect(self._on_quick_register_clicked)

        fa_lay.addWidget(self.lbl_status_details, 1)
        fa_lay.addWidget(self.btn_quick_register)
        sc_layout.addWidget(self.footer_alert_row)

        self._apply_idle_status_style()
        left_col.addWidget(self.status_card, 0)

        # Coluna Direita: KPIs de Hoje + Lista Lateral de Últimas Passagens
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.lbl_kpi_total = self._make_kpi_card("HOJE", "0", "#38BDF8")
        self.lbl_kpi_ok = self._make_kpi_card("LIBERADOS", "0", "#10B981")
        self.lbl_kpi_alert = self._make_kpi_card("ALERTAS", "0", "#F59E0B")
        kpi_row.addWidget(self.lbl_kpi_total[0])
        kpi_row.addWidget(self.lbl_kpi_ok[0])
        kpi_row.addWidget(self.lbl_kpi_alert[0])
        right_col.addLayout(kpi_row)

        feed_card = QFrame()
        feed_card.setProperty("card", "true")
        feed_layout = QVBoxLayout(feed_card)
        feed_layout.setContentsMargins(14, 12, 14, 12)
        feed_layout.setSpacing(10)

        feed_hdr = QHBoxLayout()
        lbl_feed_title = QLabel("ÚLTIMAS LEITURAS")
        lbl_feed_title.setProperty("sectionTitle", "true")
        lbl_feed_sub = QLabel(f"Últimos {MAX_RECENT_PASSAGES}")
        lbl_feed_sub.setProperty("muted", "true")
        feed_hdr.addWidget(lbl_feed_title)
        feed_hdr.addStretch()
        feed_hdr.addWidget(lbl_feed_sub)
        feed_layout.addLayout(feed_hdr)

        self.list_recent = QListWidget()
        self.list_recent.setSpacing(4)
        self.list_recent.itemClicked.connect(self._on_recent_item_clicked)
        feed_layout.addWidget(self.list_recent, 1)

        right_col.addWidget(feed_card, 1)

        body.addLayout(left_col, 7)
        body.addLayout(right_col, 3)
        root.addLayout(body, 1)

    @staticmethod
    def _make_resident_info_block(
        title: str, initial: str, value_color: str, font_px: int
    ) -> tuple[QFrame, QLabel]:
        box = QFrame()
        box.setStyleSheet(
            "QFrame { background-color: rgba(7, 13, 25, 0.55); border: 1px solid rgba(255, 255, 255, 0.14); "
            "border-radius: 10px; }"
        )
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(
            "color: #94A3B8; font-size: 11px; font-weight: 800; letter-spacing: 0.7px; background: transparent; border: none;"
        )
        lbl_v = QLabel(initial)
        lbl_v.setWordWrap(True)
        lbl_v.setStyleSheet(
            f"color: {value_color}; font-size: {font_px}px; font-weight: 900; background: transparent; border: none;"
        )
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        return box, lbl_v

    @staticmethod
    def _make_kpi_card(label: str, initial: str, color: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setProperty("card", "true")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(2)
        lbl_t = QLabel(label)
        lbl_t.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: 700; background: transparent;")
        lbl_v = QLabel(initial)
        lbl_v.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: 800; background: transparent;")
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        return frame, lbl_v

    # =========================================================================
    # MOTOR DE IA ALPR
    # =========================================================================

    def _start_alpr_engine(self) -> None:
        self._alpr_worker = ALPREngineWorker(
            cooldown_seconds=self.spin_cooldown.value(),
            parent=self,
        )
        self._alpr_worker.set_quality_preset(self.cmb_quality.currentData() or DEFAULT_QUALITY_PRESET)
        self._alpr_worker.engine_status.connect(self._on_alpr_status)
        self._alpr_worker.detections_updated.connect(self._on_alpr_detections)
        self._alpr_worker.plate_confirmed.connect(self._on_alpr_plate_confirmed)
        self._alpr_worker.inference_metrics.connect(self._on_alpr_metrics)
        self._alpr_worker.start()

    def _on_quality_changed(self) -> None:
        preset_key = self.cmb_quality.currentData() or DEFAULT_QUALITY_PRESET
        if self._alpr_worker:
            self._alpr_worker.set_quality_preset(str(preset_key))

    def _on_alpr_status(self, message: str, ready: bool) -> None:
        self._alpr_ready = ready
        self.alpr_status_changed.emit(message, ready)
        self._refresh_alpr_pill(message)

    def _refresh_alpr_pill(self, message: str = "") -> None:
        if not self._license_allowed:
            self.lbl_alpr_pill.setText("● IA ALPR: BLOQUEADA (LICENÇA)")
            self.lbl_alpr_pill.setStyleSheet(
                "color: #FCA5A5; background-color: #450A0A; border: 1px solid #EF4444; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 800;"
            )
            return

        if self._alpr_ready:
            self.lbl_alpr_pill.setText("● IA ALPR: ONLINE (CPU)")
            self.lbl_alpr_pill.setStyleSheet(
                "color: #6EE7B7; background-color: #064E3B; border: 1px solid #10B981; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 800;"
            )
        elif "Erro" in message:
            self.lbl_alpr_pill.setText("● IA ALPR: ERRO")
            self.lbl_alpr_pill.setStyleSheet(
                "color: #FCA5A5; background-color: #450A0A; border: 1px solid #EF4444; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 800;"
            )
            self.lbl_alpr_pill.setToolTip(message)
        else:
            self.lbl_alpr_pill.setText("● IA ALPR: CARREGANDO...")

    def apply_license_status(self, status: LicenseStatus) -> None:
        """Pausa imediatamente o motor ALPR caso a licença seja bloqueada ou expirada."""
        self._license_allowed = bool(status.allowed)
        if self._alpr_worker is not None:
            self._alpr_worker.set_licensed(self._license_allowed)

        if self._license_allowed:
            self.license_banner.setVisible(False)
        else:
            self.lbl_license_banner_msg.setText(
                f"⚠ Motor IA ALPR pausado ({status.mode}): {status.message}"
            )
            self.license_banner.setVisible(True)
            self._blink_timer.stop()
            self.status_card.setStyleSheet(
                "QFrame#GiantStatusCard { background-color: #450A12; border: 2px solid #EF4444; border-radius: 14px; }"
            )
            self.lbl_status_kicker.setText("LICENCIAMENTO NEXUSISTEMAS • LEITURA IA PAUSADA")
            self.lbl_status_kicker.setStyleSheet(
                "color: #FCA5A5; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; background: transparent;"
            )
            self.lbl_status_headline.setText("LICENÇA BLOQUEADA / PENDENTE")
            self.info_blocks_container.setVisible(False)
            self.footer_alert_row.setVisible(True)
            self.lbl_status_details.setText(status.message)
            self.lbl_plate_badge.setText("BLOQUEADO")
            self.btn_quick_register.setVisible(False)
        self._refresh_alpr_pill()

    def _on_alpr_metrics(self, elapsed_ms: float) -> None:
        now_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_last_trigger.setText(f"IA ALPR: {elapsed_ms:.0f} ms ({now_str})")

    def _on_alpr_detections(self, detections: list[dict[str, Any]]) -> None:
        if not self._worker:
            return
        for det in detections:
            if det.get("valid"):
                plate = det.get("plate", "")
                if plate:
                    status, _ = self.db.evaluate_plate_access(plate)
                    bgr = STATUS_THEME.get(status, STATUS_THEME[ACCESS_STATUS_NAO_CADASTRADO])["bgr"]
                    self._worker.set_plate_color_hint(plate, bgr)
        self._worker.set_alpr_detections(detections, ttl_sec=1.6)

    def _on_alpr_plate_confirmed(self, payload: dict[str, Any]) -> None:
        plate = payload["plate"]
        confidence = float(payload.get("confidence", 0.0))
        pattern = payload.get("pattern", "")
        bbox = payload.get("bbox")
        frame_bgr = payload.get("frame_bgr")

        status, vehicle = self.db.evaluate_plate_access(plate)
        theme = STATUS_THEME.get(status, STATUS_THEME[ACCESS_STATUS_NAO_CADASTRADO])

        if self._worker:
            self._worker.set_plate_color_hint(plate, theme["bgr"])

        img_path = (
            save_alpr_capture(frame_bgr, plate, bbox=bbox, box_color_bgr=theme["bgr"])
            if frame_bgr is not None
            else (self._worker.save_current_snapshot(plate) if self._worker else None)
        )

        camera_name = self._active_roi["nome"] if self._active_roi else "Câmera Principal"
        record = self.db.log_access(
            placa=plate,
            status_acesso=status,
            camera_nome=camera_name,
            veiculo_id=vehicle["id"] if vehicle else None,
            imagem_path=img_path,
        )
        record["_alpr_meta"] = f"IA {int(round(confidence * 100))}% • {pattern}"

        self._render_status_card(record, play_sound=True)
        self.refresh_recent_passages()
        self.access_logged.emit()

    def _force_alpr_scan(self) -> None:
        if not self._license_allowed:
            QMessageBox.warning(
                self,
                "Licença Necessária",
                "O motor IA ALPR está pausado por pendência de licença. Regularize na aba Conta & Licença.",
            )
            return
        if not self._worker or not self._worker.isRunning():
            QMessageBox.information(
                self,
                "Captura Inativa",
                "Inicie a captura de uma área da tela primeiro para ler a placa.",
            )
            return
        if not self._alpr_worker or not self._alpr_worker.is_ready():
            QMessageBox.information(
                self,
                "IA Carregando",
                "Aguarde alguns segundos enquanto os modelos ONNX terminam de carregar.",
            )
            return
        frame = self._worker.get_latest_bgr_frame()
        if frame is not None:
            self._alpr_worker.clear_cooldown()
            self._alpr_worker.submit_frame(frame)
            QTimer.singleShot(250, self._submit_second_manual_frame)

    def _submit_second_manual_frame(self) -> None:
        if self._worker and self._alpr_worker and self._alpr_worker.is_ready():
            frame = self._worker.get_latest_bgr_frame()
            if frame is not None:
                self._alpr_worker.submit_frame(frame)

    def _on_cooldown_changed(self, seconds: int) -> None:
        if self._alpr_worker:
            self._alpr_worker.set_cooldown_seconds(seconds)

    def _on_sound_toggled(self, checked: bool) -> None:
        self.sound.set_enabled(checked)
        self._refresh_sound_button_style(checked)

    def _refresh_sound_button_style(self, enabled: bool) -> None:
        if enabled:
            self.btn_sound_toggle.setText("🔊 Som")
            self.btn_sound_toggle.setStyleSheet(
                "background-color: #0E2A3F; color: #38BDF8; border: 1px solid #0891B2; border-radius: 8px;"
            )
        else:
            self.btn_sound_toggle.setText("🔇 Mudo")
            self.btn_sound_toggle.setStyleSheet(
                "background-color: #1E293B; color: #94A3B8; border: 1px solid #334155; border-radius: 8px;"
            )

    # =========================================================================
    # GERENCIAMENTO DE ROI E MOTOR DE CAPTURA
    # =========================================================================

    def _load_saved_roi(self) -> None:
        roi = self.db.get_active_camera_roi()
        if roi:
            self._active_roi = roi
            self.slider_sensitivity.blockSignals(True)
            self.slider_sensitivity.setValue(int(roi.get("sensibilidade_movimento", DEFAULT_MOTION_SENSITIVITY)))
            self.slider_sensitivity.blockSignals(False)
            self.lbl_sens_val.setText(f"{self.slider_sensitivity.value()}%")
            self._update_roi_label()

    def _update_roi_label(self) -> None:
        if not self._active_roi:
            self.lbl_roi_info.setText("CAPTURA AO VIVO — Nenhuma área ROI selecionada")
            return
        r = self._active_roi
        self.lbl_roi_info.setText(
            f"ROI ATIVA: {r['width']}×{r['height']} px  •  ({r['left']}, {r['top']})  •  Monitor {r['monitor_index']}"
        )

    def _open_roi_selector(self) -> None:
        main_win = self.window()
        if main_win is not None:
            main_win.showMinimized()
        QTimer.singleShot(220, self._launch_overlay)

    def _launch_overlay(self) -> None:
        self._overlay = ROISelectorOverlay()
        self._overlay.roi_selected.connect(self._on_roi_selected)
        self._overlay.selection_cancelled.connect(self._on_roi_cancelled)
        self._overlay.show_selector()

    def _restore_main_window(self) -> None:
        main_win = self.window()
        if main_win is not None:
            main_win.showNormal()
            main_win.raise_()
            main_win.activateWindow()

    def _on_roi_cancelled(self) -> None:
        self._overlay = None
        self._restore_main_window()

    def _on_roi_selected(self, roi_coords: dict[str, Any]) -> None:
        self._overlay = None
        self._restore_main_window()

        saved = self.db.upsert_camera_roi(
            nome="Câmera Principal",
            monitor_index=roi_coords["monitor_index"],
            top=roi_coords["top"],
            left=roi_coords["left"],
            width=roi_coords["width"],
            height=roi_coords["height"],
            sensibilidade_movimento=self.slider_sensitivity.value(),
            ativo=1,
        )
        self._active_roi = saved
        self._update_roi_label()

        if self._worker and self._worker.isRunning():
            self._worker.update_roi(saved)
            self._worker.set_paused(False)
            self._update_capture_button_ui(running=True, paused=False)
        else:
            self._start_capture_worker()

    def _toggle_capture(self) -> None:
        if not self._active_roi:
            QMessageBox.information(
                self,
                "Selecionar Área da Câmera",
                "Selecione primeiro a área da câmera na tela clicando em 'Selecionar Câmera'.",
            )
            return

        if self._worker and self._worker.isRunning():
            if self._worker.is_paused():
                self._worker.set_paused(False)
                self._update_capture_button_ui(running=True, paused=False)
            else:
                self._worker.set_paused(True)
                self._update_capture_button_ui(running=True, paused=True)
        else:
            self._start_capture_worker()

    def _start_capture_worker(self) -> None:
        if not self._active_roi:
            return
        self.stop_capture()
        self._worker = ScreenCaptureWorker(
            roi=self._active_roi,
            sensitivity=self.slider_sensitivity.value(),
            parent=self,
        )
        self._worker.frame_ready.connect(self._on_frame_ready)
        self._worker.motion_triggered.connect(self._on_motion_triggered)
        self._worker.alpr_frame_ready.connect(self._dispatch_frame_to_alpr)
        self._worker.error_occurred.connect(self._on_capture_error)
        self._worker.status_changed.connect(self._on_worker_status_changed)
        self._worker.start()
        self._update_capture_button_ui(running=True, paused=False)

    def _dispatch_frame_to_alpr(self, frame_bgr: object) -> None:
        if self._alpr_worker and self._alpr_worker.is_ready():
            self._alpr_worker.submit_frame(frame_bgr)  # type: ignore[arg-type]

    def stop_capture(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.deleteLater()
            self._worker = None
        self._update_capture_button_ui(running=False, paused=False)

    def shutdown(self) -> None:
        self._blink_timer.stop()
        self.stop_capture()
        if self._alpr_worker is not None:
            self._alpr_worker.stop()
            self._alpr_worker.deleteLater()
            self._alpr_worker = None

    def _update_capture_button_ui(self, running: bool, paused: bool) -> None:
        if running and not paused:
            self.btn_toggle_capture.setText("⏸  Pausar")
            self.btn_toggle_capture.setProperty("variant", "warning")
        elif running and paused:
            self.btn_toggle_capture.setText("▶  Retomar")
            self.btn_toggle_capture.setProperty("variant", "success")
        else:
            self.btn_toggle_capture.setText("▶  Iniciar")
            self.btn_toggle_capture.setProperty("variant", "success")

        self.btn_toggle_capture.style().unpolish(self.btn_toggle_capture)
        self.btn_toggle_capture.style().polish(self.btn_toggle_capture)

    def _on_sensitivity_changed(self, value: int) -> None:
        self.lbl_sens_val.setText(f"{value}%")
        if self._worker:
            self._worker.set_sensitivity(value)
        if self._active_roi and "id" in self._active_roi:
            self.db.update_camera_sensitivity(self._active_roi["id"], value)

    def _on_frame_ready(
        self, qimg: QImage, motion_pct: float, motion_detected: bool, fps: float
    ) -> None:
        self._latest_qimage = qimg
        self._render_video_pixmap()

        self.progress_motion.setValue(int(round(motion_pct)))
        self.lbl_fps.setText(f"{fps:4.1f} FPS")

        if motion_detected:
            self.lbl_motion_pill.setText("● MOVIMENTO DETECTADO")
            self.lbl_motion_pill.setStyleSheet(
                "color: #6EE7B7; background-color: #064E3B; border: 1px solid #10B981; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 800;"
            )
        else:
            self.lbl_motion_pill.setText("● AGUARDANDO MOVIMENTO")
            self.lbl_motion_pill.setStyleSheet(
                "color: #38BDF8; background-color: #0E2A3F; border: 1px solid #0891B2; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 700;"
            )

    def _render_video_pixmap(self) -> None:
        if self._latest_qimage is None:
            return
        target = self.lbl_video.contentsRect().size()
        if target.width() <= 10 or target.height() <= 10:
            return
        pix = QPixmap.fromImage(self._latest_qimage).scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl_video.setStyleSheet(
            "background-color: #050912; border: 1px solid #1E293B; border-radius: 10px;"
        )
        self.lbl_video.setPixmap(pix)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_video_pixmap()

    def _on_motion_triggered(self, motion_pct: float) -> None:
        now_str = datetime.now().strftime("%H:%M:%S")
        self.lbl_last_trigger.setText(f"Gatilho movimento: {now_str} ({motion_pct:.0f}%)")

    def _on_capture_error(self, message: str) -> None:
        self.lbl_motion_pill.setText("● RECONECTANDO")
        self.lbl_motion_pill.setStyleSheet(
            "color: #FCA5A5; background-color: #450A0A; border: 1px solid #EF4444; "
            "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 700;"
        )
        self.lbl_roi_info.setText(message)

    def _on_worker_status_changed(self, status: str) -> None:
        self.capture_state_changed.emit(status)
        if status == "PAUSADA":
            self.lbl_motion_pill.setText("● CAPTURA PAUSADA")
            self.lbl_motion_pill.setStyleSheet(
                "color: #FCD34D; background-color: #3A2208; border: 1px solid #F59E0B; "
                "border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 700;"
            )
            self.lbl_fps.setText("PAUSADA")

    # =========================================================================
    # CARD GIGANTE DE STATUS (ALTA VISIBILIDADE PARA PORTARIA)
    # =========================================================================

    def _apply_idle_status_style(self) -> None:
        self._blink_timer.stop()
        self.status_card.setStyleSheet(
            "QFrame#GiantStatusCard { background-color: #111827; border: 2px solid #26354D; border-radius: 14px; }"
        )

    def _on_blocked_blink_tick(self) -> None:
        self._blink_state = not self._blink_state
        theme = STATUS_THEME[ACCESS_STATUS_BLOQUEADO]
        bg = theme["bg_alt"] if self._blink_state else theme["bg"]
        border = "#FCA5A5" if self._blink_state else theme["border"]
        self.status_card.setStyleSheet(
            f"QFrame#GiantStatusCard {{ background-color: {bg}; border: 3px solid {border}; border-radius: 14px; }}"
        )

    def _render_status_card(self, record: dict[str, Any], play_sound: bool = False) -> None:
        status = record.get("status_acesso", ACCESS_STATUS_NAO_CADASTRADO)
        theme = STATUS_THEME.get(status, STATUS_THEME[ACCESS_STATUS_NAO_CADASTRADO])
        plate_raw = normalize_plate(record.get("placa", ""))
        plate_disp = format_plate_display(plate_raw)

        if status == ACCESS_STATUS_BLOQUEADO:
            self._blink_state = False
            self._blink_timer.start()
        else:
            self._blink_timer.stop()

        self.status_card.setStyleSheet(
            f"QFrame#GiantStatusCard {{ background-color: {theme['bg']}; "
            f"border: 2px solid {theme['border']}; border-radius: 14px; }}"
        )

        alpr_meta = record.get("_alpr_meta")
        kicker_parts = [
            f"CÂMERA: {record.get('camera_nome', 'Câmera Principal').upper()}",
            record.get("data_hora", ""),
        ]
        if alpr_meta:
            kicker_parts.append(str(alpr_meta))
        self.lbl_status_kicker.setText("  •  ".join(p for p in kicker_parts if p))
        self.lbl_status_kicker.setStyleSheet(
            f"color: {theme['accent']}; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; background: transparent;"
        )

        self.lbl_status_headline.setText(theme["title"])
        self.lbl_status_headline.setStyleSheet(
            "color: #FFFFFF; font-size: 27px; font-weight: 900; letter-spacing: 0.6px; background: transparent;"
        )

        self.lbl_plate_badge.setText(plate_disp or "SEM PLACA")
        self.lbl_plate_badge.setStyleSheet(
            f"background-color: #F8FAFC; color: #0F172A; border: 2px solid {theme['border']}; "
            "border-top: 11px solid #1E40AF; border-radius: 8px; "
            "font-family: Consolas, 'Segoe UI', monospace; font-size: 28px; font-weight: 900; letter-spacing: 2px;"
        )

        nome = (record.get("nome_responsavel") or "").strip()
        unidade = (record.get("unidade_bloco") or "").strip()
        modelo = (record.get("modelo_cor") or "").strip()

        if nome:
            # Exibe os 3 blocos gigantes de destaque (Morador | Casa/Unidade | Carro)
            self.lbl_val_resident.setText(nome.upper())
            self.lbl_val_unit.setText(unidade.upper() if unidade else "NÃO INFORMADA")
            self.lbl_val_unit.setStyleSheet(
                f"color: {theme['accent']}; font-size: 20px; font-weight: 900; background: transparent; border: none;"
            )
            self.lbl_val_car.setText(modelo.upper() if modelo else "NÃO INFORMADO")
            self.info_blocks_container.setVisible(True)

            if status == ACCESS_STATUS_EXPIRADO:
                self.lbl_status_details.setText("⚠ Validade de acesso deste visitante está vencida.")
                self.btn_quick_register.setVisible(False)
                self.footer_alert_row.setVisible(True)
            else:
                self.btn_quick_register.setVisible(False)
                self.footer_alert_row.setVisible(False)
        else:
            # Placa não cadastrada: oculta os 3 blocos e mostra alerta claro + botão rápido de cadastro
            self.info_blocks_container.setVisible(False)
            self.footer_alert_row.setVisible(True)
            self.lbl_status_details.setText(
                "Veículo não localizado na base local — confirme na portaria ou cadastre agora em 1 clique."
            )
            if status == ACCESS_STATUS_NAO_CADASTRADO and len(plate_raw) == 7:
                self._last_unregistered_plate = plate_raw
                self.btn_quick_register.setText(f"➕  Cadastrar Esta Placa Agora ({plate_disp})")
                self.btn_quick_register.setVisible(True)
            else:
                self._last_unregistered_plate = ""
                self.btn_quick_register.setVisible(False)

        if play_sound:
            self.sound.play_for_status(status)

    def _on_quick_register_clicked(self) -> None:
        if self._last_unregistered_plate:
            self.quick_register_requested.emit(self._last_unregistered_plate)

    # =========================================================================
    # LISTA LATERAL DE ÚLTIMAS PASSAGENS & KPIs
    # =========================================================================

    def refresh_recent_passages(self) -> None:
        stats = self.db.get_today_stats()
        self.lbl_kpi_total[1].setText(str(stats["total_hoje"]))
        self.lbl_kpi_ok[1].setText(str(stats["liberados_hoje"]))
        self.lbl_kpi_alert[1].setText(str(stats["alertas_hoje"]))

        records = self.db.list_access_history(limit=MAX_RECENT_PASSAGES)
        self.list_recent.clear()

        for rec in records:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, rec)
            widget = self._build_passage_row_widget(rec)
            item.setSizeHint(widget.sizeHint())
            self.list_recent.addItem(item)
            self.list_recent.setItemWidget(item, widget)

    def _build_passage_row_widget(self, rec: dict[str, Any]) -> QWidget:
        theme = STATUS_THEME.get(rec["status_acesso"], STATUS_THEME[ACCESS_STATUS_NAO_CADASTRADO])
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)

        top = QHBoxLayout()
        lbl_plate = QLabel(format_plate_display(rec["placa"]))
        lbl_plate.setStyleSheet(
            "color: #F8FAFC; font-family: Consolas, monospace; font-size: 14px; font-weight: 800; background: transparent;"
        )
        lbl_badge = QLabel(theme["short"])
        lbl_badge.setStyleSheet(
            f"background-color: {theme['badge_bg']}; color: #FFFFFF; border-radius: 4px; "
            "padding: 2px 7px; font-size: 10px; font-weight: 800;"
        )
        top.addWidget(lbl_plate)
        top.addStretch()
        top.addWidget(lbl_badge)

        nome = rec.get("nome_responsavel") or "Não cadastrado"
        unidade = rec.get("unidade_bloco") or ""
        info_txt = f"{nome} ({unidade})" if unidade else nome
        lbl_info = QLabel(info_txt)
        lbl_info.setStyleSheet("color: #CBD5E1; font-size: 12px; background: transparent;")

        ts = rec.get("data_hora", "")
        hora = ts[11:19] if len(ts) >= 19 else ts
        lbl_meta = QLabel(f"{hora}  •  {rec.get('camera_nome', '')}")
        lbl_meta.setStyleSheet("color: #64748B; font-size: 11px; background: transparent;")

        lay.addLayout(top)
        lay.addWidget(lbl_info)
        lay.addWidget(lbl_meta)
        return w

    def _on_recent_item_clicked(self, item: QListWidgetItem) -> None:
        rec = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(rec, dict):
            self._render_status_card(rec, play_sound=False)
