/**
 * @file AdminBaseImpic
 * Importação dos **Contratos Públicos do Portal Base** (dados.gov.pt) —
 * separador da aplicação «Administração».
 *
 * O conjunto «Contratos Públicos - Portal Base - IMPIC» publica, por ano, um ZIP
 * com um `Contratos<ano>.json` (centenas de MB). Esta página:
 *
 * 1. lê o **catálogo** de ficheiros publicados (ano, formato, tamanho, data de
 *    atualização) diretamente da API do dados.gov.pt — o URL do ZIP muda a cada
 *    atualização semanal, por isso nunca está escrito à mão;
 * 2. mostra o **formato real** do ZIP do ano atual: que ficheiro traz dentro,
 *    se é um *array* JSON, os campos de cada contrato (tipo e exemplo) e os
 *    primeiros contratos já normalizados — o que vai entrar no Elasticsearch;
 * 3. lança a **importação** (ano inteiro ou um ensaio com limite), com progresso
 *    ao vivo (fase, descarregamento, contratos lidos/novos/já existentes, erros,
 *    lotes), cancelamento a meio e a volumetria do índice por ano depois de
 *    terminar.
 *
 * A importação corre no servidor em segundo plano: fechar a janela não a
 * interrompe. Só entram contratos que ainda não estejam no índice (verificado
 * pelo campo `idcontrato`), por isso importar o mesmo ano outra vez não duplica
 * nem reescreve nada.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  CheckCircle2,
  Database,
  ExternalLink,
  FileJson,
  FolderOpen,
  HardDriveDownload,
  Loader2,
  RefreshCw,
  SquareDashedMousePointer,
  Square,
  Table2,
  Upload,
} from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label } from "../components/ui";
import {
  baseImpicBytes,
  baseImpicEstadoCor,
  baseImpicQuando,
  cancelarBaseImpic,
  getBaseImpicAmostra,
  getBaseImpicEstado,
  getBaseImpicFormato,
  getBaseImpicRecursos,
  importarBaseImpic,
  type BaseImpicAmostra,
  type BaseImpicEstado,
  type BaseImpicFormato,
  type BaseImpicRecursos,
  type BaseImpicTrabalho,
} from "../baseImpicApi";

/** Fases de uma importação, na ordem em que acontecem. */
const FASES = [
  { id: "a preparar", label: "Preparar" },
  { id: "a descarregar", label: "Descarregar ZIP" },
  { id: "a indexar", label: "Normalizar e indexar" },
  { id: "terminado", label: "Terminar" },
];

function faseAtual(fase?: string) {
  const indice = FASES.findIndex((item) => item.id === (fase || ""));
  return indice < 0 ? 0 : indice;
}

