"""
Overlay Transparente Multi-Monitor (ROISelectorOverlay) para Windows 10/11.
Cobre todo o desktop virtual, escurece o fundo e permite arrastar um retângulo
com borda neon ciano/verde exibindo dimensões em tempo real.
Captura coordenadas físicas exatas (Win32 GetCursorPos) para 100% de precisão com mss.
"""

from __future__ import annotations

import ctypes
import platform
from typing import Optional

import mss
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _get_physical_cursor_pos(fallback_global: QPoint, dpr: float = 1.0) -> tuple[int, int]:
    """Retorna a coordenada física real do cursor no Windows (compatível com DPI misto)."""
    if platform.system() == "Windows":
        try:
            pt = _POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
    return int(round(fallback_global.x() * dpr)), int(round(fallback_global.y() * dpr))


def _detect_monitor_index(center_x: int, center_y: int) -> int:
    """Identifica o índice do monitor no mss que contém o centro da ROI."""
    try:
        mss_factory = getattr(mss, "MSS", mss.mss)
        with mss_factory() as sct:
            for idx, mon in enumerate(sct.monitors[1:], start=1):
                if (
                    mon["left"] <= center_x < mon["left"] + mon["width"]
                    and mon["top"] <= center_y < mon["top"] + mon["height"]
                ):
                    return idx
    except Exception:
        pass
    return 1


