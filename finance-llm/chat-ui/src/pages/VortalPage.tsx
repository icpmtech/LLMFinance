/**
 * Peças do procedimento · Vortal — página do módulo (`/vortal`).
 *
 * O módulo recolhe as **peças do procedimento** (caderno de encargos, programa
 * do concurso, mapa de quantidades, modelo de resposta, esclarecimentos, ESPD…)
 * publicadas na plataforma Vortal, guarda-as em disco e indexa o texto no
 * Elasticsearch, onde fica pesquisável por dentro dos documentos.
 *
 * Quatro leituras:
 *
 * 1. **Recolher** — cola-se o URL da página pública de peças do procedimento
 *    (ou o token/UID) e o motor resolve o aviso, descarrega as peças para disco,
 *    extrai o texto e (opcionalmente) indexa. Há um botão para **rever** o aviso
 *    antes de descarregar nada. Para muitos avisos, escolhe-se o **mês e o ano**
 *    (as ligações já estão nos contratos, em `linkPecasProc`) e a recolha corre
 *    em lotes, sem colar centenas de URLs.
 * 2. **Peças** — o que está indexado (por aviso), com tipo, tamanho, texto
 *    extraído e ligação à página oficial do aviso.
 * 3. **Pesquisa** — pesquisa no texto das peças, com trechos do documento.
 * 4. **Monitorização** — **só para administradores**: disco, índice, tipos de
 *    peça e histórico de recolhas/indexações (o servidor devolve 403 a quem não
 *    for `admin`).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  CloudDownload,
  Database,
  ExternalLink,
  FileSearch,
  FileText,
  FolderDown,
  HardDrive,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import { useAuth } from "../auth";
import { Chip, EmptyState, Kpi, Loading, SectionCard, formatNumber, formatPct } from "../components/padroes/padroesKit";
import {
  apagarVortalAviso,
  getVortalEstado,
  getVortalMeta,
  getVortalMonitorizacao,
  getVortalPecas,
  getVortalPeriodo,
  getVortalPeriodos,
  indexarVortal,
  pesquisarVortal,
  recolherVortal,
  recolherVortalLote,
  reverVortalAviso,
  type VortalAvisoPeriodo,
  type VortalEstado,
  type VortalLote,
  type VortalMeta,
  type VortalMonitorizacao,
  type VortalPeca,
  type VortalPeriodo,
  type VortalPeriodos,
  type VortalRecolha,
  type VortalResultadoPeca,
} from "../vortalApi";

type Seccao = "recolher" | "pecas" | "pesquisa" | "monitorizacao";

const SECCOES: { id: Seccao; label: string; icon: typeof CloudDownload; hint: string; admin?: boolean }[] = [
  { id: "recolher", label: "Recolher", icon: CloudDownload, hint: "URL/token da página de peças → disco (+ índice)" },
  { id: "pecas", label: "Peças", icon: FolderDown, hint: "Peças indexadas, por aviso" },
  { id: "pesquisa", label: "Pesquisa", icon: FileSearch, hint: "Pesquisar dentro do texto das peças" },
  { id: "monitorizacao", label: "Monitorização", icon: BarChart3, hint: "Disco, índice e histórico — só administradores", admin: true },
];

function formatBytes(bytes?: number | null): string {
  if (bytes === undefined || bytes === null || Number.isNaN(bytes)) return "—";
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toLocaleString("pt-PT", { maximumFractionDigits: 0 })} kB`;
  return `${bytes} B`;
}

function formatDataHora(valor?: string | null): string {
  if (!valor) return "—";
  const data = new Date(valor);
  return Number.isNaN(data.getTime()) ? valor : data.toLocaleString("pt-PT");
}

function formatData(valor?: string | null): string {
  if (!valor) return "—";
  const data = new Date(valor);
  return Number.isNaN(data.getTime()) ? valor : data.toLocaleDateString("pt-PT");
}

const NOMES_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

/** Trecho do `highlight` do Elasticsearch: `<em>` passa a destaque visual. */
function Trecho({ html }: { html: string }) {
  const partes = html.split(/<\/?em>/);
  return (
    <span>
      {partes.map((parte, indice) =>
        indice % 2 === 1 ? (
          <mark key={indice} className="rounded bg-amber-300/20 px-0.5 text-amber-100">
            {parte}
          </mark>
        ) : (
          <span key={indice}>{parte}</span>
        ),
      )}
    </span>
  );
}

/* ------------------------------------------------------------------- página */