/** Barra de progresso simples (sem dependências). */
function Barra({ valor, max, cor = "bg-teal-400/70" }: { valor: number; max: number; cor?: string }) {
  const percentagem = max > 0 ? Math.min(100, Math.round((valor / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
      <div className={`h-full rounded-full ${cor} transition-all`} style={{ width: `${percentagem}%` }} />
    </div>
  );
}

function Kpi({ label, valor, hint }: { label: string; valor: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-[13.5px] font-semibold tabular-nums">{valor}</p>
      {hint && <p className="truncate text-[10.5px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function AdminBaseImpicTab({ onError }: { onError: (message: string | null) => void }) {
  const [catalogo, setCatalogo] = useState<BaseImpicRecursos | null>(null);
  const [estado, setEstado] = useState<BaseImpicEstado | null>(null);
  const [formato, setFormato] = useState<BaseImpicFormato | null>(null);
  const [amostra, setAmostra] = useState<BaseImpicAmostra | null>(null);
  const [ano, setAno] = useState<number | null>(null);
  const [limite, setLimite] = useState<string>("");
  const [descarregarZip, setDescarregarZip] = useState(true);
  const [busy, setBusy] = useState<"carregar" | "formato" | "amostra" | "importar" | "cancelar" | null>("carregar");
  const [aConfirmar, setAConfirmar] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [lidoEm, setLidoEm] = useState<string | null>(null);
  const pedidoFormato = useRef(0);

  const carregarTudo = useCallback(
    async (anoEscolhido?: number | null, forcar = false) => {
      setBusy("carregar");
      try {
        const recursos = await getBaseImpicRecursos(forcar);
        setCatalogo(recursos);
        const alvo = anoEscolhido ?? ano ?? recursos.ano_atual;
        setAno(alvo);
        const [formatoAno, amostraAno, estadoAtual] = await Promise.all([
          getBaseImpicFormato(alvo),
          getBaseImpicAmostra(alvo, 3),
          getBaseImpicEstado(),
        ]);
        setFormato(formatoAno);
        setAmostra(amostraAno);
        setEstado(estadoAtual);
        setLidoEm(new Date().toISOString());
        onError(null);
      } catch (caught) {
        onError(caught instanceof Error ? caught.message : "Erro ao carregar os dados do Portal Base.");
      } finally {
        setBusy(null);
      }
    },
    [ano, onError],
  );

  useEffect(() => {
    void carregarTudo(null);
    // Só na entrada: o ano escolhido depois é tratado por `escolherAno`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const trabalho: BaseImpicTrabalho | null = useMemo(() => {
    if (!estado || !ano) return null;
    return estado.trabalhos[String(ano)] ?? null;
  }, [estado, ano]);

  const aCorrer = trabalho?.estado === "a_correr";
  const jaTemZip = Boolean(catalogo?.em_cache.some((item) => item.ano === String(ano)));

  /**
   * ZIP em cache que foi descarregado **antes** da última atualização publicada.
   *
   * O critério é a data, não o tamanho: o `filesize` do CKAN não é exato ao byte
   * (anos com 874 bytes de diferença apareciam como «desatualizados» sem o serem),
   * mas a data de publicação diz sempre a verdade sobre quando o ficheiro mudou.
   * Quem decide de facto é o servidor, que compara o `sha1` publicado e descarrega
   * a versão nova se não coincidir.
   */
  const desatualizados = useMemo(() => {
    const publicado = new Map((catalogo?.recursos ?? []).map((item) => [item.ano, item]));
    return (catalogo?.em_cache ?? []).filter((item) => {
      const recurso = publicado.get(item.ano);
      if (!recurso?.atualizado_em || !item.modificado_em) return false;
      return new Date(item.modificado_em).getTime() < new Date(recurso.atualizado_em).getTime();
    });
  }, [catalogo]);

  /** Enquanto há uma importação a correr, a página sonda o estado a cada 3 s. */
  useEffect(() => {
    if (!aCorrer) return;
    let ativo = true;
    const temporizador = window.setInterval(async () => {
      try {
        const atual = await getBaseImpicEstado();
        if (!ativo) return;
        setEstado(atual);
        setLidoEm(new Date().toISOString());
        const terminado = atual.trabalhos[String(ano)]?.estado;
        if (terminado && terminado !== "a_correr") {
          window.clearInterval(temporizador);
          // Ao terminar, reler o formato/amostra e a volumetria do índice.
          void carregarTudo(ano);
        }
      } catch {
        /* rede instável não deve parar a página */
      }
    }, 3000);
    return () => {
      ativo = false;
      window.clearInterval(temporizador);
    };
  }, [aCorrer, ano, carregarTudo]);

  const escolherAno = async (novo: number) => {
    setAno(novo);
    setAConfirmar(false);
    setBusy("formato");
    try {
      const [formatoAno, amostraAno] = await Promise.all([getBaseImpicFormato(novo), getBaseImpicAmostra(novo, 3)]);
      setFormato(formatoAno);
      setAmostra(amostraAno);
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao ler o formato do ano.");
    } finally {
      setBusy(null);
    }
  };

  const descarregarEReler = async () => {
    if (!ano) return;
    setBusy("formato");
    setAviso(null);
    try {
      const identificador = ++pedidoFormato.current;
      const resultado = await getBaseImpicFormato(ano, true);
      if (identificador !== pedidoFormato.current) return;
      setFormato(resultado);
      setAmostra(await getBaseImpicAmostra(ano, 3));
      setCatalogo(await getBaseImpicRecursos(true));
      setAviso(
        resultado.membro_json
          ? `ZIP de ${ano} lido do dados.gov.pt: ${resultado.membro_json} (${baseImpicBytes(resultado.membro_bytes)}).`
          : "ZIP descarregado.",
      );
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao descarregar o ZIP.");
    } finally {
      setBusy(null);
    }
  };

  const limiteNumero = useMemo(() => {
    const valor = limite.trim();
    if (!valor) return null;
    const numero = Number(valor);
    return Number.isFinite(numero) && numero > 0 ? Math.floor(numero) : null;
  }, [limite]);

  const importar = async () => {
    if (!ano) return;
    if (limiteNumero === null && !aConfirmar) {
      setAConfirmar(true);
      setAviso(
        `O ano ${ano} tem ` +
          `${(estado?.indice.por_ano?.find((item) => item.ano === ano)?.contratos ?? 0).toLocaleString("pt-PT")} ` +
          "contratos já no índice. Clique outra vez para importar o ano completo — só serão acrescentados os que ainda não existem.",
      );
      return;
    }
    setBusy("importar");
    setAviso(null);
    try {
      const resultado = await importarBaseImpic({ ano, limite: limiteNumero, descarregar: descarregarZip });
      setAviso(resultado.mensagem);
      setEstado(await getBaseImpicEstado());
      setAConfirmar(false);
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao iniciar a importação.");
    } finally {
      setBusy(null);
    }
  };

  const cancelar = async () => {
    if (!ano) return;
    setBusy("cancelar");
    try {
      const resultado = await cancelarBaseImpic(ano);
      setAviso(resultado.mensagem);
      setEstado(await getBaseImpicEstado());
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao cancelar a importação.");
    } finally {
      setBusy(null);
    }
  };

  const recursosZip = useMemo(
    () => (catalogo?.recursos ?? []).filter((item) => item.formato === "zip"),
    [catalogo],
  );
  const totalIndice = estado?.indice.total ?? catalogo?.indice.total ?? 0;
  const contratosDoAno = estado?.indice.por_ano?.find((item) => item.ano === ano)?.contratos ?? 0;
  const maximoPorAno = Math.max(1, ...(estado?.indice.por_ano ?? []).map((item) => item.contratos));

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
      {/* Cabeçalho */}
      <div className="glass-card gradient-border rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <HardDriveDownload size={16} /> Contratos Públicos — Portal Base (IMPIC)
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              O ZIP de cada ano é lido do dados.gov.pt no momento (o URL muda a cada atualização semanal), o JSON é
              percorrido em <em>streaming</em> — sem o carregar para memória — e cada contrato é normalizado com{" "}
              <span className="font-mono text-[11px]">normalize_contract</span> e indexado em{" "}
              <span className="font-mono text-[11px]">contratos</span> em lotes de 1000. <strong>Só entram contratos que
              ainda não existem</strong> (verificado pelo <span className="font-mono text-[11px]">idcontrato</span>): os
              repetidos são ignorados e contados à parte — importar o mesmo ano outra vez não acrescenta nem reescreve
              nada.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              {catalogo && (
                <a
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 hover:bg-white/[0.09]"
                  href={catalogo.url_dataset}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={11} /> dados.gov.pt · {catalogo.dataset}
                </a>
              )}
              <Badge variant="outline" className="font-mono text-[10.5px]">
                ano atual: {catalogo?.ano_atual ?? "—"}
              </Badge>
              <span>índice: {totalIndice.toLocaleString("pt-PT")} contratos</span>
              {lidoEm && <span>lido às {new Date(lidoEm).toLocaleTimeString("pt-PT", { hour12: false })}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => void carregarTudo(ano, true)} disabled={busy !== null}>
              {busy === "carregar" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Recarregar
            </Button>
          </div>
        </div>
      </div>

      {aviso && (
        <p className="flex items-start gap-2 rounded-xl border border-sky-400/20 bg-sky-400/10 px-3 py-2 text-[11.5px] text-sky-100">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>{aviso}</span>
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {/* Ficheiros publicados */}
        <Card padding="none" className="overflow-hidden">
          <CardHeader className="border-b border-white/8 px-4 py-2.5">
            <CardTitle className="flex items-center gap-2 text-[13px] font-semibold">
              <FolderOpen size={14} /> Ficheiros publicados por ano
            </CardTitle>
            <span className="text-[10.5px] text-muted-foreground">{recursosZip.length} ZIP</span>
          </CardHeader>
          {desatualizados.length > 0 && (
            <p className="flex items-start gap-2 border-b border-amber-400/20 bg-amber-400/10 px-3 py-1.5 text-[10.5px] text-amber-100">
              <AlertTriangle size={11} className="mt-0.5 shrink-0" />
              <span>
                {desatualizados.length} ZIP em cache foram descarregados antes da última atualização publicada em
                dados.gov.pt (
                {desatualizados
                  .map((item) => item.ano)
                  .slice(0, 6)
                  .join(", ")}
                {desatualizados.length > 6 ? "…" : ""}). No momento da importação o servidor compara o{" "}
                <span className="font-mono">sha1</span> publicado com o ficheiro local e descarrega-o se não coincidir —
                não é preciso apagar nada à mão.
              </span>
            </p>
          )}
          <CardContent className="max-h-[340px] overflow-y-auto">
            <table className="w-full text-left text-[11.5px]">
              <thead className="sticky top-0 bg-[#0b0f14]/95 text-[10px] uppercase tracking-wide text-muted-foreground backdrop-blur">
                <tr>
                  <th className="px-3 py-2">Ano</th>
                  <th className="px-3 py-2">Ficheiro</th>
                  <th className="px-3 py-2 text-right">ZIP</th>
                  <th className="px-3 py-2 text-right">JSON (dentro)</th>
                  <th className="px-3 py-2">Atualizado</th>
                  <th className="px-3 py-2">Cache</th>
                </tr>
              </thead>
              <tbody>
                {recursosZip.map((recurso) => {
                  const emCache = catalogo?.em_cache.find((item) => item.ano === recurso.ano);
                  const desatualizado = Boolean(
                    emCache &&
                      emCache.modificado_em &&
                      recurso.atualizado_em &&
                      new Date(emCache.modificado_em).getTime() < new Date(recurso.atualizado_em).getTime(),
                  );
                  return (
                    <tr
                      key={recurso.id || recurso.ano}
                      onClick={() => void escolherAno(Number(recurso.ano))}
                      className={[
                        "cursor-pointer border-t border-white/5 transition hover:bg-white/[0.04]",
                        String(recurso.ano) === String(ano) ? "bg-teal-400/[0.07]" : "",
                      ].join(" ")}
                    >
                      <td className="px-3 py-1.5 font-mono tabular-nums">{recurso.ano}</td>
                      <td className="px-3 py-1.5 font-mono text-[11px]">{recurso.titulo || `contratos${recurso.ano}.zip`}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{baseImpicBytes(recurso.bytes)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                        {String(recurso.ano) === String(ano) && formato?.membro_bytes
                          ? baseImpicBytes(formato.membro_bytes)
                          : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{baseImpicQuando(recurso.atualizado_em)}</td>
                      <td className="px-3 py-1.5">
                        {!emCache ? (
                          <span className="text-muted-foreground">—</span>
                        ) : desatualizado ? (
                          <span
                            className="inline-flex items-center gap-1 text-amber-200"
                            title={`Descarregado em ${baseImpicQuando(emCache.modificado_em)} — o ficheiro publicado foi atualizado em ${baseImpicQuando(recurso.atualizado_em)}. A importação confirma o sha1 publicado e descarrega a versão nova se não coincidir.`}
                          >
                            <AlertTriangle size={11} /> {baseImpicBytes(emCache.bytes)} · de {baseImpicQuando(emCache.modificado_em).split(",")[0]}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-teal-200">
                            <CheckCircle2 size={11} /> {baseImpicBytes(emCache.bytes)}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!recursosZip.length && (
                  <tr>
                    <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                      {busy === "carregar" ? "A ler o catálogo do dados.gov.pt…" : "Sem ficheiros para mostrar."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* Formato do ZIP */}
        <Card padding="none" className="overflow-hidden">
          <CardHeader className="border-b border-white/8 px-4 py-2.5">
            <CardTitle className="flex items-center gap-2 text-[13px] font-semibold">
              <FileJson size={14} /> Formato do ZIP de {ano ?? "—"}
            </CardTitle>
            <div className="flex items-center gap-2">
              {formato?.forma && (
                <Badge variant="outline" className="font-mono text-[10.5px]">
                  {formato.forma}
                </Badge>
              )}
              <Button variant="ghost" size="sm" onClick={() => void descarregarEReler()} disabled={busy !== null || !ano}>
                {busy === "formato" ? <Loader2 size={12} className="animate-spin" /> : <ArrowDownToLine size={12} />}{" "}
                {jaTemZip ? "Reler do dados.gov.pt" : "Descarregar"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="max-h-[340px] overflow-y-auto">
            {formato?.erro ? (
              <p className="px-4 py-4 text-[11.5px] text-rose-200">{formato.erro}</p>
            ) : !formato?.membro_json ? (
              <p className="px-4 py-4 text-[11.5px] text-muted-foreground">
                {formato?.nota ?? "A carregar o formato…"}
              </p>
            ) : (
              <div className="space-y-3 px-4 py-3">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label="Membro JSON" valor={formato.membro_json} />
                  <Kpi label="Tamanho JSON" valor={baseImpicBytes(formato.membro_bytes)} />
                  <Kpi label="Campos" valor={String(formato.total_campos ?? 0)} />
                  <Kpi label="Índice" valor={formato.indice_destino ?? "contratos"} />
                </div>
                <p className="text-[10.5px] text-muted-foreground">
                  Normalização: <span className="font-mono">{formato.normalizacao}</span> · ficheiro local:{" "}
                  <span className="font-mono">{formato.ficheiro_local ?? "—"}</span>
                </p>
                <div className="rounded-xl border border-white/8">
                  <p className="flex items-center gap-1.5 border-b border-white/8 px-3 py-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
                    <Table2 size={11} /> Campos de cada contrato
                  </p>
                  <div className="max-h-[180px] overflow-y-auto">
                    <table className="w-full text-left text-[11px]">
                      <tbody>
                        {(formato.campos ?? []).map((campo) => (
                          <tr key={campo.nome} className="border-t border-white/5">
                            <td className="w-[34%] px-3 py-1 font-mono">{campo.nome}</td>
                            <td className="w-[12%] px-3 py-1 text-muted-foreground">{campo.tipo}</td>
                            <td className="truncate px-3 py-1 text-muted-foreground" title={campo.exemplo}>
                              {campo.exemplo || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Importação */}
      <Card padding="none" className="overflow-hidden">
        <CardHeader className="border-b border-white/8 px-4 py-2.5">
          <CardTitle className="flex items-center gap-2 text-[13px] font-semibold">
            <Upload size={14} /> Importar para o Elasticsearch
          </CardTitle>
          {trabalho && (
            <span className={`rounded-lg border px-2 py-0.5 text-[10.5px] ${baseImpicEstadoCor(trabalho.estado)}`}>
              {trabalho.estado.replace("_", " ")} · {trabalho.fase || "—"}
            </span>
          )}
        </CardHeader>
        <CardContent className="space-y-3 px-4 py-3">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <Label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Ano</Label>
              <select
                value={ano ?? ""}
                onChange={(event) => void escolherAno(Number(event.target.value))}
                className="mt-1 h-8 rounded-lg border border-white/10 bg-white/[0.04] px-2 text-[12px] tabular-nums"
              >
                {(catalogo?.anos ?? []).map((item) => (
                  <option key={item} value={item} className="bg-[#0b0f14]">
                    {item}
                    {item === catalogo?.ano_atual ? " (atual)" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                Limite (ensaio; vazio = ano completo)
              </Label>
              <Input
                value={limite}
                onChange={(event) => {
                  setLimite(event.target.value.replace(/[^0-9]/g, ""));
                  setAConfirmar(false);
                }}
                placeholder="ex.: 3000"
                inputMode="numeric"
                className="mt-1 h-8 w-[150px] text-[12px] tabular-nums"
              />
            </div>
            <label className="flex h-8 items-center gap-2 text-[11.5px] text-muted-foreground">
              <input
                type="checkbox"
                checked={descarregarZip}
                onChange={(event) => setDescarregarZip(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-white/20 bg-white/[0.05]"
              />
              Descarregar o ZIP do dados.gov.pt (recomendado: o conjunto é atualizado semanalmente)
            </label>
            <div className="ml-auto flex items-center gap-2">
              {aCorrer && (
                <Button variant="secondary" onClick={() => void cancelar()} disabled={busy !== null}>
                  {busy === "cancelar" ? <Loader2 size={14} className="animate-spin" /> : <Square size={13} />} Parar
                </Button>
              )}
              <Button
                onClick={() => void importar()}
                disabled={busy !== null || aCorrer || !ano}
                variant={aConfirmar ? "danger" : "primary"}
                icon={busy === "importar" ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              >
                {aConfirmar
                  ? `Confirmar importação de ${ano} (ano completo)`
                  : limiteNumero !== null
                    ? `Importar ${limiteNumero.toLocaleString("pt-PT")} contratos de ${ano}`
                    : `Importar ${ano} (ano completo)`}
              </Button>
            </div>
          </div>

          {/* Progresso */}
          <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.02] px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2 text-[10.5px]">
              {FASES.map((item, indice) => {
                const atual = faseAtual(trabalho?.fase);
                const feito = trabalho?.estado === "concluido" || indice < atual;
                return (
                  <span
                    key={item.id}
                    className={[
                      "inline-flex items-center gap-1 rounded-lg border px-2 py-0.5",
                      feito
                        ? "border-teal-400/30 bg-teal-400/10 text-teal-200"
                        : indice === atual && aCorrer
                          ? "border-sky-400/30 bg-sky-400/10 text-sky-200"
                          : "border-white/10 bg-white/[0.04] text-muted-foreground",
                    ].join(" ")}
                  >
                    {feito ? <CheckCircle2 size={10} /> : indice === atual && aCorrer ? <Loader2 size={10} className="animate-spin" /> : <SquareDashedMousePointer size={10} />}
                    {item.label}
                  </span>
                );
              })}
              {trabalho?.iniciado_em && (
                <span className="text-muted-foreground">
                  iniciado {baseImpicQuando(trabalho.iniciado_em)}
                  {trabalho.terminado_em ? ` · terminado ${baseImpicQuando(trabalho.terminado_em)}` : ""}
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Kpi
                label="Descarregamento"
                valor={trabalho?.bytes_total ? `${baseImpicBytes(trabalho.bytes_lidos)} / ${baseImpicBytes(trabalho.bytes_total)}` : "—"}
                hint={trabalho?.bytes_total && trabalho.bytes_lidos < trabalho.bytes_total ? "a receber do dados.gov.pt" : undefined}
              />
              <Kpi label="Contratos lidos" valor={(trabalho?.registos ?? 0).toLocaleString("pt-PT")} hint="streaming do JSON" />
              <Kpi
                label="Novos no Elasticsearch"
                valor={(trabalho?.indexados ?? 0).toLocaleString("pt-PT")}
                hint={`${trabalho?.lotes ?? 0} lote(s) de 1000`}
              />
              <Kpi
                label="Já existiam"
                valor={(trabalho?.ignorados ?? 0).toLocaleString("pt-PT")}
                hint="ignorados (não repetidos)"
              />
              <Kpi label="Erros" valor={(trabalho?.erros ?? 0).toLocaleString("pt-PT")} hint="registos inválidos ou falhas do bulk" />
              <Kpi label={`No índice em ${ano ?? "—"}`} valor={contratosDoAno.toLocaleString("pt-PT")} hint="antes/depois da importação" />
              <Kpi label="Índice total" valor={totalIndice.toLocaleString("pt-PT")} hint={estado?.indice.indice ?? "contratos"} />
            </div>

            {trabalho?.bytes_total ? (
              <Barra valor={trabalho.bytes_lidos} max={trabalho.bytes_total} />
            ) : (
              <Barra valor={trabalho?.indexados ?? 0} max={limiteNumero ?? Math.max(1, contratosDoAno)} />
            )}

            {trabalho?.mensagem && (
              <p className="text-[11px] text-muted-foreground">
                {trabalho.mensagem}
                {trabalho.utilizador ? ` · pedido por ${trabalho.utilizador}` : ""}
              </p>
            )}
          </div>

          {/* Amostra */}
          <div className="rounded-xl border border-white/8">
            <p className="flex items-center gap-1.5 border-b border-white/8 px-3 py-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <Database size={11} /> Primeiros contratos de {ano ?? "—"} (já normalizados)
            </p>
            <div className="divide-y divide-white/5">
              {(amostra?.itens ?? []).map((item) => (
                <div key={item.idcontrato} className="grid gap-1 px-3 py-2 text-[11.5px] sm:grid-cols-[110px_minmax(0,1fr)_110px_160px]">
                  <span className="font-mono tabular-nums text-muted-foreground">{item.idcontrato}</span>
                  <span className="truncate" title={item.objectoContrato ?? ""}>
                    {item.objectoContrato || "—"}
                  </span>
                  <span className="tabular-nums text-teal-200">
                    {item.precoContratual != null ? `${item.precoContratual.toLocaleString("pt-PT")} €` : "—"}
                  </span>
                  <span className="truncate text-muted-foreground" title={(item.adjudicatarios ?? []).join(", ")}>
                    {(item.adjudicantes ?? [])[0] ?? "—"}
                    {item.adjudicatarios?.[0] ? ` → ${item.adjudicatarios[0]}` : ""}
                  </span>
                </div>
              ))}
              {!amostra?.itens?.length && (
                <p className="px-3 py-3 text-[11.5px] text-muted-foreground">
                  {amostra?.erro ?? "Sem amostra: descarregue o ZIP deste ano para ver os primeiros contratos."}
                </p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Índice e cache */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card padding="none" className="overflow-hidden">
          <CardHeader className="border-b border-white/8 px-4 py-2.5">
            <CardTitle className="flex items-center gap-2 text-[13px] font-semibold">
              <Database size={14} /> Contratos no índice, por ano
            </CardTitle>
            <span className="text-[10.5px] text-muted-foreground">
              {estado?.indice.disponivel ? `${totalIndice.toLocaleString("pt-PT")} no total` : "Elasticsearch indisponível"}
            </span>
          </CardHeader>
          <CardContent className="space-y-1.5 px-4 py-3">
            {(estado?.indice.por_ano ?? []).map((item) => (
              <div key={item.ano} className="flex items-center gap-3 text-[11.5px]">
                <span className="w-10 font-mono tabular-nums text-muted-foreground">{item.ano}</span>
                <div className="min-w-0 flex-1">
                  <Barra
                    valor={item.contratos}
                    max={maximoPorAno}
                    cor={item.ano === ano ? "bg-teal-400/80" : "bg-sky-400/40"}
                  />
                </div>
                <span className="w-20 text-right tabular-nums">{item.contratos.toLocaleString("pt-PT")}</span>
              </div>
            ))}
            {!estado?.indice.por_ano?.length && (
              <p className="text-[11.5px] text-muted-foreground">{estado?.indice.erro ?? "A carregar…"}</p>
            )}
          </CardContent>
        </Card>

        <Card padding="none" className="overflow-hidden">
          <CardHeader className="border-b border-white/8 px-4 py-2.5">
            <CardTitle className="flex items-center gap-2 text-[13px] font-semibold">
              <FolderOpen size={14} /> ZIP em cache neste servidor
            </CardTitle>
            <span className="text-[10.5px] text-muted-foreground">{estado?.em_cache.length ?? catalogo?.em_cache.length ?? 0} ficheiro(s)</span>
          </CardHeader>
          <CardContent className="max-h-[280px] overflow-y-auto">
            <table className="w-full text-left text-[11.5px]">
              <thead className="sticky top-0 bg-[#0b0f14]/95 text-[10px] uppercase tracking-wide text-muted-foreground backdrop-blur">
                <tr>
                  <th className="px-3 py-2">Ano</th>
                  <th className="px-3 py-2">Ficheiro</th>
                  <th className="px-3 py-2 text-right">Tamanho</th>
                  <th className="px-3 py-2">Descarregado em</th>
                </tr>
              </thead>
              <tbody>
                {(estado?.em_cache ?? catalogo?.em_cache ?? []).map((item) => (
                  <tr key={item.ficheiro} className="border-t border-white/5">
                    <td className="px-3 py-1.5 font-mono tabular-nums">{item.ano}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px]">{item.ficheiro}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{baseImpicBytes(item.bytes)}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{baseImpicQuando(item.modificado_em)}</td>
                  </tr>
                ))}
                {!(estado?.em_cache ?? catalogo?.em_cache ?? []).length && (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                      Ainda não há ZIP em cache — a importação descarrega o ficheiro do ano escolhido.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
