/**
 * Painel **Inteligência e relatório** da análise de uma empresa.
 *
 * Três passos, pela ordem em que um analista os dá:
 *
 * 1. **Ler** — o browser do IQ OS abre páginas públicas (site da empresa,
 *    imprensa, portal) e o texto fica indexado em `finance_scraped`, ou seja,
 *    pesquisável como qualquer outra recolha;
 * 2. **Escrever** — o modelo configurado redige a ficha de risco a partir da
 *    análise, do cadastro das entidades contratantes e do texto lido (sem
 *    modelo disponível sai a ficha factual, com os mesmos números);
 * 3. **Guardar e emitir** — a análise (com a ficha e as páginas) é gravada em
 *    `finance_analises_empresa` e o relatório sai em PDF, Excel ou CSV.
 *
 * O que foi guardado pode ser reaberto mais tarde: o relatório de uma análise
 * guardada diz exatamente o mesmo que no dia em que foi feita.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Brain,
  Database,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  analisarPadroesEmpresaIA,
  apagarPadroesEmpresaGuardada,
  browserPadroesEmpresa,
  exportPadroesEmpresaRelatorio,
  guardarFicheiroPadroes,
  guardarPadroesEmpresa,
  listarPadroesEmpresasGuardadas,
  obterPadroesEmpresaGuardada,
} from "../../padroesApi";
import type {
  PadroesBrowserPagina,
  PadroesEmpresaAnalise,
  PadroesEmpresaGuardada,
  PadroesEmpresaIA,
  PadroesRelatorioFormato,
} from "../../padroesApi";
import { MARKDOWN_COMPONENTS } from "../people/peopleKit";
import { Chip, EmptyState, Loading, SectionCard, formatCompactEuro, formatDate, formatNumber } from "./padroesKit";

const SELECT_CLASS =
  "rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm normal-case tracking-normal text-foreground";
const TEXTAREA_CLASS =
  "min-h-[70px] w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-xs normal-case tracking-normal text-foreground outline-none placeholder:text-muted-foreground/60";

export function PadroesEmpresaIA({
  analise,
  pais,
  anoFrom,
  anoTo,
  maxContratos,
  onAbrirGuardada,
}: {
  analise: PadroesEmpresaAnalise;
  pais: string;
  anoFrom: string;
  anoTo: string;
  maxContratos: number;
  onAbrirGuardada?: (doc: PadroesEmpresaGuardada) => void;
}) {
  const [urls, setUrls] = useState("");
  const [notas, setNotas] = useState("");
  const [backend, setBackend] = useState("");
  const [ficha, setFicha] = useState<PadroesEmpresaIA | null>(null);
  const [paginas, setPaginas] = useState<PadroesBrowserPagina[]>([]);
  const [aCorrer, setACorrer] = useState<null | "browser" | "ia" | "guardar" | "relatorio">(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [guardado, setGuardado] = useState<string | null>(null);
  const [guardadas, setGuardadas] = useState<PadroesEmpresaGuardada[]>([]);
  const [fichaNoRelatorio, setFichaNoRelatorio] = useState(true);

  const listaUrls = useMemo(
    () =>
      urls
        .split(/[\n,;]+/)
        .map((item) => item.trim())
        .filter((item) => item.length > 3),
    [urls],
  );

  const carregarGuardadas = useCallback(async () => {
    try {
      const resposta = await listarPadroesEmpresasGuardadas({ limit: 25 });
      setGuardadas(resposta.items ?? []);
    } catch {
      setGuardadas([]);
    }
  }, []);

  useEffect(() => {
    void carregarGuardadas();
  }, [carregarGuardadas]);

  // A ficha pertence à empresa analisada: ao mudar de empresa, limpa-se.
  useEffect(() => {
    setFicha(null);
    setPaginas([]);
    setAviso(null);
    setErro(null);
    setGuardado(null);
  }, [analise.nif]);

  const lerPaginas = useCallback(async () => {
    if (!listaUrls.length) {
      setAviso("Escreva pelo menos um endereço (um por linha).");
      return;
    }
    setACorrer("browser");
    setAviso(null);
    setErro(null);
    try {
      const resposta = await browserPadroesEmpresa(listaUrls);
      setPaginas(resposta.paginas ?? []);
      setAviso(
        `${resposta.lidas ?? 0} página(s) lida(s) · ${resposta.indexadas ?? 0} indexada(s) em ${resposta.indice ?? "finance_scraped"}` +
          ((resposta.pareadas ?? []).length ? ` · falharam ${(resposta.pareadas ?? []).length}` : ""),
      );
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao ler as páginas");
    } finally {
      setACorrer(null);
    }
  }, [listaUrls]);

  const escreverFicha = useCallback(async () => {
    setACorrer("ia");
    setErro(null);
    setAviso(null);
    try {
      const resposta = await analisarPadroesEmpresaIA({
        nif: analise.nif,
        pais,
        ano_from: anoFrom ? Number(anoFrom) : null,
        ano_to: anoTo ? Number(anoTo) : null,
        max_contratos: maxContratos,
        urls: listaUrls,
        com_browser: listaUrls.length > 0,
        backend: backend.trim() || undefined,
        notas: notas || undefined,
      });
      setFicha(resposta.ia ?? null);
      if (resposta.browser?.paginas) setPaginas(resposta.browser.paginas);
      setAviso(
        resposta.ia?.mode === "ai"
          ? `Ficha redigida por ${resposta.ia?.backend?.provider ?? "IA"}:${resposta.ia?.backend?.model ?? ""}` +
              (resposta.browser?.lidas ? ` · ${resposta.browser.lidas} página(s) lida(s)` : "")
          : "Sem modelo disponível: ficha factual (os mesmos números, sem redação por IA).",
      );
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro na ficha de IA");
    } finally {
      setACorrer(null);
    }
  }, [analise.nif, anoFrom, anoTo, backend, listaUrls, maxContratos, notas, pais]);

  const guardar = useCallback(async () => {
    setACorrer("guardar");
    setErro(null);
    try {
      const resposta = await guardarPadroesEmpresa({
        nif: analise.nif,
        pais,
        ano_from: anoFrom ? Number(anoFrom) : null,
        ano_to: anoTo ? Number(anoTo) : null,
        max_contratos: maxContratos,
        notas: notas || undefined,
        ficha_ia: ficha?.text,
        analise,
        browser: paginas,
      });
      if (resposta.error) {
        setErro(resposta.error);
        return;
      }
      setGuardado(resposta.doc_id ?? null);
      await carregarGuardadas();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao guardar");
    } finally {
      setACorrer(null);
    }
  }, [analise, anoFrom, anoTo, carregarGuardadas, ficha, maxContratos, notas, paginas, pais]);

  const descarregar = useCallback(
    async (formato: PadroesRelatorioFormato, docId?: string) => {
      setACorrer("relatorio");
      setErro(null);
      try {
        const resposta = await exportPadroesEmpresaRelatorio({
          formato,
          doc_id: docId,
          nif: docId ? undefined : analise.nif,
          pais,
          ano_from: anoFrom ? Number(anoFrom) : null,
          ano_to: anoTo ? Number(anoTo) : null,
          max_contratos: maxContratos,
          ficha_ia: formato === "csv" ? false : fichaNoRelatorio && Boolean(ficha),
        });
        guardarFicheiroPadroes(resposta.blob, resposta.filename);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao gerar o relatório");
      } finally {
        setACorrer(null);
      }
    },
    [analise.nif, anoFrom, anoTo, ficha, fichaNoRelatorio, maxContratos, pais],
  );

  const abrirGuardada = useCallback(
    async (docId: string) => {
      setErro(null);
      try {
        const doc = await obterPadroesEmpresaGuardada(docId);
        if (doc.ficha_ia) {
          setFicha({ mode: doc.ia ? "ai" : "factual", text: doc.ficha_ia });
        }
        if (doc.notas) setNotas(doc.notas);
        if (doc.browser) setPaginas(doc.browser);
        onAbrirGuardada?.(doc);
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao abrir a análise guardada");
      }
    },
    [onAbrirGuardada],
  );

  const apagar = useCallback(
    async (docId: string) => {
      setErro(null);
      try {
        await apagarPadroesEmpresaGuardada(docId);
        await carregarGuardadas();
      } catch (err) {
        setErro(err instanceof Error ? err.message : "Erro ao apagar");
      }
    },
    [carregarGuardadas],
  );

  return (
    <SectionCard
      icon={Sparkles}
      title="Inteligência e relatório"
      subtitle="Ler páginas no browser, escrever a ficha com IA, guardar no Elasticsearch e emitir PDF/Excel/CSV."
      actions={
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {ficha?.mode === "ai" && (
            <Chip tone="violet" title={ficha.notes?.join(" · ")}>
              <Brain size={11} /> IA{ficha.backend?.model ? `: ${ficha.backend.model}` : ""}
            </Chip>
          )}
          {ficha?.mode === "factual" && <Chip title="Sem modelo: texto montado só com factos">factual</Chip>}
          {guardado && (
            <Chip tone="teal" title={guardado}>
              <Database size={11} /> guardada
            </Chip>
          )}
        </div>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        {/* ------------------------------------------------------------- passos */}
        <div className="flex flex-col gap-3">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
              Páginas a ler no browser (uma por linha)
            </label>
            <textarea
              value={urls}
              onChange={(event) => setUrls(event.target.value)}
              placeholder={"https://www.empresa.pt\nhttps://www.empresa.pt/obras\nhttps://pt.wikipedia.org/wiki/Empresa"}
              className={TEXTAREA_CLASS}
            />
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <button
                onClick={() => void lerPaginas()}
                disabled={aCorrer !== null}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-teal-200 transition hover:text-teal-100 disabled:opacity-40"
              >
                {aCorrer === "browser" ? <Loader2 size={13} className="animate-spin" /> : <Globe size={13} />} Ler páginas
              </button>
              <span className="text-muted-foreground">o texto lido fica em finance_scraped</span>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">Modelo (opcional)</label>
              <input
                value={backend}
                onChange={(event) => setBackend(event.target.value)}
                placeholder="ex.: deepseek:deepseek-chat"
                className={SELECT_CLASS + " w-full"}
              />
            </div>
            <div>
              <label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">Notas do analista</label>
              <input
                value={notas}
                onChange={(event) => setNotas(event.target.value)}
                placeholder="porque é que esta empresa está a ser analisada"
                className={SELECT_CLASS + " w-full"}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              onClick={() => void escreverFicha()}
              disabled={aCorrer !== null}
              className="flex items-center gap-1.5 rounded-lg border border-violet-400/25 bg-violet-400/10 px-2.5 py-1.5 text-violet-100 transition hover:bg-violet-400/20 disabled:opacity-40"
            >
              {aCorrer === "ia" ? <Loader2 size={13} className="animate-spin" /> : <Brain size={13} />}
              {listaUrls.length ? "Ler páginas e escrever ficha (IA)" : "Escrever ficha (IA)"}
            </button>
            <button
              onClick={() => void guardar()}
              disabled={aCorrer !== null}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-muted-foreground transition hover:text-foreground disabled:opacity-40"
              title="Guardar a análise (e a ficha) em finance_analises_empresa"
            >
              {aCorrer === "guardar" ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Guardar no Elastic
            </button>
          </div>

          {aviso && <p className="text-xs text-teal-200">{aviso}</p>}
          {erro && <EmptyState tone="warn">{erro}</EmptyState>}

          {/* ------------------------------------------------------ relatório */}
          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <Download size={13} /> Relatório
            </h3>
            <label className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={fichaNoRelatorio}
                onChange={(event) => setFichaNoRelatorio(event.target.checked)}
                className="accent-teal-400"
              />
              incluir a ficha de IA (se existir)
            </label>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {(
                [
                  ["pdf", FileText, "PDF"],
                  ["xlsx", FileSpreadsheet, "Excel"],
                  ["csv", FileText, "CSV"],
                ] as const
              ).map(([formato, Icone, etiqueta]) => (
                <button
                  key={formato}
                  onClick={() => void descarregar(formato)}
                  disabled={aCorrer !== null}
                  className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-teal-200 transition hover:text-teal-100 disabled:opacity-40"
                >
                  {aCorrer === "relatorio" ? <Loader2 size={13} className="animate-spin" /> : <Icone size={13} />}
                  {etiqueta}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* -------------------------------------------------------- ficha / guardadas */}
        <div className="flex flex-col gap-3">
          {aCorrer === "ia" && <Loading label="O modelo está a escrever a ficha (análise + entidades + páginas)…" />}
          {ficha ? (
            <article className="max-h-[520px] overflow-y-auto rounded-xl border border-white/10 bg-black/20 p-4">
              <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                {ficha.text}
              </Markdown>
              {(ficha.warnings ?? []).length > 0 && (
                <div className="mt-3">
                  <EmptyState tone="warn">{(ficha.warnings ?? []).join(" · ")}</EmptyState>
                </div>
              )}
            </article>
          ) : (
            <EmptyState>
              A ficha analítica ainda não foi escrita. Pode escrevê-la já (só com os dados do IQ OS) ou juntar primeiro páginas
              lidas no browser — o texto lido entra no prompt e fica indexado.
            </EmptyState>
          )}

          {paginas.length > 0 && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Globe size={13} /> Páginas lidas
              </h3>
              <ul className="max-h-40 space-y-1 overflow-y-auto pr-1 text-xs">
                {paginas.map((pagina) => (
                  <li key={pagina.url} className="flex items-start justify-between gap-2">
                    <a
                      href={pagina.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex min-w-0 items-start gap-1.5 text-teal-200 transition hover:text-teal-100"
                    >
                      <ExternalLink size={11} className="mt-0.5 shrink-0" />
                      <span className="truncate">{pagina.titulo || pagina.url}</span>
                    </a>
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                      {pagina.ok ? `${formatNumber(pagina.chars)} car.` : (pagina.erro ?? "falhou")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <h3 className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-2">
                <Database size={13} /> Análises guardadas
              </span>
              <button
                onClick={() => void carregarGuardadas()}
                className="flex items-center gap-1 text-[10px] text-muted-foreground transition hover:text-foreground"
              >
                <RefreshCw size={11} /> atualizar
              </button>
            </h3>
            {guardadas.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Nada guardado ainda. «Guardar no Elastic» fixa a análise em <code className="text-teal-200">finance_analises_empresa</code>.
              </p>
            ) : (
              <ul className="max-h-56 space-y-1 overflow-y-auto pr-1 text-xs">
                {guardadas.map((item) => (
                  <li key={item.doc_id} className="rounded-lg border border-white/5 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <button
                        onClick={() => void abrirGuardada(item.doc_id)}
                        className="min-w-0 truncate text-left text-teal-200 transition hover:text-teal-100"
                        title={`Abrir a ficha de ${item.nome ?? item.nif}`}
                      >
                        {item.nome ?? item.nif}
                      </button>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{formatDate(item.atualizado_em)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {item.severidade && item.severidade !== "info" && (
                        <Chip tone={item.severidade === "alerta" ? "rose" : "amber"}>{item.severidade}</Chip>
                      )}
                      {item.ia && <Chip tone="violet">IA</Chip>}
                      {item.insolvente && <Chip tone="rose">insolvência</Chip>}
                      <span className="text-[10px] text-muted-foreground">
                        {formatNumber(item.contratos_analisados)} contratos · {formatCompactEuro(item.valor_total)}
                      </span>
                      <button
                        onClick={() => void descarregar("pdf", item.doc_id)}
                        className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground transition hover:text-foreground"
                        title="Relatório PDF desta análise guardada"
                      >
                        <FileText size={11} /> PDF
                      </button>
                      <button
                        onClick={() => void apagar(item.doc_id)}
                        className="flex items-center gap-1 text-[10px] text-rose-300/80 transition hover:text-rose-200"
                        title="Apagar esta análise"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-300" />
            O texto do modelo não substitui a verificação: os números vêm da amostra analisada e o que foi lido no browser é
            guardado com o URL, para poder ser conferido.
          </p>
        </div>
      </div>
    </SectionCard>
  );
}

export default PadroesEmpresaIA;
