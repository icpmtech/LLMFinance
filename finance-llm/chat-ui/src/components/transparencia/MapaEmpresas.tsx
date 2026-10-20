/**
 * Mapa das sedes das empresas (OpenStreetMap, sem biblioteca externa).
 *
 * Desenha os pontos com coordenadas resolvidas a partir do «Local da sede» das
 * declarações. Dois modos:
 *
 * - **pontos** — uma marca por empresa (tamanho pelo n.º de ligações);
 * - **concelhos** — um círculo por concelho, com o total de empresas.
 *
 * O utilizador pode arrastar, usar a roda do rato ou os botões de zoom; «Centrar»
 * volta a enquadrar os pontos. Uma empresa sem coordenadas nunca é colocada numa
 * posição inventada — não aparece no mapa e o painel diz quantas ficaram de fora.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LocateFixed, Minus, Plus } from "lucide-react";
import { TILE_SIZE, latToWorld, lonToWorld } from "../graph/geo";
import type { TgEmpresa } from "../../transparenciaGrafoApi";

type Ponto = {
  id: string;
  nome: string;
  lat: number;
  lon: number;
  peso: number;
  legenda?: string;
  detalhe?: string;
};

const CENTRO_PT = { lat: 39.5, lon: -8.2 };

function limite(valor: number, minimo: number, maximo: number) {
  return Math.max(minimo, Math.min(maximo, valor));
}

/** Longitude mais próxima do centro (evita atravessar o antimeridiano). */
function lonPerto(lon: number, centro: number) {
  let resultado = lon;
  while (resultado - centro > 180) resultado -= 360;
  while (resultado - centro < -180) resultado += 360;
  return resultado;
}

