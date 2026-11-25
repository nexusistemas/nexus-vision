"""
Aba 3 — Histórico de Acessos do Nexus Vision.
Filtros por intervalo de datas, placa/nome e status + visualização da miniatura capturada.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPixmap
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
    CAPTURES_DIR,
)
from core.database import DatabaseManager, format_plate_display


STATUS_DISPLAY = {
    ACCESS_STATUS_LIBERADO_MORADOR: ("MORADOR LIBERADO", "#34D399"),
    ACCESS_STATUS_LIBERADO_VISITANTE: ("VISITANTE AUTORIZADO", "#38BDF8"),
    ACCESS_STATUS_NAO_CADASTRADO: ("NÃO CADASTRADO", "#FBBF24"),
    ACCESS_STATUS_BLOQUEADO: ("BLOQUEADO", "#F87171"),
    ACCESS_STATUS_EXPIRADO: ("EXPIRADO", "#FB923C"),
}


class HistoryTab(QWidget):
    """Aba de consulta ao histórico local de passagens com preview da imagem."""

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self._current_image_path: Optional[str] = None
        self._build_ui()
        self.refresh_history()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

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
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_from.dateChanged.connect(self.refresh_history)

        lbl_to = QLabel("Até:")
        lbl_to.setProperty("muted", "true")
        self.dt_to = QDateEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat("dd/MM/yyyy")
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.dateChanged.connect(self.refresh_history)

        self.in_plate_search = QLineEdit()
        self.in_plate_search.setPlaceholderText("🔍  Filtrar por placa, morador ou unidade...")
        self.in_plate_search.textChanged.connect(self.refresh_history)

        self.cmb_status = QComboBox()
        self.cmb_status.addItem("Todos os Status", "TODOS")
        for code, (label, _) in STATUS_DISPLAY.items():
            self.cmb_status.addItem(label, code)
        self.cmb_status.currentIndexChanged.connect(self.refresh_history)

        btn_refresh = QPushButton("↻  Atualizar")
        btn_refresh.setProperty("variant", "primary")
        btn_refresh.clicked.connect(self.refresh_history)

        fl.addWidget(lbl_from)
        fl.addWidget(self.dt_from)
        fl.addWidget(lbl_to)
        fl.addWidget(self.dt_to)
        fl.addWidget(self.in_plate_search, 1)
        fl.addWidget(self.cmb_status)
        fl.addWidget(btn_refresh)
        root.addWidget(filter_card)

        # --- Split: Tabela + Painel de Miniatura ---
        body = QHBoxLayout()
        body.setSpacing(14)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Data / Hora", "Placa", "Status", "Responsável", "Unidade", "Câmera"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_row_selected)

        # Painel Lateral de Miniatura Capturada
        preview_card = QFrame()
        preview_card.setProperty("card", "true")
        preview_card.setFixedWidth(360)
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(10)

        lbl_pv_title = QLabel("MINIATURA CAPTURADA")
        lbl_pv_title.setProperty("sectionTitle", "true")
        pv.addWidget(lbl_pv_title)

        self.lbl_thumb = QLabel("Selecione um registro na tabela para visualizar a captura.")
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setWordWrap(True)
        self.lbl_thumb.setFixedHeight(230)
        self.lbl_thumb.setStyleSheet(
            "background-color: #070D19; border: 1px dashed #26354D; "
            "border-radius: 10px; color: #64748B; padding: 14px;"
        )
        pv.addWidget(self.lbl_thumb)

        self.lbl_meta = QLabel("Nenhum evento selecionado.")
        self.lbl_meta.setWordWrap(True)
        self.lbl_meta.setStyleSheet(
            "background-color: #0B1324; border: 1px solid #1E293B; border-radius: 8px; "
            "color: #CBD5E1; padding: 12px; font-size: 12px;"
        )
        pv.addWidget(self.lbl_meta)
        pv.addStretch()

        btn_open_folder = QPushButton("📂  Abrir Pasta de Capturas")
        btn_open_folder.clicked.connect(self._open_captures_folder)
        pv.addWidget(btn_open_folder)

        body.addWidget(self.table, 1)
        body.addWidget(preview_card)
        root.addLayout(body, 1)

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

        self.table.setRowCount(len(records))
        for r_idx, rec in enumerate(records):
            it_dt = QTableWidgetItem(rec.get("data_hora") or "")
            it_dt.setData(Qt.ItemDataRole.UserRole, rec)

            it_plate = QTableWidgetItem(format_plate_display(rec.get("placa", "")))
            f = it_plate.font()
            f.setBold(True)
            it_plate.setFont(f)

            status_code = rec.get("status_acesso", ACCESS_STATUS_NAO_CADASTRADO)
            label, color_hex = STATUS_DISPLAY.get(status_code, (status_code, "#E2E8F0"))
            it_status = QTableWidgetItem(label)
            it_status.setForeground(QColor(color_hex))
            fs = it_status.font()
            fs.setBold(True)
            it_status.setFont(fs)

            it_name = QTableWidgetItem(rec.get("nome_responsavel") or "Não cadastrado")
            it_unit = QTableWidgetItem(rec.get("unidade_bloco") or "—")
            it_cam = QTableWidgetItem(rec.get("camera_nome") or "—")

            for c_idx, item in enumerate(
                (it_dt, it_plate, it_status, it_name, it_unit, it_cam)
            ):
                self.table.setItem(r_idx, c_idx, item)

    def _on_row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if not item:
            return
        rec: dict[str, Any] = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(rec, dict):
            return

        status_code = rec.get("status_acesso", "")
        status_label = STATUS_DISPLAY.get(status_code, (status_code, "#E2E8F0"))[0]
        self.lbl_meta.setText(
            f"Placa: {format_plate_display(rec.get('placa', ''))}\n"
            f"Status: {status_label}\n"
            f"Responsável: {rec.get('nome_responsavel') or 'Não cadastrado'}\n"
            f"Unidade: {rec.get('unidade_bloco') or '—'}\n"
            f"Veículo: {rec.get('modelo_cor') or '—'}\n"
            f"Câmera: {rec.get('camera_nome') or '—'}\n"
            f"Data/Hora: {rec.get('data_hora') or '—'}"
        )

        img_path = rec.get("imagem_path")
        self._current_image_path = img_path
        if img_path and Path(img_path).exists():
            pix = QPixmap(img_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    self.lbl_thumb.width() - 8,
                    self.lbl_thumb.height() - 8,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.lbl_thumb.setPixmap(scaled)
                return

        self.lbl_thumb.setPixmap(QPixmap())
        self.lbl_thumb.setText(
            "Sem miniatura salva para este evento.\n\n"
            "Dica: inicie a captura da câmera na Aba 1 antes de simular leituras "
            "para gravar o frame real automaticamente."
        )

    def _open_captures_folder(self) -> None:
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(CAPTURES_DIR))  # type: ignore[attr-defined]
        except Exception:
            pass
