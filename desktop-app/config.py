"""
Configurações centrais do aplicativo Desktop Nexus Vision (NexuSistemas Tecnologia).
Padronizado para execução em desenvolvimento E compilado em Windows (.exe):
- Quando compilado (frozen): grava banco SQLite, capturas, logs e cache de licença em
  %LOCALAPPDATA%\\NexuSistemas\\NexusVision (nunca sofre bloqueio em Program Files).
- Recursos estáticos (logos, .ico e modelos .onnx) são lidos de sys._MEIPASS / pasta interna.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from supabase_config import PORTAL_DOMAIN, PORTAL_URL

# Detecta execução compilada (PyInstaller) vs desenvolvimento
IS_FROZEN: bool = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    DESKTOP_APP_DIR: Path = Path(sys.executable).resolve().parent
    BUNDLE_DIR: Path = Path(getattr(sys, "_MEIPASS", DESKTOP_APP_DIR))
    PROJECT_ROOT: Path = DESKTOP_APP_DIR
    _local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    DATA_DIR: Path = _local_appdata / "NexuSistemas" / "NexusVision"
else:
    DESKTOP_APP_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = DESKTOP_APP_DIR
    PROJECT_ROOT = DESKTOP_APP_DIR.parent
    DATA_DIR = DESKTOP_APP_DIR / "data"

# Carrega .env local do app se existir (nunca depende do .env.deploy)
_local_env = DESKTOP_APP_DIR / ".env"
if _local_env.exists():
    load_dotenv(_local_env)

# Diretórios de persistência offline-first
CAPTURES_DIR: Path = DATA_DIR / "captures"
LOGS_DIR: Path = DATA_DIR / "logs"
DB_PATH: Path = DATA_DIR / "nexus_vision.db"
LICENSE_CACHE_PATH: Path = DATA_DIR / "license_cache.dat"

# Diretórios de recursos estáticos / modelos IA ONNX embutidos
ASSETS_DIR: Path = BUNDLE_DIR / "assets"
MODELS_DIR: Path = BUNDLE_DIR / "models"

# Metadados do aplicativo (SemVer usado no Auto-Updater e Instalador)
APP_NAME: str = "Nexus Vision"
APP_SUBTITLE: str = "Monitoramento Veicular Inteligente 24h"
COMPANY_NAME: str = "NexuSistemas Tecnologia"
APP_VERSION: str = "1.0.4"

# Parâmetros padrão de captura, movimento e motor ALPR
CAPTURE_TARGET_FPS: int = 15
DEFAULT_MOTION_SENSITIVITY: int = 35
MAX_RECENT_PASSAGES: int = 25

ALPR_DETECTOR_MODEL: str = "yolo-v9-t-384-license-plate-end2end"
ALPR_OCR_MODEL: str = "global-plates-mobile-vit-v2-model"
DEFAULT_COOLDOWN_SECONDS: int = 25
DEFAULT_VOTE_WINDOW: int = 5
DEFAULT_MIN_VOTES: int = 2
DEFAULT_HIGH_CONFIDENCE: float = 0.90
DEFAULT_SOUND_ENABLED: bool = True
CAPTURES_RETENTION_HOURS: int = 24
HISTORY_RETENTION_HOURS: int = 24
SETTINGS_PATH: Path = DATA_DIR / "app_settings.json"

# Domínios de negócio
VEHICLE_PROFILES: tuple[str, ...] = ("MORADOR", "VISITANTE", "BLOQUEADO")

ACCESS_STATUS_LIBERADO_MORADOR = "LIBERADO_MORADOR"
ACCESS_STATUS_LIBERADO_VISITANTE = "LIBERADO_VISITANTE"
ACCESS_STATUS_BLOQUEADO = "BLOQUEADO"
ACCESS_STATUS_NAO_CADASTRADO = "NAO_CADASTRADO"
ACCESS_STATUS_EXPIRADO = "EXPIRADO"


@dataclass(frozen=True)
class BrandAssets:
    """Caminhos das logos detectadas automaticamente (bundle interno ou raiz)."""

    logo_dir: Optional[Path]
    app_icon: Optional[Path]
    logo_full: Optional[Path]
    logo_mark: Optional[Path]
    logo_text: Optional[Path]


def ensure_directories() -> None:
    """Garante que os diretórios graváveis de dados e capturas existam."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not IS_FROZEN:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)


