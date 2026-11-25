"""
Gerenciador Local Anti-Fraude de Licenças — Nexus Vision (NexuSistemas Tecnologia).
Recursos:
- Validação remota via RPC SECURITY DEFINER `validar_licenca_nexus` no Supabase.
- Cache local ofuscado + assinado com HMAC-SHA256 vinculado ao HWID físico.
- Tolerância offline de 72 horas (`offline_grace_until`) caso a internet da portaria caia.
- Proteção Anti-Clock Tampering (`ultimo_timestamp_visto`): bloqueia se o relógio do Windows for atrasado.
- Heartbeat automático em background a cada 30 minutos (e na inicialização).
- Modo DEMO_LOCAL automático apenas quando SUPABASE_URL / SUPABASE_ANON_KEY ainda não estão configuradas.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

from config import APP_VERSION, DATA_DIR
from core.database import DatabaseManager
from core.hwid import MachineHardwareInfo, collect_machine_hardware_info
from supabase_config import (
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    is_supabase_configured,
)

LICENSE_KEY_REGEX = re.compile(r"^NV-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
OFFLINE_GRACE_SECONDS: int = 72 * 3600  # 72 horas de contingência offline
CLOCK_ROLLBACK_TOLERANCE_SEC: int = 120  # 2 min de folga para ajustes NTP
HEARTBEAT_INTERVAL_SECONDS: int = 30 * 60  # 30 minutos

_APP_INTEGRITY_PEPPER = b"NEXUS_VISION_ANTI_TAMPER_2026::NEXUSISTEMAS_V1"


@dataclass
class LicenseStatus:
    """Estado consolidado de licenciamento consumido pela UI e motor ALPR."""

    allowed: bool
    mode: str  # DEMO_LOCAL, ONLINE_VALID, OFFLINE_GRACE, BLOCKED, EXPIRED, UNLICENSED, HWID_MISMATCH, CLOCK_TAMPERED
    code: str
    message: str
    condominio_nome: str = ""
    plano: str = ""
    validade_ate: Optional[str] = None
    offline_grace_until: Optional[str] = None
    last_online_check: Optional[str] = None
    is_demo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _derive_machine_key(hwid: str) -> bytes:
    return hashlib.sha256(_APP_INTEGRITY_PEPPER + hwid.encode("utf-8")).digest()


def _xor_stream(data: bytes, key: bytes) -> bytes:
    """Ofuscação simétrica determinística baseada em SHA-256 counter-mode."""
    out = bytearray(len(data))
    counter = 0
    pos = 0
    while pos < len(data):
        block = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        chunk = data[pos : pos + len(block)]
        for i, b in enumerate(chunk):
            out[pos + i] = b ^ block[i]
        pos += len(chunk)
        counter += 1
    return bytes(out)


def _parse_iso_to_epoch(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        cleaned = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _epoch_to_br_str(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return None


class LicenseManager:
    """Motor local de validação, cache assinado e proteção anti-fraude."""

    def __init__(
        self,
        db: DatabaseManager,
        hw_info: Optional[MachineHardwareInfo] = None,
        cache_path: Optional[Path] = None,
    ) -> None:
        self.db = db
        self.hw_info = hw_info or collect_machine_hardware_info()
        self.cache_path = cache_path or (DATA_DIR / "license_cache.dat")
        self._lock = threading.RLock()
        self._current_status: LicenseStatus = LicenseStatus(
            allowed=True,
            mode="CHECKING",
            code="",
            message="Verificando licença...",
        )

    @property
    def hwid(self) -> str:
        return self.hw_info.hwid_sha256

    @property
    def current_status(self) -> LicenseStatus:
        with self._lock:
            return self._current_status

    def is_alpr_allowed(self) -> bool:
        with self._lock:
            return self._current_status.allowed

    # =========================================================================
    # CACHE LOCAL CRIPTOGRAFADO + ASSINATURA HMAC-SHA256
    # =========================================================================

    def _sign_and_save_cache(self, payload: dict[str, Any]) -> str:
        """Grava payload ofuscado + HMAC-SHA256 em disco e retorna token base64."""
        key = _derive_machine_key(self.hwid)
        raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        cipher = _xor_stream(raw_json, key)
        mac = hmac.new(key, cipher, hashlib.sha256).hexdigest()
        envelope = json.dumps(
            {
                "v": 1,
                "p": base64.b64encode(cipher).decode("ascii"),
                "s": mac,
            },
            separators=(",", ":"),
        )
        encoded = base64.b64encode(envelope.encode("utf-8")).decode("ascii")
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(encoded, encoding="utf-8")
        return encoded

    def _load_verified_cache(self) -> Optional[dict[str, Any]]:
        """Lê e valida integridade HMAC do cache local (ou fallback do token no SQLite)."""
        raw_token: Optional[str] = None
        if self.cache_path.exists():
            try:
                raw_token = self.cache_path.read_text(encoding="utf-8").strip()
            except OSError:
                raw_token = None

        if not raw_token:
            cfg = self.db.get_license_config()
            if cfg and cfg.get("token_assinado"):
                raw_token = str(cfg["token_assinado"]).strip()

        if not raw_token:
            return None

        try:
            envelope = json.loads(base64.b64decode(raw_token.encode("ascii")).decode("utf-8"))
            cipher = base64.b64decode(envelope["p"].encode("ascii"))
            expected_mac = str(envelope["s"])
            key = _derive_machine_key(self.hwid)
            actual_mac = hmac.new(key, cipher, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(actual_mac, expected_mac):
                return None  # Cache adulterado ou copiado de outra máquina!
            plain = _xor_stream(cipher, key)
            data = json.loads(plain.decode("utf-8"))
            if data.get("hwid") != self.hwid:
                return None
            return data
        except Exception:
            return None

    # =========================================================================
    # CHAMADA RPC AO SUPABASE
    # =========================================================================

    def _call_supabase_rpc(self, license_code: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Invoca POST /rest/v1/rpc/validar_licenca_nexus. Retorna (json_resp, erro_rede)."""
        endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/validar_licenca_nexus"
        body = json.dumps(
            {
                "p_codigo": license_code.strip().upper(),
                "p_hwid": self.hwid,
                "p_versao": APP_VERSION,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                "User-Agent": f"NexusVision/{APP_VERSION}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                if isinstance(data, dict):
                    return data, None
                return None, "Resposta inesperada do servidor de licenciamento."
        except urllib.error.HTTPError as http_err:
            try:
                detail = http_err.read().decode("utf-8", errors="ignore")
            except Exception:
                detail = str(http_err)
            return None, f"Erro HTTP {http_err.code} ao validar licença: {detail[:160]}"
        except Exception as net_err:
            return None, f"Sem conexão com o servidor de licenças ({net_err})."

    # =========================================================================
    # FLUXO PRINCIPAL DE ATIVAÇÃO / VERIFICAÇÃO / ANTI-CLOCK TAMPERING
    # =========================================================================

    def get_saved_license_code(self) -> str:
        cfg = self.db.get_license_config()
        if cfg and cfg.get("chave_licenca"):
            return str(cfg["chave_licenca"]).strip().upper()
        cache = self._load_verified_cache()
        if cache and cache.get("codigo"):
            return str(cache["codigo"]).strip().upper()
        return ""

    def activate_and_validate(self, license_code: Optional[str] = None) -> LicenseStatus:
        """
        Valida a licença informada (ou salva localmente).
        - Se Supabase NÃO configurado -> opera em DEMO_LOCAL (mas valida formato se digitada).
        - Se Supabase configurado -> tenta RPC online; se sem internet, aplica contingência 72h
          + checagem rigorosa de Anti-Clock Tampering.
        """
        with self._lock:
            code = (license_code if license_code is not None else self.get_saved_license_code()).strip().upper()

            # 1) MODO DEMO_LOCAL (apenas antes de colar as chaves em supabase_config.py)
            if not is_supabase_configured():
                if code:
                    if not LICENSE_KEY_REGEX.match(code):
                        st = LicenseStatus(
                            allowed=True,
                            mode="DEMO_LOCAL",
                            code=code,
                            message="Formato inválido (use NV-XXXX-XXXX-XXXX). Operando em modo DEMO_LOCAL.",
                            condominio_nome="Ambiente de Demonstração Local",
                            plano="DEMO",
                            is_demo=True,
                        )
                        self._current_status = st
                        return st
                    now_ts = time.time()
                    cache_payload = {
                        "codigo": code,
                        "hwid": self.hwid,
                        "condominio_nome": "Ambiente de Demonstração Local",
                        "plano": "DEMO",
                        "status": "DEMO_LOCAL",
                        "validade_ate": None,
                        "ultimo_timestamp_visto": now_ts,
                        "offline_grace_until": now_ts + OFFLINE_GRACE_SECONDS,
                        "last_online_check": now_ts,
                    }
                    token = self._sign_and_save_cache(cache_payload)
                    self.db.save_license_config(code, self.hwid, token, "DEMO_LOCAL")

                st = LicenseStatus(
                    allowed=True,
                    mode="DEMO_LOCAL",
                    code=code,
                    message=(
                        "Modo DEMO_LOCAL ativo (Supabase ainda não configurado em supabase_config.py). "
                        "Motor IA ALPR liberado para testes locais."
                    ),
                    condominio_nome="Ambiente de Testes Local",
                    plano="DEMO",
                    is_demo=True,
                )
                self._current_status = st
                return st

            # 2) MODO PRODUÇÃO (Supabase configurado)
            if not code or not LICENSE_KEY_REGEX.match(code):
                st = LicenseStatus(
                    allowed=False,
                    mode="UNLICENSED",
                    code=code,
                    message=(
                        "Nenhuma chave válida ativada. Insira sua licença NV-XXXX-XXXX-XXXX "
                        "na aba Conta & Licença para liberar o motor IA ALPR."
                    ),
                )
                self._current_status = st
                return st

            rpc_resp, net_error = self._call_supabase_rpc(code)
            local_now = time.time()

            # 2A) Servidor respondeu online -> autoridade máxima
            if rpc_resp is not None:
                is_valid = bool(rpc_resp.get("valido", False))
                server_epoch = _parse_iso_to_epoch(rpc_resp.get("server_time")) or local_now
                validade_str = rpc_resp.get("validade_ate")
                condominio = str(rpc_resp.get("condominio_nome") or "")
                plano = str(rpc_resp.get("plano") or "")
                err_code = str(rpc_resp.get("error_code") or "")
                msg = str(rpc_resp.get("message") or "")

                if is_valid:
                    # Avança relógio monotônico de referência usando a hora oficial do servidor
                    grace_until = max(local_now, server_epoch) + OFFLINE_GRACE_SECONDS
                    cache_payload = {
                        "codigo": code,
                        "hwid": self.hwid,
                        "condominio_nome": condominio,
                        "plano": plano,
                        "status": "ATIVA",
                        "validade_ate": validade_str,
                        "ultimo_timestamp_visto": max(local_now, server_epoch),
                        "offline_grace_until": grace_until,
                        "last_online_check": server_epoch,
                    }
                    token = self._sign_and_save_cache(cache_payload)
                    self.db.save_license_config(code, self.hwid, token, "ATIVA")

                    st = LicenseStatus(
                        allowed=True,
                        mode="ONLINE_VALID",
                        code=code,
                        message=msg or "Licença ativa e validada com o servidor NexuSistemas.",
                        condominio_nome=condominio,
                        plano=plano,
                        validade_ate=validade_str,
                        offline_grace_until=_epoch_to_br_str(grace_until),
                        last_online_check=_epoch_to_br_str(server_epoch),
                    )
                    self._current_status = st
                    return st

                # Servidor recusou explicitamente (BLOQUEADA, SUSPENSA, EXPIRADA, HWID_MISMATCH, NOT_FOUND)
                blocked_mode = {
                    "HWID_MISMATCH": "HWID_MISMATCH",
                    "LICENSE_EXPIRED": "EXPIRED",
                    "LICENSE_NOT_FOUND": "UNLICENSED",
                }.get(err_code, "BLOCKED")

                # Invalida cache offline para impedir uso após bloqueio remoto no /admin!
                self._revoke_local_cache(code, blocked_mode)

                st = LicenseStatus(
                    allowed=False,
                    mode=blocked_mode,
                    code=code,
                    message=msg or "Licença bloqueada ou expirada. Contate a NexuSistemas.",
                    condominio_nome=condominio,
                    plano=plano,
                    validade_ate=validade_str,
                    last_online_check=_epoch_to_br_str(server_epoch),
                )
                self._current_status = st
                return st

            # 2B) Sem internet -> Contingência Offline 72h + Anti-Clock Tampering
            return self._evaluate_offline_cache(code, local_now, net_error or "Sem conexão.")

    def _revoke_local_cache(self, code: str, status_tag: str) -> None:
        try:
            if self.cache_path.exists():
                self.cache_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.db.save_license_config(code, self.hwid, None, status_tag)

    def _evaluate_offline_cache(
        self, code: str, local_now: float, net_error: str
    ) -> LicenseStatus:
        cache = self._load_verified_cache()
        if not cache or cache.get("codigo") != code or cache.get("status") != "ATIVA":
            st = LicenseStatus(
                allowed=False,
                mode="UNLICENSED",
                code=code,
                message=(
                    f"Não foi possível validar a licença online ({net_error}) e não há "
                    "cache assinado válido nesta máquina."
                ),
            )
            self._current_status = st
            return st

        last_seen = float(cache.get("ultimo_timestamp_visto") or 0.0)
        grace_until = float(cache.get("offline_grace_until") or 0.0)
        validade_str = cache.get("validade_ate")
        validade_epoch = _parse_iso_to_epoch(validade_str)

        # PROTEÇÃO ANTI-CLOCK TAMPERING: relógio do Windows atrasado manualmente!
        if local_now < (last_seen - CLOCK_ROLLBACK_TOLERANCE_SEC):
            st = LicenseStatus(
                allowed=False,
                mode="CLOCK_TAMPERED",
                code=code,
                message=(
                    "Inconsistência detectada no relógio do Windows (data/hora retrocedida). "
                    "Ajuste o relógio e conecte-se à internet para revalidar a licença."
                ),
                condominio_nome=str(cache.get("condominio_nome") or ""),
                plano=str(cache.get("plano") or ""),
                validade_ate=validade_str,
            )
            self._current_status = st
            return st

        # Verifica expiração da própria licença mesmo offline
        if validade_epoch is not None and local_now >= validade_epoch:
            st = LicenseStatus(
                allowed=False,
                mode="EXPIRED",
                code=code,
                message="Validade da licença expirada. Conecte-se à internet após a renovação.",
                condominio_nome=str(cache.get("condominio_nome") or ""),
                plano=str(cache.get("plano") or ""),
                validade_ate=validade_str,
            )
            self._current_status = st
            return st

        # Verifica se a janela de tolerância offline de 72h expirou
        if local_now > grace_until:
            st = LicenseStatus(
                allowed=False,
                mode="BLOCKED",
                code=code,
                message=(
                    "Tolerância offline de 72h esgotada. Restabeleça a conexão com a internet "
                    "para sincronizar a licença com a NexuSistemas."
                ),
                condominio_nome=str(cache.get("condominio_nome") or ""),
                plano=str(cache.get("plano") or ""),
                validade_ate=validade_str,
            )
            self._current_status = st
            return st

        # Contingência offline válida -> avança `ultimo_timestamp_visto` no cache assinado
        cache["ultimo_timestamp_visto"] = max(last_seen, local_now)
        token = self._sign_and_save_cache(cache)
        self.db.save_license_config(code, self.hwid, token, "OFFLINE_GRACE")

        hours_left = max(1, int((grace_until - local_now) // 3600))
        st = LicenseStatus(
            allowed=True,
            mode="OFFLINE_GRACE",
            code=code,
            message=(
                f"Operando em contingência offline segura ({hours_left}h restantes de 72h). "
                "Revalidação automática assim que a internet retornar."
            ),
            condominio_nome=str(cache.get("condominio_nome") or ""),
            plano=str(cache.get("plano") or ""),
            validade_ate=validade_str,
            offline_grace_until=_epoch_to_br_str(grace_until),
            last_online_check=_epoch_to_br_str(cache.get("last_online_check")),
        )
        self._current_status = st
        return st


class LicenseHeartbeatWorker(QThread):
    """
    Thread em background que valida a licença na inicialização e a cada 30 minutos.
    Também permite disparo sob demanda ao clicar em 'Ativar / Validar' na Aba 4.
    """

    license_updated = Signal(object)  # LicenseStatus

    def __init__(
        self,
        manager: LicenseManager,
        interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self._interval = max(30, int(interval_seconds))
        self._cond = threading.Condition()
        self._running = False
        self._pending_code: Optional[str] = None
        self._immediate_requested = False

    def trigger_validation(self, license_code: Optional[str] = None) -> None:
        with self._cond:
            self._pending_code = license_code
            self._immediate_requested = True
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        if self.isRunning():
            self.wait(3000)

    def run(self) -> None:
        with self._cond:
            self._running = True

        # Validação imediata na inicialização
        status = self.manager.activate_and_validate()
        self.license_updated.emit(status)

        while True:
            with self._cond:
                if not self._running:
                    break
                if not self._immediate_requested:
                    self._cond.wait(timeout=float(self._interval))
                if not self._running:
                    break
                code = self._pending_code if self._immediate_requested else None
                self._immediate_requested = False
                self._pending_code = None

            status = self.manager.activate_and_validate(code)
            self.license_updated.emit(status)
