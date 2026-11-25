"""
Folha de estilo QSS corporativa Dark 24h — Nexus Vision (NexuSistemas Tecnologia).
Projetada para conforto visual em operação contínua de portaria/monitoramento.
"""

from __future__ import annotations

DARK_STYLESHEET = """
/* ============================================================================
   BASE GLOBAL
   ============================================================================ */
QMainWindow, QWidget {
    background-color: #0B1120;
    color: #E2E8F0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QFrame {
    border: none;
}

/* ============================================================================
   SIDEBAR LATERAL
   ============================================================================ */
QFrame#Sidebar {
    background-color: #0F172A;
    border-right: 1px solid #1E293B;
}

QFrame#BrandContainer {
    background-color: #131E34;
    border-bottom: 1px solid #1E293B;
}

QLabel#LogoBadge {
    background-color: #F1F5F9;
    border: 2px solid #06B6D4;
    border-radius: 12px;
    padding: 4px;
}

QLabel#BrandTitle {
    color: #F8FAFC;
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.8px;
    background: transparent;
}

QLabel#BrandSubtitle {
    color: #38BDF8;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}

QPushButton[nav="true"] {
    background-color: transparent;
    color: #94A3B8;
    text-align: left;
    padding: 12px 16px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid transparent;
}

QPushButton[nav="true"]:hover {
    background-color: #1E293B;
    color: #F1F5F9;
}

QPushButton[nav="true"][active="true"] {
    background-color: #0E2A3F;
    color: #38BDF8;
    border: 1px solid #0891B2;
    border-left: 4px solid #22D3EE;
}

QFrame#SidebarFooter {
    background-color: #0B1325;
    border-top: 1px solid #1E293B;
    border-radius: 8px;
}

/* ============================================================================
   TOPBAR / CABEÇALHO
   ============================================================================ */
QFrame#TopBar {
    background-color: #0F172A;
    border-bottom: 1px solid #1E293B;
}

QLabel#PageTitle {
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 700;
    background: transparent;
}

QLabel#PageSubtitle {
    color: #94A3B8;
    font-size: 12px;
    background: transparent;
}

QLabel#ClockLabel {
    color: #22D3EE;
    font-family: "Consolas", "Cascadia Code", monospace;
    font-size: 16px;
    font-weight: 700;
    background-color: #131E34;
    border: 1px solid #1E293B;
    border-radius: 8px;
    padding: 6px 12px;
}

QLabel#PillBadge {
    color: #CBD5E1;
    background-color: #131E34;
    border: 1px solid #1E293B;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}

/* ============================================================================
   CARDS E CONTÊINERES
   ============================================================================ */
QFrame[card="true"] {
    background-color: #111827;
    border: 1px solid #1E293B;
    border-radius: 12px;
}

QFrame[card="elevated"] {
    background-color: #151F32;
    border: 1px solid #24334D;
    border-radius: 12px;
}

QLabel[sectionTitle="true"] {
    color: #F1F5F9;
    font-size: 14px;
    font-weight: 700;
    background: transparent;
}

QLabel[muted="true"] {
    color: #94A3B8;
    font-size: 12px;
    background: transparent;
}

/* ============================================================================
   BOTÕES
   ============================================================================ */
QPushButton {
    background-color: #1E293B;
    color: #F1F5F9;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #283549;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #0F172A;
}

QPushButton:disabled {
    background-color: #131C2E;
    color: #475569;
    border-color: #1E293B;
}

QPushButton[variant="primary"] {
    background-color: #0891B2;
    color: #FFFFFF;
    border: 1px solid #06B6D4;
}

QPushButton[variant="primary"]:hover {
    background-color: #06B6D4;
}

QPushButton[variant="success"] {
    background-color: #059669;
    color: #FFFFFF;
    border: 1px solid #10B981;
}

QPushButton[variant="success"]:hover {
    background-color: #10B981;
}

QPushButton[variant="warning"] {
    background-color: #B45309;
    color: #FFFFFF;
    border: 1px solid #F59E0B;
}

QPushButton[variant="warning"]:hover {
    background-color: #D97706;
}

QPushButton[variant="danger"] {
    background-color: #B91C1C;
    color: #FFFFFF;
    border: 1px solid #EF4444;
}

QPushButton[variant="danger"]:hover {
    background-color: #DC2626;
}

/* ============================================================================
   CAMPOS DE ENTRADA
   ============================================================================ */
QLineEdit, QComboBox, QDateEdit, QSpinBox {
    background-color: #0B1324;
    color: #F8FAFC;
    border: 1px solid #26354D;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: #0891B2;
}

QSpinBox {
    padding: 6px 26px 6px 10px;
}

QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 22px;
    background-color: #162238;
    border-left: 1px solid #26354D;
}

QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 7px;
    border-bottom: 1px solid #26354D;
}

QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 7px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #1E3352;
}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {
    border: 1px solid #22D3EE;
    background-color: #0E172B;
}

QLineEdit[readOnly="true"] {
    background-color: #0F172A;
    color: #38BDF8;
}

QComboBox::drop-down {
    border: none;
    width: 26px;
}

QComboBox QAbstractItemView {
    background-color: #0F172A;
    color: #F1F5F9;
    border: 1px solid #334155;
    selection-background-color: #0E7490;
}

QCheckBox {
    spacing: 8px;
    color: #CBD5E1;
    background: transparent;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #0B1324;
}

QCheckBox::indicator:checked {
    background-color: #06B6D4;
    border-color: #22D3EE;
}

/* ============================================================================
   SLIDER & PROGRESS BAR (NÍVEL DE MOVIMENTO)
   ============================================================================ */
QSlider::groove:horizontal {
    height: 6px;
    background: #1E293B;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #22D3EE;
    border: 2px solid #0B1120;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::sub-page:horizontal {
    background: #0891B2;
    border-radius: 3px;
}

QProgressBar#MotionBar {
    background-color: #0B1324;
    border: 1px solid #1E293B;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #F8FAFC;
    font-size: 11px;
    font-weight: 700;
}

QProgressBar#MotionBar::chunk {
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #06B6D4, stop:0.65 #10B981, stop:1 #F59E0B
    );
    border-radius: 5px;
}

/* ============================================================================
   TABELAS & LISTAS
   ============================================================================ */
QTableWidget {
    background-color: #0D1526;
    alternate-background-color: #111C31;
    gridline-color: #1E293B;
    border: 1px solid #1E293B;
    border-radius: 10px;
    color: #E2E8F0;
    selection-background-color: #0E3A53;
    selection-color: #FFFFFF;
}

QTableWidget::item {
    padding: 6px 8px;
}

QHeaderView::section {
    background-color: #152138;
    color: #94A3B8;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #26354D;
    border-right: 1px solid #1E293B;
    font-weight: 700;
    font-size: 12px;
    text-transform: uppercase;
}

QListWidget {
    background-color: #0D1526;
    border: 1px solid #1E293B;
    border-radius: 10px;
    outline: none;
}

QListWidget::item {
    border-bottom: 1px solid #172236;
    padding: 6px;
}

QListWidget::item:selected {
    background-color: #132C44;
    border-radius: 6px;
}

/* ============================================================================
   SCROLLBARS DISCRETAS
   ============================================================================ */
QScrollBar:vertical {
    background: #0B1120;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #293852;
    min-height: 28px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #3B4F73;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #0B1120;
    height: 10px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #293852;
    min-width: 28px;
    border-radius: 5px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""
