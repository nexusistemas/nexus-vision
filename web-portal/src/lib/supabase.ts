import { createClient, type SupabaseClient } from '@supabase/supabase-js';

export type PlanoLicenca = 'MENSAL' | 'ANUAL' | 'VITALICIO';
export type StatusLicenca = 'ATIVA' | 'BLOQUEADA' | 'SUSPENSA';

export interface Licenca {
  id: string;
  codigo: string;
  condominio_nome: string;
  responsavel_contato: string;
  plano: PlanoLicenca;
  status: StatusLicenca;
  hwid_vinculado: string | null;
  validade_ate: string;
  ultimo_ping: string | null;
  ultimo_ip_info: string | null;
  versao_app: string | null;
  observacoes: string | null;
  criado_em: string;
}

export interface PortalConfig {
  id: number;
  whatsapp_numero: string;
  whatsapp_mensagem: string;
  atualizado_em?: string;
}

export const DEFAULT_WHATSAPP_MESSAGE =
  'Olá! Tenho interesse em ativar o Nexus Vision na portaria do meu condomínio.';

/** Normaliza número brasileiro para formato internacional wa.me (ex: 5511999998888). */
export function normalizeWhatsAppNumber(raw: string): string {
  const digits = (raw || '').replace(/\D/g, '');
  if (!digits) return '';
  if (digits.length === 10 || digits.length === 11) {
    return `55${digits}`;
  }
  return digits;
}

export const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL || '').trim();
export const SUPABASE_ANON_KEY = (import.meta.env.VITE_SUPABASE_ANON_KEY || '').trim();
export const GITHUB_REPO = (import.meta.env.VITE_GITHUB_REPO || 'nexusistemas/nexus-vision').trim();
export const WHATSAPP_NUMBER = (import.meta.env.VITE_WHATSAPP_NUMBER || '5511999999999').replace(/\D/g, '');

export const isSupabaseConfigured =
  Boolean(SUPABASE_URL) &&
  Boolean(SUPABASE_ANON_KEY) &&
  SUPABASE_URL.startsWith('https://') &&
  !SUPABASE_URL.includes('SEU-PROJETO');

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
      },
    })
  : null;

/**
 * Gera chave criptograficamente aleatória no padrão NV-XXXX-XXXX-XXXX.
 * Remove caracteres visualmente ambíguos (0/O, 1/I) para facilitar digitação na portaria.
 */
export function generateLicenseCode(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  let chars = '';
  for (let i = 0; i < 12; i++) {
    chars += alphabet[bytes[i] % alphabet.length];
  }
  return `NV-${chars.slice(0, 4)}-${chars.slice(4, 8)}-${chars.slice(8, 12)}`;
}

/** Verifica se a portaria enviou heartbeat nos últimos 40 minutos. */
export function isPortariaOnline(ultimoPing: string | null): boolean {
  if (!ultimoPing) return false;
  const diffMs = Date.now() - new Date(ultimoPing).getTime();
  return diffMs >= 0 && diffMs <= 40 * 60 * 1000;
}

/** Verifica se a validade expirou ou vence nos próximos 7 dias. */
export function getValidityBadge(validadeAte: string): {
  label: string;
  expired: boolean;
  expiringSoon: boolean;
} {
  const expMs = new Date(validadeAte).getTime();
  const diffDays = Math.ceil((expMs - Date.now()) / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) {
    return { label: 'Vencida', expired: true, expiringSoon: false };
  }
  if (diffDays <= 7) {
    return { label: `Vence em ${diffDays}d`, expired: false, expiringSoon: true };
  }
  if (diffDays > 3650) {
    return { label: 'Vitalícia', expired: false, expiringSoon: false };
  }
  return {
    label: new Date(validadeAte).toLocaleDateString('pt-BR'),
    expired: false,
    expiringSoon: false,
  };
}
