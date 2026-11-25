"""
Alertas sonoros nativos do Windows (winsound) sem bloqueio da interface PySide6.
Não depende de bibliotecas externas de áudio.
"""

from __future__ import annotations

import platform
import queue
import threading
import time
from typing import Optional

from config import (
    ACCESS_STATUS_BLOQUEADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_LIBERADO_MORADOR,
    ACCESS_STATUS_LIBERADO_VISITANTE,
    DEFAULT_SOUND_ENABLED,
)

if platform.system() == "Windows":
    import winsound
else:  # pragma: no cover
    winsound = None  # type: ignore[assignment]


# Sequências de (frequência_hz, duração_ms). Frequência 0 = pausa silenciosa.
_TONES: dict[str, list[tuple[int, int]]] = {
    "AUTHORIZED": [(880, 80), (0, 25), (1175, 130)],
    "ATTENTION": [(660, 110), (0, 55), (520, 150)],
    "BLOCKED": [(1020, 125), (0, 45), (720, 125), (0, 45), (1020, 180)],
}


class SoundAlertManager:
    """Reprodutor assíncrono de alertas sonoros com suporte a mudo instantâneo."""

    def __init__(self, enabled: bool = DEFAULT_SOUND_ENABLED) -> None:
        self._enabled = bool(enabled)
        self._queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=2)
        self._thread = threading.Thread(
            target=self._worker_loop, name="NexusSoundWorker", daemon=True
        )
        self._thread.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def play_for_status(self, status_acesso: str) -> None:
        """Toca o perfil sonoro adequado ao status de acesso sem travar a UI."""
        if not self._enabled:
            return

        if status_acesso in (
            ACCESS_STATUS_LIBERADO_MORADOR,
            ACCESS_STATUS_LIBERADO_VISITANTE,
        ):
            profile = "AUTHORIZED"
        elif status_acesso == ACCESS_STATUS_BLOQUEADO:
            profile = "BLOCKED"
        elif status_acesso == ACCESS_STATUS_EXPIRADO:
            profile = "ATTENTION"
        else:
            profile = "ATTENTION"

        try:
            # Descarta alerta pendente se fila estiver cheia para nunca acumular beeps
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait(profile)
        except queue.Full:
            pass

    def _worker_loop(self) -> None:
        while True:
            profile = self._queue.get()
            if profile is None:
                break
            if not self._enabled or winsound is None:
                continue
            sequence = _TONES.get(profile, _TONES["ATTENTION"])
            for freq, dur_ms in sequence:
                if not self._enabled:
                    break
                if freq <= 0:
                    time.sleep(dur_ms / 1000.0)
                else:
                    try:
                        winsound.Beep(int(freq), int(dur_ms))
                    except RuntimeError:
                        # Máquina sem dispositivo de áudio ativo
                        break
