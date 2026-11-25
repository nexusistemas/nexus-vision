"""
Motor de IA Nativa ALPR Offline (fast-alpr + ONNX Runtime 100% CPU).
Executa em QThread dedicada consumindo apenas o frame mais recente (zero lag),
com pré-processamento CLAHE opcional, heurística brasileira, votação (debounce)
e cooldown inteligente por placa.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import onnxruntime as ort
from PySide6.QtCore import QThread, Signal

from config import (
    ALPR_DETECTOR_MODEL,
    ALPR_OCR_MODEL,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_HIGH_CONFIDENCE,
    DEFAULT_MIN_VOTES,
    DEFAULT_VOTE_WINDOW,
    MODELS_DIR,
    get_daily_captures_dir,
)
from core.plate_validator import ValidatedPlate, validate_brazilian_plate


# Perfis de Distância / Nitidez para evitar leituras borradas ou de veículos muito longe
QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "LIVRE": {
        "label": "Livre (Qualquer distância)",
        "min_plate_width": 44,
        "min_sharpness": 18.0,
        "min_confidence": 0.55,
    },
    "MEDIA": {
        "label": "Média (Balanceada)",
        "min_plate_width": 68,
        "min_sharpness": 45.0,
        "min_confidence": 0.72,
    },
    "PERTO": {
        "label": "Perto / Nítida (Recomendado)",
        "min_plate_width": 92,
        "min_sharpness": 75.0,
        "min_confidence": 0.80,
    },
    "RIGOROSA": {
        "label": "Muito Perto / Rigorosa",
        "min_plate_width": 120,
        "min_sharpness": 115.0,
        "min_confidence": 0.87,
    },
}
DEFAULT_QUALITY_PRESET = "PERTO"


def measure_plate_sharpness(crop_bgr: np.ndarray) -> float:
    """Mede a nitidez (foco) do recorte da placa via variância do Laplaciano normalizada."""
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0
    h, w = crop_bgr.shape[:2]
    if h < 8 or w < 16:
        return 0.0
    target_h = 48
    target_w = max(24, int(round((w / float(h)) * target_h)))
    resized = cv2.resize(crop_bgr, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def resolve_models_root() -> Path:
    """
    Resolve a pasta local dos modelos ONNX, compatível tanto com execução em
    desenvolvimento quanto empacotado em executável PyInstaller (_MEIPASS).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "models"
        if bundled.exists():
            return bundled
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return MODELS_DIR


