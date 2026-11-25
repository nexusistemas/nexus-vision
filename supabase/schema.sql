-- ==============================================================================
-- Nexus Vision (NexuSistemas Tecnologia) — Schema de Licenciamento Anti-Fraude
-- Executar no SQL Editor do projeto Supabase (vision.nexusistemas.app.br)
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Tabela principal de licenças comerciais
CREATE TABLE IF NOT EXISTS public.licencas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo text NOT NULL UNIQUE,
    condominio_nome text NOT NULL,
    responsavel_contato text NOT NULL DEFAULT '',
    plano text NOT NULL DEFAULT 'MENSAL'
        CHECK (plano IN ('MENSAL', 'ANUAL', 'VITALICIO')),
    status text NOT NULL DEFAULT 'ATIVA'
        CHECK (status IN ('ATIVA', 'BLOQUEADA', 'SUSPENSA')),
    hwid_vinculado text DEFAULT NULL,
    validade_ate timestamptz NOT NULL,
    ultimo_ping timestamptz DEFAULT NULL,
    ultimo_ip_info text DEFAULT NULL,
    versao_app text DEFAULT NULL,
    observacoes text DEFAULT NULL,
    criado_em timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_licencas_codigo_formato
        CHECK (codigo ~ '^NV-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$')
);