class ROISelectorOverlay(QWidget):
    """
    Janela fullscreen transparente abrangendo todos os monitores conectados.
    Emite roi_selected(dict) ao soltar o mouse ou selection_cancelled() no ESC.
    """

    roi_selected = Signal(dict)
    selection_cancelled = Signal()

    MIN_ROI_SIZE = 32

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)

        # Cobre o desktop virtual completo (todos os monitores)
        primary = QGuiApplication.primaryScreen()
        self._virtual_geo: QRect = (
            primary.virtualGeometry() if primary is not None else QRect(0, 0, 1920, 1080)
        )
        self._primary_geo: QRect = (
            primary.geometry() if primary is not None else QRect(0, 0, 1920, 1080)
        )
        self.setGeometry(self._virtual_geo)

        self._dragging = False
        self._start_local: Optional[QPoint] = None
        self._current_local: Optional[QPoint] = None
        self._hover_local: QPoint = QPoint(0, 0)

        self._start_phys: Optional[tuple[int, int]] = None
        self._current_phys: Optional[tuple[int, int]] = None

    def show_selector(self) -> None:
        """Exibe o overlay em tela cheia multi-monitor e captura foco de teclado."""
        self.setGeometry(self._virtual_geo)
        self.move(self._virtual_geo.topLeft())
        self.resize(self._virtual_geo.size())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.selection_cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.selection_cancelled.emit()
            self.close()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_local = event.position().toPoint()
            self._current_local = self._start_local
            self._start_phys = _get_physical_cursor_pos(
                event.globalPosition().toPoint(), self.devicePixelRatioF()
            )
            self._current_phys = self._start_phys
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self._hover_local = pos
        if self._dragging:
            self._current_local = pos
            self._current_phys = _get_physical_cursor_pos(
                event.globalPosition().toPoint(), self.devicePixelRatioF()
            )
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return

        self._dragging = False
        end_phys = _get_physical_cursor_pos(
            event.globalPosition().toPoint(), self.devicePixelRatioF()
        )
        start_phys = self._start_phys or end_phys

        left = min(start_phys[0], end_phys[0])
        top = min(start_phys[1], end_phys[1])
        width = abs(end_phys[0] - start_phys[0])
        height = abs(end_phys[1] - start_phys[1])

        if width < self.MIN_ROI_SIZE or height < self.MIN_ROI_SIZE:
            # Seleção muito pequena: permite tentar novamente sem fechar abruptamente
            self._start_local = None
            self._current_local = None
            self._start_phys = None
            self._current_phys = None
            self.update()
            return

        center_x = left + width // 2
        center_y = top + height // 2
        monitor_index = _detect_monitor_index(center_x, center_y)

        roi_payload = {
            "left": int(left),
            "top": int(top),
            "width": int(width),
            "height": int(height),
            "monitor_index": int(monitor_index),
        }
        self.roi_selected.emit(roi_payload)
        self.close()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        full_rect = self.rect()
        veil_color = QColor(6, 11, 23, 148)

        selection_rect: Optional[QRect] = None
        if self._start_local is not None and self._current_local is not None:
            selection_rect = QRect(self._start_local, self._current_local).normalized()

        # Escurece tudo, mantendo a área selecionada cristalina (recorte)
        if selection_rect and selection_rect.width() > 2 and selection_rect.height() > 2:
            path = QPainterPath()
            path.addRect(full_rect)
            cutout = QPainterPath()
            cutout.addRect(selection_rect)
            painter.fillPath(path.subtracted(cutout), veil_color)
        else:
            painter.fillRect(full_rect, veil_color)

        # Linhas guia sutis enquanto o usuário posiciona o cursor
        if not self._dragging:
            guide_pen = QPen(QColor(34, 211, 238, 95), 1, Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            painter.drawLine(self._hover_local.x(), 0, self._hover_local.x(), full_rect.height())
            painter.drawLine(0, self._hover_local.y(), full_rect.width(), self._hover_local.y())

        # Banner superior de instrução centralizado no monitor principal
        prim_local_x = self._primary_geo.x() - self._virtual_geo.x()
        prim_local_y = self._primary_geo.y() - self._virtual_geo.y()
        banner_w = 560
        banner_h = 42
        banner_rect = QRect(
            prim_local_x + (self._primary_geo.width() - banner_w) // 2,
            prim_local_y + 26,
            banner_w,
            banner_h,
        )
        painter.setPen(QPen(QColor("#22D3EE"), 1.5))
        painter.setBrush(QColor(15, 23, 42, 235))
        painter.drawRoundedRect(banner_rect, 10, 10)

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor("#F8FAFC"))
        painter.drawText(
            banner_rect,
            Qt.AlignmentFlag.AlignCenter,
            "NEXUS VISION  •  Arraste sobre a câmera na tela  •  ESC ou botão direito para cancelar",
        )

        # Retângulo neon ciano/verde + cantoneiras + HUD de dimensões em tempo real
        if selection_rect and selection_rect.width() > 2 and selection_rect.height() > 2:
            # Glow externo sutil
            painter.setPen(QPen(QColor(16, 185, 129, 90), 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(selection_rect)

            # Borda principal neon ciano
            painter.setPen(QPen(QColor("#22D3EE"), 2))
            painter.drawRect(selection_rect)

            # Cantoneiras neon verde esmeralda
            corner = min(18, selection_rect.width() // 3, selection_rect.height() // 3)
            painter.setPen(QPen(QColor("#10B981"), 3))
            x1, y1 = selection_rect.left(), selection_rect.top()
            x2, y2 = selection_rect.right(), selection_rect.bottom()
            # Topo-esquerdo
            painter.drawLine(x1, y1, x1 + corner, y1)
            painter.drawLine(x1, y1, x1, y1 + corner)
            # Topo-direito
            painter.drawLine(x2, y1, x2 - corner, y1)
            painter.drawLine(x2, y1, x2, y1 + corner)
            # Base-esquerda
            painter.drawLine(x1, y2, x1 + corner, y2)
            painter.drawLine(x1, y2, x1, y2 - corner)
            # Base-direita
            painter.drawLine(x2, y2, x2 - corner, y2)
            painter.drawLine(x2, y2, x2, y2 - corner)

            # Dimensões físicas reais em tempo real
            if self._start_phys and self._current_phys:
                pw = abs(self._current_phys[0] - self._start_phys[0])
                ph = abs(self._current_phys[1] - self._start_phys[1])
                px = min(self._start_phys[0], self._current_phys[0])
                py = min(self._start_phys[1], self._current_phys[1])
                hud_text = f"{pw} × {ph} px  |  ({px}, {py})"
            else:
                hud_text = f"{selection_rect.width()} × {selection_rect.height()} px"

            hud_font = QFont("Consolas", 10, QFont.Weight.Bold)
            painter.setFont(hud_font)
            fm = painter.fontMetrics()
            pill_w = fm.horizontalAdvance(hud_text) + 22
            pill_h = 28

            pill_x = max(8, min(selection_rect.left(), full_rect.width() - pill_w - 8))
            pill_y = selection_rect.top() - pill_h - 8
            if pill_y < 8:
                pill_y = selection_rect.bottom() + 8
            pill_rect = QRect(pill_x, pill_y, pill_w, pill_h)

            painter.setPen(QPen(QColor("#10B981"), 1.5))
            painter.setBrush(QColor(11, 17, 32, 235))
            painter.drawRoundedRect(pill_rect, 6, 6)
            painter.setPen(QColor("#6EE7B7"))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, hud_text)
