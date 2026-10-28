/**
 * Árvore do raciocínio: como o modelo chegou àquela resposta.
 *
 * Cada `passo` que a API devolve é um nó da árvore — pedido → skill → memória →
 * evidências → geração → verificação. Abaixo, a fita de tokens com a
 * probabilidade que o modelo deu a cada um (verde = convicto, âmbar = a
 * adivinhar) e as **matrizes de conhecimento** que entraram no prompt.
 */
import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, CircleCheck, Database, GitBranch, Sparkles, TriangleAlert } from "lucide-react";
import type { RespostaModelo } from "../../llmModeloApi";

const ICONES: Record<string, React.ReactNode> = {
  pergunta: <Sparkles size={12} />,
  skill: <Database size={12} />,
  memoria: <GitBranch size={12} />,
  rag: <Database size={12} />,
  dados: <Database size={12} />,
  geracao: <Sparkles size={12} />,
  verificacao: <CircleCheck size={12} />,
};

function corDaProbabilidade(probabilidade?: number): string {
  if (probabilidade === undefined) return "rgba(154,160,170,0.35)";
  if (probabilidade > 0.85) return "rgba(16,163,127,0.85)";
  if (probabilidade > 0.55) return "rgba(16,163,127,0.55)";
  if (probabilidade > 0.3) return "rgba(251,191,36,0.55)";
  return "rgba(244,63,94,0.55)";
}

export default function ArvoreDoRaciocinio({ resposta }: { resposta: RespostaModelo }) {
  const [abertos, setAbertos] = useState<Record<number, boolean>>({ 0: true });
  const verificacao = resposta.verificacao ?? {};
  const inventados = verificacao.inventados ?? [];
  const tokens = resposta.tokens ?? [];

  const estatisticas = useMemo(() => {
    const comProb = tokens.filter((t) => t.probabilidade !== undefined);
    if (!comProb.length) return null;
    const media = comProb.reduce((soma, t) => soma + (t.probabilidade ?? 0), 0) / comProb.length;
    const minimo = Math.min(...comProb.map((t) => t.probabilidade ?? 0));
    return { media, minimo, total: comProb.length };
  }, [tokens]);

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border bg-card/60 p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <GitBranch size={14} className="text-primary" />
            árvore do raciocínio
          </span>
          <span className="text-[10.5px] text-muted-foreground">
            {resposta.passos.length} passos · {resposta.duracao_s.toFixed(1)} s
          </span>
        </div>
        <ol className="relative ml-3 border-l border-border/70 pl-4">
          {resposta.passos.map((passo, i) => {
            const aberto = abertos[i] ?? false;
            const temDados = passo.dados && Object.keys(passo.dados).length > 0;
            return (
              <li key={`${passo.fase}-${i}`} className="relative mb-2 last:mb-0">
                <span className="absolute -left-[21px] top-1 flex h-3 w-3 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
                  <span className="h-1 w-1 rounded-full bg-primary" />
                </span>
                <button
                  type="button"
                  onClick={() => setAbertos((antes) => ({ ...antes, [i]: !aberto }))}
                  className="flex w-full items-start gap-1.5 text-left"
                >
                  <span className="mt-[2px] text-primary">{ICONES[passo.fase] ?? <GitBranch size={12} />}</span>
                  <span className="flex-1">
                    <span className="text-[11.5px] font-medium text-foreground">{passo.titulo}</span>
                    {passo.detalhe && (
                      <span className="ml-1 text-[10.5px] text-muted-foreground">{passo.detalhe.slice(0, 140)}</span>
                    )}
                  </span>
                  {temDados &&
                    (aberto ? (
                      <ChevronDown size={12} className="mt-1 text-muted-foreground" />
                    ) : (
                      <ChevronRight size={12} className="mt-1 text-muted-foreground" />
                    ))}
                </button>
                {aberto && temDados && (
                  <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted/40 p-2 text-[10px] leading-relaxed text-muted-foreground">
                    {JSON.stringify(passo.dados, null, 1)}
                  </pre>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {tokens.length > 0 && (
        <div className="rounded-xl border border-border bg-card/60 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">tokens gerados · pesos</span>
            {estatisticas && (
              <span className="text-[10.5px] text-muted-foreground">
                confiança média {estatisticas.media.toFixed(2)} · mínima {estatisticas.minimo.toFixed(2)} ·{" "}
                {estatisticas.total} tokens
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-[3px]">
            {tokens.map((token, i) => (
              <span
                key={i}
                title={`p=${token.probabilidade ?? "?"} · entropia=${token.entropia ?? "?"}`}
                className="rounded px-1 py-[1px] font-mono text-[10.5px] text-foreground"
                style={{ backgroundColor: corDaProbabilidade(token.probabilidade) }}
              >
                {token.token.replace(/\n/g, "⏎") || "·"}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
            Cada cor é a probabilidade que o <span className="text-foreground">softmax</span> da cabeça deu ao token
            escolhido: verde = convicto, âmbar/rosa = a adivinhar. É a leitura direta dos pesos nesta resposta.
          </p>
        </div>
      )}

      <div
        className={`rounded-xl border p-3 text-[11px] ${
          inventados.length === 0 ? "border-primary/30 bg-primary/5" : "border-amber-400/40 bg-amber-400/5"
        }`}
      >
        <div className="flex items-center gap-2 font-medium">
          {inventados.length === 0 ? (
            <CircleCheck size={13} className="text-primary" />
          ) : (
            <TriangleAlert size={13} className="text-amber-400" />
          )}
          {verificacao.motivo ?? "sem verificação"}
          <span className="ml-auto text-[10px] text-muted-foreground">
            confiança {verificacao.confianca !== undefined ? `${(verificacao.confianca * 100).toFixed(0)}%` : "—"}
          </span>
        </div>
        {inventados.length > 0 && (
          <p className="mt-1 text-[10.5px] text-muted-foreground">
            Números sem suporte no contexto: {inventados.join(", ")} — trate estes valores como não verificados.
          </p>
        )}
      </div>

      {resposta.evidencias.length > 0 && (
        <div className="rounded-xl border border-border bg-card/60 p-3">
          <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            matriz de conhecimento usada ({resposta.evidencias.length})
          </div>
          <ul className="space-y-1.5">
            {resposta.evidencias.map((evidencia, i) => (
              <li key={i} className="rounded-md bg-muted/30 p-2 text-[10.5px] leading-relaxed text-muted-foreground">
                <span className="mr-1 rounded bg-primary/20 px-1 text-[9.5px] uppercase text-primary">
                  {evidencia.fonte ?? "?"}
                </span>
                {evidencia.texto}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