-- Índices para performance do painel /admin e métricas em tempo real
CREATE INDEX IF NOT EXISTS idx_licencas_status ON public.licencas (status);
CREATE INDEX IF NOT EXISTS idx_licencas_ultimo_ping ON public.licencas (ultimo_ping DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_licencas_validade_ate ON public.licencas (validade_ate);
CREATE INDEX IF NOT EXISTS idx_licencas_hwid ON public.licencas (hwid_vinculado) WHERE hwid_vinculado IS NOT NULL;

-- 2. Segurança: Row Level Security (RLS) rigoroso
-- Nenhum usuário anônimo (desktop ou público) pode ler/alterar a tabela diretamente.
ALTER TABLE public.licencas ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.licencas FROM anon, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.licencas TO authenticated;

DROP POLICY IF EXISTS "admin_select_licencas" ON public.licencas;
CREATE POLICY "admin_select_licencas"
    ON public.licencas
    FOR SELECT
    TO authenticated
    USING ((SELECT auth.role()) = 'authenticated');

DROP POLICY IF EXISTS "admin_insert_licencas" ON public.licencas;
CREATE POLICY "admin_insert_licencas"
    ON public.licencas
    FOR INSERT
    TO authenticated
    WITH CHECK ((SELECT auth.role()) = 'authenticated');

DROP POLICY IF EXISTS "admin_update_licencas" ON public.licencas;
CREATE POLICY "admin_update_licencas"
    ON public.licencas
    FOR UPDATE
    TO authenticated
    USING ((SELECT auth.role()) = 'authenticated')
    WITH CHECK ((SELECT auth.role()) = 'authenticated');

DROP POLICY IF EXISTS "admin_delete_licencas" ON public.licencas;
CREATE POLICY "admin_delete_licencas"
    ON public.licencas
    FOR DELETE
    TO authenticated
    USING ((SELECT auth.role()) = 'authenticated');

-- 3. Função RPC segura SECURITY DEFINER chamada pelo aplicativo Desktop (anon key)
CREATE OR REPLACE FUNCTION public.validar_licenca_nexus(
    p_codigo text,
    p_hwid text,
    p_versao text DEFAULT '1.0.0'
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_codigo text := upper(trim(coalesce(p_codigo, '')));
    v_hwid text := upper(trim(coalesce(p_hwid, '')));
    v_versao text := left(trim(coalesce(p_versao, '1.0.0')), 32);
    v_now timestamptz := now();
    v_lic public.licencas%ROWTYPE;
    v_headers jsonb;
    v_ip text := NULL;
BEGIN
    IF v_codigo = '' OR v_hwid = '' THEN
        RETURN jsonb_build_object(
            'valido', false,
            'error_code', 'INVALID_PARAMS',
            'message', 'Código de licença e HWID são obrigatórios.',
            'server_time', v_now
        );
    END IF;

    -- Bloqueio de linha (FOR UPDATE) evita corrida no primeiro vínculo de HWID
    SELECT *
    INTO v_lic
    FROM public.licencas
    WHERE codigo = v_codigo
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'valido', false,
            'error_code', 'LICENSE_NOT_FOUND',
            'message', 'Chave de licença não encontrada. Verifique o código informado.',
            'server_time', v_now
        );
    END IF;

    IF v_lic.status <> 'ATIVA' THEN
        RETURN jsonb_build_object(
            'valido', false,
            'error_code', CASE WHEN v_lic.status = 'SUSPENSA' THEN 'LICENSE_SUSPENDED' ELSE 'LICENSE_BLOCKED' END,
            'message', CASE
                WHEN v_lic.status = 'SUSPENSA' THEN 'Licença suspensa temporariamente. Entre em contato com a NexuSistemas.'
                ELSE 'Licença bloqueada pelo administrador. Regularize seu acesso com a NexuSistemas.'
            END,
            'status', v_lic.status,
            'condominio_nome', v_lic.condominio_nome,
            'validade_ate', v_lic.validade_ate,
            'server_time', v_now
        );
    END IF;

    IF v_lic.validade_ate <= v_now THEN
        RETURN jsonb_build_object(
            'valido', false,
            'error_code', 'LICENSE_EXPIRED',
            'message', 'Sua licença expirou. Renove com a NexuSistemas Tecnologia para retomar a leitura automática.',
            'status', 'EXPIRADA',
            'condominio_nome', v_lic.condominio_nome,
            'validade_ate', v_lic.validade_ate,
            'server_time', v_now
        );
    END IF;

    -- Extrai IP de origem dos headers HTTP do PostgREST (se disponível)
    BEGIN
        v_headers := current_setting('request.headers', true)::jsonb;
        v_ip := coalesce(
            v_headers ->> 'cf-connecting-ip',
            split_part(v_headers ->> 'x-forwarded-for', ',', 1),
            v_headers ->> 'x-real-ip'
        );
        v_ip := nullif(trim(coalesce(v_ip, '')), '');
    EXCEPTION WHEN OTHERS THEN
        v_ip := NULL;
    END;

    -- Node-Locked: vincula automaticamente no primeiro uso ou valida HWID existente
    IF v_lic.hwid_vinculado IS NULL OR trim(v_lic.hwid_vinculado) = '' THEN
        UPDATE public.licencas
        SET hwid_vinculado = v_hwid,
            ultimo_ping = v_now,
            ultimo_ip_info = coalesce(v_ip, ultimo_ip_info),
            versao_app = v_versao
        WHERE id = v_lic.id;
        v_lic.hwid_vinculado := v_hwid;
    ELSIF upper(trim(v_lic.hwid_vinculado)) <> v_hwid THEN
        RETURN jsonb_build_object(
            'valido', false,
            'error_code', 'HWID_MISMATCH',
            'message', 'Licença já em uso em outro computador. Solicite o reset de HWID à NexuSistemas.',
            'status', v_lic.status,
            'condominio_nome', v_lic.condominio_nome,
            'server_time', v_now
        );
    ELSE
        UPDATE public.licencas
        SET ultimo_ping = v_now,
            ultimo_ip_info = coalesce(v_ip, ultimo_ip_info),
            versao_app = v_versao
        WHERE id = v_lic.id;
    END IF;

    RETURN jsonb_build_object(
        'valido', true,
        'error_code', NULL,
        'message', 'Licença ativa e validada com sucesso.',
        'codigo', v_lic.codigo,
        'condominio_nome', v_lic.condominio_nome,
        'plano', v_lic.plano,
        'status', v_lic.status,
        'hwid_vinculado', v_lic.hwid_vinculado,
        'validade_ate', v_lic.validade_ate,
        'server_time', v_now
    );
END;
$$;

REVOKE ALL ON FUNCTION public.validar_licenca_nexus(text, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.validar_licenca_nexus(text, text, text) TO anon, authenticated;

-- 4. Configurações públicas do Portal Web (WhatsApp comercial editável pelo /#/admin)
CREATE TABLE IF NOT EXISTS public.config_portal (
    id integer PRIMARY KEY CHECK (id = 1),
    whatsapp_numero text NOT NULL DEFAULT '5511999999999',
    whatsapp_mensagem text NOT NULL DEFAULT 'Olá! Tenho interesse em ativar o Nexus Vision na portaria do meu condomínio.',
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.config_portal (id, whatsapp_numero, whatsapp_mensagem)
VALUES (1, '5511999999999', 'Olá! Tenho interesse em ativar o Nexus Vision na portaria do meu condomínio.')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.config_portal ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.config_portal FROM anon, public;
GRANT SELECT ON TABLE public.config_portal TO anon, authenticated;
GRANT INSERT, UPDATE ON TABLE public.config_portal TO authenticated;

DROP POLICY IF EXISTS "public_select_config_portal" ON public.config_portal;
CREATE POLICY "public_select_config_portal"
    ON public.config_portal
    FOR SELECT
    TO anon, authenticated
    USING (true);

DROP POLICY IF EXISTS "admin_upsert_config_portal" ON public.config_portal;
CREATE POLICY "admin_upsert_config_portal"
    ON public.config_portal
    FOR INSERT
    TO authenticated
    WITH CHECK ((SELECT auth.role()) = 'authenticated');

DROP POLICY IF EXISTS "admin_update_config_portal" ON public.config_portal;
CREATE POLICY "admin_update_config_portal"
    ON public.config_portal
    FOR UPDATE
    TO authenticated
    USING ((SELECT auth.role()) = 'authenticated')
    WITH CHECK ((SELECT auth.role()) = 'authenticated');

-- ==============================================================================
-- 5. Backup Automático na Nuvem de Veículos por Licença (Recuperação de PC Novo)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS public.veiculos_backup (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    licenca_id uuid NOT NULL REFERENCES public.licencas(id) ON DELETE CASCADE,
    placa text NOT NULL,
    nome_responsavel text NOT NULL,
    unidade_bloco text NOT NULL DEFAULT '',
    modelo_cor text NOT NULL DEFAULT '',
    perfil text NOT NULL DEFAULT 'MORADOR'
        CHECK (perfil IN ('MORADOR', 'VISITANTE', 'BLOQUEADO')),
    validade_ate text DEFAULT NULL,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_veiculos_backup_licenca_placa UNIQUE (licenca_id, placa)
);

CREATE INDEX IF NOT EXISTS idx_veiculos_backup_licenca ON public.veiculos_backup (licenca_id);

ALTER TABLE public.veiculos_backup ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.veiculos_backup FROM anon, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.veiculos_backup TO authenticated;

DROP POLICY IF EXISTS "admin_all_veiculos_backup" ON public.veiculos_backup;
CREATE POLICY "admin_all_veiculos_backup"
    ON public.veiculos_backup
    FOR ALL
    TO authenticated
    USING ((SELECT auth.role()) = 'authenticated')
    WITH CHECK ((SELECT auth.role()) = 'authenticated');

-- RPC 1: Envia snapshot dos veículos do PC para a nuvem (somente licença ATIVA + HWID válido)
CREATE OR REPLACE FUNCTION public.sincronizar_veiculos_backup(
    p_codigo text,
    p_hwid text,
    p_veiculos jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_codigo text := upper(trim(coalesce(p_codigo, '')));
    v_hwid text := upper(trim(coalesce(p_hwid, '')));
    v_lic public.licencas%ROWTYPE;
    v_item jsonb;
    v_placa text;
    v_nome text;
    v_perfil text;
    v_count integer := 0;
BEGIN
    SELECT *
    INTO v_lic
    FROM public.licencas
    WHERE codigo = v_codigo;

    IF NOT FOUND OR v_lic.status <> 'ATIVA' OR v_lic.validade_ate <= now() THEN
        RETURN jsonb_build_object('ok', false, 'error', 'LICENCA_INATIVA');
    END IF;

    IF v_lic.hwid_vinculado IS NULL OR upper(trim(v_lic.hwid_vinculado)) <> v_hwid THEN
        RETURN jsonb_build_object('ok', false, 'error', 'HWID_MISMATCH');
    END IF;

    IF p_veiculos IS NULL OR jsonb_typeof(p_veiculos) <> 'array' THEN
        RETURN jsonb_build_object('ok', false, 'error', 'PAYLOAD_INVALIDO');
    END IF;

    -- Sincronização atômica: substitui o snapshot desta licença pelo estado atual do SQLite
    DELETE FROM public.veiculos_backup WHERE licenca_id = v_lic.id;

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_veiculos)
    LOOP
        v_placa := upper(regexp_replace(coalesce(v_item ->> 'placa', ''), '[^A-Za-z0-9]', '', 'g'));
        v_nome := trim(coalesce(v_item ->> 'nome_responsavel', ''));
        v_perfil := upper(trim(coalesce(v_item ->> 'perfil', 'MORADOR')));
        IF v_perfil NOT IN ('MORADOR', 'VISITANTE', 'BLOQUEADO') THEN
            v_perfil := 'MORADOR';
        END IF;

        IF length(v_placa) >= 7 AND v_nome <> '' THEN
            INSERT INTO public.veiculos_backup (
                licenca_id, placa, nome_responsavel, unidade_bloco, modelo_cor, perfil, validade_ate, atualizado_em
            )
            VALUES (
                v_lic.id,
                left(v_placa, 7),
                v_nome,
                trim(coalesce(v_item ->> 'unidade_bloco', '')),
                trim(coalesce(v_item ->> 'modelo_cor', '')),
                v_perfil,
                nullif(trim(coalesce(v_item ->> 'validade_ate', '')), ''),
                now()
            )
            ON CONFLICT (licenca_id, placa) DO UPDATE SET
                nome_responsavel = excluded.nome_responsavel,
                unidade_bloco = excluded.unidade_bloco,
                modelo_cor = excluded.modelo_cor,
                perfil = excluded.perfil,
                validade_ate = excluded.validade_ate,
                atualizado_em = now();
            v_count := v_count + 1;
        END IF;
    END LOOP;

    RETURN jsonb_build_object(
        'ok', true,
        'total_salvos', v_count,
        'condominio_nome', v_lic.condominio_nome,
        'server_time', now()
    );
END;
$$;

REVOKE ALL ON FUNCTION public.sincronizar_veiculos_backup(text, text, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.sincronizar_veiculos_backup(text, text, jsonb) TO anon, authenticated;

-- RPC 2: Restaura todos os veículos salvos na nuvem para um PC novo/formatado
CREATE OR REPLACE FUNCTION public.restaurar_veiculos_backup(
    p_codigo text,
    p_hwid text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_codigo text := upper(trim(coalesce(p_codigo, '')));
    v_hwid text := upper(trim(coalesce(p_hwid, '')));
    v_lic public.licencas%ROWTYPE;
    v_veiculos jsonb;
BEGIN
    SELECT *
    INTO v_lic
    FROM public.licencas
    WHERE codigo = v_codigo;

    IF NOT FOUND OR v_lic.status <> 'ATIVA' OR v_lic.validade_ate <= now() THEN
        RETURN jsonb_build_object('ok', false, 'error', 'LICENCA_INATIVA', 'veiculos', '[]'::jsonb);
    END IF;

    IF v_lic.hwid_vinculado IS NULL OR upper(trim(v_lic.hwid_vinculado)) <> v_hwid THEN
        RETURN jsonb_build_object('ok', false, 'error', 'HWID_MISMATCH', 'veiculos', '[]'::jsonb);
    END IF;

    SELECT coalesce(
        jsonb_agg(
            jsonb_build_object(
                'placa', vb.placa,
                'nome_responsavel', vb.nome_responsavel,
                'unidade_bloco', vb.unidade_bloco,
                'modelo_cor', vb.modelo_cor,
                'perfil', vb.perfil,
                'validade_ate', vb.validade_ate
            )
            ORDER BY vb.nome_responsavel ASC
        ),
        '[]'::jsonb
    )
    INTO v_veiculos
    FROM public.veiculos_backup vb
    WHERE vb.licenca_id = v_lic.id;

    RETURN jsonb_build_object(
        'ok', true,
        'condominio_nome', v_lic.condominio_nome,
        'total', jsonb_array_length(v_veiculos),
        'veiculos', v_veiculos,
        'server_time', now()
    );
END;
$$;

REVOKE ALL ON FUNCTION public.restaurar_veiculos_backup(text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.restaurar_veiculos_backup(text, text) TO anon, authenticated;
