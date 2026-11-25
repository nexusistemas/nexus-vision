"""
Script automatizado de Build & Empacotamento Windows — Nexus Vision (NexuSistemas).

Executa o pipeline completo de produção:
  1. Gera ícone multi-resolução desktop-app/assets/nexus_vision.ico (256..16px) via Pillow
     a partir da logo na raiz e prepara assets internos.
  2. Garante os modelos ONNX offline em desktop-app/models/ para embutimento no .exe.
  3. Compila o aplicativo standalone via PyInstaller (--onedir --noconsole) sem bloat
     e com todas as DLLs do onnxruntime, OpenCV, mss e PySide6.
  4. Gera o script Inno Setup em Português do Brasil (desktop-app/installer/NexusVision.iss)
     com atalho na Área de Trabalho e inicialização automática com o Windows marcados por padrão.
  5. Compila automaticamente o instalador final Output/NexusVision_Setup_v1.0.0.exe se ISCC.exe existir.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

DESKTOP_APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DESKTOP_APP_DIR.parent
ASSETS_DIR = DESKTOP_APP_DIR / "assets"
MODELS_DIR = DESKTOP_APP_DIR / "models"
INSTALLER_DIR = DESKTOP_APP_DIR / "installer"
DIST_DIR = DESKTOP_APP_DIR / "dist"
BUILD_DIR = DESKTOP_APP_DIR / "build"
OUTPUT_DIR = PROJECT_ROOT / "Output"

if str(DESKTOP_APP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_APP_DIR))

from config import (
    ALPR_DETECTOR_MODEL,
    ALPR_OCR_MODEL,
    APP_NAME,
    APP_VERSION,
    BRAND_ASSETS,
    COMPANY_NAME,
    PORTAL_URL,
)


def step_1_prepare_icon_and_assets() -> Path:
    """Gera nexus_vision.ico multi-resolução (256..16px) via Pillow e copia logos para assets/."""
    print("\n[1/5] Gerando ícone multi-resolução .ico e preparando assets internos...")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Identifica a melhor imagem PNG de origem na pasta de logos da raiz
    source_png: Optional[Path] = None
    logo_mark = BRAND_ASSETS.logo_mark
    logo_full = BRAND_ASSETS.logo_full

    for candidate in (logo_mark, logo_full, BRAND_ASSETS.app_icon):
        if candidate and candidate.exists() and candidate.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}:
            source_png = candidate
            break

    ico_path = ASSETS_DIR / "nexus_vision.ico"
    if source_png is not None:
        raw_img = Image.open(source_png).convert("RGBA")
        # Remove margens transparentes excessivas para o símbolo ficar grande e nítido
        bbox = raw_img.getbbox()
        if bbox:
            raw_img = raw_img.crop(bbox)

        # Cria ícone moderno Windows 11 com fundo sólido arredondado + borda ciano
        # (garante alta visibilidade sobre qualquer papel de parede escuro ou texturizado)
        canvas_size = 512
        badge = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)
        margin = 14
        radius = 104
        # Fundo claro elegante (#F1F5F9) com borda ciano corporativa (#06B6D4)
        draw.rounded_rectangle(
            (margin, margin, canvas_size - margin, canvas_size - margin),
            radius=radius,
            fill=(241, 245, 249, 255),
            outline=(6, 182, 212, 255),
            width=18,
        )

        # Redimensiona o símbolo ocupando ~76% do interior do ícone
        inner_max = int(canvas_size * 0.74)
        raw_img.thumbnail((inner_max, inner_max), Image.Resampling.LANCZOS)
        offset_x = (canvas_size - raw_img.width) // 2
        offset_y = (canvas_size - raw_img.height) // 2
        badge.paste(raw_img, (offset_x, offset_y), raw_img)

        sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        badge.save(ico_path, format="ICO", sizes=sizes)
        print(f"  -> Ícone alto-contraste gerado: {ico_path} (origem: {source_png.name})")
    elif BRAND_ASSETS.app_icon and BRAND_ASSETS.app_icon.exists():
        shutil.copy2(BRAND_ASSETS.app_icon, ico_path)
        print(f"  -> Ícone copiado: {ico_path}")
    else:
        raise FileNotFoundError("Nenhuma logo encontrada na raiz do projeto para gerar o ícone .ico.")

    if logo_mark and logo_mark.exists():
        dst_mark = ASSETS_DIR / "logo_mark.png"
        if logo_mark.resolve() != dst_mark.resolve():
            shutil.copy2(logo_mark, dst_mark)
    if logo_full and logo_full.exists():
        dst_full = ASSETS_DIR / "logo_full.png"
        if logo_full.resolve() != dst_full.resolve():
            shutil.copy2(logo_full, dst_full)

    return ico_path


def step_2_ensure_offline_onnx_models() -> None:
    """Garante que os modelos ONNX leves estejam em desktop-app/models/ antes do build."""
    print("\n[2/5] Verificando modelos ONNX offline em desktop-app/models/...")
    det_dir = MODELS_DIR / "detector"
    ocr_dir = MODELS_DIR / "ocr"
    det_dir.mkdir(parents=True, exist_ok=True)
    ocr_dir.mkdir(parents=True, exist_ok=True)

    existing_onnx = list(MODELS_DIR.rglob("*.onnx"))
    if len(existing_onnx) >= 2:
        for f in existing_onnx:
            print(f"  -> Modelo pronto: {f.relative_to(MODELS_DIR)} ({f.stat().st_size / 1_048_576:.2f} MB)")
        return

    print("  -> Baixando/populando cache ONNX local para embutimento offline...")
    import fast_plate_ocr.inference.hub as ocr_hub
    import open_image_models.detection.core.hub as det_hub
    from fast_alpr import ALPR

    det_hub.MODEL_CACHE_DIR = det_dir
    ocr_hub.MODEL_CACHE_DIR = ocr_dir
    ALPR(
        detector_model=ALPR_DETECTOR_MODEL,
        detector_providers=["CPUExecutionProvider"],
        ocr_model=ALPR_OCR_MODEL,
        ocr_device="cpu",
        ocr_providers=["CPUExecutionProvider"],
    )
    for f in MODELS_DIR.rglob("*.onnx"):
        print(f"  -> Modelo pronto: {f.relative_to(MODELS_DIR)} ({f.stat().st_size / 1_048_576:.2f} MB)")


def step_3_build_pyinstaller(ico_path: Path) -> Path:
    """Empacota o aplicativo Windows standalone (--onedir --noconsole)."""
    print("\n[3/5] Compilando executável Windows via PyInstaller (--onedir --noconsole)...")

    # Limpa build anterior para evitar lixo de versões antigas
    for folder in (DIST_DIR / "NexusVision", BUILD_DIR / "NexusVision"):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noconsole",
        "--name",
        "NexusVision",
        "--icon",
        str(ico_path),
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(DESKTOP_APP_DIR),
        # Assets internos + modelos ONNX offline embutidos
        "--add-data",
        f"{ASSETS_DIR}{sep}assets",
        "--add-data",
        f"{MODELS_DIR}{sep}models",
        # Coleta garantida de DLLs ONNX Runtime e metadados ALPR
        "--collect-binaries",
        "onnxruntime",
        "--collect-data",
        "onnxruntime",
        "--collect-data",
        "fast_alpr",
        "--collect-data",
        "fast_plate_ocr",
        "--collect-data",
        "open_image_models",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "mss",
        "--hidden-import",
        "PIL",
        "--hidden-import",
        "yaml",
        "--hidden-import",
        "onnxruntime",
        # Exclui módulos Qt gigantes não utilizados (reduz >150 MB do instalador!)
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "PySide6.QtWebEngineQuick",
        "--exclude-module",
        "PySide6.Qt3DCore",
        "--exclude-module",
        "PySide6.Qt3DRender",
        "--exclude-module",
        "PySide6.Qt3DInput",
        "--exclude-module",
        "PySide6.Qt3DExtras",
        "--exclude-module",
        "PySide6.QtQuick",
        "--exclude-module",
        "PySide6.QtQuick3D",
        "--exclude-module",
        "PySide6.QtQml",
        "--exclude-module",
        "PySide6.QtMultimedia",
        "--exclude-module",
        "PySide6.QtMultimediaWidgets",
        "--exclude-module",
        "PySide6.QtPdf",
        "--exclude-module",
        "PySide6.QtPdfWidgets",
        "--exclude-module",
        "PySide6.QtDesigner",
        "--exclude-module",
        "PySide6.QtCharts",
        "--exclude-module",
        "PySide6.QtDataVisualization",
        "--exclude-module",
        "PySide6.QtGraphs",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "matplotlib",
        "--exclude-module",
        "pytest",
        str(DESKTOP_APP_DIR / "main.py"),
    ]

    subprocess.run(cmd, check=True, cwd=str(DESKTOP_APP_DIR))
    exe_path = DIST_DIR / "NexusVision" / "NexusVision.exe"
    if not exe_path.exists():
        raise RuntimeError(f"PyInstaller finalizou sem gerar {exe_path}")
    print(f"  -> Executável standalone gerado: {exe_path}")
    return exe_path


def step_4_generate_inno_script(ico_path: Path) -> Path:
    """Gera o script completo do Inno Setup em Português do Brasil."""
    print("\n[4/5] Gerando script Inno Setup (desktop-app/installer/NexusVision.iss)...")
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    iss_path = INSTALLER_DIR / "NexusVision.iss"
    dist_src = str((DIST_DIR / "NexusVision").resolve())
    out_dir_str = str(OUTPUT_DIR.resolve())
    ico_str = str(ico_path.resolve())
    setup_base_name = f"NexusVision_Setup_v{APP_VERSION}"

    iss_content = f'''\
; =============================================================================
; Instalador Windows — {APP_NAME} ({COMPANY_NAME})
; Gerado automaticamente por desktop-app/build_installer.py
; =============================================================================

#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{COMPANY_NAME}"
#define MyAppURL "{PORTAL_URL}"
#define MyAppExeName "NexusVision.exe"

[Setup]
AppId={{{{7B4F91D2-9C35-4D8E-A123-8E55F4A0E911}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppVerName={{#MyAppName}} v{{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
AppPublisherURL={{#MyAppURL}}
AppSupportURL={{#MyAppURL}}
AppUpdatesURL={{#MyAppURL}}
DefaultDirName={{autopf}}\\NexuSistemas\\{{#MyAppName}}
DefaultGroupName=NexuSistemas\\{{#MyAppName}}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={out_dir_str}
OutputBaseFilename={setup_base_name}
SetupIconFile={ico_str}
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho (Nexus Vision)"; GroupDescription: "Atalhos e Inicialização:"
Name: "autostart"; Description: "Iniciar o Nexus Vision automaticamente com o Windows (Recomendado para Portaria)"; GroupDescription: "Atalhos e Inicialização:"

[Files]
Source: "{dist_src}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\_internal\\assets\\nexus_vision.ico"
Name: "{{group}}\\Desinstalar {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\_internal\\assets\\nexus_vision.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueType: string; ValueName: "NexusVision"; ValueData: """{{app}}\\{{#MyAppExeName}}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "Iniciar o {{#MyAppName}} agora"; Flags: nowait postinstall skipifsilent
'''

    iss_path.write_text(iss_content, encoding="utf-8-sig")
    print(f"  -> Script Inno Setup salvo: {iss_path}")
    return iss_path


def find_iscc_executable() -> Optional[Path]:
    """Procura o compilador ISCC.exe do Inno Setup no Windows."""
    from_path = shutil.which("ISCC.exe") or shutil.which("iscc")
    if from_path:
        return Path(from_path)

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def step_5_compile_installer(iss_path: Path) -> Optional[Path]:
    """Executa ISCC.exe para gerar Output/NexusVision_Setup_v1.0.0.exe."""
    print("\n[5/5] Compilando instalador final via Inno Setup (ISCC.exe)...")
    iscc = find_iscc_executable()
    if iscc is None:
        print("  [AVISO] ISCC.exe não encontrado. Instale via: winget install JRSoftware.InnoSetup")
        print(f"          Depois execute: ISCC.exe \"{iss_path}\"")
        return None

    print(f"  -> Compilador encontrado: {iscc}")
    subprocess.run([str(iscc), str(iss_path)], check=True)
    final_exe = OUTPUT_DIR / f"NexusVision_Setup_v{APP_VERSION}.exe"
    if final_exe.exists():
        size_mb = final_exe.stat().st_size / 1_048_576
        print(f"\n[SUCESSO] Instalador pronto: {final_exe} ({size_mb:.1f} MB)")
        return final_exe
    return None


def main() -> int:
    print(f"=== BUILD PRODUÇÃO: {APP_NAME} v{APP_VERSION} ({COMPANY_NAME}) ===")
    ico_path = step_1_prepare_icon_and_assets()
    step_2_ensure_offline_onnx_models()
    step_3_build_pyinstaller(ico_path)
    iss_path = step_4_generate_inno_script(ico_path)
    step_5_compile_installer(iss_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
