/**
 * Grafo do modelo: tokens → embedding → 24 camadas (com a LoRA colada) → cabeça → resposta.
 *
 * As partículas percorrem as **ligações** no sentido do forward (teal) e, quando
 * há treino, também no sentido do backward (âmbar) — na vertical de cada camada
 * está a magnitude real da actualização LoRA daquela camada, lida da matriz de
 * pesos. Clicar numa camada selecciona-a na matriz.
 */
import { useMemo } from "react";
import { Brain, ArrowRight } from "lucide-react";
import type { MatrizAdaptador } from "../../llmModeloApi";

export default function GrafoDoModelo({
  matriz,
  camadaSelecionada,
  onSelecionar,
  animar,
}: {
  matriz: MatrizAdaptador | null;
  camadaSelecionada: number;
  onSelecionar: (camada: number) => void;
  animar: boolean;
}) {
  const camadas = matriz?.camadas ?? Array.from({ length: 24 }, (_, i) => i);
  const maximo = matriz?.maximo ?? 1;
  const valoresQ = useMemo(() => {
    if (!matriz?.valores || !matriz.modulos) return null;
    const indiceQ = matriz.modulos.indexOf("q");
    return matriz.valores.map((linha) => linha[Math.max(0, indiceQ)]);
  }, [matriz]);

  const largura = 960;
  const altura = 360;
  const topo = 26;
  const base = altura - 30;
  const alturaLinha = (base - topo) / camadas.length;
  const xCamadas = 300;
  const larguraCamada = 300;

  const y = (indice: number) => topo + alturaLinha * indice + alturaLinha / 2;
  const caminhoCamadas = camadas.map((_, i) => `${i ? "L" : "M"}${xCamadas + larguraCamada},${y(i).toFixed(1)}`).join(" ");

  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Brain size={14} className="text-primary" />
          grafo do modelo · onde a LoRA escreve
        </span>
        <div className="flex items-center gap-3 text-[10.5px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-4 rounded-full bg-primary" /> forward
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-4 rounded-full bg-amber-400" /> backward (treino)
          </span>
        </div>
      </div>

      <svg viewBox={`0 0 ${largura} ${altura}`} className="w-full" role="img" aria-label="Grafo da arquitetura do modelo">
        <defs>
          <linearGradient id="mc-grafo-ligacao" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#10a37f" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#10a37f" stopOpacity="0.7" />
          </linearGradient>
          <marker id="mc-seta" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="#10a37f" opacity="0.75" />
          </marker>
        </defs>

        {/* tokens → embedding */}
        <g>
          <rect x={10} y={altura / 2 - 26} width={92} height={52} rx={10} fill="rgba(30,33,40,0.8)" stroke="#2e323b" />
          <text x={56} y={altura / 2 - 4} textAnchor="middle" fontSize={11.5} fill="#e8e9ec">
            tokens
          </text>
          <text x={56} y={altura / 2 + 12} textAnchor="middle" fontSize={9.5} fill="#9aa0aa">
            prompt + contexto
          </text>
          <line x1={102} y1={altura / 2} x2={150} y2={altura / 2} stroke="url(#mc-grafo-ligacao)" strokeWidth={2} />
          {animar && (
            <circle r={3} fill="#10a37f">
              <animateMotion dur="1.6s" repeatCount="indefinite" path={`M102,${altura / 2} L150,${altura / 2}`} />
            </circle>
          )}
        </g>

        {/* embedding */}
        <g>
          <rect x={152} y={altura / 2 - 30} width={96} height={60} rx={10} fill="rgba(16,163,127,0.10)" stroke="#10a37f" />
          <text x={200} y={altura / 2 - 8} textAnchor="middle" fontSize={11.5} fill="#e8e9ec">
            embedding
          </text>
          <text x={200} y={altura / 2 + 7} textAnchor="middle" fontSize={9.5} fill="#9aa0aa">
            896 dim
          </text>
          <text x={200} y={altura / 2 + 21} textAnchor="middle" fontSize={9} fill="#6b7280">
            vocab 151 936
          </text>
        </g>

        {/* ligação embedding → camada 0 */}
        <path
          d={`M248,${altura / 2} C270,${altura / 2} 278,${y(0)} ${xCamadas},${y(0)}`}
          fill="none"
          stroke="url(#mc-grafo-ligacao)"
          strokeWidth={2}
          markerEnd="url(#mc-seta)"
        />
        {animar && (
          <circle r={3} fill="#10a37f">
            <animateMotion
              dur="1.4s"
              repeatCount="indefinite"
              path={`M248,${altura / 2} C270,${altura / 2} 278,${y(0)} ${xCamadas},${y(0)}`}
            />
          </circle>
        )}

        {/* camadas */}
        {camadas.map((camada, i) => {
          const selecionada = camada === camadaSelecionada;
          const valor = valoresQ ? valoresQ[i] : 0;
          const intensidade = maximo ? Math.min(1, valor / maximo) : 0;
          return (
            <g key={camada} className="cursor-pointer" onClick={() => onSelecionar(camada)}>
              <rect
                x={xCamadas}
                y={y(i) - alturaLinha / 2 + 1}
                width={larguraCamada}
                height={alturaLinha - 2.5}
                rx={4}
                fill={selecionada ? "rgba(16,163,127,0.35)" : `rgba(16,163,127,${0.06 + intensidade * 0.18})`}
                stroke={selecionada ? "#e8e9ec" : "#2e323b"}
                strokeWidth={selecionada ? 1.3 : 0.8}
              />
              <text x={xCamadas + 8} y={y(i) + 3} fontSize={9} fill={selecionada ? "#e8e9ec" : "#9aa0aa"}>
                camada {camada}
              </text>
              <text x={xCamadas + larguraCamada - 8} y={y(i) + 3} textAnchor="end" fontSize={8.5} fill="#6b7280">
                LoRA {valor ? valor.toFixed(2) : "—"}
              </text>
            </g>
          );
        })}

        {/* cadeia entre camadas (forward) + backward */}
        <path d={caminhoCamadas} fill="none" stroke="url(#mc-grafo-ligacao)" strokeWidth={1.6} strokeDasharray="5 4" className={animar ? "mc-fluxo" : undefined} />
        {animar && (
          <>
            <circle r={2.6} fill="#10a37f">
              <animateMotion dur="3.2s" repeatCount="indefinite" path={caminhoCamadas} />
            </circle>
            <circle r={2.6} fill="#10a37f">
              <animateMotion dur="3.2s" begin="1.1s" repeatCount="indefinite" path={caminhoCamadas} />
            </circle>
            <circle r={2.6} fill="#fbbf24">
              <animateMotion dur="3.6s" repeatCount="indefinite" keyPoints="1;0" keyTimes="0;1" calcMode="linear" path={caminhoCamadas} />
            </circle>
          </>
        )}

        {/* camada 23 → cabeça */}
        <path
          d={`M${xCamadas + larguraCamada},${y(camadas.length - 1)} C760,${y(camadas.length - 1)} 770,${altura / 2} 796,${altura / 2}`}
          fill="none"
          stroke="url(#mc-grafo-ligacao)"
          strokeWidth={2}
          markerEnd="url(#mc-seta)"
        />

        {/* cabeça + resposta */}
        <g>
          <rect x={796} y={altura / 2 - 30} width={70} height={60} rx={10} fill="rgba(16,163,127,0.10)" stroke="#10a37f" />
          <text x={831} y={altura / 2 - 8} textAnchor="middle" fontSize={10.5} fill="#e8e9ec">
            lm head
          </text>
          <text x={831} y={altura / 2 + 8} textAnchor="middle" fontSize={9} fill="#9aa0aa">
            softmax
          </text>
        </g>
        <line x1={866} y1={altura / 2} x2={906} y2={altura / 2} stroke="url(#mc-grafo-ligacao)" strokeWidth={2} markerEnd="url(#mc-seta)" />
        {animar && (
          <circle r={3} fill="#10a37f">
            <animateMotion dur="1.2s" repeatCount="indefinite" path={`M866,${altura / 2} L906,${altura / 2}`} />
          </circle>
        )}
        <g>
          <rect x={908} y={altura / 2 - 20} width={44} height={40} rx={8} fill="rgba(30,33,40,0.8)" stroke="#2e323b" />
          <text x={930} y={altura / 2 + 4} textAnchor="middle" fontSize={9.5} fill="#e8e9ec">
            texto
          </text>
        </g>

        {/* etiquetas laterais */}
        <text x={xCamadas + larguraCamada / 2} y={14} textAnchor="middle" fontSize={9.5} fill="#9aa0aa">
          24 blocos transformer · atenção (q,k,v,o) + MLP (gate,up,down)
        </text>
        <text x={xCamadas + larguraCamada / 2} y={altura - 8} textAnchor="middle" fontSize={9} fill="#6b7280">
          largura da barra = magnitude da actualização LoRA da camada (projeção q)
        </text>
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-3 text-[10.5px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <ArrowRight size={11} /> clicar numa camada abre os pesos dela na matriz
        </span>
        <span>
          camada selecionada: <span className="text-foreground">{camadaSelecionada}</span>
        </span>
        <span>
          adaptador: {matriz?.parametros ? `${(matriz.parametros / 1e6).toFixed(1)} M parâmetros` : "—"}
        </span>
      </div>
    </div>
  );
}
