"""
Motor de Captura Universal de Tela (QThread + mss) com Detector de Movimento OpenCV.
Captura exclusivamente a área ROI selecionada (~15 FPS) sem travar a UI principal,
encaminha frames com movimento para o motor ALPR e renderiza Bounding Boxes ao vivo.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Optional

import cv2
import mss
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from config import (
    CAPTURE_TARGET_FPS,
    DEFAULT_MOTION_SENSITIVITY,
    get_daily_captures_dir,
)


class ScreenCaptureWorker(QThread):
    """
    Thread dedicada para captura de ROI na tela do Windows via mss
    e análise de movimento por diferença absoluta de frames (cv2.absdiff).
    """

    # (frame_anotado, nivel_movimento_0_100, movimento_detectado, fps_real)
    frame_ready = Signal(QImage, float, bool, float)
    # Emitido com cooldown quando movimento ultrapassa o limiar
    motion_triggered = Signal(float)
    # Emite frame BGR puro para o motor ALPR durante movimento e cauda pós-movimento
    alpr_frame_ready = Signal(object)
    error_occurred = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        roi: dict[str, Any],
        target_fps: int = CAPTURE_TARGET_FPS,
        sensitivity: int = DEFAULT_MOTION_SENSITIVITY,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._roi = dict(roi)
        self._target_fps = max(1, min(30, int(target_fps)))
        self._sensitivity = max(1, min(100, int(sensitivity)))
        self._running = False
        self._paused = False
        self._latest_bgr_frame: Optional[np.ndarray] = None

        self._last_trigger_ts: float = 0.0
        self._trigger_cooldown_sec: float = 1.5

        # Cauda pós-movimento (1.8s): continua enviando frames para o ALPR quando o carro
        # freia no portão, momento em que a placa fica mais nítida sem motion blur.
        self._last_motion_seen_ts: float = 0.0
        self._motion_tail_sec: float = 1.8
        self._last_alpr_dispatch_ts: float = 0.0
        self._alpr_dispatch_interval_sec: float = 0.16  # até ~6 FPS para o worker ALPR

        # Detecções ALPR ao vivo para desenhar Bounding Boxes no vídeo
        self._alpr_detections: list[dict[str, Any]] = []
        self._alpr_detections_expires_at: float = 0.0
        # Mapa placa -> cor BGR baseada no status do banco (verde/vermelho/amarelo)
        self._plate_color_hints: dict[str, tuple[int, int, int]] = {}

    def update_roi(self, roi: dict[str, Any]) -> None:
        with self._lock:
            self._roi = dict(roi)
            self._alpr_detections = []

    def set_sensitivity(self, sensitivity: int) -> None:
        with self._lock:
            self._sensitivity = max(1, min(100, int(sensitivity)))

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
        self.status_changed.emit("PAUSADA" if paused else "ATIVA")

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_alpr_detections(
        self, detections: list[dict[str, Any]], ttl_sec: float = 1.6
    ) -> None:
        """Atualiza as bounding boxes ALPR renderizadas no preview em tempo real."""
        with self._lock:
            self._alpr_detections = list(detections)
            self._alpr_detections_expires_at = time.monotonic() + max(0.3, float(ttl_sec))

    def set_plate_color_hint(self, plate: str, bgr_color: tuple[int, int, int]) -> None:
        """Associa cor visual (verde/vermelho/amarelo) à placa confirmada no banco."""
        with self._lock:
            self._plate_color_hints[plate.upper()] = bgr_color
            if len(self._plate_color_hints) > 40:
                oldest_key = next(iter(self._plate_color_hints))
                self._plate_color_hints.pop(oldest_key, None)

    def get_latest_bgr_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._latest_bgr_frame is None else self._latest_bgr_frame.copy()

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self.isRunning():
            self.wait(3000)

    def save_current_snapshot(self, plate_tag: str = "CAPTURA") -> Optional[str]:
        """Salva o frame BGR mais recente da ROI em data/captures/YYYY-MM-DD/."""
        frame = self.get_latest_bgr_frame()
        if frame is None:
            return None

        out_dir = get_daily_captures_dir()
        safe_tag = "".join(ch for ch in plate_tag.upper() if ch.isalnum())[:12] or "CAP"
        filename = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_{safe_tag}.jpg"
        out_path = out_dir / filename
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if ok:
            out_path.write_bytes(buf.tobytes())
            return str(out_path)
        return None

    def _compute_thresholds(self, sensitivity: int) -> tuple[int, float]:
        pixel_thresh = int(round(46 - (sensitivity * 0.34)))  # 46 .. 12
        area_thresh_pct = max(0.35, round(6.5 - (sensitivity * 0.058), 2))  # 6.5% .. 0.7%
        return max(10, pixel_thresh), area_thresh_pct

    def _clamp_region(self, sct: Any, roi: dict[str, Any]) -> Optional[dict[str, int]]:
        virt = sct.monitors[0]
        v_left = int(virt["left"])
        v_top = int(virt["top"])
        v_right = v_left + int(virt["width"])
        v_bottom = v_top + int(virt["height"])

        left = max(v_left, int(roi["left"]))
        top = max(v_top, int(roi["top"]))
        right = min(v_right, int(roi["left"]) + int(roi["width"]))
        bottom = min(v_bottom, int(roi["top"]) + int(roi["height"]))

        width = right - left
        height = bottom - top
        if width < 16 or height < 16:
            return None

        return {"left": left, "top": top, "width": width, "height": height}

    def run(self) -> None:
        with self._lock:
            self._running = True
        self.status_changed.emit("ATIVA")

        prev_gray: Optional[np.ndarray] = None
        last_region_sig: Optional[tuple[int, int, int, int]] = None
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

        frame_interval = 1.0 / float(self._target_fps)
        fps_counter = 0
        fps_window_start = time.monotonic()
        current_fps = float(self._target_fps)

        try:
            mss_factory = getattr(mss, "MSS", mss.mss)
            with mss_factory() as sct:
                while True:
                    loop_start = time.monotonic()
                    with self._lock:
                        if not self._running:
                            break
                        paused = self._paused
                        roi_copy = dict(self._roi)
                        sensitivity = self._sensitivity

                    if paused:
                        time.sleep(0.08)
                        continue

                    region = self._clamp_region(sct, roi_copy)
                    if region is None:
                        self.error_occurred.emit(
                            "A área ROI configurada está fora dos limites dos monitores atuais. Selecione novamente."
                        )
                        time.sleep(0.5)
                        continue

                    sig = (region["left"], region["top"], region["width"], region["height"])
                    if sig != last_region_sig:
                        prev_gray = None
                        last_region_sig = sig

                    # Captura ultra-leve BGRA via GDI/mss (com recuperação automática 24h)
                    try:
                        raw = sct.grab(region)
                    except mss.exception.ScreenShotError:
                        self.error_occurred.emit(
                            "Tela bloqueada ou área temporariamente indisponível — aguardando retorno automático..."
                        )
                        time.sleep(0.6)
                        continue

                    frame_bgra = np.asarray(raw)
                    frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)

                    with self._lock:
                        self._latest_bgr_frame = frame_bgr

                    # Pipeline de detecção de movimento
                    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    gray_blur = cv2.GaussianBlur(gray, (15, 15), 0)

                    motion_detected = False
                    motion_meter = 0.0
                    motion_boxes: list[tuple[int, int, int, int]] = []
                    now_ts = time.monotonic()

                    if prev_gray is not None and prev_gray.shape == gray_blur.shape:
                        pixel_thresh, area_thresh_pct = self._compute_thresholds(sensitivity)
                        diff = cv2.absdiff(prev_gray, gray_blur)
                        _, thresh = cv2.threshold(diff, pixel_thresh, 255, cv2.THRESH_BINARY)
                        dilated = cv2.dilate(thresh, kernel, iterations=2)

                        changed_pixels = float(cv2.countNonZero(dilated))
                        total_pixels = float(dilated.shape[0] * dilated.shape[1]) or 1.0
                        changed_pct = (changed_pixels / total_pixels) * 100.0

                        motion_meter = min(100.0, (changed_pct / max(area_thresh_pct, 0.25)) * 50.0)
                        motion_detected = changed_pct >= area_thresh_pct

                        if motion_detected:
                            self._last_motion_seen_ts = now_ts
                            contours, _ = cv2.findContours(
                                dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                            )
                            min_area = max(180.0, total_pixels * 0.002)
                            for c in contours:
                                if cv2.contourArea(c) >= min_area:
                                    motion_boxes.append(cv2.boundingRect(c))

                            if now_ts - self._last_trigger_ts >= self._trigger_cooldown_sec:
                                self._last_trigger_ts = now_ts
                                self.motion_triggered.emit(motion_meter)

                    # Encaminha frame para o motor ALPR durante movimento ou na janela de parada
                    in_active_window = motion_detected or (
                        (now_ts - self._last_motion_seen_ts) <= self._motion_tail_sec
                    )
                    if (
                        in_active_window
                        and (now_ts - self._last_alpr_dispatch_ts) >= self._alpr_dispatch_interval_sec
                    ):
                        self._last_alpr_dispatch_ts = now_ts
                        self.alpr_frame_ready.emit(frame_bgr.copy())

                    # Atualização suave do fundo de referência
                    if prev_gray is None or prev_gray.shape != gray_blur.shape:
                        prev_gray = gray_blur
                    else:
                        prev_gray = cv2.addWeighted(prev_gray, 0.72, gray_blur, 0.28, 0)

                    # Coleta detecções ALPR vivas dentro do TTL
                    with self._lock:
                        if now_ts <= self._alpr_detections_expires_at:
                            active_alpr = list(self._alpr_detections)
                            color_hints = dict(self._plate_color_hints)
                        else:
                            active_alpr = []
                            color_hints = {}

                    annotated = self._draw_overlay(
                        frame_bgr.copy(),
                        motion_detected,
                        motion_meter,
                        motion_boxes,
                        active_alpr,
                        color_hints,
                    )

                    # Atualiza FPS real
                    fps_counter += 1
                    elapsed_fps = time.monotonic() - fps_window_start
                    if elapsed_fps >= 1.0:
                        current_fps = fps_counter / elapsed_fps
                        fps_counter = 0
                        fps_window_start = time.monotonic()

                    rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self.frame_ready.emit(qimg, motion_meter, motion_detected, current_fps)

                    elapsed = time.monotonic() - loop_start
                    sleep_time = frame_interval - elapsed
                    if sleep_time > 0.002:
                        time.sleep(sleep_time)
        except Exception as exc:
            self.error_occurred.emit(f"Erro no motor de captura: {exc}")
        finally:
            self.status_changed.emit("PARADA")

    @staticmethod
    def _draw_overlay(
        frame: np.ndarray,
        motion_detected: bool,
        motion_meter: float,
        motion_boxes: list[tuple[int, int, int, int]],
        alpr_detections: Optional[list[dict[str, Any]]] = None,
        color_hints: Optional[dict[str, tuple[int, int, int]]] = None,
    ) -> np.ndarray:
        """Desenha moldura, caixas de movimento e Bounding Boxes das placas ALPR."""
        h, w = frame.shape[:2]

        # Caixas sutis nos focos de movimento (apenas se não houver detecção ALPR sobreposta)
        if not alpr_detections:
            for x, y, bw, bh in motion_boxes[:5]:
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (248, 189, 56), 1)

        # Bounding Boxes ALPR (Verde para autorizada/válida, Vermelho para bloqueada, Âmbar para pendente)
        hints = color_hints or {}
        for det in alpr_detections or []:
            bbox = det.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = [int(v) for v in bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            plate_txt = str(det.get("plate") or "")
            conf = float(det.get("confidence") or 0.0)
            is_valid = bool(det.get("valid", False))
            too_far = bool(det.get("too_far", False))

            if too_far:
                box_color = (160, 130, 100)  # BGR cinza-azulado discreto (aguardando aproximação/foco)
                thickness = 2
            elif plate_txt in hints:
                box_color = hints[plate_txt]
                thickness = 3
            elif is_valid:
                box_color = (129, 185, 16)  # BGR verde esmeralda (#10B981)
                thickness = 3
            else:
                box_color = (11, 158, 245)  # BGR âmbar (#F59E0B)
                thickness = 2

            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, thickness)

            tag = f"{plate_txt} {int(round(conf * 100))}%" if is_valid else plate_txt
            font_s = 0.62 if w >= 420 else 0.48
            (tw, th), bl = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, font_s, 2)
            label_y1 = max(0, y1 - th - bl - 8)
            label_y2 = max(th + bl + 8, y1)
            cv2.rectangle(
                frame,
                (x1, label_y1),
                (min(w - 1, x1 + tw + 12), label_y2),
                box_color,
                -1,
            )
            cv2.putText(
                frame,
                tag,
                (x1 + 6, label_y2 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_s,
                (11, 17, 32),
                2,
                cv2.LINE_AA,
            )

        # Borda externa de alerta (BGR: verde esmeralda #10B981 vs azul ciano #38BDF8)
        border_color = (129, 185, 16) if motion_detected else (248, 189, 56)
        border_thickness = 4 if motion_detected else 2
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), border_color, border_thickness)

        # Barra superior translúcida com status
        bar_h = max(30, min(42, int(h * 0.11)))
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, bar_h), (11, 17, 32), -1)
        cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

        dot_center = (16, bar_h // 2)
        cv2.circle(frame, dot_center, 6, border_color, -1, cv2.LINE_AA)

        label = (
            "MOVIMENTO DETECTADO - IA ALPR ATIVA"
            if motion_detected
            else "AGUARDANDO MOVIMENTO"
        )
        font_scale = 0.54 if w >= 420 else 0.41
        text_color = (110, 231, 183) if motion_detected else (203, 213, 225)
        cv2.putText(
            frame,
            label,
            (30, int(bar_h * 0.67)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            text_color,
            1,
            cv2.LINE_AA,
        )

        if w >= 260:
            pct_text = f"{motion_meter:4.0f}%"
            (tw, _), _ = cv2.getTextSize(pct_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            cv2.putText(
                frame,
                pct_text,
                (w - tw - 12, int(bar_h * 0.67)),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                border_color,
                1,
                cv2.LINE_AA,
            )

        return frame
