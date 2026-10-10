/**
 * **Mapa OSM das regiões de compra** (tiles do OpenStreetMap, sem dependências).
 *
 * Repõe o mesmo princípio da página «Mapa de Contratos»: os dados trazem códigos
 * de região (NUTS/distrito em PT, `nuts` em ES, `lieu_execution_code` em FR) e o
 * `components/graph/geo.ts` resolve-os para centroides, dizendo se a posição é
 * exata ou aproximada. Cada região é um ponto clicável (com menu de contexto).
 */
import { useEffect, useMemo, useState } from "react";
import { Minus, Plus } from "lucide-react";

import { TILE_SIZE, latToWorld, lonToWorld, lookupPlace, worldToLat, worldToLon } from "../graph/geo";
import type { BenchmarkBuyerRegion } from "../../benchmarkApi";

export type RegionPoint = {
  region: BenchmarkBuyerRegion;
  lat: number;
  lon: number;
  exact: boolean;
};

const LARGURA = 720;
const ALTURA = 420;

function euroCurto(valor: number): string {
  const abs = Math.abs(valor);
  if (abs >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 10_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return `${Math.round(valor)} €`;
}

export default function BuyerMap({
  regioes,
  selecionada,
  onSelect,
  onContexto,
}: {
  regioes: BenchmarkBuyerRegion[];
  selecionada: string | null;
  onSelect: (ponto: RegionPoint) => void;
  onContexto: (
    evento: { clientX: number; clientY: number; currentTarget: Element; preventDefault: () => void },
    ponto: RegionPoint,
  ) => void;
}) {
  const pontos = useMemo<RegionPoint[]>(() => {
    const saida: RegionPoint[] = [];
    for (const regiao of regioes) {
      const lugar = lookupPlace(regiao.code, regiao.code);
      if (!lugar) continue;
      saida.push({ region: regiao, lat: lugar.lat, lon: lugar.lon, exact: lugar.exact });
    }
    return saida;
  }, [regioes]);

  const [zoom, setZoom] = useState(6);
  const [centro, setCentro] = useState<{ lat: number; lon: number }>({ lat: 39.6, lon: -8.6 });
  const [arrasto, setArrasto] = useState<{ x: number; y: number; lat: number; lon: number } | null>(null);

  // Enquadra os pontos assim que chegam (média ponderada pelo volume).
  useEffect(() => {
    if (!pontos.length) return;
    const total = pontos.reduce((soma, ponto) => soma + Math.max(1, ponto.region.contracts), 0);
    const lat = pontos.reduce((soma, ponto) => soma + ponto.lat * Math.max(1, ponto.region.contracts), 0) / total;
    const lon = pontos.reduce((soma, ponto) => soma + ponto.lon * Math.max(1, ponto.region.contracts), 0) / total;
    setCentro({ lat, lon });
    setZoom(pontos.length > 6 ? 6 : 7);
  }, [pontos]);

  const maxValor = pontos.reduce((maior, ponto) => Math.max(maior, ponto.region.value), 0);

  const centroX = lonToWorld(centro.lon, zoom);
  const centroY = latToWorld(centro.lat, zoom);

  const projectar = (lat: number, lon: number) => ({
    x: LARGURA / 2 + (lonToWorld(lon, zoom) - centroX),
    y: ALTURA / 2 + (latToWorld(lat, zoom) - centroY),
  });

  const tiles = useMemo(() => {
    const mundo = 2 ** zoom;
    const primeiroX = Math.floor((centroX - LARGURA / 2) / TILE_SIZE);
    const ultimoX = Math.floor((centroX + LARGURA / 2) / TILE_SIZE);
    const primeiroY = Math.max(0, Math.floor((centroY - ALTURA / 2) / TILE_SIZE));
    const ultimoY = Math.min(mundo - 1, Math.floor((centroY + ALTURA / 2) / TILE_SIZE));
    const lista: { key: string; url: string; left: number; top: number }[] = [];
    for (let y = primeiroY; y <= ultimoY; y += 1) {
      for (let x = primeiroX; x <= ultimoX; x += 1) {
        const envolvido = ((x % mundo) + mundo) % mundo;
        lista.push({
          key: `${zoom}/${envolvido}/${y}`,
          url: `https://tile.openstreetmap.org/${zoom}/${envolvido}/${y}.png`,
          left: LARGURA / 2 + (x * TILE_SIZE - centroX),
          top: ALTURA / 2 + (y * TILE_SIZE - centroY),
        });
      }
    }
    return lista;
  }, [centroX, centroY, zoom]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-border/60 bg-[#04121a]" data-context-scope>
      <div className="absolute right-2 top-2 z-20 flex items-center gap-1">
        <button
          type="button"
          className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-xs text-foreground transition hover:bg-white/10"
          onClick={() => setZoom((valor) => Math.max(4, valor - 1))}
          title="Menos zoom"
        >
          <Minus size={13} />
        </button>
        <span className="rounded-lg bg-[#07151b]/90 px-2 py-1 text-[10px] text-muted-foreground">z{zoom}</span>
        <button
          type="button"
          className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-xs text-foreground transition hover:bg-white/10"
          onClick={() => setZoom((valor) => Math.min(12, valor + 1))}
          title="Mais zoom"
        >
          <Plus size={13} />
        </button>
      </div>

      <svg
        viewBox={`0 0 ${LARGURA} ${ALTURA}`}
        className="h-[420px] w-full cursor-grab select-none"
        onMouseDown={(evento) =>
          setArrasto({ x: evento.clientX, y: evento.clientY, lat: centro.lat, lon: centro.lon })
        }
        onMouseMove={(evento) => {
          if (!arrasto) return;
          const dx = evento.clientX - arrasto.x;
          const dy = evento.clientY - arrasto.y;
          const mundoX = lonToWorld(arrasto.lon, zoom) - dx;
          const mundoY = latToWorld(arrasto.lat, zoom) - dy;
          setCentro({ lat: worldToLat(mundoY, zoom), lon: worldToLon(mundoX, zoom) });
        }}
        onMouseUp={() => setArrasto(null)}
        onMouseLeave={() => setArrasto(null)}
        onContextMenu={(evento) => {
          // o menu abre em cada ponto (o handler do SVG só serve para travar o menu nativo)
          evento.preventDefault();
        }}
      >
        {tiles.map((tile) => (
          <image
            key={tile.key}
            href={tile.url}
            x={tile.left}
            y={tile.top}
            width={TILE_SIZE}
            height={TILE_SIZE}
            opacity={0.75}
            preserveAspectRatio="none"
          />
        ))}

        {pontos.map((ponto) => {
          const posicao = projectar(ponto.lat, ponto.lon);
          const raio = 6 + 16 * (maxValor ? Math.min(1, ponto.region.value / maxValor) : 0.3);
          const activo = selecionada === ponto.region.code;
          return (
            <g
              key={ponto.region.code}
              className="cursor-pointer"
              onClick={() => onSelect(ponto)}
              onContextMenu={(evento) => onContexto(evento, ponto)}
            >
              <circle
                cx={posicao.x}
                cy={posicao.y}
                r={raio}
                fill={activo ? "#f59e0b" : "#0ea5e9"}
                fillOpacity={0.45}
                stroke={activo ? "#fbbf24" : "#38bdf8"}
                strokeWidth={activo ? 2.4 : 1.2}
              />
              <circle cx={posicao.x} cy={posicao.y} r={2} fill="#e2e8f0" />
              <text x={posicao.x + raio + 3} y={posicao.y + 3} className="fill-slate-200 text-[9px]">
                {ponto.region.code.slice(0, 22)}
              </text>
              <title>
                {`${ponto.region.code}${ponto.exact ? "" : " (posição aproximada)"}\n${ponto.region.contracts} contratos · ${euroCurto(
                  ponto.region.value,
                )}`}
              </title>
            </g>
          );
        })}
      </svg>
      <p className="px-2 pb-1 text-[10px] text-muted-foreground">
        Arraste para navegar, use +/− para o zoom · © OpenStreetMap. O tamanho do ponto é o valor contratado na região;
        «posição aproximada» quando o código só é resolvido ao nível do país.
      </p>
    </div>
  );
}
