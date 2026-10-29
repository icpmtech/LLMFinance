/**
 * Auto-aprendizagem do modelo de contratos: estado, retreino e ações.
 *
 * Um só componente serve dois sítios:
 * - `variante="painel"` → bloco compacto dentro do painel lateral do chat;
 * - `variante="pagina"` → dashboard completo em `/modelo/retreino`.
 *
 * Todas as ações passam pela API (`/llm/modelo/*`): retreinar, parar, reverter
 * para uma versão guardada, reindexar o corpus RAG e correr uma avaliação.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCheck,
  Database,
  Gauge,
  History,
  Loader2,
  Play,
  RotateCcw,
  Sparkles,
  Square,
} from "lucide-react";
import RetreinoAoVivo from "./RetreinoAoVivo";
import {
  correrAvaliacao,
  getEstadoRag,
  getEstadoRetreino,
  getHistoricoRetreino,
  getVersoesAdaptador,
  indexarRag,
  pararRetreino,
  pedirRetreino,
  reverterAdaptador,
  type EstadoRetreino,
  type RegistoAdaptacao,
  type VersaoAdaptador,
} from "../../llmModeloApi";

type Props = {
  variante?: "painel" | "pagina";
  className?: string;
};

const formatarData = (valor?: string | null) => {
  if (!valor) return "—";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
};

const formatarBytes = (bytes: number) => {
  if (!bytes) return "—";
  const mb = bytes / 1024 / 1024;
  return `${mb.toFixed(1)} MB`;
};

const formatarPerda = (valor?: number | null) =>
  typeof valor === "number" ? valor.toFixed(4) : "—";

/** A nota média vem a -1 quando ninguém avaliou: mostrar um número ali seria mentira. */
const formatarNota = (valor?: number | null) =>
  typeof valor === "number" && Number.isFinite(valor) && valor >= 0 ? valor.toFixed(1) : "—";