def get_daily_captures_dir(dt: Optional[datetime] = None) -> Path:
    """Retorna (e cria) a subpasta diária captures/YYYY-MM-DD/."""
    ref = dt or datetime.now()
    folder = CAPTURES_DIR / ref.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cleanup_old_captures(max_hours: int = CAPTURES_RETENTION_HOURS) -> int:
    """
    Remove fotos capturadas mais antigas que max_hours (padrão: 24 horas)
    e limpa pastas diárias vazias para operação contínua 24h sem encher o disco.
    """
    if not CAPTURES_DIR.exists() or max_hours <= 0:
        return 0
    cutoff_ts = (datetime.now() - timedelta(hours=int(max_hours))).timestamp()
    removed = 0
    for file_path in list(CAPTURES_DIR.rglob("*")):
        if not file_path.is_file():
            continue
        try:
            if file_path.stat().st_mtime < cutoff_ts:
                file_path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue

    # Remove subpastas vazias (YYYY-MM-DD)
    for folder in sorted(
        (p for p in CAPTURES_DIR.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            continue
    return removed


def detect_brand_assets(root: Path = PROJECT_ROOT) -> BrandAssets:
    """
    Detecta automaticamente ícone (.ico) e logos (.png):
    1. Prioriza assets/ interno (desktop-app/assets ou sys._MEIPASS/assets).
    2. Em seguida inspeciona pastas de logo na raiz do projeto (ex: 'logo nexus/').
    """
    image_exts = {".png", ".ico", ".jpg", ".jpeg", ".webp", ".svg"}
    candidate_dirs: list[Path] = []

    if ASSETS_DIR.exists():
        candidate_dirs.append(ASSETS_DIR)

    if root.exists() and root != ASSETS_DIR:
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                lname = entry.name.lower()
                if any(k in lname for k in ("logo", "brand", "asset", "icon", "img", "media")):
                    if entry not in candidate_dirs:
                        candidate_dirs.append(entry)
        if root not in candidate_dirs:
            candidate_dirs.append(root)

    discovered_files: list[Path] = []
    detected_dir: Optional[Path] = None

    for folder in candidate_dirs:
        if not folder.exists() or not folder.is_dir():
            continue
        files = [
            f
            for f in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if f.is_file() and f.suffix.lower() in image_exts
        ]
        if files:
            if detected_dir is None:
                detected_dir = folder
            discovered_files.extend(files)

    if not discovered_files:
        return BrandAssets(None, None, None, None, None)

    def _pick(predicate) -> Optional[Path]:
        for path in discovered_files:
            if predicate(path):
                return path
        return None

    png_files = [p for p in discovered_files if p.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}]

    # Prioridade absoluta para nexus_vision.ico (multi-resolução gerado no build) ou qualquer .ico
    app_icon = (
        _pick(lambda p: p.name.lower() == "nexus_vision.ico")
        or _pick(lambda p: p.suffix.lower() == ".ico")
        or _pick(lambda p: p in png_files and any(k in p.stem.lower() for k in ("logo_mark", "sem letras", "icon", "mark")))
        or (png_files[0] if png_files else discovered_files[0])
    )

    logo_mark = (
        _pick(lambda p: p in png_files and any(k in p.stem.lower() for k in ("logo_mark", "sem letras", "icon", "mark", "simbolo")))
        or _pick(lambda p: p in png_files and any(k in p.stem.lower() for k in ("logo_full", "completo", "full")))
        or (png_files[0] if png_files else app_icon)
    )

    logo_full = (
        _pick(lambda p: p in png_files and any(k in p.stem.lower() for k in ("logo_full", "completo", "full", "horizontal")))
        or logo_mark
        or (png_files[0] if png_files else app_icon)
    )

    logo_text = (
        _pick(lambda p: p in png_files and any(k in p.stem.lower() for k in ("letras sem", "wordmark", "texto")))
        or logo_full
    )

    return BrandAssets(
        logo_dir=detected_dir,
        app_icon=app_icon,
        logo_full=logo_full,
        logo_mark=logo_mark,
        logo_text=logo_text,
    )


BRAND_ASSETS: BrandAssets = detect_brand_assets()
ensure_directories()