export default function VortalPage() {
  const { user } = useAuth();
  const admin = user?.role === "admin";

  const [meta, setMeta] = useState<VortalMeta | null>(null);
  const [estado, setEstado] = useState<VortalEstado | null>(null);
  const [seccao, setSeccao] = useState<Seccao>("recolher");

  /* recolha */
  const [urls, setUrls] = useState("");
  const [indexar, setIndexar] = useState(true);
  const [extrair, setExtrair] = useState(true);
  const [forcar, setForcar] = useState(false);
  const [aRever, setARever] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [aviso, setAviso] = useState<{ uid: string; url_aviso?: string | null; publicado?: boolean; pecas: VortalPeca[]; total: number; em_disco: boolean } | null>(null);
  const [recolha, setRecolha] = useState<VortalRecolha | null>(null);

  /* peças + pesquisa */
  const [uidFiltro, setUidFiltro] = useState("");
  const [pecas, setPecas] = useState<{ itens: VortalResultadoPeca[]; total: number; uid?: string } | null>(null);
  const [aCarregarPecas, setACarregarPecas] = useState(false);
  const [termo, setTermo] = useState("");
  const [resultados, setResultados] = useState<{ itens: VortalResultadoPeca[]; total: number; termo: string } | null>(null);
  const [aPesquisar, setAPesquisar] = useState(false);

  /* monitorização (admin) */
  const [monitor, setMonitor] = useState<VortalMonitorizacao | null>(null);
  const [aMonitorizar, setAMonitorizar] = useState(false);
  const [aIndexar, setAIndexar] = useState(false);

  const [erro, setErro] = useState<string | null>(null);
  const [avisoOk, setAvisoOk] = useState<string | null>(null);

  const lista = useMemo(() => urls.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean), [urls]);

  // A ficha do contrato passa o aviso nesta ligação (`/vortal?url=…`): a caixa
  // chega preenchida e a revisão arranca sozinha, para não repetir o trabalho.
  useEffect(() => {
    const parametros = new URLSearchParams(window.location.search);
    const daFicha = [parametros.get("url"), parametros.get("uid")].filter(
      (valor): valor is string => Boolean(valor && valor.trim()),
    );
    if (!daFicha.length) return;
    setUrls((atual) => (atual.trim() ? atual : daFicha.join("\n")));
    setSeccao("recolher");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const carregarEstado = useCallback(async () => {
    try {
      setEstado(await getVortalEstado());
    } catch {
      /* o estado é acessório */
    }
  }, []);

  useEffect(() => {
    let cancelado = false;
    getVortalMeta()
      .then((resposta) => {
        if (!cancelado) setMeta(resposta);
      })
      .catch(() => {
        /* o metamodelo é acessório */
      });
    void carregarEstado();
    return () => {
      cancelado = true;
    };
  }, [carregarEstado]);

  const carregarPecas = useCallback(
    async (uid?: string) => {
      setACarregarPecas(true);
      try {
        const resposta = await getVortalPecas({ uid: uid || undefined, limite: 100 });
        setPecas(resposta);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao listar as peças");
      } finally {
        setACarregarPecas(false);
      }
    },
    [],
  );

  const carregarMonitor = useCallback(async () => {
    if (!admin) return;
    setAMonitorizar(true);
    try {
      setMonitor(await getVortalMonitorizacao(25));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao carregar a monitorização");
    } finally {
      setAMonitorizar(false);
    }
  }, [admin]);

  useEffect(() => {
    if (seccao === "pecas" && !pecas) void carregarPecas();
    if (seccao === "monitorizacao" && admin && !monitor) void carregarMonitor();
  }, [admin, carregarMonitor, carregarPecas, monitor, pecas, seccao]);

  const rever = useCallback(async () => {
    if (!lista.length) return;
    setARever(true);
    setErro(null);
    setAvisoOk(null);
    try {
      const resposta = await reverVortalAviso(lista[0]);
      setAviso(resposta);
      setUidFiltro(resposta.uid);
    } catch (falha) {
      setAviso(null);
      setErro(falha instanceof Error ? falha.message : "Erro ao consultar o aviso");
    } finally {
      setARever(false);
    }
  }, [lista]);

  const recolher = useCallback(async () => {
    if (!lista.length) return;
    setARecolher(true);
    setErro(null);
    setAvisoOk(null);
    try {
      const resposta = await recolherVortal({ urls: lista, indexar, extrair, forcar });
      setRecolha(resposta);
      setAvisoOk(
        `${resposta.avisos} aviso(s), ${resposta.pecas} peça(s), ${formatBytes(resposta.bytes)} em disco` +
          (resposta.indice ? ` · ${resposta.indice.indexados} indexada(s)` : ""),
      );
      setPecas(null);
      setResultados(null);
      await carregarEstado();
      if (admin) setMonitor(null);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro na recolha");
    } finally {
      setARecolher(false);
    }
  }, [admin, carregarEstado, extrair, forcar, indexar, lista]);

  const indexarDisco = useCallback(async () => {
    setAIndexar(true);
    setErro(null);
    try {
      const resposta = await indexarVortal({});
      setAvisoOk(`Indexadas ${resposta.indexados} peça(s) no índice ${resposta.index}`);
      await carregarEstado();
      await carregarMonitor();
      setPecas(null);
      if (seccao === "pecas") await carregarPecas(uidFiltro || undefined);
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao indexar");
    } finally {
      setAIndexar(false);
    }
  }, [carregarEstado, carregarMonitor, carregarPecas, seccao, uidFiltro]);

  const apagar = useCallback(
    async (uid: string, comDisco: boolean) => {
      setErro(null);
      try {
        const resposta = await apagarVortalAviso(uid, comDisco);
        setAvisoOk(`Aviso ${uid}: ${resposta.apagados} documento(s) removido(s) do índice${comDisco ? " e do disco" : ""}`);
        await carregarEstado();
        await carregarMonitor();
        setPecas(null);
      } catch (falha) {
        setErro(falha instanceof Error ? falha.message : "Erro ao remover");
      }
    },
    [carregarEstado, carregarMonitor],
  );

  const pesquisar = useCallback(async () => {
    if (termo.trim().length < 2) return;
    setAPesquisar(true);
    setErro(null);
    try {
      setResultados(await pesquisarVortal({ q: termo.trim(), uid: uidFiltro || undefined, limite: 30 }));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro na pesquisa");
    } finally {
      setAPesquisar(false);
    }
  }, [termo, uidFiltro]);

  const seccoes = useMemo(() => SECCOES.filter((item) => !item.admin || admin), [admin]);

  /* ------------------------------------------------------------------- ecrã */
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden text-foreground">
      <header className="shrink-0 border-b border-white/10 bg-white/[0.02] px-4 py-3 backdrop-blur-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold">
              <FolderDown size={18} className="text-teal-300" />
              Peças do procedimento · Vortal
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {meta?.descricao ??
                "Resolve o aviso a partir do URL público de peças, descarrega os documentos para disco, extrai o texto e indexa em Elasticsearch."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {estado ? (
              <>
                <Chip tone="teal" title={`${estado.disco.avisos} avisos em ${estado.disco.raiz}`}>
                  <HardDrive size={11} /> {formatNumber(estado.disco.pecas)} peças · {formatBytes(estado.disco.bytes)}
                </Chip>
                <Chip tone={estado.indice.disponivel ? "blue" : "rose"} title={estado.indice.index}>
                  <Database size={11} /> {formatNumber(estado.indice.documentos ?? 0)} indexadas
                </Chip>
              </>
            ) : null}
            <button
              type="button"
              onClick={() => {
                void carregarEstado();
                setPecas(null);
                setMonitor(null);
                if (seccao === "pecas") void carregarPecas(uidFiltro || undefined);
                if (seccao === "monitorizacao") void carregarMonitor();
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs transition hover:bg-white/[0.1]"
            >
              <RefreshCw size={13} /> Atualizar
            </button>
          </div>
        </div>

        <nav className="mt-3 flex flex-wrap gap-1">
          {seccoes.map((item) => {
            const Icone = item.icon;
            const ativo = seccao === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setSeccao(item.id)}
                title={item.hint}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
                  ativo ? "border-teal-400/40 bg-teal-400/15 text-teal-100" : "border-white/10 bg-white/[0.03] text-muted-foreground hover:bg-white/[0.08]"
                }`}
              >
                <Icone size={13} />
                {item.label}
                {item.admin ? <Chip tone="violet">admin</Chip> : null}
              </button>
            );
          })}
        </nav>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {erro && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle size={15} /> {erro}
          </div>
        )}
        {avisoOk && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-xs text-teal-100">
            <CheckCircle2 size={15} /> {avisoOk}
          </div>
        )}

        {seccao === "recolher" ? (
          <div className="space-y-4">
            <SectionCard
              title="Recolher peças de um procedimento"
              subtitle="Cole o URL da página pública de peças (ou o token/UID). Vários avisos: um por linha."
              icon={CloudDownload}
              actions={
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void rever()}
                    disabled={aRever || !lista.length}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
                  >
                    {aRever ? <Loader2 size={12} className="animate-spin" /> : <FileSearch size={12} />} Rever aviso
                  </button>
                  <button
                    type="button"
                    onClick={() => void recolher()}
                    disabled={aRecolher || !lista.length}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
                  >
                    {aRecolher ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Recolher
                  </button>
                </div>
              }
            >
              <textarea
                value={urls}
                onChange={(evento) => setUrls(evento.target.value)}
                rows={4}
                spellCheck={false}
                placeholder={"https://community.vortal.biz/Public/public-tender-documents/<token>\nPT1.NTC.3612674"}
                className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 font-mono text-[11.5px] outline-none placeholder:text-muted-foreground/60"
              />
              <div className="mt-3 flex flex-wrap items-center gap-4 text-[11.5px]">
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" checked={indexar} onChange={(evento) => setIndexar(evento.target.checked)} className="accent-teal-400" />
                  Indexar no Elasticsearch
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="checkbox" checked={extrair} onChange={(evento) => setExtrair(evento.target.checked)} className="accent-teal-400" />
                  Extrair texto (PDF/DOCX/XLSX/XML)
                </label>
                <label className="inline-flex items-center gap-2" title="Voltar a descarregar peças que já existem em disco">
                  <input type="checkbox" checked={forcar} onChange={(evento) => setForcar(evento.target.checked)} className="accent-teal-400" />
                  Forçar nova descarga
                </label>
                <span className="text-muted-foreground">
                  destino: <span className="font-mono">{recolha?.destino ?? estado?.disco.raiz ?? meta?.destino ?? "data/vortal"}</span>
                </span>
              </div>

              {aviso ? (
                <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                  <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-mono text-[12px]">{aviso.uid}</p>
                      <p className="text-[11px] text-muted-foreground">
                        {aviso.publicado ? "aviso publicado" : "aviso não publicado"} · {aviso.total} peça(s) ·{" "}
                        {aviso.em_disco ? "já existe em disco" : "ainda não está em disco"}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {aviso.url_aviso ? (
                        <a
                          href={aviso.url_aviso}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                        >
                          <ExternalLink size={12} /> página do aviso
                        </a>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setUidFiltro(aviso.uid)}
                        className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                      >
                        filtrar por este aviso
                      </button>
                    </div>
                  </header>
                  <TabelaPecas pecas={aviso.pecas} />
                </div>
              ) : null}

              {recolha ? (
                <div className="mt-4 space-y-3">
                  <p className="text-[11.5px] text-muted-foreground">
                    {recolha.avisos} aviso(s) · {formatNumber(recolha.pecas)} peça(s) · {formatBytes(recolha.bytes)} · {recolha.duracao_s ?? "—"} s
                    {recolha.indice ? ` · ${recolha.indice.indexados} indexada(s) em ${recolha.indice.index}` : ""}
                  </p>
                  {recolha.erros?.length ? (
                    <ul className="space-y-1 text-[11px] text-amber-200">
                      {recolha.erros.slice(0, 6).map((item) => (
                        <li key={item}>· {item}</li>
                      ))}
                    </ul>
                  ) : null}
                  {recolha.detalhe?.map((item, indice) => (
                    <div key={`${item.uid}-${indice}`} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                      <p className="mb-2 font-mono text-[12px]">{item.uid}</p>
                      <TabelaPecas pecas={item.pecas} />
                    </div>
                  ))}
                </div>
              ) : null}

              {!aviso && !recolha ? (
                <div className="mt-3">
                  <EmptyState>
                    O token vive no endereço da página de peças do procedimento (
                    <span className="font-mono">…/Public/public-tender-documents/&lt;token&gt;</span>). «Rever aviso» lista as peças sem descarregar
                    nada; «Recolher» guarda os ficheiros em disco e indexa-os.
                  </EmptyState>
                </div>
              ) : null}
            </SectionCard>

            <LotePorPeriodo
              meta={meta}
              indexar={indexar}
              extrair={extrair}
              forcar={forcar}
              aoRecolher={async () => {
                setPecas(null);
                setResultados(null);
                await carregarEstado();
                if (admin) setMonitor(null);
              }}
            />

            {meta ? (
              <SectionCard title="Como este módulo recolhe" subtitle={meta.titulo} icon={FileText}>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-1 text-[11.5px]">
                    <p className="text-muted-foreground">API pública usada (sem sessão):</p>
                    {meta.endpoints_api.map((endpoint) => (
                      <p key={endpoint} className="font-mono text-[10.5px] text-teal-200">
                        {endpoint}
                      </p>
                    ))}
                    <p className="pt-2 text-muted-foreground">
                      Anfitriões autorizados: <span className="font-mono">{meta.hosts_permitidos.join(", ")}</span>
                    </p>
                    <p className="text-muted-foreground">
                      Limites: {formatBytes(meta.limites.bytes_por_peca)} por peça · {formatNumber(meta.limites.chars_por_peca)} caracteres de texto
                    </p>
                  </div>
                  <ul className="space-y-1 text-[11px] text-muted-foreground">
                    {meta.notas.map((nota) => (
                      <li key={nota}>· {nota}</li>
                    ))}
                  </ul>
                </div>
              </SectionCard>
            ) : null}
          </div>
        ) : null}

        {seccao === "pecas" ? (
          <SectionCard
            title="Peças indexadas"
            subtitle={pecas?.uid ? `Aviso ${pecas.uid}` : "Todos os avisos recolhidos"}
            icon={FolderDown}
            actions={
              <div className="flex flex-wrap items-center gap-1.5">
                <input
                  value={uidFiltro}
                  onChange={(evento) => setUidFiltro(evento.target.value)}
                  placeholder="UID do aviso (ex.: PT1.NTC.3612674)"
                  className="w-56 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11px] outline-none"
                />
                <button
                  type="button"
                  onClick={() => void carregarPecas(uidFiltro || undefined)}
                  disabled={aCarregarPecas}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
                >
                  {aCarregarPecas ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Filtrar
                </button>
                {admin ? (
                  <button
                    type="button"
                    onClick={() => void indexarDisco()}
                    disabled={aIndexar}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
                  >
                    {aIndexar ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />} Indexar o que está em disco
                  </button>
                ) : null}
              </div>
            }
          >
            {aCarregarPecas && !pecas ? <Loading label="A ler o índice das peças…" /> : null}
            {pecas && !pecas.itens.length ? (
              <EmptyState>Ainda não há peças indexadas. Recolha um procedimento na aba «Recolher».</EmptyState>
            ) : null}
            {pecas?.itens.length ? <TabelaIndexadas itens={pecas.itens} /> : null}
            {pecas && pecas.total > pecas.itens.length ? (
              <p className="mt-2 text-[11px] text-muted-foreground">
                A mostrar {pecas.itens.length} de {formatNumber(pecas.total)} — refine pelo UID do aviso.
              </p>
            ) : null}
          </SectionCard>
        ) : null}

        {seccao === "pesquisa" ? (
          <div className="space-y-4">
            <SectionCard
              title="Pesquisar dentro das peças"
              subtitle="O texto extraído dos cadernos de encargos, programas do concurso, mapas de quantidades e restantes peças"
              icon={FileSearch}
              actions={
                <div className="flex flex-wrap items-center gap-1.5">
                  <input
                    value={termo}
                    onChange={(evento) => setTermo(evento.target.value)}
                    onKeyDown={(evento) => {
                      if (evento.key === "Enter") void pesquisar();
                    }}
                    placeholder="ex.: preço base, caução, prazo de entrega"
                    className="w-72 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => void pesquisar()}
                    disabled={aPesquisar || termo.trim().length < 2}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
                  >
                    {aPesquisar ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Pesquisar
                  </button>
                </div>
              }
            >
              {!resultados ? (
                <EmptyState>A pesquisa corre sobre o texto das peças já indexadas (não sobre o PDF em bruto).</EmptyState>
              ) : (
                <div className="space-y-2">
                  <p className="text-[11px] text-muted-foreground">
                    {formatNumber(resultados.total)} resultado(s) para «{resultados.termo}»
                    {uidFiltro ? ` no aviso ${uidFiltro}` : ""}.
                  </p>
                  {resultados.itens.map((item) => (
                    <article key={`${item.uid}-${item.nome}-${item.sha256 ?? ""}`} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                      <header className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-[12.5px]" title={item.nome}>
                            {item.nome}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            <span className="font-mono">{item.uid}</span> · {item.tipo_label ?? item.tipo} · {formatNumber(item.texto_chars)} chars
                          </p>
                        </div>
                        <Chip tone="neutral" title="Pontuação de relevância">
                          {item.score !== undefined ? item.score.toFixed(2) : "—"}
                        </Chip>
                      </header>
                      {item.trechos?.length ? (
                        <ul className="mt-2 space-y-1 text-[11.5px] text-muted-foreground">
                          {item.trechos.map((trecho, indice) => (
                            <li key={indice} className="rounded-lg border border-white/5 bg-black/20 px-2 py-1">
                              <Trecho html={trecho} />
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>
        ) : null}

        {seccao === "monitorizacao" ? (
          <div className="space-y-4">
            {!admin ? (
              <SectionCard title="Monitorização" subtitle="Área reservada a administradores" icon={BarChart3}>
                <EmptyState tone="warn">Só contas com papel `admin` veem a monitorização deste módulo.</EmptyState>
              </SectionCard>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Kpi icon={HardDrive} label="Peças em disco" value={formatNumber(monitor?.disco.pecas ?? 0)} sub={`${formatBytes(monitor?.disco.bytes ?? 0)} · ${monitor?.disco.ficheiros ?? 0} ficheiros`} />
                  <Kpi icon={FileText} label="Com texto extraído" value={formatNumber(monitor?.disco.com_texto ?? 0)} sub="pesquisáveis por dentro" color="text-sky-300" glow="glow-sky" />
                  <Kpi icon={Database} label="Documentos no índice" value={formatNumber(monitor?.indice.documentos ?? 0)} sub={monitor?.indice.index} color="text-violet-300" />
                  <Kpi
                    icon={CloudDownload}
                    label="Avisos recolhidos"
                    value={formatNumber(monitor?.disco.avisos ?? 0)}
                    sub={`${monitor?.indice.avisos ?? 0} no índice`}
                    color="text-amber-300"
                  />
                </div>

                <SectionCard
                  title="Monitorização"
                  subtitle={monitor ? `Destino ${monitor.disco.raiz}` : "A carregar…"}
                  icon={BarChart3}
                  actions={
                    <div className="flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => void carregarMonitor()}
                        disabled={aMonitorizar}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
                      >
                        {aMonitorizar ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Atualizar
                      </button>
                      <button
                        type="button"
                        onClick={() => void indexarDisco()}
                        disabled={aIndexar}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
                      >
                        {aIndexar ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />} Indexar o que está em disco
                      </button>
                    </div>
                  }
                >
                  {aMonitorizar && !monitor ? <Loading label="A ler o disco e o índice…" /> : null}
                  {monitor ? (
                    <div className="space-y-4">
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Disco</p>
                          <Linha rotulo="Raiz">{monitor.disco.raiz}</Linha>
                          <Linha rotulo="Peças / avisos">
                            {formatNumber(monitor.disco.pecas)} / {formatNumber(monitor.disco.avisos)}
                          </Linha>
                          <Linha rotulo="Bytes">{formatBytes(monitor.disco.bytes)}</Linha>
                          <Linha rotulo="Com texto">
                            {formatNumber(monitor.disco.com_texto)} ({formatPct(monitor.disco.pecas ? monitor.disco.com_texto / monitor.disco.pecas : 0, 0)})
                          </Linha>
                          {monitor.indice.erro ? <Linha rotulo="Erro do índice">{monitor.indice.erro}</Linha> : null}
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                          <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Por tipo de peça</p>
                          {Object.entries(monitor.disco.por_tipo).length ? (
                            Object.entries(monitor.disco.por_tipo).map(([tipo, quantidade]) => (
                              <Linha key={tipo} rotulo={tipo.replace(/_/g, " ")}>
                                {formatNumber(quantidade)}
                              </Linha>
                            ))
                          ) : (
                            <p className="text-[11px] text-muted-foreground">sem peças em disco</p>
                          )}
                        </div>
                      </div>

                      <div className="space-y-2">
                        {monitor.avisos.map((item) => (
                          <article key={item.uid} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                            <header className="flex flex-wrap items-center justify-between gap-2">
                              <div className="min-w-0">
                                <p className="font-mono text-[12px]">{item.uid}</p>
                                <p className="text-[11px] text-muted-foreground">
                                  recolhido {formatDataHora(item.recolhido_em)} · {formatNumber(item.totais?.pecas ?? 0)} peça(s) ·{" "}
                                  {formatBytes(item.totais?.bytes ?? 0)} · {formatNumber(item.totais?.com_texto ?? 0)} com texto
                                </p>
                              </div>
                              <div className="flex flex-wrap items-center gap-1.5">
                                {item.url_aviso ? (
                                  <a
                                    href={item.url_aviso}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                                  >
                                    <ExternalLink size={12} /> aviso
                                  </a>
                                ) : null}
                                <button
                                  type="button"
                                  onClick={() => {
                                    setUidFiltro(item.uid);
                                    setSeccao("pecas");
                                    setPecas(null);
                                    void carregarPecas(item.uid);
                                  }}
                                  className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] hover:bg-white/[0.09]"
                                >
                                  ver peças
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void apagar(item.uid, false)}
                                  className="inline-flex items-center gap-1 rounded-lg border border-rose-400/25 bg-rose-400/10 px-2.5 py-1 text-[11.5px] text-rose-200 hover:bg-rose-400/20"
                                  title="Remover do índice (mantém os ficheiros em disco)"
                                >
                                  <Trash2 size={12} /> do índice
                                </button>
                              </div>
                            </header>
                          </article>
                        ))}
                      </div>

                      <div>
                        <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Histórico de recolhas e indexações</p>
                        {monitor.historico.length ? (
                          <div className="overflow-x-auto">
                            <table className="w-full min-w-[720px] text-[11.5px]">
                              <thead className="text-left text-muted-foreground">
                                <tr className="border-b border-white/10">
                                  <th className="py-1">Quando</th>
                                  <th className="py-1">Tipo</th>
                                  <th className="py-1">Autor</th>
                                  <th className="py-1 text-right">Avisos</th>
                                  <th className="py-1 text-right">Peças</th>
                                  <th className="py-1 text-right">Bytes</th>
                                  <th className="py-1 text-right">Indexadas</th>
                                  <th className="py-1">Erros</th>
                                </tr>
                              </thead>
                              <tbody>
                                {monitor.historico.map((item, indice) => (
                                  <tr key={`${item.em}-${indice}`} className="border-b border-white/5">
                                    <td className="py-1">{formatDataHora(item.em)}</td>
                                    <td className="py-1">{item.tipo}</td>
                                    <td className="max-w-[160px] truncate py-1" title={item.autor ?? ""}>
                                      {item.autor ?? "—"}
                                    </td>
                                    <td className="py-1 text-right font-mono">{formatNumber(item.avisos)}</td>
                                    <td className="py-1 text-right font-mono">{formatNumber(item.pecas)}</td>
                                    <td className="py-1 text-right font-mono">{formatBytes(item.bytes)}</td>
                                    <td className="py-1 text-right font-mono">{formatNumber(item.indexados)}</td>
                                    <td className="max-w-[260px] truncate py-1 text-amber-200" title={(item.erros ?? []).join(" · ")}>
                                      {item.erros?.length ? item.erros[0] : "—"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <EmptyState>Ainda não há recolhas registadas.</EmptyState>
                        )}
                      </div>
                    </div>
                  ) : null}
                </SectionCard>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ pedaços */

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/5 py-1 last:border-0">
      <span className="text-[11px] text-muted-foreground">{rotulo}</span>
      <span className="truncate text-right font-mono text-[11.5px]">{children}</span>
    </div>
  );
}

/** Peças de um aviso (o que veio da API pública, ainda antes ou depois da descarga). */
function TabelaPecas({ pecas }: { pecas: VortalPeca[] }) {
  if (!pecas?.length) return <EmptyState>Este aviso não tem peças públicas listadas.</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-[11.5px]">
        <thead className="text-left text-muted-foreground">
          <tr className="border-b border-white/10">
            <th className="py-1">Peça</th>
            <th className="py-1">Tipo</th>
            <th className="py-1 text-right">Tamanho</th>
            <th className="py-1 text-right">Texto</th>
            <th className="py-1">Estado</th>
          </tr>
        </thead>
        <tbody>
          {pecas.map((peca) => (
            <tr key={`${peca.uid}-${peca.file_id ?? peca.nome}`} className="border-b border-white/5">
              <td className="max-w-[320px] truncate py-1" title={peca.nome}>
                {peca.url ? (
                  <a href={peca.url} target="_blank" rel="noreferrer" className="hover:text-teal-200" title="Abrir a peça na origem">
                    {peca.nome}
                  </a>
                ) : (
                  peca.nome
                )}
              </td>
              <td className="py-1">
                <Chip tone={peca.tipo === "caderno_encargos" ? "teal" : peca.tipo === "programa_concurso" ? "blue" : "neutral"}>
                  {peca.tipo_label ?? peca.tipo.replace(/_/g, " ")}
                </Chip>
              </td>
              <td className="py-1 text-right font-mono">{formatBytes(peca.bytes)}</td>
              <td className="py-1 text-right font-mono" title={peca.texto_metodo ?? ""}>
                {peca.texto_chars !== undefined ? formatNumber(peca.texto_chars) : "—"}
              </td>
              <td className="py-1">
                {peca.erro ? (
                  <Chip tone="rose" title={peca.erro}>
                    erro
                  </Chip>
                ) : peca.precisa_ocr ? (
                  <Chip tone="amber" title="PDF digitalizado (imagem sem camada de texto): precisa de OCR">
                    precisa OCR
                  </Chip>
                ) : peca.texto_chars ? (
                  <Chip tone="teal">com texto</Chip>
                ) : (
                  <Chip tone="neutral">só ficheiro</Chip>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Recolha em lote: um mês (ou um ano inteiro) de avisos do índice de contratos. */
function LotePorPeriodo({
  meta,
  indexar,
  extrair,
  forcar,
  aoRecolher,
}: {
  meta: VortalMeta | null;
  indexar: boolean;
  extrair: boolean;
  forcar: boolean;
  aoRecolher: () => Promise<void>;
}) {
  const [periodos, setPeriodos] = useState<VortalPeriodos | null>(null);
  const [ano, setAno] = useState("");
  const [mes, setMes] = useState("");
  const [lote, setLote] = useState(10);
  const [lotesVez, setLotesVez] = useState(1);
  const [saltarEmDisco, setSaltarEmDisco] = useState(true);
  const [periodo, setPeriodo] = useState<VortalPeriodo | null>(null);
  const [resultado, setResultado] = useState<VortalLote | null>(null);
  const [aRever, setARever] = useState(false);
  const [aRecolher, setARecolher] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    getVortalPeriodos()
      .then((resposta) => {
        if (cancelado) return;
        setPeriodos(resposta);
        const anos = resposta.anos;
        const ultimo = anos.length ? anos[anos.length - 1].ano : null;
        if (ultimo === null) return;
        setAno(String(ultimo));
        const meses = resposta.meses.filter((item) => item.mes.startsWith(`${ultimo}-`));
        if (meses.length) setMes(String(Number(meses[meses.length - 1].mes.slice(5, 7))));
      })
      .catch((falha) => {
        if (!cancelado) setErro(falha instanceof Error ? falha.message : "Erro ao listar os períodos");
      });
    return () => {
      cancelado = true;
    };
  }, []);

  const mesesDoAno = useMemo(
    () => (periodos?.meses ?? []).filter((item) => item.mes.startsWith(`${ano}-`)),
    [ano, periodos],
  );

  const parametros = useMemo(() => ({ ano: Number(ano), mes: mes ? Number(mes) : undefined }), [ano, mes]);
  const pronto = Number(ano) >= 2000 && Number(ano) <= 2100;

  const reverPeriodo = useCallback(async () => {
    if (!pronto) return;
    setARever(true);
    setErro(null);
    try {
      setPeriodo(await getVortalPeriodo({ ...parametros, limite: 20 }));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro ao ler o período");
    } finally {
      setARever(false);
    }
  }, [parametros, pronto]);

  const recolherLote = useCallback(async () => {
    if (!pronto) return;
    setARecolher(true);
    setErro(null);
    try {
      setResultado(
        await recolherVortalLote({
          ...parametros,
          lote,
          lotes: lotesVez,
          indexar,
          extrair,
          forcar,
          saltar_em_disco: forcar ? false : saltarEmDisco,
        }),
      );
      await aoRecolher();
      if (periodo) setPeriodo(await getVortalPeriodo({ ...parametros, limite: 20 }));
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Erro na recolha em lote");
    } finally {
      setARecolher(false);
    }
  }, [aoRecolher, extrair, forcar, indexar, lote, lotesVez, parametros, periodo, pronto, saltarEmDisco]);

  return (
    <SectionCard
      title="Recolher em lote por mês e ano"
      subtitle={`As ligações das peças já estão nos contratos (${meta?.lotes?.indice_contratos ?? "contratos"}.${
        meta?.lotes?.campo_ligacao ?? "linkPecasProc"
      }): escolher o período evita colar centenas de URLs.`}
      icon={Layers}
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => void reverPeriodo()}
            disabled={aRever || !pronto}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1 text-[11.5px] hover:bg-white/[0.09] disabled:opacity-50"
          >
            {aRever ? <Loader2 size={12} className="animate-spin" /> : <CalendarDays size={12} />} Rever período
          </button>
          <button
            type="button"
            onClick={() => void recolherLote()}
            disabled={aRecolher || !pronto}
            className="inline-flex items-center gap-1.5 rounded-lg border border-teal-400/30 bg-teal-400/15 px-3 py-1 text-[11.5px] text-teal-100 hover:bg-teal-400/25 disabled:opacity-50"
          >
            {aRecolher ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Recolher lote
          </button>
        </div>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Ano de publicação
          <select
            value={ano}
            onChange={(evento) => {
              setAno(evento.target.value);
              setMes("");
              setPeriodo(null);
            }}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] text-foreground outline-none"
          >
            {[...(periodos?.anos ?? [])].reverse().map((item) => (
              <option key={item.ano} value={item.ano}>
                {item.ano} · {formatNumber(item.avisos)} avisos
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Mês
          <select
            value={mes}
            onChange={(evento) => {
              setMes(evento.target.value);
              setPeriodo(null);
            }}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11.5px] text-foreground outline-none"
          >
            <option value="">todos os meses</option>
            {mesesDoAno.map((item) => {
              const numero = Number(item.mes.slice(5, 7));
              return (
                <option key={item.mes} value={numero}>
                  {NOMES_MESES[numero - 1]} · {formatNumber(item.avisos)}
                </option>
              );
            })}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Avisos por lote
          <input
            type="number"
            min={1}
            max={meta?.lotes?.lote_maximo ?? 100}
            value={lote}
            onChange={(evento) => setLote(Math.max(1, Math.min(Number(evento.target.value) || 1, meta?.lotes?.lote_maximo ?? 100)))}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11.5px] text-foreground outline-none"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Lotes por vez
          <input
            type="number"
            min={1}
            max={meta?.lotes?.lotes_por_vez ?? 20}
            value={lotesVez}
            onChange={(evento) => setLotesVez(Math.max(1, Math.min(Number(evento.target.value) || 1, meta?.lotes?.lotes_por_vez ?? 20)))}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 font-mono text-[11.5px] text-foreground outline-none"
          />
        </label>
      </div>

      <label className="mt-3 inline-flex items-center gap-2 text-[11.5px]">
        <input
          type="checkbox"
          checked={forcar ? false : saltarEmDisco}
          disabled={forcar}
          onChange={(evento) => setSaltarEmDisco(evento.target.checked)}
          className="accent-teal-400"
        />
        Só avisos ainda não recolhidos
        {forcar ? <span className="text-muted-foreground">— com «Forçar nova descarga» o período é refeito desde o início</span> : null}
      </label>

      {erro ? (
        <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-rose-200">
          <AlertTriangle size={13} /> {erro}
        </p>
      ) : null}

      {periodos && !periodos.anos.length ? (
        <div className="mt-3">
          <EmptyState tone="warn">O índice de contratos não devolveu avisos Vortal — confirme que está acessível.</EmptyState>
        </div>
      ) : null}

      {periodo ? (
        <div className="mt-4 space-y-2">
          <p className="text-[11.5px] text-muted-foreground">
            {periodo.mes ? `${NOMES_MESES[periodo.mes - 1]} de ${periodo.ano}` : `todo o ano ${periodo.ano}`} · {formatNumber(periodo.total)} contrato(s) com peças
            Vortal · {formatNumber(periodo.unicos)} aviso(s) · {formatNumber(periodo.em_disco)} já em disco ·{" "}
            <span className="text-foreground">{formatNumber(periodo.pendentes)} por recolher</span>
            {periodo.truncado ? ` · lidos os primeiros ${formatNumber(periodo.lidos ?? 0)} contratos` : ""}
          </p>
          <TabelaPeriodo avisos={periodo.avisos} />
        </div>
      ) : null}

      {resultado ? (
        <div className="mt-4 space-y-2">
          <p className="text-[11.5px] text-muted-foreground">
            {resultado.lotes.length} lote(s) · {formatNumber(resultado.processados)} aviso(s) · {formatNumber(resultado.pecas)} peça(s) ·{" "}
            {formatBytes(resultado.bytes)} · {formatNumber(resultado.indexados)} indexada(s) · {resultado.duracao_s} s · faltam{" "}
            {formatNumber(resultado.restantes)} neste período
          </p>
          <ul className="space-y-1 text-[11px] text-muted-foreground">
            {resultado.lotes.map((item) => (
              <li key={item.n}>
                · lote {item.n}: {item.avisos} aviso(s), {item.pecas} peça(s), {formatBytes(item.bytes)}, {item.indexados} indexada(s)
                {item.erros ? `, ${item.erros} erro(s)` : ""}
              </li>
            ))}
          </ul>
          {resultado.erros.length ? (
            <ul className="space-y-1 text-[11px] text-amber-200">
              {resultado.erros.slice(0, 5).map((item) => (
                <li key={item}>· {item}</li>
              ))}
            </ul>
          ) : null}
          {resultado.restantes ? (
            <p className="text-[11px] text-teal-200">
              O período continua a ter avisos por recolher: repita «Recolher lote» para avançar (a lista acima é atualizada a cada lote).
            </p>
          ) : null}
        </div>
      ) : null}
    </SectionCard>
  );
}

/** Avisos de um período: ligação pública, contratos de origem e estado em disco. */
function TabelaPeriodo({ avisos }: { avisos: VortalAvisoPeriodo[] }) {
  if (!avisos.length) return <EmptyState>Este período não tem avisos Vortal com peças publicadas.</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-[11.5px]">
        <thead className="text-left text-muted-foreground">
          <tr className="border-b border-white/10">
            <th className="py-1">Publicação</th>
            <th className="py-1">Aviso</th>
            <th className="py-1">Contratos</th>
            <th className="py-1">Estado</th>
          </tr>
        </thead>
        <tbody>
          {avisos.map((item) => (
            <tr key={item.token} className="border-b border-white/5">
              <td className="whitespace-nowrap py-1">{formatData(item.data_publicacao)}</td>
              <td className="max-w-[420px] py-1">
                <a href={item.url} target="_blank" rel="noreferrer" className="font-mono hover:text-teal-200" title={item.url}>
                  {item.uid ?? `${item.token.slice(0, 24)}…`}
                </a>
                {item.contratos[0]?.objecto ? (
                  <p className="truncate text-[10.5px] text-muted-foreground">{item.contratos[0].objecto}</p>
                ) : null}
              </td>
              <td className="py-1 font-mono">
                {item.contratos.length}
                {item.contratos[0]?.idcontrato ? ` · ${item.contratos[0].idcontrato}` : ""}
              </td>
              <td className="py-1">{item.em_disco ? <Chip tone="teal">em disco</Chip> : <Chip tone="neutral">por recolher</Chip>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Peças como estão no índice (cada documento tem o seu registo). */
function TabelaIndexadas({ itens }: { itens: VortalResultadoPeca[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-[11.5px]">
        <thead className="text-left text-muted-foreground">
          <tr className="border-b border-white/10">
            <th className="py-1">Aviso</th>
            <th className="py-1">Peça</th>
            <th className="py-1">Tipo</th>
            <th className="py-1 text-right">Páginas</th>
            <th className="py-1 text-right">Tamanho</th>
            <th className="py-1 text-right">Texto</th>
            <th className="py-1">Recolhido</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((item) => (
            <tr key={`${item.uid}-${item.sha256 ?? item.nome}`} className="border-b border-white/5">
              <td className="py-1 font-mono">{item.uid}</td>
              <td className="max-w-[300px] truncate py-1" title={item.nome}>
                {item.nome}
              </td>
              <td className="py-1">{item.tipo_label ?? item.tipo}</td>
              <td className="py-1 text-right font-mono">{item.paginas ? formatNumber(item.paginas) : "—"}</td>
              <td className="py-1 text-right font-mono">{formatBytes(item.bytes)}</td>
              <td className="py-1 text-right font-mono" title={item.texto_metodo ?? ""}>
                {formatNumber(item.texto_chars ?? 0)}
              </td>
              <td className="py-1">{formatDataHora(item.descarregado_em ?? item.recolhido_em)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