def apply_low_light_clahe(frame_bgr: np.ndarray) -> np.ndarray:
    """Realça contraste em cenas noturnas/escurecidas via CLAHE no canal de luminância."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l_chan)
    merged = cv2.merge((l_enhanced, a_chan, b_chan))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def save_alpr_capture(
    frame_bgr: np.ndarray,
    plate: str,
    bbox: Optional[tuple[int, int, int, int]] = None,
    box_color_bgr: tuple[int, int, int] = (129, 185, 16),
) -> Optional[str]:
    """
    Salva a captura do veículo/placa organizada em data/captures/YYYY-MM-DD/.
    Desenha a bounding box e o carimbo da placa para auditoria no Histórico.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None

    out_dir = get_daily_captures_dir()
    safe_plate = "".join(ch for ch in plate.upper() if ch.isalnum())[:10] or "PLACA"
    ts_str = datetime.now().strftime("%H%M%S_%f")[:-3]
    out_path = out_dir / f"{ts_str}_{safe_plate}.jpg"

    img = frame_bgr.copy()
    h, w = img.shape[:2]
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)
        if x2 > x1 and y2 > y1:
            cv2.rectangle(img, (x1, y1), (x2, y2), box_color_bgr, 3)
            label = safe_plate
            (tw, th), bl = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            ly1 = max(0, y1 - th - bl - 8)
            cv2.rectangle(img, (x1, ly1), (x1 + tw + 12, y1), box_color_bgr, -1)
            cv2.putText(
                img,
                label,
                (x1 + 6, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (10, 15, 25),
                2,
                cv2.LINE_AA,
            )

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if ok:
        out_path.write_bytes(buf.tobytes())
        return str(out_path)
    return None


class ALPREngineWorker(QThread):
    """
    Thread dedicada para inferência ALPR offline via ONNX Runtime (CPU).
    Mantém fila de 1 único slot (frame mais recente) para jamais atrasar a UI.
    """

    # Emite (mensagem_status, pronto_bool)
    engine_status = Signal(str, bool)
    # Emite lista de detecções atuais para desenhar Bounding Box ao vivo no preview
    detections_updated = Signal(list)
    # Emite dicionário completo quando uma placa passa na votação e fora do cooldown
    plate_confirmed = Signal(dict)
    # Emite estatísticas de inferência (tempo_ms)
    inference_metrics = Signal(float)

    def __init__(
        self,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        vote_window: int = DEFAULT_VOTE_WINDOW,
        min_votes: int = DEFAULT_MIN_VOTES,
        high_confidence: float = DEFAULT_HIGH_CONFIDENCE,
        enable_clahe: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cond = threading.Condition()
        self._running = False
        self._ready = False
        self._licensed = True
        self._pending_frame: Optional[np.ndarray] = None

        self._cooldown_seconds = max(3, int(cooldown_seconds))
        self._vote_window_size = max(2, int(vote_window))
        self._min_votes = max(1, int(min_votes))
        self._high_confidence = max(0.50, min(0.99, float(high_confidence)))
        self._enable_clahe = bool(enable_clahe)

        # Filtro de distância/nitidez (ignora placas longe ou desfocadas)
        preset = QUALITY_PRESETS[DEFAULT_QUALITY_PRESET]
        self._min_plate_width: int = int(preset["min_plate_width"])
        self._min_sharpness: float = float(preset["min_sharpness"])
        self._min_confidence: float = float(preset["min_confidence"])

        # Histórico circular dos últimos N frames analisados (cada item = set de placas válidas)
        self._recent_votes: deque[set[str]] = deque(maxlen=self._vote_window_size)
        # Mapa placa -> timestamp monotonic da última confirmação registrada
        self._cooldown_map: dict[str, float] = {}
        self._alpr = None

    # =========================================================================
    # CONTROLES THREAD-SAFE CHAMADOS PELA UI / CAPTURA
    # =========================================================================

    def is_ready(self) -> bool:
        with self._cond:
            return self._ready

    def set_licensed(self, allowed: bool) -> None:
        """Bloqueia ou libera inferência ALPR em tempo real conforme status da licença."""
        with self._cond:
            self._licensed = bool(allowed)
            if not self._licensed:
                self._pending_frame = None

    def is_licensed(self) -> bool:
        with self._cond:
            return self._licensed

    def set_cooldown_seconds(self, seconds: int) -> None:
        with self._cond:
            self._cooldown_seconds = max(3, int(seconds))

    def set_voting_params(self, min_votes: int, high_confidence: float) -> None:
        with self._cond:
            self._min_votes = max(1, int(min_votes))
            self._high_confidence = max(0.50, min(0.99, float(high_confidence)))

    def set_clahe_enabled(self, enabled: bool) -> None:
        with self._cond:
            self._enable_clahe = bool(enabled)

    def set_quality_preset(self, preset_key: str) -> None:
        """Ajusta filtro de distância (largura mínima px), nitidez (Laplaciano) e confiança mínima."""
        preset = QUALITY_PRESETS.get(preset_key.upper(), QUALITY_PRESETS[DEFAULT_QUALITY_PRESET])
        with self._cond:
            self._min_plate_width = int(preset["min_plate_width"])
            self._min_sharpness = float(preset["min_sharpness"])
            self._min_confidence = float(preset["min_confidence"])
            self._recent_votes.clear()

    def clear_cooldown(self) -> None:
        with self._cond:
            self._cooldown_map.clear()
            self._recent_votes.clear()

    def submit_frame(self, frame_bgr: np.ndarray) -> None:
        """
        Submete o frame mais recente para inferência ALPR.
        Substitui qualquer frame anterior ainda não processado (zero fila acumulada).
        Ignora imediatamente se a licença estiver bloqueada/expirada.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return
        with self._cond:
            if not self._running or not self._ready or not self._licensed:
                return
            self._pending_frame = frame_bgr
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._pending_frame = None
            self._cond.notify_all()
        if self.isRunning():
            self.wait(4000)

    # =========================================================================
    # INICIALIZAÇÃO ONNX OFFLINE (100% CPU)
    # =========================================================================

    def _load_alpr_models(self) -> Any:
        import fast_plate_ocr.inference.hub as ocr_hub
        import open_image_models.detection.core.hub as det_hub
        from fast_alpr import ALPR

        models_root = resolve_models_root()
        det_dir = models_root / "detector"
        ocr_dir = models_root / "ocr"
        det_dir.mkdir(parents=True, exist_ok=True)
        ocr_dir.mkdir(parents=True, exist_ok=True)

        # Redireciona cache dos hubs para desktop-app/models/ (100% offline-ready)
        det_hub.MODEL_CACHE_DIR = det_dir
        ocr_hub.MODEL_CACHE_DIR = ocr_dir

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3  # Somente erros críticos
        cpu_threads = max(1, min(4, (os.cpu_count() or 2) // 2 or 1))
        sess_opts.intra_op_num_threads = cpu_threads
        sess_opts.inter_op_num_threads = 1

        return ALPR(
            detector_model=ALPR_DETECTOR_MODEL,
            detector_conf_thresh=0.35,
            detector_providers=["CPUExecutionProvider"],
            detector_sess_options=sess_opts,
            ocr_model=ALPR_OCR_MODEL,
            ocr_device="cpu",
            ocr_providers=["CPUExecutionProvider"],
            ocr_sess_options=sess_opts,
        )

    # =========================================================================
    # LOOP PRINCIPAL DA THREAD DE IA
    # =========================================================================

    def run(self) -> None:
        with self._cond:
            self._running = True

        self.engine_status.emit("IA ALPR: Carregando modelos ONNX (CPU)...", False)
        try:
            self._alpr = self._load_alpr_models()
            # Warmup rápido para compilar grafos ONNX antes do primeiro carro chegar
            warmup = np.zeros((240, 320, 3), dtype=np.uint8)
            self._alpr.predict(warmup)
            with self._cond:
                self._ready = True
            self.engine_status.emit("IA ALPR: ONLINE (ONNX CPU)", True)
        except Exception as exc:
            with self._cond:
                self._ready = False
            self.engine_status.emit(f"IA ALPR: Erro ao carregar ONNX ({exc})", False)
            return

        while True:
            with self._cond:
                while self._running and self._pending_frame is None:
                    self._cond.wait(timeout=0.4)
                if not self._running:
                    break
                frame = self._pending_frame
                self._pending_frame = None
                enable_clahe = self._enable_clahe

            if frame is None:
                continue

            try:
                t0 = time.perf_counter()
                self._process_frame(frame, enable_clahe)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.inference_metrics.emit(elapsed_ms)
            except Exception as exc:
                self.engine_status.emit(f"IA ALPR: Falha na inferência ({exc})", True)

    def _extract_ocr_confidence(
        self, raw_conf: Any
    ) -> tuple[float, Optional[list[float]]]:
        if isinstance(raw_conf, (list, tuple, np.ndarray)):
            vals = [float(x) for x in raw_conf]
            if not vals:
                return 0.0, None
            return float(sum(vals) / len(vals)), vals
        try:
            return float(raw_conf), None
        except (TypeError, ValueError):
            return 0.0, None

    def _run_predict_with_optional_clahe(
        self, frame_bgr: np.ndarray, enable_clahe: bool
    ) -> list[Any]:
        assert self._alpr is not None
        work_frame = frame_bgr

        # Em ambientes noturnos/escuros, aplica CLAHE automaticamente antes da inferência
        used_clahe = False
        if enable_clahe:
            mean_luma = float(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).mean())
            if mean_luma < 82.0:
                work_frame = apply_low_light_clahe(frame_bgr)
                used_clahe = True

        results = self._alpr.predict(work_frame)

        # Fallback CLAHE leve se a cena estiver com contraste baixo e nada foi detectado
        if not results and enable_clahe and not used_clahe:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            if float(gray.std()) < 42.0:
                results = self._alpr.predict(apply_low_light_clahe(frame_bgr))

        return results or []

    def _process_frame(self, frame_bgr: np.ndarray, enable_clahe: bool) -> None:
        results = self._run_predict_with_optional_clahe(frame_bgr, enable_clahe)

        h, w = frame_bgr.shape[:2]
        now = time.monotonic()
        frame_valid_plates: set[str] = set()
        overlay_detections: list[dict[str, Any]] = []
        validated_candidates: list[tuple[ValidatedPlate, float, float, tuple[int, int, int, int]]] = []

        with self._cond:
            min_plate_w = self._min_plate_width
            min_sharp = self._min_sharpness
            min_conf = self._min_confidence

        for item in results:
            det = getattr(item, "detection", None)
            ocr = getattr(item, "ocr", None)
            if det is None:
                continue

            bbox_obj = det.bounding_box
            x1 = max(0, int(bbox_obj.x1))
            y1 = max(0, int(bbox_obj.y1))
            x2 = min(w - 1, int(bbox_obj.x2))
            y2 = min(h - 1, int(bbox_obj.y2))
            bbox = (x1, y1, x2, y2)
            det_conf = float(det.confidence)
            plate_w = x2 - x1

            # 1) Filtro de distância (ignora placas pequenas/longe na rua)
            if plate_w < min_plate_w:
                overlay_detections.append(
                    {
                        "bbox": bbox,
                        "plate": f"LONGE ({plate_w}px)",
                        "confidence": det_conf,
                        "valid": False,
                        "too_far": True,
                        "in_cooldown": False,
                    }
                )
                continue

            # 2) Filtro de nitidez/foco (ignora placas tremidas ou borradas)
            crop_bgr = frame_bgr[y1:y2, x1:x2]
            sharpness = measure_plate_sharpness(crop_bgr)
            if sharpness < min_sharp:
                overlay_detections.append(
                    {
                        "bbox": bbox,
                        "plate": "AGUARDANDO FOCO...",
                        "confidence": det_conf,
                        "valid": False,
                        "too_far": True,
                        "in_cooldown": False,
                    }
                )
                continue

            if ocr is None or not getattr(ocr, "text", ""):
                overlay_detections.append(
                    {
                        "bbox": bbox,
                        "plate": "LENDO...",
                        "confidence": det_conf,
                        "valid": False,
                        "in_cooldown": False,
                    }
                )
                continue

            ocr_conf, char_confs = self._extract_ocr_confidence(ocr.confidence)
            combined_conf = float(min(1.0, (det_conf * 0.35) + (ocr_conf * 0.65)))

            # 3) Filtro de confiança mínima (descarta chutes imprecisos)
            if combined_conf < min_conf:
                overlay_detections.append(
                    {
                        "bbox": bbox,
                        "plate": f"BAIXA CONF. ({int(round(combined_conf * 100))}%)",
                        "confidence": combined_conf,
                        "valid": False,
                        "too_far": True,
                        "in_cooldown": False,
                    }
                )
                continue

            validated = validate_brazilian_plate(
                raw_text=ocr.text,
                confidence=ocr_conf,
                char_confidences=char_confs,
            )

            if validated is None:
                overlay_detections.append(
                    {
                        "bbox": bbox,
                        "plate": f"? {ocr.text.strip().upper()[:8]}",
                        "confidence": ocr_conf,
                        "valid": False,
                        "in_cooldown": False,
                    }
                )
                continue

            frame_valid_plates.add(validated.plate)
            in_cd = self._is_in_cooldown(validated.plate, now)
            overlay_detections.append(
                {
                    "bbox": bbox,
                    "plate": validated.plate,
                    "confidence": combined_conf,
                    "valid": True,
                    "in_cooldown": in_cd,
                }
            )
            validated_candidates.append((validated, det_conf, ocr_conf, bbox))

        # Atualiza overlay no vídeo ao vivo sempre que houver detecção
        if overlay_detections:
            self.detections_updated.emit(overlay_detections)

        # Registra este frame na janela de votação
        self._recent_votes.append(frame_valid_plates)

        with self._cond:
            min_votes = self._min_votes
            high_conf = self._high_confidence

        # Avalia votação + confiança altíssima + cooldown por placa
        for validated, det_conf, ocr_conf, bbox in validated_candidates:
            plate = validated.plate
            votes = sum(1 for s in self._recent_votes if plate in s)
            combined_conf = float(min(1.0, (det_conf * 0.35) + (ocr_conf * 0.65)))

            if votes < min_votes and combined_conf < high_conf:
                continue

            if self._is_in_cooldown(plate, now):
                continue

            # Confirma a leitura e registra cooldown (sem salvar foto em disco para performance máxima)
            self._cooldown_map[plate] = now
            self._prune_expired_cooldowns(now)

            self.plate_confirmed.emit(
                {
                    "plate": plate,
                    "raw_text": validated.raw_text,
                    "pattern": validated.pattern,
                    "confidence": combined_conf,
                    "det_confidence": det_conf,
                    "ocr_confidence": ocr_conf,
                    "votes": votes,
                    "bbox": bbox,
                }
            )

    def _is_in_cooldown(self, plate: str, now: float) -> bool:
        last_ts = self._cooldown_map.get(plate)
        if last_ts is None:
            return False
        with self._cond:
            cd = self._cooldown_seconds
        return (now - last_ts) < cd

    def _prune_expired_cooldowns(self, now: float) -> None:
        with self._cond:
            cd = self._cooldown_seconds
        expired = [p for p, ts in self._cooldown_map.items() if (now - ts) >= cd * 2]
        for p in expired:
            self._cooldown_map.pop(p, None)
