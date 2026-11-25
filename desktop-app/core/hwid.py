"""
Coleta determinística do HWID (Hardware ID) físico no Windows 10/11.
Combina:
  1. MachineGuid do Registro HKLM\\SOFTWARE\\Microsoft\\Cryptography
  2. UUID da Placa-Mãe / BIOS via PowerShell/WMI (sem abrir janela preta)
  3. Serial do Volume do Sistema (C:\\) via Win32 GetVolumeInformationW
Retorna hash SHA-256 imutável por estação.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import subprocess
import uuid
from dataclasses import dataclass
from typing import Optional

_HWID_SALT = "NEXUS_VISION_HWID_V2::NEXUSISTEMAS_PROD"


@dataclass(frozen=True)
class MachineHardwareInfo:
    hwid_sha256: str
    hwid_short: str
    machine_guid: str
    system_uuid: str
    volume_serial: str
    hostname: str
    os_summary: str


def _read_windows_machine_guid() -> Optional[str]:
    """Lê o MachineGuid nativo do Registro do Windows (não requer admin)."""
    if platform.system() != "Windows":
        return None
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            cleaned = str(value).strip()
            return cleaned if cleaned else None
    except Exception:
        return None


def _read_windows_system_uuid() -> Optional[str]:
    """Obtém o UUID da placa-mãe/BIOS via CIM/WMI sem abrir janela de console."""
    if platform.system() != "Windows":
        return None

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    commands = [
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID",
        ],
        ["wmic", "csproduct", "get", "uuid"],
    ]

    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3.5,
                creationflags=creation_flags,
            )
            if proc.returncode == 0 and proc.stdout:
                lines = [
                    line.strip()
                    for line in proc.stdout.splitlines()
                    if line.strip() and line.strip().upper() != "UUID"
                ]
                if lines:
                    candidate = lines[0]
                    if candidate and candidate not in {
                        "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
                        "00000000-0000-0000-0000-000000000000",
                    }:
                        return candidate
        except Exception:
            continue
    return None


def _read_windows_volume_serial() -> Optional[str]:
    """Lê o serial do volume do sistema (ex: C:\\) via Win32 API (zero console)."""
    if platform.system() != "Windows":
        return None
    try:
        sys_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/") + "\\"
        vol_serial = ctypes.c_uint32(0)
        max_comp = ctypes.c_uint32(0)
        fs_flags = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(sys_drive),
            None,
            0,
            ctypes.byref(vol_serial),
            ctypes.byref(max_comp),
            ctypes.byref(fs_flags),
            None,
            0,
        )
        if ok and vol_serial.value:
            return f"{vol_serial.value:08X}"
    except Exception:
        pass
    return None


def collect_machine_hardware_info() -> MachineHardwareInfo:
    """Coleta identificadores físicos do Windows e gera o HWID SHA-256."""
    machine_guid = _read_windows_machine_guid() or f"NODE-{uuid.getnode():012X}"
    system_uuid = _read_windows_system_uuid() or "UUID-UNAVAILABLE"
    volume_serial = _read_windows_volume_serial() or "VOL-UNAVAILABLE"
    hostname = platform.node() or "WORKSTATION"
    os_summary = f"{platform.system()} {platform.release()} ({platform.machine()})"

    raw_fingerprint = (
        f"{_HWID_SALT}|{machine_guid}|{system_uuid}|{volume_serial}|{platform.machine()}"
    )
    hwid_sha256 = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest().upper()
    hwid_short = "-".join(hwid_sha256[i : i + 4] for i in range(0, 16, 4))

    return MachineHardwareInfo(
        hwid_sha256=hwid_sha256,
        hwid_short=hwid_short,
        machine_guid=machine_guid,
        system_uuid=system_uuid,
        volume_serial=volume_serial,
        hostname=hostname,
        os_summary=os_summary,
    )


def get_hwid() -> str:
    """Retorna diretamente o hash SHA-256 (64 caracteres hexadecimais) do HWID."""
    return collect_machine_hardware_info().hwid_sha256