export function MapaEmpresas({
  pontos: empresas,
  concelhos,
  modo,
  altura = 480,
  onSelecionar,
}: {
  pontos: TgEmpresa[];
  concelhos: { concelho: string; lat: number; lon: number; empresas: number; ligacoes: number }[];
  modo: "pontos" | "concelhos";
  altura?: number;
  onSelecionar?: (item: Ponto) => void;
}) {
  const caixaRef = useRef<HTMLDivElement | null>(null);
  const [largura, setLargura] = useState(900);
  const [centro, setCentro] = useState(CENTRO_PT);
  const [zoom, setZoom] = useState(6);
  const [seguir, setSeguir] = useState(true);
  const arrastarRef = useRef<{ x: number; y: number; lat: number; lon: number } | null>(null);

  const pontos = useMemo<Ponto[]>(() => {
    if (modo === "concelhos") {
      return concelhos.map((item) => ({
        id: `concelho:${item.concelho}`,
        nome: item.concelho,
        lat: item.lat,
        lon: item.lon,
        peso: item.empresas,
        legenda: `${item.empresas} empresa(s)`,
        detalhe: `${item.ligacoes} ligações`,
      }));
    }
    return empresas
      .filter((item) => item.lat !== null && item.lon !== null)
      .map((item) => ({
        id: item.no_id,
        nome: item.nome,
        lat: Number(item.lat),
        lon: Number(item.lon),
        peso: Math.max(1, item.ligacoes),
        legenda: item.concelho ?? undefined,
        detalhe: [item.nif ? `NIF ${item.nif}` : null, item.local_sede].filter(Boolean).join(" · "),
      }));
  }, [concelhos, empresas, modo]);

  const maxPeso = useMemo(() => Math.max(1, ...pontos.map((ponto) => ponto.peso)), [pontos]);

  const enquadrar = useCallback(() => {
    if (!pontos.length) {
      setCentro(CENTRO_PT);
      setZoom(6);
      return;
    }
    // Percentis 2–98: um punhado de sedes em Bruxelas/Madrid não deve afastar o
    // mapa de Portugal (mas Açores e Madeira continuam dentro do enquadramento).
    const lats = pontos.map((ponto) => ponto.lat).sort((a, b) => a - b);
    const lons = pontos.map((ponto) => ponto.lon).sort((a, b) => a - b);
    const indice = (fracao: number, tamanho: number) =>
      Math.min(tamanho - 1, Math.max(0, Math.floor(fracao * (tamanho - 1))));
    const latMin = lats[indice(0.02, lats.length)];
    const latMax = lats[indice(0.98, lats.length)];
    const lonMin = lons[indice(0.02, lons.length)];
    const lonMax = lons[indice(0.98, lons.length)];
    const centroLat = (latMin + latMax) / 2;
    // Centro numa longitude próxima das existentes (Açores/Madeira incluídos).
    const centroLon = (lonMin + lonMax) / 2;
    const spanX = (Math.max(0.05, lonMax - lonMin) / 360) * TILE_SIZE;
    const spanY = Math.max(1, Math.abs(latToWorld(latMin, 0) - latToWorld(latMax, 0)));
    const zx = Math.log2((largura * 0.85) / spanX);
    const zy = Math.log2((altura * 0.85) / spanY);
    setCentro({ lat: centroLat, lon: centroLon });
    setZoom(limite(Math.round(Math.min(zx, zy)), 3, 10));
    setSeguir(true);
  }, [altura, largura, pontos]);

  useEffect(() => {
    if (seguir) enquadrar();
  }, [enquadrar, seguir]);

  useEffect(() => {
    const caixa = caixaRef.current;
    if (!caixa || typeof ResizeObserver === "undefined") return;
    const observador = new ResizeObserver((entradas) => {
      const medida = entradas[0]?.contentRect?.width;
      if (medida) setLargura(Math.round(medida));
    });
    observador.observe(caixa);
    return () => observador.disconnect();
  }, []);

  // Roda do rato: `preventDefault` exige um listener não passivo.
  useEffect(() => {
    const caixa = caixaRef.current;
    if (!caixa) return;
    const aoRodar = (evento: WheelEvent) => {
      evento.preventDefault();
      const delta = evento.deltaY > 0 ? -1 : 1;
      setSeguir(false);
      setZoom((valor) => limite(valor + delta, 3, 12));
    };
    caixa.addEventListener("wheel", aoRodar, { passive: false });
    return () => caixa.removeEventListener("wheel", aoRodar);
  }, []);

  const tiles = useMemo(() => {
    const centroX = lonToWorld(centro.lon, zoom);
    const centroY = latToWorld(centro.lat, zoom);
    const mundo = 2 ** zoom;
    const primeiroX = Math.floor((centroX - largura / 2) / TILE_SIZE);
    const ultimoX = Math.floor((centroX + largura / 2) / TILE_SIZE);
    const primeiroY = Math.max(0, Math.floor((centroY - altura / 2) / TILE_SIZE));
    const ultimoY = Math.min(mundo - 1, Math.floor((centroY + altura / 2) / TILE_SIZE));
    const lista: { key: string; url: string; left: number; top: number }[] = [];
    for (let y = primeiroY; y <= ultimoY; y += 1) {
      for (let x = primeiroX; x <= ultimoX; x += 1) {
        const tileX = ((x % mundo) + mundo) % mundo;
        lista.push({
          key: `${zoom}/${tileX}/${y}`,
          url: `https://tile.openstreetmap.org/${zoom}/${tileX}/${y}.png`,
          left: largura / 2 + (x * TILE_SIZE - centroX),
          top: altura / 2 + (y * TILE_SIZE - centroY),
        });
      }
    }
    return lista;
  }, [altura, centro, largura, zoom]);

  const marcadores = useMemo(() => {
    const centroX = lonToWorld(centro.lon, zoom);
    const centroY = latToWorld(centro.lat, zoom);
    return pontos
      .map((ponto) => {
        const x = largura / 2 + (lonToWorld(lonPerto(ponto.lon, centro.lon), zoom) - centroX);
        const y = altura / 2 + (latToWorld(ponto.lat, zoom) - centroY);
        const raio = modo === "concelhos" ? 8 + Math.sqrt(ponto.peso / maxPeso) * 20 : 4 + Math.sqrt(ponto.peso / maxPeso) * 8;
        return { ponto, x, y, raio };
      })
      .filter((item) => item.x > -50 && item.x < largura + 50 && item.y > -50 && item.y < altura + 50);
  }, [altura, centro, largura, maxPeso, modo, pontos, zoom]);

  const aoMover = (evento: React.PointerEvent<HTMLDivElement>) => {
    const estado = arrastarRef.current;
    if (!estado) return;
    const dx = evento.clientX - estado.x;
    const dy = evento.clientY - estado.y;
    const mundo = TILE_SIZE * 2 ** zoom;
    const lon = estado.lon - (dx / mundo) * 360;
    const lat = worldToLatClamped(latToWorld(estado.lat, zoom) - dy, zoom);
    setSeguir(false);
    setCentro({ lat, lon });
  };

  return (
    <div className="space-y-2">
      <div
        ref={caixaRef}
        className="relative overflow-hidden rounded-xl border border-border bg-[#0a1f29] touch-none select-none"
        style={{ height: altura }}
        onPointerDown={(evento) => {
          if ((evento.target as HTMLElement).closest("button")) return;
          arrastarRef.current = { x: evento.clientX, y: evento.clientY, lat: centro.lat, lon: centro.lon };
          (evento.currentTarget as HTMLElement).setPointerCapture(evento.pointerId);
        }}
        onPointerMove={aoMover}
        onPointerUp={() => {
          arrastarRef.current = null;
        }}
        onPointerCancel={() => {
          arrastarRef.current = null;
        }}
        role="application"
        aria-label="Mapa das sedes das empresas"
      >
        {tiles.map((tile) => (
          <img
            key={tile.key}
            src={tile.url}
            alt=""
            draggable={false}
            loading="lazy"
            decoding="async"
            className="absolute opacity-80"
            style={{ left: tile.left, top: tile.top, width: TILE_SIZE, height: TILE_SIZE }}
          />
        ))}

        {marcadores.map(({ ponto, x, y, raio }) => (
          <button
            key={ponto.id}
            type="button"
            onClick={() => onSelecionar?.(ponto)}
            title={`${ponto.nome}${ponto.legenda ? ` — ${ponto.legenda}` : ""}${ponto.detalhe ? ` · ${ponto.detalhe}` : ""}`}
            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/70 shadow-lg transition hover:scale-110 focus:outline-none focus:ring-2 focus:ring-white/70"
            style={{
              left: x,
              top: y,
              width: raio * 2,
              height: raio * 2,
              background: modo === "concelhos" ? "rgba(96,165,250,.55)" : "rgba(244,114,182,.65)",
            }}
            aria-label={ponto.nome}
          />
        ))}

        {modo === "concelhos" &&
          marcadores
            .filter((item) => item.raio > 13)
            .map((item) => (
              <span
                key={`legenda-${item.ponto.id}`}
                className="pointer-events-none absolute -translate-x-1/2 text-[9.5px] text-white/90 drop-shadow"
                style={{ left: item.x, top: item.y + item.raio + 2 }}
              >
                {item.ponto.nome}
              </span>
            ))}

        <div className="absolute right-2 top-2 flex flex-col gap-1">
          <button
            type="button"
            onClick={() => {
              setSeguir(false);
              setZoom((valor) => limite(valor + 1, 3, 12));
            }}
            className="rounded-lg border border-white/15 bg-black/50 p-1.5 text-white/80 hover:bg-black/70"
            aria-label="Aproximar"
          >
            <Plus size={13} />
          </button>
          <button
            type="button"
            onClick={() => {
              setSeguir(false);
              setZoom((valor) => limite(valor - 1, 3, 12));
            }}
            className="rounded-lg border border-white/15 bg-black/50 p-1.5 text-white/80 hover:bg-black/70"
            aria-label="Afastar"
          >
            <Minus size={13} />
          </button>
          <button
            type="button"
            onClick={() => setSeguir(true)}
            className="rounded-lg border border-white/15 bg-black/50 p-1.5 text-white/80 hover:bg-black/70"
            aria-label="Centrar nos pontos"
            title="Centrar nos pontos"
          >
            <LocateFixed size={13} />
          </button>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-black/45 px-2 py-1 text-[9.5px] text-white/75">
          <span>
            {pontos.length.toLocaleString("pt-PT")} marca(s) · {modo === "concelhos" ? "por concelho" : "por empresa"}
          </span>
          <span>© OpenStreetMap</span>
        </div>
      </div>
      {!pontos.length && (
        <p className="text-center text-[11px] text-muted-foreground">
          Sem sedes geocodificadas para os filtros atuais.
        </p>
      )}
    </div>
  );
}

/** Inversa de `latToWorld`, limitada aos polos. */
function worldToLatClamped(worldY: number, zoom: number) {
  const n = Math.PI - (2 * Math.PI * worldY) / (TILE_SIZE * 2 ** zoom);
  const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return limite(lat, -85, 85);
}
