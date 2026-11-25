"""
Configuração de Produção — Supabase & GitHub Releases (Nexus Vision).
Chave pública Publishable + RLS + RPC SECURITY DEFINER (validar_licenca_nexus).
"""

from __future__ import annotations

import os

# ==============================================================================
# CONFIGURAÇÃO DE PRODUÇÃO — SUPABASE (vision.nexusistemas.app.br)
# ==============================================================================
SUPABASE_URL: str = os.getenv(
    "NEXUS_SUPABASE_URL", "https://taerywvenofafxsbbmlk.supabase.co"
).strip()
SUPABASE_ANON_KEY: str = os.getenv(
    "NEXUS_SUPABASE_ANON_KEY", "sb_publishable_aYMexxpT6NvNwzlenRoCuQ_JONPq1aJ"
).strip()

# Repositório GitHub para verificação automática de atualizações (Auto-Updater)
GITHUB_REPO: str = os.getenv("NEXUS_GITHUB_REPO", "nexusistemas/nexus-vision").strip()

# Domínio oficial do portal comercial e administrativo
PORTAL_DOMAIN: str = "vision.nexusistemas.app.br"
PORTAL_URL: str = f"https://{PORTAL_DOMAIN}"


def is_supabase_configured() -> bool:
    """Retorna True somente quando URL e chave pública reais estiverem configuradas."""
    return (
        bool(SUPABASE_URL)
        and bool(SUPABASE_ANON_KEY)
        and SUPABASE_URL.startswith("https://")
        and "SEU-PROJETO" not in SUPABASE_URL.upper()
        and "SUA_ANON_KEY" not in SUPABASE_ANON_KEY.upper()
    )
