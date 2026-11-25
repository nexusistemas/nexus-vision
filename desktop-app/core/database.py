"""
Banco de Dados Local Offline-First (SQLite em modo WAL) do Nexus Vision.
Gerencia câmeras ROI, cadastro de moradores/veículos, histórico de acessos e licença.
"""

from __future__ import annotations

import csv
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from config import (
    ACCESS_STATUS_BLOQUEADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_LIBERADO_MORADOR,
    ACCESS_STATUS_LIBERADO_VISITANTE,
    ACCESS_STATUS_NAO_CADASTRADO,
    DB_PATH,
    DEFAULT_MOTION_SENSITIVITY,
    VEHICLE_PROFILES,
)


def normalize_plate(plate: str) -> str:
    """Normaliza a placa removendo espaços, hífens e caracteres inválidos."""
    if not plate:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", plate.strip().upper())
    return cleaned[:7]


def format_plate_display(plate: str) -> str:
    """Formata placa para leitura humana (ABC-1234 ou ABC1D23)."""
    p = normalize_plate(plate)
    if len(p) == 7 and p[4].isdigit():
        return f"{p[:3]}-{p[3:]}"
    return p


class DatabaseManager:
    """Gerenciador SQLite thread-safe em modo WAL para operação contínua 24h."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=15.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._configure_pragmas()
        self._initialize_schema()

    def _configure_pragmas(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode = WAL;")
            cur.execute("PRAGMA synchronous = NORMAL;")
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.execute("PRAGMA busy_timeout = 5000;")
            cur.execute("PRAGMA temp_store = MEMORY;")
            self._conn.commit()

    def _initialize_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS cameras_roi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE,
                    monitor_index INTEGER NOT NULL DEFAULT 0,
                    top INTEGER NOT NULL,
                    left INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sensibilidade_movimento INTEGER NOT NULL DEFAULT 35,
                    ativo INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS veiculos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    placa TEXT NOT NULL UNIQUE,
                    nome_responsavel TEXT NOT NULL,
                    unidade_bloco TEXT NOT NULL DEFAULT '',
                    modelo_cor TEXT NOT NULL DEFAULT '',
                    perfil TEXT NOT NULL DEFAULT 'MORADOR'
                        CHECK (perfil IN ('MORADOR', 'VISITANTE', 'BLOQUEADO')),
                    validade_ate TEXT DEFAULT NULL,
                    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_veiculos_placa ON veiculos(placa);
                CREATE INDEX IF NOT EXISTS idx_veiculos_perfil ON veiculos(perfil);

                CREATE TABLE IF NOT EXISTS historico_acessos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    placa TEXT NOT NULL,
                    veiculo_id INTEGER DEFAULT NULL,
                    status_acesso TEXT NOT NULL,
                    camera_nome TEXT NOT NULL DEFAULT 'Câmera Portaria',
                    imagem_path TEXT DEFAULT NULL,
                    data_hora TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (veiculo_id) REFERENCES veiculos(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_historico_data_hora ON historico_acessos(data_hora DESC);
                CREATE INDEX IF NOT EXISTS idx_historico_placa ON historico_acessos(placa);

                CREATE TABLE IF NOT EXISTS config_licenca (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    chave_licenca TEXT NOT NULL DEFAULT '',
                    hwid TEXT NOT NULL DEFAULT '',
                    token_assinado TEXT DEFAULT NULL,
                    ultimo_timestamp TEXT DEFAULT NULL,
                    status TEXT NOT NULL DEFAULT 'NAO_ATIVADA'
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def get_journal_mode(self) -> str:
        with self._lock:
            row = self._conn.execute("PRAGMA journal_mode;").fetchone()
            return str(row[0]).upper() if row else "UNKNOWN"

    # =========================================================================
    # 1. CÂMERAS ROI (cameras_roi)
    # =========================================================================

    def upsert_camera_roi(
        self,
        nome: str,
        monitor_index: int,
        top: int,
        left: int,
        width: int,
        height: int,
        sensibilidade_movimento: int = DEFAULT_MOTION_SENSITIVITY,
        ativo: int = 1,
    ) -> dict[str, Any]:
        nome_clean = nome.strip() or "Câmera Principal"
        sens = max(1, min(100, int(sensibilidade_movimento)))
        with self._lock:
            if ativo:
                self._conn.execute("UPDATE cameras_roi SET ativo = 0;")
            self._conn.execute(
                """
                INSERT INTO cameras_roi (
                    nome, monitor_index, top, left, width, height, sensibilidade_movimento, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nome) DO UPDATE SET
                    monitor_index = excluded.monitor_index,
                    top = excluded.top,
                    left = excluded.left,
                    width = excluded.width,
                    height = excluded.height,
                    sensibilidade_movimento = excluded.sensibilidade_movimento,
                    ativo = excluded.ativo;
                """,
                (
                    nome_clean,
                    int(monitor_index),
                    int(top),
                    int(left),
                    int(width),
                    int(height),
                    sens,
                    1 if ativo else 0,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM cameras_roi WHERE nome = ?;", (nome_clean,)
            ).fetchone()
            return dict(row)

    def list_cameras_roi(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM cameras_roi ORDER BY ativo DESC, id ASC;"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_active_camera_roi(self) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cameras_roi WHERE ativo = 1 ORDER BY id DESC LIMIT 1;"
            ).fetchone()
            if not row:
                row = self._conn.execute(
                    "SELECT * FROM cameras_roi ORDER BY id DESC LIMIT 1;"
                ).fetchone()
            return dict(row) if row else None

    def set_active_camera_roi(self, camera_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            self._conn.execute("UPDATE cameras_roi SET ativo = 0;")
            self._conn.execute(
                "UPDATE cameras_roi SET ativo = 1 WHERE id = ?;", (int(camera_id),)
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM cameras_roi WHERE id = ?;", (int(camera_id),)
            ).fetchone()
            return dict(row) if row else None

    def update_camera_sensitivity(self, camera_id: int, sensibilidade: int) -> None:
        sens = max(1, min(100, int(sensibilidade)))
        with self._lock:
            self._conn.execute(
                "UPDATE cameras_roi SET sensibilidade_movimento = ? WHERE id = ?;",
                (sens, int(camera_id)),
            )
            self._conn.commit()

    def delete_camera_roi(self, camera_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cameras_roi WHERE id = ?;", (int(camera_id),))
            self._conn.commit()

    # =========================================================================
    # 2. CADASTRO DE MORADORES / VEÍCULOS (veiculos)
    # =========================================================================

    def create_vehicle(
        self,
        placa: str,
        nome_responsavel: str,
        unidade_bloco: str = "",
        modelo_cor: str = "",
        perfil: str = "MORADOR",
        validade_ate: Optional[str] = None,
    ) -> dict[str, Any]:
        placa_norm = normalize_plate(placa)
        if len(placa_norm) < 7:
            raise ValueError("A placa deve conter 7 caracteres alfanuméricos (ex: ABC1D23 ou ABC1234).")
        nome_clean = nome_responsavel.strip()
        if not nome_clean:
            raise ValueError("O nome do responsável é obrigatório.")

        perfil_norm = perfil.strip().upper()
        if perfil_norm not in VEHICLE_PROFILES:
            raise ValueError(f"Perfil inválido: {perfil}. Use {', '.join(VEHICLE_PROFILES)}.")

        val_clean = validade_ate.strip() if validade_ate and validade_ate.strip() else None

        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO veiculos (
                    placa, nome_responsavel, unidade_bloco, modelo_cor, perfil, validade_ate
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    placa_norm,
                    nome_clean,
                    unidade_bloco.strip(),
                    modelo_cor.strip(),
                    perfil_norm,
                    val_clean,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM veiculos WHERE id = ?;", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def update_vehicle(
        self,
        vehicle_id: int,
        placa: str,
        nome_responsavel: str,
        unidade_bloco: str = "",
        modelo_cor: str = "",
        perfil: str = "MORADOR",
        validade_ate: Optional[str] = None,
    ) -> dict[str, Any]:
        placa_norm = normalize_plate(placa)
        if len(placa_norm) < 7:
            raise ValueError("A placa deve conter 7 caracteres alfanuméricos.")
        nome_clean = nome_responsavel.strip()
        if not nome_clean:
            raise ValueError("O nome do responsável é obrigatório.")

        perfil_norm = perfil.strip().upper()
        if perfil_norm not in VEHICLE_PROFILES:
            raise ValueError(f"Perfil inválido: {perfil}.")

        val_clean = validade_ate.strip() if validade_ate and validade_ate.strip() else None

        with self._lock:
            self._conn.execute(
                """
                UPDATE veiculos
                SET placa = ?,
                    nome_responsavel = ?,
                    unidade_bloco = ?,
                    modelo_cor = ?,
                    perfil = ?,
                    validade_ate = ?
                WHERE id = ?;
                """,
                (
                    placa_norm,
                    nome_clean,
                    unidade_bloco.strip(),
                    modelo_cor.strip(),
                    perfil_norm,
                    val_clean,
                    int(vehicle_id),
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM veiculos WHERE id = ?;", (int(vehicle_id),)
            ).fetchone()
            if not row:
                raise ValueError("Veículo não encontrado para atualização.")
            return dict(row)

    def delete_vehicle(self, vehicle_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM veiculos WHERE id = ?;", (int(vehicle_id),))
            self._conn.commit()

    def get_vehicle_by_id(self, vehicle_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM veiculos WHERE id = ?;", (int(vehicle_id),)
            ).fetchone()
            return dict(row) if row else None

    def get_vehicle_by_plate(self, placa: str) -> Optional[dict[str, Any]]:
        placa_norm = normalize_plate(placa)
        if not placa_norm:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM veiculos WHERE placa = ?;", (placa_norm,)
            ).fetchone()
            return dict(row) if row else None

    def search_vehicles(
        self, query: str = "", perfil: str = "TODOS"
    ) -> list[dict[str, Any]]:
        q = query.strip()
        q_plate = normalize_plate(q)
        clauses: list[str] = []
        params: list[Any] = []

        if q:
            like_q = f"%{q}%"
            if q_plate:
                clauses.append(
                    "(placa LIKE ? OR nome_responsavel LIKE ? OR unidade_bloco LIKE ? OR modelo_cor LIKE ?)"
                )
                params.extend([f"%{q_plate}%", like_q, like_q, like_q])
            else:
                clauses.append(
                    "(nome_responsavel LIKE ? OR unidade_bloco LIKE ? OR modelo_cor LIKE ?)"
                )
                params.extend([like_q, like_q, like_q])

        if perfil and perfil.upper() != "TODOS":
            clauses.append("perfil = ?")
            params.append(perfil.upper())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM veiculos {where_sql} ORDER BY criado_em DESC, id DESC;"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def count_vehicles(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM veiculos;").fetchone()
            return int(row[0]) if row else 0

    def bulk_upsert_vehicles(self, vehicles: list[dict[str, Any]]) -> dict[str, int]:
        """Insere ou atualiza em lote veículos vindos da restauração em nuvem."""
        inserted = 0
        updated = 0
        with self._lock:
            for item in vehicles:
                placa = normalize_plate(str(item.get("placa") or ""))
                nome = str(item.get("nome_responsavel") or "").strip()
                if len(placa) < 7 or not nome:
                    continue
                unidade = str(item.get("unidade_bloco") or "").strip()
                modelo = str(item.get("modelo_cor") or "").strip()
                perfil = str(item.get("perfil") or "MORADOR").strip().upper()
                if perfil not in VEHICLE_PROFILES:
                    perfil = "MORADOR"
                validade = str(item.get("validade_ate") or "").strip() or None

                existing = self._conn.execute(
                    "SELECT id FROM veiculos WHERE placa = ?;", (placa,)
                ).fetchone()
                if existing:
                    self._conn.execute(
                        """
                        UPDATE veiculos
                        SET nome_responsavel = ?, unidade_bloco = ?, modelo_cor = ?,
                            perfil = ?, validade_ate = ?
                        WHERE id = ?;
                        """,
                        (nome, unidade, modelo, perfil, validade, existing["id"]),
                    )
                    updated += 1
                else:
                    self._conn.execute(
                        """
                        INSERT INTO veiculos (
                            placa, nome_responsavel, unidade_bloco, modelo_cor, perfil, validade_ate
                        )
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (placa, nome, unidade, modelo, perfil, validade),
                    )
                    inserted += 1
            self._conn.commit()
        return {"inserted": inserted, "updated": updated}

    def evaluate_plate_access(self, placa: str) -> tuple[str, Optional[dict[str, Any]]]:
        """
        Avalia uma placa contra o banco local offline-first e retorna:
        (status_acesso, veiculo_dict | None).
        """
        vehicle = self.get_vehicle_by_plate(placa)
        if not vehicle:
            return ACCESS_STATUS_NAO_CADASTRADO, None

        perfil = vehicle["perfil"]
        if perfil == "BLOQUEADO":
            return ACCESS_STATUS_BLOQUEADO, vehicle

        # Verifica validade caso preenchida (YYYY-MM-DD ou DD/MM/YYYY)
        validade = vehicle.get("validade_ate")
        if validade:
            parsed_date = _parse_date_flexible(validade)
            if parsed_date and parsed_date < date.today():
                return ACCESS_STATUS_EXPIRADO, vehicle

        if perfil == "VISITANTE":
            return ACCESS_STATUS_LIBERADO_VISITANTE, vehicle
        return ACCESS_STATUS_LIBERADO_MORADOR, vehicle

    # =========================================================================
    # IMPORTAÇÃO / EXPORTAÇÃO CSV DE MORADORES E VEÍCULOS
    # =========================================================================

    def import_vehicles_csv(self, csv_path: str | Path) -> dict[str, Any]:
        """
        Importa veículos de um arquivo CSV (UTF-8 / UTF-8-SIG / Latin-1, delimitador ',' ou ';').
        Faz upsert por placa normalizada.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo CSV não encontrado: {path}")

        raw_text = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                raw_text = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if raw_text is None:
            raise ValueError("Não foi possível decodificar o arquivo CSV.")

        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        if not lines:
            return {"inserted": 0, "updated": 0, "skipped": 0, "errors": ["Arquivo CSV vazio."]}

        delimiter = ";" if lines[0].count(";") >= lines[0].count(",") else ","
        reader = csv.DictReader(lines, delimiter=delimiter)

        inserted = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        def _get_field(row_norm: dict[str, str], aliases: tuple[str, ...]) -> str:
            for alias in aliases:
                if alias in row_norm and row_norm[alias] is not None:
                    val = row_norm[alias].strip()
                    if val:
                        return val
            return ""

        with self._lock:
            for idx, raw_row in enumerate(reader, start=2):
                row_norm = {
                    (k or "").strip().lower().replace(" ", "_"): (v or "").strip()
                    for k, v in raw_row.items()
                }
                placa_raw = _get_field(row_norm, ("placa", "plate", "placa_veiculo"))
                placa = normalize_plate(placa_raw)
                nome = _get_field(
                    row_norm,
                    ("nome_responsavel", "nome", "responsavel", "morador", "proprietario", "condomino"),
                )
                unidade = _get_field(
                    row_norm,
                    ("unidade_bloco", "unidade", "apartamento", "apto", "casa", "bloco", "lote"),
                )
                modelo = _get_field(
                    row_norm,
                    ("modelo_cor", "modelo", "veiculo", "carro", "marca_modelo"),
                )
                perfil_raw = _get_field(row_norm, ("perfil", "tipo", "categoria", "status")).upper()
                validade = _get_field(row_norm, ("validade_ate", "validade", "expira_em")) or None

                if len(placa) < 7 or not nome:
                    skipped += 1
                    errors.append(f"Linha {idx}: placa ('{placa_raw}') ou nome inválido.")
                    continue

                if perfil_raw not in VEHICLE_PROFILES:
                    if "VIS" in perfil_raw:
                        perfil_raw = "VISITANTE"
                    elif "BLOQ" in perfil_raw or "RESTR" in perfil_raw:
                        perfil_raw = "BLOQUEADO"
                    else:
                        perfil_raw = "MORADOR"

                existing = self._conn.execute(
                    "SELECT id FROM veiculos WHERE placa = ?;", (placa,)
                ).fetchone()

                if existing:
                    self._conn.execute(
                        """
                        UPDATE veiculos
                        SET nome_responsavel = ?, unidade_bloco = ?, modelo_cor = ?,
                            perfil = ?, validade_ate = ?
                        WHERE id = ?;
                        """,
                        (nome, unidade, modelo, perfil_raw, validade, existing["id"]),
                    )
                    updated += 1
                else:
                    self._conn.execute(
                        """
                        INSERT INTO veiculos (
                            placa, nome_responsavel, unidade_bloco, modelo_cor, perfil, validade_ate
                        )
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (placa, nome, unidade, modelo, perfil_raw, validade),
                    )
                    inserted += 1

            self._conn.commit()

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": errors[:20],
        }

    def export_vehicles_csv(self, csv_path: str | Path) -> int:
        """Exporta todos os veículos cadastrados em CSV UTF-8 com BOM (compatível com Excel)."""
        vehicles = self.search_vehicles()
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = [
            "placa",
            "nome_responsavel",
            "unidade_bloco",
            "modelo_cor",
            "perfil",
            "validade_ate",
            "criado_em",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=";")
            writer.writeheader()
            for v in vehicles:
                writer.writerow({h: v.get(h) or "" for h in headers})
        return len(vehicles)

    # =========================================================================
    # 3. HISTÓRICO DE ACESSOS (historico_acessos)
    # =========================================================================

    def log_access(
        self,
        placa: str,
        status_acesso: str,
        camera_nome: str = "Câmera Principal",
        veiculo_id: Optional[int] = None,
        imagem_path: Optional[str] = None,
        data_hora: Optional[str] = None,
    ) -> dict[str, Any]:
        placa_norm = normalize_plate(placa) or placa.strip().upper()
        ts = data_hora or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO historico_acessos (
                    placa, veiculo_id, status_acesso, camera_nome, imagem_path, data_hora
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (placa_norm, veiculo_id, status_acesso, camera_nome, imagem_path, ts),
            )
            self._conn.commit()
            row = self._conn.execute(
                """
                SELECT h.*, v.nome_responsavel, v.unidade_bloco, v.modelo_cor, v.perfil
                FROM historico_acessos h
                LEFT JOIN veiculos v ON v.id = h.veiculo_id
                WHERE h.id = ?;
                """,
                (cur.lastrowid,),
            ).fetchone()
            return dict(row)

    def list_access_history(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        plate_query: str = "",
        status_filter: str = "TODOS",
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if date_from:
            clauses.append("h.data_hora >= ?")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            clauses.append("h.data_hora <= ?")
            params.append(f"{date_to} 23:59:59")
        if plate_query.strip():
            pq = normalize_plate(plate_query) or plate_query.strip().upper()
            clauses.append("(h.placa LIKE ? OR COALESCE(v.nome_responsavel, '') LIKE ? OR COALESCE(v.unidade_bloco, '') LIKE ?)")
            params.extend([f"%{pq}%", f"%{plate_query.strip()}%", f"%{plate_query.strip()}%"])
        if status_filter and status_filter != "TODOS":
            clauses.append("h.status_acesso = ?")
            params.append(status_filter)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT h.*, v.nome_responsavel, v.unidade_bloco, v.modelo_cor, v.perfil
            FROM historico_acessos h
            LEFT JOIN veiculos v ON v.id = h.veiculo_id
            {where_sql}
            ORDER BY h.data_hora DESC, h.id DESC
            LIMIT ?;
        """
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_today_stats(self) -> dict[str, int]:
        today_prefix = date.today().strftime("%Y-%m-%d")
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT status_acesso, COUNT(*) AS total
                FROM historico_acessos
                WHERE data_hora LIKE ?
                GROUP BY status_acesso;
                """,
                (f"{today_prefix}%",),
            ).fetchall()
            counts = {r["status_acesso"]: int(r["total"]) for r in rows}
            total = sum(counts.values())
            liberados = counts.get(ACCESS_STATUS_LIBERADO_MORADOR, 0) + counts.get(
                ACCESS_STATUS_LIBERADO_VISITANTE, 0
            )
            alertas = (
                counts.get(ACCESS_STATUS_NAO_CADASTRADO, 0)
                + counts.get(ACCESS_STATUS_BLOQUEADO, 0)
                + counts.get(ACCESS_STATUS_EXPIRADO, 0)
            )
            return {
                "total_hoje": total,
                "liberados_hoje": liberados,
                "alertas_hoje": alertas,
            }

    # =========================================================================
    # 4. LICENCIAMENTO LOCAL (config_licenca)
    # =========================================================================

    def get_license_config(self) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM config_licenca WHERE id = 1;"
            ).fetchone()
            return dict(row) if row else None

    def save_license_config(
        self,
        chave_licenca: str,
        hwid: str,
        token_assinado: Optional[str] = None,
        status: str = "AGUARDANDO_SINCRONIZACAO_ETAPA3",
    ) -> dict[str, Any]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO config_licenca (
                    id, chave_licenca, hwid, token_assinado, ultimo_timestamp, status
                )
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    chave_licenca = excluded.chave_licenca,
                    hwid = excluded.hwid,
                    token_assinado = excluded.token_assinado,
                    ultimo_timestamp = excluded.ultimo_timestamp,
                    status = excluded.status;
                """,
                (chave_licenca.strip().upper(), hwid.strip().upper(), token_assinado, ts, status),
            )
            self._conn.commit()
            return self.get_license_config() or {}


def _parse_date_flexible(raw: str) -> Optional[date]:
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
