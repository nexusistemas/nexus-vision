"""
Aba 3 — Histórico de Acessos Ultra-Rápido do Nexus Vision (Apenas Registros).
Sem gravação de imagens em disco para abertura instantânea e zero peso no HD/SSD;
mantém automaticamente as últimas 24 horas de passagens com filtros por data, placa e status.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import (
    ACCESS_STATUS_BLOQUEADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_LIBERADO_MORADOR,
    ACCESS_STATUS_LIBERADO_VISITANTE,
    ACCESS_STATUS_NAO_CADASTRADO,
)
from core.database import DatabaseManager, format_plate_display


STATUS_DISPLAY = {
    ACCESS_STATUS_LIBERADO_MORADOR: ("MORADOR AUTORIZADO", "#34D399"),
    ACCESS_STATUS_LIBERADO_VISITANTE: ("VISITANTE AUTORIZADO", "#38BDF8"),
    ACCESS_STATUS_NAO_CADASTRADO: ("NÃO CADASTRADO", "#FBBF24"),
    ACCESS_STATUS_BLOQUEADO: ("BLOQUEADO", "#F87171"),
    ACCESS_STATUS_EXPIRADO: ("EXPIRADO", "#FB923C"),
}


class HistoryTab(QWidget):
    """Aba leve e instantânea de consulta ao histórico de passagens (últimas 24h)."""

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self._bold_font = QFont()
        self._bold_font.setBold(True)
        self._build_ui()
        self.refresh_history()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # --- Barra de Filtros ---
        filter_card = QFrame()
        filter_card.setProperty("card", "true")
        fl = QHBoxLayout(filter_card)
        fl.setContentsMargins(14, 10, 14, 10)
        fl.setSpacing(10)

        lbl_from = QLabel("De:")
        lbl_from.setProperty("muted", "true")
        self.dt_from = QDateEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat("dd/MM/yyyy")
        self.dt_from.setDate(QDate.currentDate().addDays(-1))
        self.dt_from.dateChanged.connect(self.refresh_history)

        lbl_to = QLabel("Até:")
        lbl_to.setProperty("muted", "true")
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("dd/MM/yyyy")
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.dateChanged.connect(self.refresh_history)

        self.in_plate_search = QLineEdit()
        self.in_plate_search.setPlaceholderText("🔍  Filtrar por placa, morador ou casa/unidade...")
        self.in_plate_search.textChanged.connect(self.refresh_history)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Todos os Status", "TODOS")
        for code, (label, _) in STATUS_DISPLAY.items():
            self.cmb_status.addItem(label, code)
        self.cmb_status.currentIndexChanged.connect(self.refresh_history)

        btn_refresh = QPushButton("↻  Atualizar")
        btn_refresh.setProperty("variant", "primary")
        btn_refresh.clicked.connect(self.refresh_history)

        self.lbl_count = QLabel("0 registros")
        self.lbl_count.setProperty("muted", "true")

        fl.addWidget(lbl_from)
        fl.addWidget(self.dt_from)
        fl.addWidget(lbl_to)
        fl.addWidget(self.dt_to)
        fl.addWidget(self.in_plate_search, 1)
        fl.addWidget(self.cmb_status)
        fl.addWidget(btn_refresh)
        fl.addWidget(self.lbl_count)
        root.addWidget(filter_card)

        # --- Tabela 100% largura (larguras fixas/stretch -> abertura instantânea em <5ms!) ---
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Data / Hora", "Placa", "Status", "Responsável", "Casa / Unidade", "Veículo / Cor", "Câmera"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)

        self.table.setColumnWidth(0, 155)
        self.table.setColumnWidth(1, 105)
        self.table.setColumnWidth(2, 185)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(6, 145)

        root.addWidget(self.table, 1)

        lbl_note = QLabel(
            "⚡ Modo leve ativo: apenas registros de texto são armazenados (sem fotos em disco) • Limpeza automática a cada 24h."
        )
        lbl_note.setStyleSheet("color: #64748B; font-size: 11px; padding-left: 4px; background: transparent;")
        root.addWidget(lbl_note)

    def refresh_history(self) -> None:
        date_from = self.dt_from.date().toString("yyyy-MM-dd")
        date_to = self.dt_to.date().toString("yyyy-MM-dd")
        query = self.in_plate_search.text()
        status = self.cmb_status.currentData() or "TODOS"

        records = self.db.list_access_history(
            date_from=date_from,
            date_to=date_to,
            plate_query=query,
            status_filter=status,
            limit=300,
        )

        # Desabilita repintura durante o preenchimento -> abre instantaneamente sem travar
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(records))
            for r_idx, rec in enumerate(records):
                it_dt = QTableWidgetItem(rec.get("data_hora") or "")

                it_plate = QTableWidgetItem(format_plate_display(rec.get("placa", "")))
                it_plate.setFont(self._bold_font)
                it_plate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                status_code = rec.get("status_acesso", ACCESS_STATUS_NAO_CADASTRADO)
                label, color_hex = STATUS_DISPLAY.get(status_code, (status_code, "#E2E8F0"))
                it_status = QTableWidgetItem(label)
                it_status.setForeground(QColor(color_hex))
                it_status.setFont(self._bold_font)

                it_name = QTableWidgetItem(rec.get("nome_responsavel") or "Não cadastrado")
                it_unit = QTableWidgetItem(rec.get("unidade_bloco") or "—")
                it_car = QTableWidgetItem(rec.get("modelo_cor") or "—")
                it_cam = QTableWidgetItem(rec.get("camera_nome") or "—")

                self.table.setItem(r_idx, 0, it_dt)
                self.table.setItem(r_idx, 1, it_plate)
                self.table.setItem(r_idx, 2, it_status)
                self.table.setItem(r_idx, 3, it_name)
                self.table.setItem(r_idx, 4, it_unit)
                self.table.setItem(r_idx, 5, it_car)
                self.table.setItem(r_idx, 6, it_cam)
        finally:
            self.table.setUpdatesEnabled(True)

        self.lbl_count.setText(f"{len(records)} registro(s)")
