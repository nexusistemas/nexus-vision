"""
Aba 2 — Cadastro de Moradores e Veículos do Nexus Vision.
Formulário completo, busca instantânea, filtro por perfil, edição/exclusão
e importação/exportação CSV.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import VEHICLE_PROFILES
from core.database import DatabaseManager, format_plate_display, normalize_plate


PROFILE_COLORS = {
    "MORADOR": "#34D399",
    "VISITANTE": "#38BDF8",
    "BLOQUEADO": "#F87171",
}


class VehiclesTab(QWidget):
    """Aba de gerenciamento local de moradores, visitantes e bloqueados."""

    vehicles_changed = Signal()
    cloud_backup_requested = Signal()
    cloud_restore_requested = Signal()

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self._editing_id: Optional[int] = None
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # --- Card do Formulário de Cadastro / Edição ---
        form_card = QFrame()
        form_card.setProperty("card", "true")
        fc_layout = QVBoxLayout(form_card)
        fc_layout.setContentsMargins(16, 14, 16, 14)
        fc_layout.setSpacing(12)

        hdr = QHBoxLayout()
        self.lbl_form_mode = QLabel("NOVO CADASTRO DE VEÍCULO / MORADOR")
        self.lbl_form_mode.setProperty("sectionTitle", "true")
        self.lbl_edit_hint = QLabel("Preencha os campos abaixo ou selecione uma linha da tabela para editar")
        self.lbl_edit_hint.setProperty("muted", "true")
        hdr.addWidget(self.lbl_form_mode)
        hdr.addStretch()
        hdr.addWidget(self.lbl_edit_hint)
        fc_layout.addLayout(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.in_plate = QLineEdit()
        self.in_plate.setPlaceholderText("ABC1D23 ou ABC-1234")
        self.in_plate.setMaxLength(8)
        self.in_plate.textEdited.connect(self._uppercase_plate_input)

        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText("Ex: João Carlos da Silva")

        self.in_unit = QLineEdit()
        self.in_unit.setPlaceholderText("Ex: Bloco B - Apto 304 / Casa 12")

        self.in_model = QLineEdit()
        self.in_model.setPlaceholderText("Ex: Honda Civic Preto")

        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(list(VEHICLE_PROFILES))

        val_row = QHBoxLayout()
        val_row.setSpacing(8)
        self.chk_has_validity = QCheckBox("Com validade:")
        self.chk_has_validity.toggled.connect(self._on_validity_toggled)
        self.dt_validity = QDateEdit()
        self.dt_validity.setCalendarPopup(True)
        self.dt_validity.setDisplayFormat("dd/MM/yyyy")
        self.dt_validity.setDate(QDate.currentDate().addDays(7))
        self.dt_validity.setEnabled(False)
        val_row.addWidget(self.chk_has_validity)
        val_row.addWidget(self.dt_validity, 1)

        grid.addWidget(self._field_label("Placa *"), 0, 0)
        grid.addWidget(self._field_label("Nome do Responsável *"), 0, 1)
        grid.addWidget(self._field_label("Unidade / Bloco"), 0, 2)
        grid.addWidget(self.in_plate, 1, 0)
        grid.addWidget(self.in_name, 1, 1)
        grid.addWidget(self.in_unit, 1, 2)

        grid.addWidget(self._field_label("Modelo / Cor"), 2, 0)
        grid.addWidget(self._field_label("Perfil de Acesso"), 2, 1)
        grid.addWidget(self._field_label("Validade Temporária (Opcional)"), 2, 2)
        grid.addWidget(self.in_model, 3, 0)
        grid.addWidget(self.cmb_profile, 3, 1)
        grid.addLayout(val_row, 3, 2)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 3)
        fc_layout.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_save = QPushButton("✓  Salvar Cadastro")
        self.btn_save.setProperty("variant", "success")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.clicked.connect(self._save_vehicle)

        self.btn_clear = QPushButton("Limpar / Novo")
        self.btn_clear.setMinimumHeight(36)
        self.btn_clear.clicked.connect(self._reset_form)

        self.btn_delete = QPushButton("🗑  Excluir Selecionado")
        self.btn_delete.setProperty("variant", "danger")
        self.btn_delete.setMinimumHeight(36)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_selected)

        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_clear)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch()
        fc_layout.addLayout(btn_row)

        root.addWidget(form_card)

        # --- Barra de Busca, Filtro e CSV ---
        tools_card = QFrame()
        tools_card.setProperty("card", "true")
        tc_layout = QHBoxLayout(tools_card)
        tc_layout.setContentsMargins(14, 10, 14, 10)
        tc_layout.setSpacing(10)

        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText("🔍  Busca instantânea por placa, nome, apartamento ou modelo...")
        self.in_search.textChanged.connect(self.refresh_table)

        self.cmb_filter_profile = QComboBox()
        self.cmb_filter_profile.addItems(["TODOS", "MORADOR", "VISITANTE", "BLOQUEADO"])
        self.cmb_filter_profile.setFixedWidth(150)
        self.cmb_filter_profile.currentIndexChanged.connect(self.refresh_table)

        self.btn_import_csv = QPushButton("⬆  Importar Excel / CSV")
        self.btn_import_csv.setProperty("variant", "primary")
        self.btn_import_csv.setToolTip("Importa planilhas Excel (.xlsx) ou arquivos CSV (.csv)")
        self.btn_import_csv.clicked.connect(self._import_csv)

        self.btn_export_csv = QPushButton("⬇  Exportar Excel / CSV")
        self.btn_export_csv.setToolTip("Exporta todos os veículos para Excel (.xlsx) ou CSV (.csv)")
        self.btn_export_csv.clicked.connect(self._export_csv)

        self.btn_cloud_backup = QPushButton("☁  Backup Nuvem")
        self.btn_cloud_backup.setToolTip(
            "Envia agora uma cópia dos veículos cadastrados para a nuvem vinculada à sua licença"
        )
        self.btn_cloud_backup.clicked.connect(self.cloud_backup_requested.emit)

        self.btn_cloud_restore = QPushButton("☁  Restaurar")
        self.btn_cloud_restore.setToolTip(
            "Baixa e restaura todos os veículos salvos na nuvem para esta licença"
        )
        self.btn_cloud_restore.clicked.connect(self.cloud_restore_requested.emit)

        self.lbl_count = QLabel("0 registros")
        self.lbl_count.setProperty("muted", "true")

        tc_layout.addWidget(self.in_search, 1)
        tc_layout.addWidget(self.cmb_filter_profile)
        tc_layout.addWidget(self.btn_import_csv)
        tc_layout.addWidget(self.btn_export_csv)
        tc_layout.addWidget(self.btn_cloud_backup)
        tc_layout.addWidget(self.btn_cloud_restore)
        tc_layout.addWidget(self.lbl_count)
        root.addWidget(tools_card)

        self.lbl_cloud_status = QLabel("☁ Backup automático na nuvem vinculado à licença (ativo ao cadastrar/editar veículos)")
        self.lbl_cloud_status.setStyleSheet("color: #64748B; font-size: 11px; padding-left: 4px; background: transparent;")
        root.addWidget(self.lbl_cloud_status)

        # --- Tabela de Veículos ---
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Placa", "Responsável", "Unidade / Bloco", "Modelo / Cor", "Perfil", "Validade", "Cadastrado em"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemSelectionChanged.connect(self._on_table_selection)
        root.addWidget(self.table, 1)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 700; background: transparent;")
        return lbl

    def _uppercase_plate_input(self, text: str) -> None:
        pos = self.in_plate.cursorPosition()
        self.in_plate.blockSignals(True)
        self.in_plate.setText(text.upper())
        self.in_plate.setCursorPosition(pos)
        self.in_plate.blockSignals(False)

    def _on_validity_toggled(self, checked: bool) -> None:
        self.dt_validity.setEnabled(checked)

    # =========================================================================
    # AÇÕES CRUD & CSV
    # =========================================================================

    def _reset_form(self) -> None:
        self._editing_id = None
        self.in_plate.clear()
        self.in_name.clear()
        self.in_unit.clear()
        self.in_model.clear()
        self.cmb_profile.setCurrentIndex(0)
        self.chk_has_validity.setChecked(False)
        self.dt_validity.setDate(QDate.currentDate().addDays(7))
        self.lbl_form_mode.setText("NOVO CADASTRO DE VEÍCULO / MORADOR")
        self.btn_save.setText("✓  Salvar Cadastro")
        self.btn_delete.setEnabled(False)
        self.table.clearSelection()
        self.in_plate.setFocus()

    def prefill_new_vehicle(self, placa: str) -> None:
        """Pré-preenche o formulário a partir do botão rápido da Aba 1."""
        plate_norm = normalize_plate(placa)
        self._reset_form()
        self.in_plate.setText(plate_norm)
        self.lbl_form_mode.setText(
            f"CADASTRO RÁPIDO DA PLACA DETECTADA — {format_plate_display(plate_norm)}"
        )
        self.in_name.setFocus()

    def set_cloud_status(self, message: str, ok: bool = True) -> None:
        color = "#34D399" if ok else "#FBBF24"
        self.lbl_cloud_status.setText(f"☁ {message}")
        self.lbl_cloud_status.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600; padding-left: 4px; background: transparent;"
        )

    def _save_vehicle(self) -> None:
        placa = normalize_plate(self.in_plate.text())
        nome = self.in_name.text().strip()
        unidade = self.in_unit.text().strip()
        modelo = self.in_model.text().strip()
        perfil = self.cmb_profile.currentText()
        validade = (
            self.dt_validity.date().toString("yyyy-MM-dd")
            if self.chk_has_validity.isChecked()
            else None
        )

        try:
            if self._editing_id is None:
                self.db.create_vehicle(
                    placa=placa,
                    nome_responsavel=nome,
                    unidade_bloco=unidade,
                    modelo_cor=modelo,
                    perfil=perfil,
                    validade_ate=validade,
                )
            else:
                self.db.update_vehicle(
                    vehicle_id=self._editing_id,
                    placa=placa,
                    nome_responsavel=nome,
                    unidade_bloco=unidade,
                    modelo_cor=modelo,
                    perfil=perfil,
                    validade_ate=validade,
                )
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                "Placa Duplicada",
                f"A placa {format_plate_display(placa)} já está cadastrada no sistema.",
            )
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Dados Inválidos", str(exc))
            return

        self._reset_form()
        self.refresh_table()
        self.vehicles_changed.emit()

    def _delete_selected(self) -> None:
        if self._editing_id is None:
            return
        vehicle = self.db.get_vehicle_by_id(self._editing_id)
        if not vehicle:
            return

        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            f"Deseja realmente remover o veículo {format_plate_display(vehicle['placa'])} "
            f"({vehicle['nome_responsavel']})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_vehicle(self._editing_id)
            self._reset_form()
            self.refresh_table()
            self.vehicles_changed.emit()

    def _on_table_selection(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row_idx = rows[0].row()
        item = self.table.item(row_idx, 0)
        if not item:
            return
        rec: dict[str, Any] = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(rec, dict):
            return

        self._editing_id = int(rec["id"])
        self.in_plate.setText(rec["placa"])
        self.in_name.setText(rec["nome_responsavel"])
        self.in_unit.setText(rec.get("unidade_bloco") or "")
        self.in_model.setText(rec.get("modelo_cor") or "")

        idx = self.cmb_profile.findText(rec.get("perfil", "MORADOR"))
        if idx >= 0:
            self.cmb_profile.setCurrentIndex(idx)

        val = rec.get("validade_ate")
        if val:
            qd = QDate.fromString(val[:10], "yyyy-MM-dd")
            if qd.isValid():
                self.chk_has_validity.setChecked(True)
                self.dt_validity.setDate(qd)
            else:
                self.chk_has_validity.setChecked(False)
        else:
            self.chk_has_validity.setChecked(False)

        self.lbl_form_mode.setText(f"EDITANDO VEÍCULO — {format_plate_display(rec['placa'])}")
        self.btn_save.setText("✓  Atualizar Cadastro")
        self.btn_delete.setEnabled(True)

    def refresh_table(self) -> None:
        query = self.in_search.text()
        perfil = self.cmb_filter_profile.currentText()
        vehicles = self.db.search_vehicles(query=query, perfil=perfil)

        self.table.setRowCount(len(vehicles))
        for r_idx, v in enumerate(vehicles):
            it_plate = QTableWidgetItem(format_plate_display(v["placa"]))
            it_plate.setData(Qt.ItemDataRole.UserRole, v)
            it_plate.setForeground(QColor("#F8FAFC"))
            f = it_plate.font()
            f.setBold(True)
            it_plate.setFont(f)

            it_name = QTableWidgetItem(v.get("nome_responsavel") or "")
            it_unit = QTableWidgetItem(v.get("unidade_bloco") or "—")
            it_model = QTableWidgetItem(v.get("modelo_cor") or "—")

            perfil_val = v.get("perfil", "MORADOR")
            it_perfil = QTableWidgetItem(perfil_val)
            it_perfil.setForeground(QColor(PROFILE_COLORS.get(perfil_val, "#E2E8F0")))
            fp = it_perfil.font()
            fp.setBold(True)
            it_perfil.setFont(fp)

            val_raw = v.get("validade_ate") or "Permanente"
            it_val = QTableWidgetItem(val_raw)
            it_created = QTableWidgetItem((v.get("criado_em") or "")[:16])

            for c_idx, item in enumerate(
                (it_plate, it_name, it_unit, it_model, it_perfil, it_val, it_created)
            ):
                self.table.setItem(r_idx, c_idx, item)

        self.lbl_count.setText(f"{len(vehicles)} veículo(s)")

    def _import_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar Moradores / Veículos (Excel ou CSV)",
            str(Path.home()),
            "Planilhas Excel e CSV (*.xlsx *.xlsm *.csv);;Planilha Excel (*.xlsx *.xlsm);;Arquivos CSV (*.csv);;Todos os Arquivos (*.*)",
        )
        if not file_path:
            return
        try:
            summary = self.db.import_vehicles_file(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Erro na Importação", str(exc))
            return

        self.refresh_table()
        self.vehicles_changed.emit()

        msg = (
            f"Importação concluída!\n\n"
            f"• Inseridos: {summary['inserted']}\n"
            f"• Atualizados: {summary['updated']}\n"
            f"• Ignorados: {summary['skipped']}"
        )
        if summary["errors"]:
            msg += "\n\nAvisos:\n" + "\n".join(summary["errors"][:6])
        QMessageBox.information(self, "Resultado da Importação", msg)

    def _export_csv(self) -> None:
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar Cadastro de Veículos (Excel ou CSV)",
            str(Path.home() / "nexus_vision_veiculos.xlsx"),
            "Planilha Excel (*.xlsx);;Arquivo CSV (*.csv)",
        )
        if not file_path:
            return
        if "." not in Path(file_path).name:
            file_path += ".csv" if "CSV" in selected_filter else ".xlsx"
        try:
            total = self.db.export_vehicles_file(file_path)
            QMessageBox.information(
                self,
                "Exportação Concluída",
                f"{total} veículo(s) exportado(s) com sucesso para:\n{file_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao Exportar", str(exc))
