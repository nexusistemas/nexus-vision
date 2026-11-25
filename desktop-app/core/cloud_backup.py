"""
Backup e Restauração Automática na Nuvem por Licença (Supabase RPC).
Mantém o aplicativo 100% offline-first (SQLite local), mas envia uma cópia
silenciosa dos veículos cadastrados para a nuvem vinculada à chave da portaria.
Se o PC da portaria queimar ou for formatado, basta ativar a mesma licença
no PC novo para restaurar todos os moradores automaticamente!
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

from config import APP_VERSION
from core.database import DatabaseManager
from supabase_config import (
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    is_supabase_configured,
)


def _post_supabase_rpc(rpc_name: str, payload: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not is_supabase_configured():
        return None, "Supabase não configurado (modo DEMO_LOCAL)."

    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/{rpc_name}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "User-Agent": f"NexusVision/{APP_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return (data if isinstance(data, dict) else None), None
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")[:180]
        return None, f"Erro HTTP {err.code}: {detail}"
    except Exception as exc:
        return None, f"Sem conexão para sincronizar ({exc})."


class CloudBackupWorker(QThread):
    """Thread assíncrona para backup (upload) ou restauração (download) de veículos."""

    # (sucesso, modo ['backup'|'restore'], mensagem, dados_extras)
    finished_operation = Signal(bool, str, str, dict)

    def __init__(
        self,
        mode: str,
        db: DatabaseManager,
        license_code: str,
        hwid: str,
        silent: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode  # "backup" ou "restore"
        self.db = db
        self.license_code = (license_code or "").strip().upper()
        self.hwid = (hwid or "").strip().upper()
        self.silent = silent

    def run(self) -> None:
        if not self.license_code or not self.hwid:
            self.finished_operation.emit(
                False,
                self.mode,
                "Ative uma licença válida antes de usar o backup na nuvem.",
                {"silent": self.silent},
            )
            return

        if self.mode == "backup":
            self._run_backup()
        else:
            self._run_restore()

    def _run_backup(self) -> None:
        vehicles = self.db.search_vehicles()
        compact_list = [
            {
                "placa": v["placa"],
                "nome_responsavel": v["nome_responsavel"],
                "unidade_bloco": v.get("unidade_bloco") or "",
                "modelo_cor": v.get("modelo_cor") or "",
                "perfil": v.get("perfil") or "MORADOR",
                "validade_ate": v.get("validade_ate") or "",
            }
            for v in vehicles
        ]

        resp, err = _post_supabase_rpc(
            "sincronizar_veiculos_backup",
            {
                "p_codigo": self.license_code,
                "p_hwid": self.hwid,
                "p_veiculos": compact_list,
            },
        )
        if err or not resp:
            self.finished_operation.emit(
                False, "backup", err or "Falha no backup em nuvem.", {"silent": self.silent}
            )
            return

        if not resp.get("ok"):
            self.finished_operation.emit(
                False,
                "backup",
                f"Backup recusado pelo servidor ({resp.get('error', 'ERRO')}).",
                {"silent": self.silent},
            )
            return

        total = int(resp.get("total_salvos") or 0)
        self.finished_operation.emit(
            True,
            "backup",
            f"Backup na nuvem atualizado ({total} veículo(s) protegidos).",
            {"total": total, "silent": self.silent},
        )

    def _run_restore(self) -> None:
        resp, err = _post_supabase_rpc(
            "restaurar_veiculos_backup",
            {
                "p_codigo": self.license_code,
                "p_hwid": self.hwid,
            },
        )
        if err or not resp:
            self.finished_operation.emit(
                False, "restore", err or "Falha ao restaurar backup.", {"silent": self.silent}
            )
            return

        if not resp.get("ok"):
            self.finished_operation.emit(
                False,
                "restore",
                f"Restauração recusada ({resp.get('error', 'ERRO')}).",
                {"silent": self.silent},
            )
            return

        vehicles = resp.get("veiculos") or []
        if not vehicles:
            self.finished_operation.emit(
                True,
                "restore",
                "Nenhum backup de veículos encontrado na nuvem para esta licença ainda.",
                {"inserted": 0, "updated": 0, "total": 0, "silent": self.silent},
            )
            return

        summary = self.db.bulk_upsert_vehicles(vehicles)
        condo = str(resp.get("condominio_nome") or "")
        total = len(vehicles)
        msg = (
            f"Restauração concluída ({condo}): {summary['inserted']} novo(s) e "
            f"{summary['updated']} atualizado(s) ({total} no total)."
        )
        self.finished_operation.emit(
            True,
            "restore",
            msg,
            {**summary, "total": total, "condominio_nome": condo, "silent": self.silent},
        )
