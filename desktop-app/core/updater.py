"""
Auto-Updater via GitHub Releases API — Nexus Vision (NexuSistemas Tecnologia).
Consulta a última Release, compara versão semântica com APP_VERSION e baixa
o instalador NexusVision_Setup.exe com barra de progresso em QThread dedicada.
"""

from __future__ import annotations

import json
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

from config import APP_VERSION
from supabase_config import GITHUB_REPO


def parse_semver(version_str: str) -> tuple[int, int, int]:
    """Converte strings como 'v1.2.3' ou '1.0.0-beta' em tupla (1, 2, 3)."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str or "")
    if not match:
        return (0, 0, 0)
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return parse_semver(latest) > parse_semver(current)


class UpdateCheckWorker(QThread):
    """Consulta a última Release do repositório GitHub sem travar a UI."""

    check_finished = Signal(dict)

    def __init__(self, repo: str = GITHUB_REPO, current_version: str = APP_VERSION, parent=None) -> None:
        super().__init__(parent)
        self.repo = repo.strip()
        self.current_version = current_version

    def run(self) -> None:
        result: dict[str, Any] = {
            "available": False,
            "current_version": self.current_version,
            "latest_version": self.current_version,
            "download_url": "",
            "asset_name": "",
            "release_notes": "",
            "html_url": f"https://github.com/{self.repo}/releases",
            "error": None,
        }

        if not self.repo or "/" not in self.repo:
            result["error"] = "Repositório GitHub não configurado em supabase_config.py."
            self.check_finished.emit(result)
            return

        api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"NexusVision/{self.current_version}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                result["error"] = "Nenhuma release publicada ainda no repositório GitHub."
            else:
                result["error"] = f"Erro HTTP {err.code} ao consultar GitHub Releases."
            self.check_finished.emit(result)
            return
        except Exception as exc:
            result["error"] = f"Não foi possível verificar atualizações ({exc})."
            self.check_finished.emit(result)
            return

        tag = str(data.get("tag_name") or "").strip()
        latest_clean = tag.lstrip("vV") or self.current_version
        result["latest_version"] = latest_clean
        result["release_notes"] = str(data.get("body") or "").strip()[:600]
        result["html_url"] = str(data.get("html_url") or result["html_url"])

        # Procura asset .exe (prioridade para NexusVision_Setup*.exe)
        assets = data.get("assets") or []
        chosen_asset: Optional[dict[str, Any]] = None
        for asset in assets:
            name = str(asset.get("name") or "")
            if name.lower().endswith(".exe") and "setup" in name.lower():
                chosen_asset = asset
                break
        if chosen_asset is None:
            for asset in assets:
                name = str(asset.get("name") or "")
                if name.lower().endswith(".exe"):
                    chosen_asset = asset
                    break

        if chosen_asset:
            result["download_url"] = str(chosen_asset.get("browser_download_url") or "")
            result["asset_name"] = str(chosen_asset.get("name") or "NexusVision_Setup.exe")

        result["available"] = is_newer_version(latest_clean, self.current_version)
        self.check_finished.emit(result)


class UpdateDownloadWorker(QThread):
    """Baixa o novo instalador .exe com relatório de progresso (0..100%)."""

    progress_changed = Signal(int)
    download_finished = Signal(str, str)  # (caminho_arquivo, erro)

    def __init__(self, download_url: str, asset_name: str = "NexusVision_Setup.exe", parent=None) -> None:
        super().__init__(parent)
        self.download_url = download_url
        self.asset_name = asset_name or "NexusVision_Setup.exe"
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if not self.download_url:
            self.download_finished.emit("", "URL de download do instalador indisponível.")
            return

        target_dir = Path(tempfile.gettempdir()) / "NexusVision_Update"
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / self.asset_name

        req = urllib.request.Request(
            self.download_url,
            headers={"User-Agent": f"NexusVision/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                total_size = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                chunk_size = 64 * 1024
                with out_path.open("wb") as f:
                    while True:
                        if self._cancelled:
                            self.download_finished.emit("", "Download cancelado pelo usuário.")
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = min(100, int((downloaded * 100) / total_size))
                            self.progress_changed.emit(pct)
            self.progress_changed.emit(100)
            self.download_finished.emit(str(out_path), "")
        except Exception as exc:
            self.download_finished.emit("", f"Falha ao baixar atualização: {exc}")
