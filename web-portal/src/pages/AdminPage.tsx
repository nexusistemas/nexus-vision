import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CalendarPlus,
  Check,
  CheckCircle2,
  Copy,
  KeyRound,
  Lock,
  LogOut,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Unlock,
  Users,
  X,
} from 'lucide-react';
import {
  DEFAULT_WHATSAPP_MESSAGE,
  WHATSAPP_NUMBER,
  generateLicenseCode,
  getValidityBadge,
  isPortariaOnline,
  isSupabaseConfigured,
  normalizeWhatsAppNumber,
  supabase,
  type Licenca,
  type PlanoLicenca,
} from '../lib/supabase';

export function AdminPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [submittingLogin, setSubmittingLogin] = useState(false);

  const [licencas, setLicencas] = useState<Licenca[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [search, setSearch] = useState('');
  const [filterMode, setFilterMode] = useState<'TODAS' | 'ATIVAS' | 'ONLINE' | 'BLOQUEADAS'>('TODAS');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Modal Gerar Nova Licença
  const [showNewModal, setShowNewModal] = useState(false);
  const [newCodigo, setNewCodigo] = useState(generateLicenseCode());
  const [newCondominio, setNewCondominio] = useState('');
  const [newContato, setNewContato] = useState('');
  const [newPlano, setNewPlano] = useState<PlanoLicenca>('MENSAL');
  const [newDias, setNewDias] = useState(30);
  const [newObs, setNewObs] = useState('');
  const [creating, setCreating] = useState(false);

  // Modal Configurar WhatsApp Comercial do Site
  const [showPortalModal, setShowPortalModal] = useState(false);
  const [portalWhatsApp, setPortalWhatsApp] = useState(WHATSAPP_NUMBER);
  const [portalMessage, setPortalMessage] = useState(DEFAULT_WHATSAPP_MESSAGE);
  const [savingPortal, setSavingPortal] = useState(false);

  // Modal Editar Licença existente
  const [editingLic, setEditingLic] = useState<Licenca | null>(null);
  const [editCondominio, setEditCondominio] = useState('');
  const [editContato, setEditContato] = useState('');
  const [editPlano, setEditPlano] = useState<PlanoLicenca>('MENSAL');
  const [editValidade, setEditValidade] = useState('');
  const [editObs, setEditObs] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  // Modal Confirmar Exclusão (apaga licença + todos os backups na nuvem)
  const [deletingLic, setDeletingLic] = useState<Licenca | null>(null);
  const [deletingBusy, setDeletingBusy] = useState(false);

  const notify = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((prev) => (prev === msg ? null : prev)), 3200);
  }, []);

  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthLoading(false);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });
    return () => subscription.unsubscribe();
  }, []);

  const fetchLicencas = useCallback(async () => {
    if (!supabase) return;
    setLoadingList(true);
    const { data, error } = await supabase
      .from('licencas')
      .select('*')
      .order('criado_em', { ascending: false });
    setLoadingList(false);
    if (error) {
      notify(`Erro ao carregar licenças: ${error.message}`);
      return;
    }
    setLicencas((data as Licenca[]) || []);
  }, [notify]);

  const fetchPortalConfig = useCallback(async () => {
    if (!supabase) return;
    const { data } = await supabase
      .from('config_portal')
      .select('whatsapp_numero, whatsapp_mensagem')
      .eq('id', 1)
      .maybeSingle();
    if (data) {
      if (data.whatsapp_numero) setPortalWhatsApp(data.whatsapp_numero);
      if (data.whatsapp_mensagem) setPortalMessage(data.whatsapp_mensagem);
    }
  }, []);

  useEffect(() => {
    if (session) {
      fetchLicencas();
      fetchPortalConfig();
    }
  }, [session, fetchLicencas, fetchPortalConfig]);

  const handleSavePortalConfig = async (e: FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    const normalized = normalizeWhatsAppNumber(portalWhatsApp);
    if (normalized.length < 12) {
      notify('Informe um número válido com DDD (ex: 11999998888 ou 5511999998888).');
      return;
    }
    setSavingPortal(true);
    const { error } = await supabase.from('config_portal').upsert(
      {
        id: 1,
        whatsapp_numero: normalized,
        whatsapp_mensagem: portalMessage.trim() || DEFAULT_WHATSAPP_MESSAGE,
        atualizado_em: new Date().toISOString(),
      },
      { onConflict: 'id' }
    );
    setSavingPortal(false);
    if (error) {
      notify(`Erro ao salvar WhatsApp (rode o SQL da tabela config_portal no Supabase): ${error.message}`);
      return;
    }
    setPortalWhatsApp(normalized);
    setShowPortalModal(false);
    notify(`WhatsApp comercial (${normalized}) atualizado no site!`);
  };

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    setAuthError('');
    setSubmittingLogin(true);
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    setSubmittingLogin(false);
    if (error) {
      setAuthError('E-mail ou senha inválidos. Verifique suas credenciais de administrador no Supabase.');
    }
  };

  const handleLogout = async () => {
    if (!supabase) return;
    await supabase.auth.signOut();
    setLicencas([]);
  };

  const openCreateModal = () => {
    setNewCodigo(generateLicenseCode());
    setNewCondominio('');
    setNewContato('');
    setNewPlano('MENSAL');
    setNewDias(30);
    setNewObs('');
    setShowNewModal(true);
  };

  const handlePlanoSelect = (plano: PlanoLicenca) => {
    setNewPlano(plano);
    if (plano === 'MENSAL') setNewDias(30);
    else if (plano === 'ANUAL') setNewDias(365);
    else setNewDias(36500);
  };

  const handleCreateLicense = async (e: FormEvent) => {
    e.preventDefault();
    if (!supabase || !newCondominio.trim()) return;
    setCreating(true);
    const validade = new Date(Date.now() + newDias * 24 * 60 * 60 * 1000).toISOString();
    const { error } = await supabase.from('licencas').insert({
      codigo: newCodigo.trim().toUpperCase(),
      condominio_nome: newCondominio.trim(),
      responsavel_contato: newContato.trim(),
      plano: newPlano,
      status: 'ATIVA',
      validade_ate: validade,
      observacoes: newObs.trim() || null,
    });
    setCreating(false);
    if (error) {
      notify(`Falha ao gerar licença: ${error.message}`);
      return;
    }
    setShowNewModal(false);
    notify(`Licença ${newCodigo} criada com sucesso!`);
    fetchLicencas();
  };

  const handleToggleStatus = async (lic: Licenca) => {
    if (!supabase) return;
    const nextStatus = lic.status === 'ATIVA' ? 'BLOQUEADA' : 'ATIVA';
    setBusyId(lic.id);
    const { error } = await supabase.from('licencas').update({ status: nextStatus }).eq('id', lic.id);
    setBusyId(null);
    if (error) {
      notify(`Erro ao atualizar status: ${error.message}`);
      return;
    }
    notify(
      nextStatus === 'ATIVA'
        ? `Licença de ${lic.condominio_nome} REATIVADA!`
        : `Licença de ${lic.condominio_nome} BLOQUEADA remotamente!`
    );
    fetchLicencas();
  };

  const handleResetHwid = async (lic: Licenca) => {
    if (!supabase) return;
    setBusyId(lic.id);
    const { error } = await supabase.from('licencas').update({ hwid_vinculado: null }).eq('id', lic.id);
    setBusyId(null);
    if (error) {
      notify(`Erro ao resetar HWID: ${error.message}`);
      return;
    }
    notify(`HWID de ${lic.condominio_nome} liberado para novo PC!`);
    fetchLicencas();
  };

  const handleRenew = async (lic: Licenca, days: number) => {
    if (!supabase) return;
    const baseMs = Math.max(Date.now(), new Date(lic.validade_ate).getTime());
    const nextValidade = new Date(baseMs + days * 24 * 60 * 60 * 1000).toISOString();
    setBusyId(lic.id);
    const { error } = await supabase
      .from('licencas')
      .update({ validade_ate: nextValidade, status: 'ATIVA' })
      .eq('id', lic.id);
    setBusyId(null);
    if (error) {
      notify(`Erro ao renovar: ${error.message}`);
      return;
    }
    notify(`${lic.condominio_nome} renovado (+${days === 365 ? '1 Ano' : `${days} Dias`})!`);
    fetchLicencas();
  };

  const handleCopyWhatsApp = async (lic: Licenca) => {
    const valStr = getValidityBadge(lic.validade_ate).label;
    const message =
      `*Nexus Vision — Ativação de Licença (NexuSistemas)*\n\n` +
      `🏢 *Condomínio:* ${lic.condominio_nome}\n` +
      `🔑 *Chave de Ativação:* \`${lic.codigo}\`\n` +
      `📅 *Plano / Validade:* ${lic.plano} (${valStr})\n\n` +
      `💻 *Download do Instalador Windows:* https://vision.nexusistemas.app.br\n` +
      `Abra o Nexus Vision -> Aba *Conta & Licença* -> cole a chave acima e clique em *Ativar / Validar Online*.`;
    try {
      await navigator.clipboard.writeText(message);
      notify(`Texto + chave ${lic.codigo} copiados para colar no WhatsApp!`);
    } catch {
      notify(`Chave: ${lic.codigo}`);
    }
  };

  const openEditModal = (lic: Licenca) => {
    setEditingLic(lic);
    setEditCondominio(lic.condominio_nome);
    setEditContato(lic.responsavel_contato || '');
    setEditPlano(lic.plano);
    setEditValidade(lic.validade_ate ? lic.validade_ate.slice(0, 10) : '');
    setEditObs(lic.observacoes || '');
  };

  const handleSaveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!supabase || !editingLic || !editCondominio.trim()) return;
    setSavingEdit(true);
    const updatePayload: Record<string, string | null> = {
      condominio_nome: editCondominio.trim(),
      responsavel_contato: editContato.trim(),
      plano: editPlano,
      observacoes: editObs.trim() || null,
    };
    if (editValidade) {
      updatePayload.validade_ate = new Date(`${editValidade}T23:59:59.000Z`).toISOString();
    }
    const { error } = await supabase
      .from('licencas')
      .update(updatePayload)
      .eq('id', editingLic.id);
    setSavingEdit(false);
    if (error) {
      notify(`Erro ao salvar alterações: ${error.message}`);
      return;
    }
    setEditingLic(null);
    notify(`Licença de ${editCondominio.trim()} atualizada com sucesso!`);
    fetchLicencas();
  };

  const handleConfirmDelete = async () => {
    if (!supabase || !deletingLic) return;
    setDeletingBusy(true);
    // Apaga backups explicitamente + exclui a licença (ON DELETE CASCADE garante limpeza total)
    await supabase.from('veiculos_backup').delete().eq('licenca_id', deletingLic.id);
    const { error } = await supabase.from('licencas').delete().eq('id', deletingLic.id);
    setDeletingBusy(false);
    if (error) {
      notify(`Erro ao excluir licença: ${error.message}`);
      return;
    }
    const removedName = deletingLic.condominio_nome;
    setDeletingLic(null);
    notify(`Licença de ${removedName} e todos os backups na nuvem foram excluídos!`);
    fetchLicencas();
  };

  const metrics = useMemo(() => {
    const total = licencas.length;
    const ativas = licencas.filter((l) => l.status === 'ATIVA').length;
    const online = licencas.filter((l) => isPortariaOnline(l.ultimo_ping)).length;
    const alertas = licencas.filter((l) => {
      const vb = getValidityBadge(l.validade_ate);
      return l.status !== 'ATIVA' || vb.expired || vb.expiringSoon;
    }).length;
    return { total, ativas, online, alertas };
  }, [licencas]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return licencas.filter((l) => {
      if (filterMode === 'ATIVAS' && l.status !== 'ATIVA') return false;
      if (filterMode === 'ONLINE' && !isPortariaOnline(l.ultimo_ping)) return false;
      if (filterMode === 'BLOQUEADAS' && l.status === 'ATIVA') return false;
      if (!q) return true;
      return (
        l.codigo.toLowerCase().includes(q) ||
        l.condominio_nome.toLowerCase().includes(q) ||
        (l.responsavel_contato || '').toLowerCase().includes(q)
      );
    });
  }, [licencas, search, filterMode]);

  // =========================================================================
  // TELA DE CONFIGURAÇÃO PENDENTE OU LOGIN
  // =========================================================================
  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#070D19] text-slate-300">
        Carregando painel administrativo...
      </div>
    );
  }

  if (!isSupabaseConfigured) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#070D19] p-4">
        <div className="w-full max-w-lg rounded-2xl border border-amber-500/40 bg-[#0F172A] p-7">
          <div className="mb-4 flex items-center gap-3 text-amber-300">
            <AlertTriangle className="h-7 w-7" />
            <h1 className="text-xl font-black text-white">Supabase Ainda Não Configurado</h1>
          </div>
          <p className="text-sm leading-relaxed text-slate-300">
            Para habilitar o Painel Master de Licenças em <code className="text-cyan-300">/#/admin</code>,
            configure as variáveis <code className="text-cyan-300">VITE_SUPABASE_URL</code> e{' '}
            <code className="text-cyan-300">VITE_SUPABASE_ANON_KEY</code> no arquivo{' '}
            <code className="text-emerald-300">web-portal/.env.local</code> (ou nos GitHub Actions
            Secrets para deploy no GitHub Pages) e execute o script{' '}
            <code className="text-emerald-300">supabase/schema.sql</code>.
          </p>
          <div className="mt-6">
            <Link
              to="/"
              className="inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-700"
            >
              <ArrowLeft className="h-4 w-4" />
              Voltar para Landing Page
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#070D19] p-4 nexus-grid-bg">
        <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-[#0F172A]/95 p-7 shadow-2xl">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-500/50 bg-slate-100 p-1.5">
                <img src="./logo.png" alt="Nexus Vision" className="h-full w-full object-contain" />
              </div>
              <div>
                <h1 className="text-lg font-black text-white">Painel Master</h1>
                <p className="text-xs text-cyan-400">NexuSistemas • Gestão de Licenças</p>
              </div>
            </div>
            <Link to="/" className="text-xs text-slate-400 hover:text-white">
              ← Site
            </Link>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                E-mail Administrador
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@nexusistemas.app.br"
                className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-bold uppercase text-slate-400">Senha</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
              />
            </div>

            {authError && (
              <div className="rounded-lg border border-red-500/40 bg-red-950/60 px-3 py-2 text-xs text-red-200">
                {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={submittingLogin}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 py-3 text-sm font-extrabold text-slate-950 transition hover:brightness-110 disabled:opacity-60"
            >
              <Lock className="h-4 w-4" />
              {submittingLogin ? 'Autenticando...' : 'Entrar no Painel Master'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // =========================================================================
  // PAINEL MASTER AUTENTICADO (DESKTOP + MOBILE)
  // =========================================================================
  return (
    <div className="min-h-screen bg-[#070D19] text-slate-100">
      {/* Toast Flutuante */}
      {toast && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-xl border border-emerald-500/50 bg-slate-900/95 px-4 py-3 text-sm font-semibold text-emerald-200 shadow-2xl">
          <Check className="h-4 w-4 text-emerald-400" />
          {toast}
        </div>
      )}

      {/* Header Admin */}
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-[#0F172A]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-cyan-500/50 bg-slate-100 p-1">
              <img src="./logo.png" alt="Nexus Vision" className="h-full w-full object-contain" />
            </div>
            <div>
              <div className="text-sm font-black text-white sm:text-base">
                NEXUS VISION — PAINEL MASTER
              </div>
              <div className="text-[11px] text-cyan-400">{session.user.email}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPortalModal(true)}
              title="Configurar número do WhatsApp comercial exibido no site"
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-300 transition hover:bg-emerald-500/20 sm:text-sm"
            >
              <MessageCircle className="h-4 w-4" />
              <span className="hidden sm:inline">WhatsApp Site</span>
            </button>
            <button
              onClick={openCreateModal}
              className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-3.5 py-2 text-xs font-extrabold text-slate-950 transition hover:brightness-110 sm:text-sm"
            >
              <Plus className="h-4 w-4" />
              Gerar Licença
            </button>
            <button
              onClick={fetchLicencas}
              title="Atualizar lista"
              className="rounded-xl border border-slate-700 bg-slate-900 p-2 text-slate-300 hover:border-cyan-400 hover:text-white"
            >
              <RefreshCw className={`h-4 w-4 ${loadingList ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={handleLogout}
              title="Sair"
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-red-500/60 hover:text-red-300"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Sair</span>
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {/* Cards de KPIs */}
        <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
          {[
            { label: 'Total de Clientes', value: metrics.total, icon: Users, color: 'text-cyan-400' },
            { label: 'Licenças Ativas', value: metrics.ativas, icon: ShieldCheck, color: 'text-emerald-400' },
            { label: 'Portarias Online (40m)', value: metrics.online, icon: Activity, color: 'text-sky-400' },
            { label: 'Bloqueadas / Vencendo', value: metrics.alertas, icon: ShieldAlert, color: 'text-amber-400' },
          ].map((k) => {
            const Icon = k.icon;
            return (
              <div
                key={k.label}
                className="rounded-2xl border border-slate-800 bg-[#0F172A] p-4 sm:p-5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-400">{k.label}</span>
                  <Icon className={`h-4 w-4 ${k.color}`} />
                </div>
                <div className={`mt-2 text-2xl font-black sm:text-3xl ${k.color}`}>{k.value}</div>
              </div>
            );
          })}
        </div>

        {/* Barra de Busca e Filtros */}
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por condomínio, chave NV-XXXX ou contato..."
              className="w-full rounded-xl border border-slate-800 bg-[#0F172A] py-2.5 pl-10 pr-4 text-sm text-white outline-none focus:border-cyan-400"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {(['TODAS', 'ATIVAS', 'ONLINE', 'BLOQUEADAS'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setFilterMode(tab)}
                className={`rounded-lg px-3 py-2 text-xs font-bold transition ${
                  filterMode === tab
                    ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/60'
                    : 'bg-[#0F172A] text-slate-400 hover:text-white'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Lista de Licenças (Cards Responsivos + Visão Completa) */}
        <div className="mt-5 space-y-3">
          {filtered.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-800 bg-[#0F172A]/60 p-10 text-center text-sm text-slate-400">
              {loadingList
                ? 'Carregando licenças...'
                : 'Nenhuma licença encontrada. Clique em "Gerar Licença" para criar a primeira.'}
            </div>
          ) : (
            filtered.map((lic) => {
              const online = isPortariaOnline(lic.ultimo_ping);
              const val = getValidityBadge(lic.validade_ate);
              const isBusy = busyId === lic.id;

              return (
                <div
                  key={lic.id}
                  className="rounded-2xl border border-slate-800 bg-[#0F172A] p-4 transition hover:border-slate-700 sm:p-5"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    {/* Identificação & Status */}
                    <div className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-base font-extrabold text-white">
                          {lic.condominio_nome}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-extrabold ${
                            lic.status === 'ATIVA'
                              ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40'
                              : 'bg-red-500/15 text-red-300 ring-1 ring-red-500/40'
                          }`}
                        >
                          {lic.status === 'ATIVA' ? (
                            <CheckCircle2 className="h-3 w-3" />
                          ) : (
                            <Lock className="h-3 w-3" />
                          )}
                          {lic.status}
                        </span>
                        {online && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2.5 py-0.5 text-[11px] font-bold text-sky-300 ring-1 ring-sky-500/40">
                            <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulse" />
                            ONLINE AGORA
                          </span>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                        <span className="inline-flex items-center gap-1.5 font-mono text-sm font-bold text-cyan-300">
                          <KeyRound className="h-3.5 w-3.5" />
                          {lic.codigo}
                        </span>
                        <span>
                          Plano: <strong className="text-slate-200">{lic.plano}</strong>
                        </span>
                        <span
                          className={
                            val.expired
                              ? 'font-bold text-red-400'
                              : val.expiringSoon
                              ? 'font-bold text-amber-400'
                              : ''
                          }
                        >
                          Validade: <strong>{val.label}</strong>
                        </span>
                        {lic.responsavel_contato && <span>Contato: {lic.responsavel_contato}</span>}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                        <span>
                          HWID:{' '}
                          <code className="text-slate-300">
                            {lic.hwid_vinculado
                              ? `${lic.hwid_vinculado.slice(0, 16)}...`
                              : 'Aguardando 1ª ativação'}
                          </code>
                        </span>
                        <span>
                          Último ping:{' '}
                          {lic.ultimo_ping
                            ? new Date(lic.ultimo_ping).toLocaleString('pt-BR')
                            : 'Nunca'}
                        </span>
                        {lic.versao_app && <span>App v{lic.versao_app}</span>}
                      </div>
                    </div>

                    {/* Ações em 1 Clique */}
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        disabled={isBusy}
                        onClick={() => handleCopyWhatsApp(lic)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-300 transition hover:bg-cyan-500/20"
                      >
                        <Copy className="h-3.5 w-3.5" />
                        Copiar p/ WhatsApp
                      </button>

                      <button
                        disabled={isBusy}
                        onClick={() => handleRenew(lic, 30)}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/90 px-2.5 py-2 text-xs font-bold text-slate-200 hover:border-emerald-500/50 hover:text-emerald-300"
                      >
                        <CalendarPlus className="h-3.5 w-3.5" />
                        +30d
                      </button>

                      <button
                        disabled={isBusy}
                        onClick={() => handleRenew(lic, 365)}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/90 px-2.5 py-2 text-xs font-bold text-slate-200 hover:border-emerald-500/50 hover:text-emerald-300"
                      >
                        +1 Ano
                      </button>

                      <button
                        disabled={isBusy || !lic.hwid_vinculado}
                        onClick={() => handleResetHwid(lic)}
                        title="Limpa o HWID para permitir ativação em outro computador"
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/90 px-2.5 py-2 text-xs font-bold text-amber-300 hover:border-amber-500/50 disabled:opacity-40"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Resetar HWID
                      </button>

                      <button
                        disabled={isBusy}
                        onClick={() => openEditModal(lic)}
                        title="Editar nome do condomínio, contato, plano ou validade"
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/90 px-2.5 py-2 text-xs font-bold text-slate-200 hover:border-cyan-400 hover:text-cyan-300"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Editar
                      </button>

                      <button
                        disabled={isBusy}
                        onClick={() => handleToggleStatus(lic)}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-extrabold transition ${
                          lic.status === 'ATIVA'
                            ? 'bg-red-600/90 text-white hover:bg-red-500'
                            : 'bg-emerald-600/90 text-white hover:bg-emerald-500'
                        }`}
                      >
                        {lic.status === 'ATIVA' ? (
                          <>
                            <Lock className="h-3.5 w-3.5" /> Bloquear
                          </>
                        ) : (
                          <>
                            <Unlock className="h-3.5 w-3.5" /> Reativar
                          </>
                        )}
                      </button>

                      <button
                        disabled={isBusy}
                        onClick={() => setDeletingLic(lic)}
                        title="Excluir licença e apagar todos os backups na nuvem"
                        className="inline-flex items-center gap-1 rounded-lg border border-red-500/40 bg-red-950/60 px-2.5 py-2 text-xs font-bold text-red-300 transition hover:bg-red-600 hover:text-white"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Excluir
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </main>

      {/* Modal Editar Licença */}
      {editingLic && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-[#0F172A] p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-black text-white">Editar Licença</h2>
                <p className="font-mono text-xs text-cyan-400">{editingLic.codigo}</p>
              </div>
              <button
                onClick={() => setEditingLic(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                  Nome do Condomínio / Cliente *
                </label>
                <input
                  type="text"
                  required
                  value={editCondominio}
                  onChange={(e) => setEditCondominio(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Responsável / WhatsApp
                  </label>
                  <input
                    type="text"
                    value={editContato}
                    onChange={(e) => setEditContato(e.target.value)}
                    placeholder="(11) 99999-9999"
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Plano Comercial
                  </label>
                  <select
                    value={editPlano}
                    onChange={(e) => setEditPlano(e.target.value as PlanoLicenca)}
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  >
                    <option value="MENSAL">MENSAL</option>
                    <option value="ANUAL">ANUAL</option>
                    <option value="VITALICIO">VITALÍCIO</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Validade Até
                  </label>
                  <input
                    type="date"
                    value={editValidade}
                    onChange={(e) => setEditValidade(e.target.value)}
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Observações
                  </label>
                  <input
                    type="text"
                    value={editObs}
                    onChange={(e) => setEditObs(e.target.value)}
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingLic(null)}
                  className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-slate-800"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={savingEdit}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-5 py-2.5 text-sm font-extrabold text-slate-950 hover:brightness-110 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {savingEdit ? 'Salvando...' : 'Salvar Alterações'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Confirmar Exclusão (Licença + Backups na Nuvem) */}
      {deletingLic && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-red-500/50 bg-[#0F172A] p-6 shadow-2xl">
            <div className="mb-3 flex items-center gap-2.5 text-red-400">
              <AlertTriangle className="h-6 w-6" />
              <h2 className="text-lg font-black text-white">Excluir Licença Permanentemente?</h2>
            </div>
            <p className="text-sm leading-relaxed text-slate-300">
              Você está prestes a excluir a licença{' '}
              <strong className="font-mono text-cyan-300">{deletingLic.codigo}</strong> de{' '}
              <strong className="text-white">{deletingLic.condominio_nome}</strong>.
            </p>
            <div className="mt-3 rounded-xl border border-red-500/30 bg-red-950/50 p-3 text-xs text-red-200">
              ⚠ Esta ação também <strong>apagará todos os veículos salvos no backup em nuvem</strong>{' '}
              deste condomínio e bloqueará o computador vinculado na próxima verificação. Não pode ser desfeita.
            </div>
            <div className="mt-5 flex justify-end gap-2.5">
              <button
                type="button"
                disabled={deletingBusy}
                onClick={() => setDeletingLic(null)}
                className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-slate-800"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={deletingBusy}
                onClick={handleConfirmDelete}
                className="inline-flex items-center gap-1.5 rounded-xl bg-red-600 px-5 py-2.5 text-sm font-extrabold text-white hover:bg-red-500 disabled:opacity-60"
              >
                <Trash2 className="h-4 w-4" />
                {deletingBusy ? 'Excluindo...' : 'Sim, Excluir Tudo'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Configurar WhatsApp Comercial do Site */}
      {showPortalModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-[#0F172A] p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MessageCircle className="h-5 w-5 text-emerald-400" />
                <h2 className="text-lg font-black text-white">WhatsApp Comercial do Site</h2>
              </div>
              <button
                onClick={() => setShowPortalModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleSavePortalConfig} className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                  Número do WhatsApp (com DDD) *
                </label>
                <input
                  type="text"
                  required
                  value={portalWhatsApp}
                  onChange={(e) => setPortalWhatsApp(e.target.value)}
                  placeholder="Ex: (11) 99999-8888 ou 5511999998888"
                  className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-emerald-400"
                />
                <p className="mt-1 text-[11px] text-slate-400">
                  Usado nos botões "Solicitar Licença Comercial", "Falar com Comercial" e "Suporte Comercial" da página inicial.
                </p>
              </div>

              <div>
                <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                  Mensagem Automática Inicial
                </label>
                <textarea
                  rows={3}
                  value={portalMessage}
                  onChange={(e) => setPortalMessage(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-emerald-400"
                />
              </div>

              <div className="flex justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setShowPortalModal(false)}
                  className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-slate-800"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={savingPortal}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-5 py-2.5 text-sm font-extrabold text-slate-950 hover:brightness-110 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {savingPortal ? 'Salvando...' : 'Salvar Número'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Gerar Nova Licença */}
      {showNewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-[#0F172A] p-6 shadow-2xl">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-lg font-black text-white">Gerar Nova Licença Nexus Vision</h2>
              <button
                onClick={() => setShowNewModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateLicense} className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                  Código Gerado (Criptográfico)
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    value={newCodigo}
                    className="flex-1 rounded-xl border border-cyan-500/50 bg-[#070D19] px-3.5 py-2.5 font-mono text-base font-black tracking-widest text-cyan-300"
                  />
                  <button
                    type="button"
                    onClick={() => setNewCodigo(generateLicenseCode())}
                    className="rounded-xl border border-slate-700 bg-slate-800 px-3 text-slate-200 hover:border-cyan-400"
                    title="Gerar outra chave"
                  >
                    <RefreshCw className="h-4 w-4" />
                  </button>
                </div>
              </div>

              <div>
                <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                  Nome do Condomínio / Empresa *
                </label>
                <input
                  type="text"
                  required
                  value={newCondominio}
                  onChange={(e) => setNewCondominio(e.target.value)}
                  placeholder="Ex: Condomínio Residencial Jardim Europa"
                  className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Responsável / WhatsApp
                  </label>
                  <input
                    type="text"
                    value={newContato}
                    onChange={(e) => setNewContato(e.target.value)}
                    placeholder="(11) 99999-9999"
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Plano Comercial
                  </label>
                  <select
                    value={newPlano}
                    onChange={(e) => handlePlanoSelect(e.target.value as PlanoLicenca)}
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  >
                    <option value="MENSAL">MENSAL (30 dias)</option>
                    <option value="ANUAL">ANUAL (365 dias)</option>
                    <option value="VITALICIO">VITALÍCIO</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Dias de Validade
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={36500}
                    value={newDias}
                    onChange={(e) => setNewDias(Math.max(1, Number(e.target.value) || 30))}
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-bold uppercase text-slate-400">
                    Observações (Opcional)
                  </label>
                  <input
                    type="text"
                    value={newObs}
                    onChange={(e) => setNewObs(e.target.value)}
                    placeholder="Ex: Portaria Principal + Garagem"
                    className="w-full rounded-xl border border-slate-700 bg-[#070D19] px-3.5 py-2.5 text-sm text-white outline-none focus:border-cyan-400"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  className="rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-slate-800"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-5 py-2.5 text-sm font-extrabold text-slate-950 hover:brightness-110 disabled:opacity-60"
                >
                  {creating ? 'Salvando...' : 'Criar e Ativar Chave'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
