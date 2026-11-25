import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Camera,
  CheckCircle2,
  Cpu,
  Download,
  Lock,
  MessageCircle,
  Monitor,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Volume2,
  Zap,
} from 'lucide-react';
import {
  DEFAULT_WHATSAPP_MESSAGE,
  GITHUB_REPO,
  WHATSAPP_NUMBER,
  normalizeWhatsAppNumber,
  supabase,
} from '../lib/supabase';

interface ReleaseInfo {
  version: string;
  downloadUrl: string;
  fileName: string;
}

const FALLBACK_RELEASE: ReleaseInfo = {
  version: 'v1.0.0',
  downloadUrl: `https://github.com/${GITHUB_REPO}/releases/latest/download/NexusVision_Setup.exe`,
  fileName: 'NexusVision_Setup_v1.0.0.exe',
};

export function LandingPage() {
  const [release, setRelease] = useState<ReleaseInfo>(FALLBACK_RELEASE);
  const [whatsappNumber, setWhatsappNumber] = useState<string>(WHATSAPP_NUMBER);
  const [whatsappMessage, setWhatsappMessage] = useState<string>(DEFAULT_WHATSAPP_MESSAGE);

  useEffect(() => {
    let active = true;
    if (supabase) {
      supabase
        .from('config_portal')
        .select('whatsapp_numero, whatsapp_mensagem')
        .eq('id', 1)
        .maybeSingle()
        .then(({ data }) => {
          if (!active || !data) return;
          const clean = normalizeWhatsAppNumber(data.whatsapp_numero || '');
          if (clean) setWhatsappNumber(clean);
          if (data.whatsapp_mensagem) setWhatsappMessage(data.whatsapp_mensagem);
        });
    }
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    fetch(`https://api.github.com/repos/${GITHUB_REPO}/releases/latest`, {
      headers: { Accept: 'application/vnd.github+json' },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!active || !data) return;
        const assets: Array<{ name?: string; browser_download_url?: string }> = data.assets || [];
        const exe =
          assets.find((a) => a.name?.toLowerCase().endsWith('.exe') && a.name.toLowerCase().includes('setup')) ||
          assets.find((a) => a.name?.toLowerCase().endsWith('.exe'));
        setRelease({
          version: data.tag_name || FALLBACK_RELEASE.version,
          downloadUrl: exe?.browser_download_url || data.html_url || FALLBACK_RELEASE.downloadUrl,
          fileName: exe?.name || FALLBACK_RELEASE.fileName,
        });
      })
      .catch(() => {
        /* mantém fallback */
      });
    return () => {
      active = false;
    };
  }, []);

  const whatsappUrl = `https://wa.me/${whatsappNumber}?text=${encodeURIComponent(whatsappMessage)}`;

  const features = [
    {
      icon: Monitor,
      title: 'Captura Universal de Tela (Multi-Monitor)',
      desc: 'Funciona por cima do Intelbras SIM Next, Hikvision iVMS, D-Guard ou navegador. Basta arrastar o retângulo sobre o vídeo da câmera — sem mexer em rede ou RTSP.',
    },
    {
      icon: ScanLine,
      title: 'Placas Mercosul & Antigas com Heurística BR',
      desc: 'IA ONNX nativa 100% CPU com pós-processamento brasileiro (LLLNLNN e LLLNNNN), correção inteligente de caracteres e votação anti-ruído.',
    },
    {
      icon: Volume2,
      title: 'Alerta Visual e Sonoro Instantâneo p/ Porteiro',
      desc: 'Card gigante em tela cheia: Morador Autorizado em verde, Visitante com controle de validade, Não Cadastrado com cadastro em 1 clique e Bloqueado piscante.',
    },
    {
      icon: Camera,
      title: 'Auditoria Completa com Foto da Passagem',
      desc: 'Salva automaticamente a captura do veículo com a bounding box da placa organizada por data (YYYY-MM-DD) no banco local SQLite WAL.',
    },
    {
      icon: Cpu,
      title: '100% Offline & Sem GPU Cara',
      desc: 'Modelos de visão computacional leves embutidos no instalador. Roda liso em PCs comuns de portaria Windows 10/11 mesmo se a internet cair (contingência 72h).',
    },
    {
      icon: ShieldCheck,
      title: 'Segurança SaaS Node-Locked por HWID',
      desc: 'Licenciamento comercial vinculado ao hardware físico da portaria, gestão remota instantânea e atualizações automáticas via GitHub Releases.',
    },
  ];

  return (
    <div className="min-h-screen bg-[#070D19] text-slate-100 nexus-grid-bg">
      {/* Navbar */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-[#070D19]/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-400/60 bg-slate-100 p-1.5 shadow-lg shadow-cyan-500/20">
              <img src="./logo.png" alt="Nexus Vision" className="h-full w-full object-contain" />
            </div>
            <div>
              <div className="text-base font-extrabold tracking-wide text-white">NEXUS VISION</div>
              <div className="text-[11px] font-semibold text-cyan-400">NexuSistemas Tecnologia</div>
            </div>
          </div>

          <nav className="hidden items-center gap-7 text-sm font-medium text-slate-300 md:flex">
            <a href="#recursos" className="transition hover:text-cyan-300">
              Recursos
            </a>
            <a href="#como-funciona" className="transition hover:text-cyan-300">
              Como Funciona
            </a>
            <a href="#download" className="transition hover:text-cyan-300">
              Download Windows
            </a>
          </nav>

          <div className="flex items-center gap-2.5">
            <a
              href={whatsappUrl}
              target="_blank"
              rel="noreferrer"
              className="hidden items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2 text-xs font-bold text-emerald-300 transition hover:bg-emerald-500/20 sm:inline-flex"
            >
              <MessageCircle className="h-4 w-4" />
              Falar com Comercial
            </a>
            <Link
              to="/admin"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/90 px-3.5 py-2 text-xs font-semibold text-slate-300 transition hover:border-cyan-500/60 hover:text-white"
            >
              <Lock className="h-3.5 w-3.5 text-cyan-400" />
              Painel Admin
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 sm:px-6 sm:pt-20">
        <div className="grid items-center gap-12 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3.5 py-1.5 text-xs font-bold text-cyan-300">
              <Sparkles className="h-3.5 w-3.5" />
              IA NATIVA OFFLINE PARA PORTARIAS 24H • WINDOWS 10 / 11
            </div>

            <h1 className="text-3xl font-black leading-tight tracking-tight text-white sm:text-5xl">
              Transforme qualquer câmera comum da portaria em{' '}
              <span className="bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent">
                leitora automática de placas com IA Nativa
              </span>
            </h1>

            <p className="mt-5 text-base leading-relaxed text-slate-300 sm:text-lg">
              Sem trocar DVR, sem investir em câmeras LPR caras e funcionando{' '}
              <strong className="text-white">100% offline</strong> direto no computador da guarita.
              Recorte a câmera na tela e identifique moradores, visitantes e veículos bloqueados em
              milissegundos.
            </p>

            <div id="download" className="mt-8 flex flex-wrap items-center gap-3.5">
              <a
                href={release.downloadUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-6 py-3.5 text-sm font-extrabold text-slate-950 shadow-xl shadow-cyan-500/20 transition hover:brightness-110"
              >
                <Download className="h-5 w-5" />
                Baixar para Windows 10/11 (.exe)
                <span className="rounded-md bg-slate-950/20 px-2 py-0.5 text-xs font-bold">
                  {release.version}
                </span>
              </a>

              <a
                href={whatsappUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-5 py-3.5 text-sm font-bold text-white transition hover:border-emerald-400/60 hover:bg-slate-800"
              >
                <MessageCircle className="h-4 w-4 text-emerald-400" />
                Solicitar Licença Comercial
              </a>
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs font-medium text-slate-400">
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Modelos IA ONNX embutidos (sem internet)
              </span>
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Não requer placa de vídeo NVIDIA
              </span>
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                Importação de moradores via CSV
              </span>
            </div>
          </div>

          {/* Mockup visual do Card Gigante do Porteiro */}
          <div className="lg:col-span-5">
            <div className="rounded-2xl border border-cyan-500/30 bg-[#0F172A]/95 p-5 shadow-2xl shadow-cyan-950/50">
              <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-xs font-bold tracking-wider text-cyan-300">
                    PORTARIA PRINCIPAL • IA ONNX ATIVA
                  </span>
                </div>
                <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] font-bold text-slate-300">
                  15.0 FPS
                </span>
              </div>

              <div className="relative mb-4 overflow-hidden rounded-xl border border-slate-700/80 bg-[#070D19] p-6">
                <div className="mx-auto max-w-[260px] rounded-lg border-2 border-emerald-400 bg-emerald-500/10 p-3 text-center shadow-lg shadow-emerald-500/15">
                  <div className="mb-1 inline-block rounded bg-emerald-400 px-2 py-0.5 font-mono text-[11px] font-black text-slate-950">
                    ABC1D23 • 96%
                  </div>
                  <div className="mx-auto mt-1 rounded-md border-2 border-slate-900 border-t-[9px] border-t-blue-700 bg-slate-50 px-4 py-2 font-mono text-2xl font-black tracking-widest text-slate-950">
                    ABC1D23
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between text-[11px] text-slate-400">
                  <span>● MOVIMENTO DETECTADO — GATILHO IA</span>
                  <span className="font-mono text-emerald-400">84 ms CPU</span>
                </div>
              </div>

              <div className="rounded-xl border-2 border-emerald-500 bg-[#052E1F] p-4">
                <div className="text-[10px] font-bold tracking-widest text-emerald-300">
                  VERIFICAÇÃO LOCAL SQLITE WAL • INSTANTÂNEA
                </div>
                <div className="mt-1 text-xl font-black text-white">MORADOR AUTORIZADO</div>
                <div className="mt-1 text-xs text-slate-200">
                  Carlos Eduardo Mendes • Bloco A — Apto 302 • Corolla Prata
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Recursos */}
      <section id="recursos" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="mb-10 max-w-2xl">
          <div className="text-xs font-extrabold uppercase tracking-widest text-cyan-400">
            Arquitetura Corporativa 24 Horas
          </div>
          <h2 className="mt-2 text-2xl font-black text-white sm:text-3xl">
            Projetado para a rotina real de portarias e condomínios
          </h2>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => {
            const Icon = f.icon;
            return (
              <div
                key={f.title}
                className="rounded-2xl border border-slate-800 bg-[#0F172A]/90 p-6 transition hover:border-cyan-500/40"
              >
                <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-base font-bold text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{f.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Como Funciona */}
      <section id="como-funciona" className="border-y border-slate-800/80 bg-[#0B1324]/70 py-16">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="mb-10 text-center">
            <div className="text-xs font-extrabold uppercase tracking-widest text-emerald-400">
              Implantação em Menos de 3 Minutos
            </div>
            <h2 className="mt-2 text-2xl font-black text-white sm:text-3xl">
              Como o Nexus Vision opera no seu condomínio
            </h2>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                step: '01',
                title: 'Instale no PC da Portaria',
                desc: 'Execute o instalador Windows (.exe) com atalho automático na Área de Trabalho e inicialização junto com o Windows.',
              },
              {
                step: '02',
                title: 'Selecione a Câmera na Tela',
                desc: 'Clique em "Selecionar Câmera" e arraste o retângulo neon sobre o vídeo do seu DVR/VMS existente — funciona em múltiplos monitores.',
              },
              {
                step: '03',
                title: 'Liberação Automática 24h',
                desc: 'Importe a planilha CSV de moradores e ative sua chave NV-XXXX. Cada veículo é identificado com alerta visual, sonoro e foto auditada.',
              },
            ].map((item) => (
              <div
                key={item.step}
                className="rounded-2xl border border-slate-800 bg-[#0F172A] p-6"
              >
                <div className="mb-3 inline-flex items-center gap-1.5 font-mono text-sm font-black text-cyan-400">
                  <Zap className="h-4 w-4 text-emerald-400" />
                  PASSO {item.step}
                </div>
                <h3 className="text-lg font-bold text-white">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-4 py-8 text-xs text-slate-400 sm:flex-row sm:px-6">
        <div className="flex items-center gap-2.5">
          <img src="./logo.png" alt="NexuSistemas" className="h-6 w-6 rounded bg-slate-100 p-0.5 object-contain" />
          <span>
            © {new Date().getFullYear()} <strong className="text-slate-200">NexuSistemas Tecnologia</strong> — vision.nexusistemas.app.br
          </span>
        </div>
        <div className="flex items-center gap-5">
          <a href={release.downloadUrl} target="_blank" rel="noreferrer" className="hover:text-cyan-300">
            Download {release.version}
          </a>
          <a href={whatsappUrl} target="_blank" rel="noreferrer" className="hover:text-emerald-300">
            Suporte Comercial
          </a>
          <Link to="/admin" className="hover:text-cyan-300">
            Acesso Administrativo
          </Link>
        </div>
      </footer>
    </div>
  );
}