export default function PainelDeRetreino({ variante = "painel", className = "" }: Props) {
  const completo = variante === "pagina";

  const [estado, setEstado] = useState<EstadoRetreino | null>(null);
  const [historico, setHistorico] = useState<RegistoAdaptacao[]>([]);
  const [versoes, setVersoes] = useState<VersaoAdaptador[]>([]);
  const [passos, setPassos] = useState(12);
  const [lr, setLr] = useState(0.00005);
  const [reutilizar, setReutilizar] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "erro" | "ok"; texto: string } | null>(null);
  const [documentosRag, setDocumentosRag] = useState<number | null>(null);
  const [avaliacao, setAvaliacao] = useState<{ f1: number; amostras: number } | null>(null);
  const montado = useRef(true);

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const recarregar = useCallback(async () => {
    const [novoEstado, novoHistorico, novasVersoes] = await Promise.all([
      getEstadoRetreino().catch(() => null),
      getHistoricoRetreino(8).catch(() => ({ total: 0, registos: [] })),
      getVersoesAdaptador().catch(() => ({ total: 0, versoes: [], atual: 0 })),
    ]);
    if (!montado.current) return;
    if (novoEstado) setEstado(novoEstado);
    setHistorico(novoHistorico.registos);
    setVersoes(novasVersoes.versoes);
  }, []);

  useEffect(() => {
    void getEstadoRag()
      .then((rag) => {
        if (!montado.current) return;
        const total = typeof rag.documentos === "number" ? rag.documentos : Number(rag.documentos);
        setDocumentosRag(Number.isFinite(total) ? total : null);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    void recarregar();
    const aoAtualizar = () => void recarregar();
    window.addEventListener("iqos:retreino-atualizar", aoAtualizar);
    return () => window.removeEventListener("iqos:retreino-atualizar", aoAtualizar);
  }, [recarregar]);

  const aCorrer = Boolean(estado?.a_correr);
  useEffect(() => {
    if (!aCorrer) return;
    const timer = window.setInterval(() => {
      void getEstadoRetreino()
        .then((novo) => {
          if (!montado.current) return;
          setEstado(novo);
          if (!novo.a_correr) void recarregar();
        })
        .catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [aCorrer, recarregar]);

  const paresNovos = estado?.feedback?.por_utilizar ?? 0;
  const paresDisponiveis = reutilizar ? (estado?.feedback?.corrigidos ?? 0) : paresNovos;
  const podeRetreinar = !aCorrer && paresDisponiveis >= 3;

  const progresso = useMemo(() => {
    if (!estado?.passos) return 0;
    return Math.min(100, Math.round((estado.passo / estado.passos) * 100));
  }, [estado?.passo, estado?.passos]);

  const executar = async (chave: string, acao: () => Promise<string>) => {
    setOcupado(chave);
    setMensagem(null);
    try {
      const texto = await acao();
      if (!montado.current) return;
      setMensagem({ tipo: "ok", texto });
    } catch (falha) {
      if (!montado.current) return;
      setMensagem({
        tipo: "erro",
        texto: falha instanceof Error ? falha.message : "A ação falhou",
      });
    } finally {
      if (!montado.current) return;
      setOcupado(null);
      void recarregar();
    }
  };

  const retreinar = () =>
    executar("retreinar", async () => {
      const resposta = await pedirRetreino({
        passos,
        lr,
        reutilizar_existentes: reutilizar,
      });
      if (resposta.ja_estava_a_correr) return "Já havia uma adaptação a correr.";
      setEstado((antes) => (antes ? { ...antes, a_correr: true, passo: 0, passos } : antes));
      return `Adaptação arrancada: ${passos} passos sobre ${paresDisponiveis} pares.`;
    });

  const parar = () =>
    executar("parar", async () => {
      const resposta = await pararRetreino();
      return resposta.ok ? "Paragem pedida — termina no próximo passo." : "Não havia adaptação a correr.";
    });

  const reverter = (versao: string) =>
    executar(`reverter:${versao}`, async () => {
      const resposta = await reverterAdaptador(versao);
      return `Adaptador reposto a ${resposta.versao}.`;
    });

  const reindexar = () =>
    executar("rag", async () => {
      const resposta = await indexarRag({ max_por_fonte: 200 });
      setDocumentosRag(resposta.total);
      return `Corpus RAG reindexado: ${resposta.total} documentos.`;
    });

  const avaliar = () =>
    executar("avaliar", async () => {
      const resposta = await correrAvaliacao({ limite: 40, gerar: 4 });
      const f1 = resposta.f1_medio ?? 0;
      setAvaliacao({ f1, amostras: resposta.amostras?.length ?? 0 });
      return `Avaliação concluída: F1 ${f1.toFixed(3)} em ${resposta.amostras?.length ?? 0} amostras.`;
    });

  const ultimo = estado?.ultimo_resultado;
  // Registos antigos de `metricas_adaptacao.jsonl` não têm `estado`: se há
  // passos, foi uma adaptação concluída.
  const estadoUltimo = ultimo?.estado ?? (ultimo?.passos ? "concluido" : undefined);
  const ultimoRevertido = estadoUltimo === "revertido";
  const ultimoParado = estadoUltimo === "parado";
  const ultimoOk = estadoUltimo === "concluido";

  const cartao = completo
    ? "rounded-2xl border border-border bg-card/40 p-4"
    : "rounded-xl border border-border bg-card/60 p-3";

  return (
    <div className={`${completo ? "space-y-4" : ""} ${className}`}>
      <div className={cartao}>
        <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
          <span className="flex items-center gap-1">
            <CheckCheck size={12} /> auto-aprendizagem
          </span>
          {aCorrer ? (
            <span className="flex items-center gap-1 text-primary">
              <Loader2 size={11} className="animate-spin" />
              {estado?.paragem_pedida ? "a parar…" : "a treinar…"}
            </span>
          ) : (
            <span className="text-muted-foreground">parado</span>
          )}
        </div>

        <div
          className={`mb-3 grid gap-x-2 gap-y-1 text-muted-foreground ${
            completo ? "grid-cols-2 text-[12px] sm:grid-cols-4" : "grid-cols-2 text-[11px]"
          }`}
        >
          <span>feedback: {estado?.feedback?.total ?? 0}</span>
          <span>corrigidos: {estado?.feedback?.corrigidos ?? 0}</span>
          <span>pares novos: {paresNovos}</span>
          <span>nota média: {formatarNota(estado?.feedback?.nota_media)}</span>
        </div>

        {aCorrer && (
          <div className="mb-3">
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${progresso}%` }}
              />
            </div>
            <p className="mt-1 text-[10px] text-muted-foreground">
              passo {estado?.passo}/{estado?.passos} · perda {formatarPerda(estado?.perda)}
            </p>
          </div>
        )}

        <div className="mb-2 grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            passos
            <input
              type="number"
              min={1}
              max={40}
              value={passos}
              disabled={aCorrer}
              onChange={(evento) => setPassos(Math.max(1, Math.min(40, Number(evento.target.value) || 1)))}
              className="rounded-lg border border-border bg-background px-2 py-1 text-[11px] text-foreground outline-none focus:border-primary disabled:opacity-50"
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
            learning rate
            <input
              type="number"
              step={0.00001}
              min={0.000001}
              max={0.001}
              value={lr}
              disabled={aCorrer}
              onChange={(evento) => setLr(Number(evento.target.value) || 0.00005)}
              className="rounded-lg border border-border bg-background px-2 py-1 text-[11px] text-foreground outline-none focus:border-primary disabled:opacity-50"
            />
          </label>
        </div>

        <label className="mb-2 flex cursor-pointer items-center gap-1.5 text-[10px] text-muted-foreground">
          <input
            type="checkbox"
            checked={reutilizar}
            disabled={aCorrer}
            onChange={(evento) => setReutilizar(evento.target.checked)}
            className="accent-[hsl(var(--primary))]"
          />
          reutilizar pares já treinados ({estado?.feedback?.corrigidos ?? 0})
        </label>

        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => void retreinar()}
            disabled={!podeRetreinar || ocupado !== null}
            className="inline-flex flex-1 items-center justify-center gap-1 rounded-lg border border-primary/40 bg-primary/10 px-2 py-1.5 text-[11px] font-medium text-primary transition hover:bg-primary/20 disabled:opacity-40"
          >
            {ocupado === "retreinar" ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
            retreinar
          </button>
          <button
            type="button"
            onClick={() => void parar()}
            disabled={!aCorrer || ocupado !== null}
            className="inline-flex items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[11px] text-foreground transition hover:bg-muted disabled:opacity-40"
          >
            {ocupado === "parar" ? <Loader2 size={11} className="animate-spin" /> : <Square size={11} />}
            parar
          </button>
        </div>

        {!podeRetreinar && !aCorrer && (
          <p className="mt-2 flex items-start gap-1 text-[10px] leading-relaxed text-amber-500">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" />
            {paresNovos < 3
              ? `Só há ${paresDisponiveis} pares com correção (mínimo 3). Dê feedback com correção ou ative «reutilizar».`
              : "Falta autorização para treinar — inicie sessão."}
          </p>
        )}

        {ultimo && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
            {ultimoRevertido ? (
              <>última ação: revertido para <span className="text-foreground">{ultimo.mensagem ?? ultimo.estado}</span></>
            ) : ultimoParado ? (
              <>
                última: <span className="text-amber-500">parado</span> · {ultimo.passos ?? 0} passos · perda{" "}
                {formatarPerda(ultimo.perda_antes)} → {formatarPerda(ultimo.perda_depois)}
              </>
            ) : ultimoOk ? (
              <>
                última: {ultimo.passos ?? 0} passos · perda {formatarPerda(ultimo.perda_antes)} →{" "}
                {formatarPerda(ultimo.perda_depois)} (
                <span className={(ultimo.delta ?? 0) < 0 ? "text-primary" : "text-amber-500"}>
                  {(ultimo.delta ?? 0) > 0 ? "+" : ""}
                  {formatarPerda(ultimo.delta)}
                </span>
                ) · {formatarData(ultimo.concluido_em)}
              </>
            ) : (
              <>{ultimo.mensagem ?? estadoUltimo ?? "sem adaptações registadas"}</>
            )}
          </p>
        )}

        {mensagem && (
          <p
            className={`mt-2 text-[10px] leading-relaxed ${
              mensagem.tipo === "erro" ? "text-red-400" : "text-primary"
            }`}
          >
            {mensagem.texto}
          </p>
        )}

        {!completo && (
          <a
            href="/modelo/retreino"
            onClick={(evento) => {
              evento.preventDefault();
              window.history.pushState({}, "", "/modelo/retreino");
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
            className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <History size={10} />
            ver versões e histórico
          </a>
        )}
      </div>

      {(completo || aCorrer) && (
        <RetreinoAoVivo aCorrer={aCorrer} className={completo ? "mt-1" : "mt-3"} autoLigar />
      )}

      {completo && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className={cartao}>
              <p className="mb-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                <Database size={12} /> corpus RAG
              </p>
              <p className="text-lg font-semibold text-foreground">
                {documentosRag ?? "—"}
              </p>
              <button
                type="button"
                onClick={() => void reindexar()}
                disabled={ocupado !== null || aCorrer}
                className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[11px] text-foreground hover:bg-muted disabled:opacity-40"
              >
                {ocupado === "rag" ? <Loader2 size={11} className="animate-spin" /> : <Database size={11} />}
                reindexar índices
              </button>
            </div>
            <div className={cartao}>
              <p className="mb-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                <Gauge size={12} /> avaliação
              </p>
              <p className="text-lg font-semibold text-foreground">
                {avaliacao ? avaliacao.f1.toFixed(3) : "—"}
              </p>
              <button
                type="button"
                onClick={() => void avaliar()}
                disabled={ocupado !== null || aCorrer}
                className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-border bg-background px-2 py-1.5 text-[11px] text-foreground hover:bg-muted disabled:opacity-40"
              >
                {ocupado === "avaliar" ? <Loader2 size={11} className="animate-spin" /> : <Gauge size={11} />}
                correr avaliação
              </button>
              {avaliacao && (
                <p className="mt-1 text-[10px] text-muted-foreground">{avaliacao.amostras} amostras</p>
              )}
            </div>
            <div className={cartao}>
              <p className="mb-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                <RotateCcw size={12} /> versões guardadas
              </p>
              <p className="text-lg font-semibold text-foreground">{versoes.length}</p>
              <p className="mt-1 text-[10px] text-muted-foreground">
                cada adaptação guarda o adaptador anterior
              </p>
            </div>
          </div>

          <div className={cartao}>
            <p className="mb-2 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
              <ArrowRightLeft size={12} /> reverter adaptador
            </p>
            {versoes.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">Ainda não há versões guardadas.</p>
            ) : (
              <ul className="space-y-1.5">
                {versoes.slice(0, 6).map((versao) => (
                  <li
                    key={versao.nome}
                    className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-background/60 px-2 py-1.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[11px] text-foreground">{versao.nome}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {formatarData(versao.criado_em)} · {formatarBytes(versao.bytes)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void reverter(versao.nome)}
                      disabled={ocupado !== null || aCorrer}
                      className="shrink-0 rounded-lg border border-border px-2 py-1 text-[10px] text-foreground hover:bg-muted disabled:opacity-40"
                    >
                      {ocupado === `reverter:${versao.nome}` ? (
                        <Loader2 size={10} className="animate-spin" />
                      ) : (
                        "reverter"
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={cartao}>
            <p className="mb-2 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
              <History size={12} /> histórico de adaptações
            </p>
            {historico.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">Sem registos em metricas_adaptacao.jsonl.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="py-1 pr-2">quando</th>
                      <th className="py-1 pr-2">estado</th>
                      <th className="py-1 pr-2">passos</th>
                      <th className="py-1 pr-2">pares</th>
                      <th className="py-1 pr-2">perda antes</th>
                      <th className="py-1 pr-2">perda depois</th>
                      <th className="py-1">delta</th>
                    </tr>
                  </thead>
                  <tbody className="text-muted-foreground">
                    {historico.map((registo, indice) => (
                      <tr key={`${registo.concluido_em ?? indice}-${indice}`} className="border-t border-border/50">
                        <td className="py-1 pr-2 whitespace-nowrap">{formatarData(registo.concluido_em)}</td>
                        <td className="py-1 pr-2">{registo.estado ?? "concluido"}</td>
                        <td className="py-1 pr-2">{registo.passos ?? "—"}</td>
                        <td className="py-1 pr-2">{registo.pares ?? "—"}</td>
                        <td className="py-1 pr-2">{formatarPerda(registo.perda_antes)}</td>
                        <td className="py-1 pr-2">{formatarPerda(registo.perda_depois)}</td>
                        <td
                          className={`py-1 ${
                            typeof registo.delta === "number" && registo.delta < 0 ? "text-primary" : ""
                          }`}
                        >
                          {formatarPerda(registo.delta)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
            <Sparkles size={12} className="mt-0.5 shrink-0 text-primary" />
            A adaptação incremental usa apenas correções humanas e skills com exemplo. Cada execução guarda o
            adaptador anterior em <code className="rounded bg-muted px-1">.bak-&lt;data&gt;</code>, mede a perda antes
            e depois e recarrega o modelo na inferência seguinte.
          </p>
        </>
      )}
    </div>
  );
}
