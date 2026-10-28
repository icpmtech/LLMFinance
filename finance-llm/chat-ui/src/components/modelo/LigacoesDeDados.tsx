/**
 * Ligações dos dados: índices do Elasticsearch → dataset → treino → adaptador.
 *
 * A largura de cada ligação é o número **real** de pares que aquela fonte pôs no
 * dataset (a API conta as linhas do ficheiro que o treino usou). As gotas
 * animadas só correm quando o modelo está a treinar — parado, mostra-se o
 * retrato do que já aconteceu.
 */
import { Database, FileJson2, Layers, Zap } from "lucide-react";
import type { Ligacoes } from "../../llmModeloApi";

const CORES: Record<string, string> = {
  contratos: "#10a37f",
  empresas: "#38bdf8",
  subvencoes: "#c084fc",
};

export default function LigacoesDeDados({ ligacoes, animar }: { ligacoes: Ligacoes | null; animar: boolean }) {
  if (!ligacoes || !ligacoes.fontes.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
        Sem dataset ligado ao modelo.
      </div>
    );
  }

  const largura = 960;
  const altura = 300;
  const total = ligacoes.fontes.reduce((soma, f) => soma + f.pares, 0) || 1;
  const fonteX = 20;
  const fonteLargura = 190;
  const datasetX = 380;
  const treinoX = 620;
  const adaptadorX = 830;

  // Distribui as fontes verticalmente e o destino (dataset) centrado.
  const passoFonte = (altura - 60) / Math.max(1, ligacoes.fontes.length);
  const nosFonte = ligacoes.fontes.map((fonte, i) => ({
    ...fonte,
    y: 30 + passoFonte * i + passoFonte / 2,
    altura: Math.max(14, (fonte.pares / total) * (altura - 90)),
  }));
  const datasetY = altura / 2;

  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Layers size={14} className="text-primary" />
          ligações · índices → dataset → treino → adaptador
        </span>
        <span className="text-[10.5px] text-muted-foreground">
          {ligacoes.dataset.pares} pares · treino {ligacoes.dataset.pares_treino ?? "—"} · held-out{" "}
          {ligacoes.dataset.pares_holdout ?? "—"}
        </span>
      </div>

      <svg viewBox={`0 0 ${largura} ${altura}`} className="w-full" role="img" aria-label="Ligações dos dados ao modelo">
        <defs>
          {ligacoes.fontes.map((fonte) => (
            <linearGradient key={fonte.id} id={`mc-lig-${fonte.id}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={CORES[fonte.id] ?? "#10a37f"} stopOpacity="0.55" />
              <stop offset="100%" stopColor={CORES[fonte.id] ?? "#10a37f"} stopOpacity="0.18" />
            </linearGradient>
          ))}
        </defs>

        {/* ligações fonte → dataset */}
        {nosFonte.map((fonte, i) => {
          const espessura = Math.max(2, (fonte.pares / total) * 46);
          const inicio = `${fonteX + fonteLargura},${fonte.y}`;
          const fim = `${datasetX},${datasetY - 30 + i * 22}`;
          const curva = `M${inicio} C${fonteX + fonteLargura + 90},${fonte.y} ${datasetX - 90},${datasetY - 30 + i * 22} ${fim}`;
          return (
            <g key={fonte.id}>
              <path d={curva} fill="none" stroke={`url(#mc-lig-${fonte.id})`} strokeWidth={espessura} strokeLinecap="round" />
              <path
                d={curva}
                fill="none"
                stroke={CORES[fonte.id] ?? "#10a37f"}
                strokeWidth={1.4}
                strokeDasharray="4 7"
                opacity={0.75}
                className={animar ? "mc-fluxo" : undefined}
              />
              {animar && (
                <circle r={3.2} fill={CORES[fonte.id] ?? "#10a37f"}>
                  <animateMotion dur={`${2.4 + i * 0.4}s`} repeatCount="indefinite" path={curva} />
                </circle>
              )}
            </g>
          );
        })}

        {/* nós fonte */}
        {nosFonte.map((fonte) => (
          <g key={`no-${fonte.id}`}>
            <rect
              x={fonteX}
              y={fonte.y - 26}
              width={fonteLargura}
              height={52}
              rx={10}
              fill="rgba(30,33,40,0.85)"
              stroke={CORES[fonte.id] ?? "#2e323b"}
              strokeWidth={1.2}
            />
            <text x={fonteX + 12} y={fonte.y - 7} fontSize={11} fill="#e8e9ec" fontWeight={600}>
              {fonte.id}
            </text>
            <text x={fonteX + 12} y={fonte.y + 8} fontSize={9} fill="#9aa0aa">
              {fonte.indice}
            </text>
            <text x={fonteX + fonteLargura - 12} y={fonte.y + 8} textAnchor="end" fontSize={10} fill={CORES[fonte.id] ?? "#10a37f"}>
              {fonte.pares} pares
            </text>
          </g>
        ))}

        {/* dataset */}
        <g>
          <rect x={datasetX} y={datasetY - 54} width={190} height={108} rx={12} fill="rgba(16,163,127,0.12)" stroke="#10a37f" />
          <text x={datasetX + 95} y={datasetY - 26} textAnchor="middle" fontSize={11.5} fill="#e8e9ec" fontWeight={600}>
            dataset
          </text>
          <text x={datasetX + 95} y={datasetY - 8} textAnchor="middle" fontSize={9} fill="#9aa0aa">
            {ligacoes.dataset.ficheiro ?? "jsonl"}
          </text>
          <text x={datasetX + 95} y={datasetY + 12} textAnchor="middle" fontSize={16} fill="#10a37f" fontWeight={700}>
            {ligacoes.dataset.pares}
          </text>
          <text x={datasetX + 95} y={datasetY + 28} textAnchor="middle" fontSize={8.5} fill="#6b7280">
            pares instruction/input/output
          </text>
        </g>

        <path
          d={`M${datasetX + 190},${datasetY} L${treinoX},${datasetY}`}
          fill="none"
          stroke="#10a37f"
          strokeWidth={Math.max(3, (total / total) * 14)}
          opacity={0.35}
        />
        <path
          d={`M${datasetX + 190},${datasetY} L${treinoX},${datasetY}`}
          fill="none"
          stroke="#10a37f"
          strokeWidth={1.4}
          strokeDasharray="4 7"
          className={animar ? "mc-fluxo" : undefined}
        />

        {/* treino */}
        <g>
          <rect x={treinoX} y={datasetY - 46} width={170} height={92} rx={12} fill="rgba(30,33,40,0.85)" stroke="#2e323b" />
          <text x={treinoX + 85} y={datasetY - 22} textAnchor="middle" fontSize={11} fill="#e8e9ec" fontWeight={600}>
            treino LoRA
          </text>
          <text x={treinoX + 85} y={datasetY - 4} textAnchor="middle" fontSize={9} fill="#9aa0aa">
            {ligacoes.treino.passos ?? 0}/{ligacoes.treino.passos_planeados ?? 0} passos
          </text>
          <text x={treinoX + 85} y={datasetY + 12} textAnchor="middle" fontSize={9} fill="#9aa0aa">
            {(ligacoes.treino.tokens ?? 0).toLocaleString("pt-PT")} tokens
          </text>
          <text x={treinoX + 85} y={datasetY + 28} textAnchor="middle" fontSize={9} fill="#10a37f">
            perda {ligacoes.treino.perda_final ?? "—"}
          </text>
        </g>

        <path
          d={`M${treinoX + 170},${datasetY} L${adaptadorX},${datasetY}`}
          fill="none"
          stroke="#10a37f"
          strokeWidth={1.4}
          strokeDasharray="4 7"
          className={animar ? "mc-fluxo" : undefined}
        />

        {/* adaptador */}
        <g>
          <rect x={adaptadorX} y={datasetY - 40} width={118} height={80} rx={12} fill="rgba(16,163,127,0.16)" stroke="#10a37f" />
          <text x={adaptadorX + 59} y={datasetY - 16} textAnchor="middle" fontSize={10.5} fill="#e8e9ec" fontWeight={600}>
            adaptador
          </text>
          <text x={adaptadorX + 59} y={datasetY + 1} textAnchor="middle" fontSize={8.5} fill="#9aa0aa">
            r={ligacoes.adaptador.lora_r ?? 16}
          </text>
          <text x={adaptadorX + 59} y={datasetY + 16} textAnchor="middle" fontSize={8.5} fill="#9aa0aa">
            {ligacoes.adaptador.parametros ? `${(ligacoes.adaptador.parametros / 1e6).toFixed(1)} M` : "—"}
          </text>
          <text x={adaptadorX + 59} y={datasetY + 31} textAnchor="middle" fontSize={8} fill="#6b7280">
            (ficheiro 35 MB)
          </text>
        </g>
      </svg>

      <div className="mt-2 flex flex-wrap gap-4 text-[10.5px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Database size={11} /> índice de origem
        </span>
        <span className="flex items-center gap-1">
          <FileJson2 size={11} /> dataset em disco
        </span>
        <span className="flex items-center gap-1">
          <Zap size={11} /> passos de treino
        </span>
        <span>
          fração do dataset:{" "}
          {ligacoes.fontes.map((f) => `${f.id} ${(f.fracao * 100).toFixed(0)}%`).join(" · ")}
        </span>
      </div>
    </div>
  );
}
