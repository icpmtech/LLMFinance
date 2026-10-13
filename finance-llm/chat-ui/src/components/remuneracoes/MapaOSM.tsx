/**
 * **Mapa OpenStreetMap** dos territórios do módulo de remunerações.
 *
 * Os dados do MAI não trazem latitude/longitude — os polígonos que publica vivem
 * no sistema de coordenadas do seu próprio mapa. Por isso o mapa assenta nas
 * coordenadas geográficas recolhidas da Wikidata (as que servem o OpenStreetMap,
 * ver `getMapaRemuneracoes` no cliente da API) e desenha **um ponto por
 * concelho**, ou por freguesia quando o mapa é o de um município.
 *
 * É navegável: arrastar para percorrer, roda do rato ou +/− para o zoom e
 * «Enquadrar» para voltar a ver tudo. Cada ponto é clicável e abre a ficha do
 * território; ao passar por cima mostra os eleitores, os votantes e o abono.
 *
 * Os *tiles* são servidos pelo OpenStreetMap, sem dependências de mapas — o
 * mesmo princípio do mapa de contratos (`components/benchmark/BuyerMap.tsx`).
 * A navegação fica presa a Portugal: nem o arrasto nem o zoom saem de
 * `LIMITES_PORTUGAL`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Loader2, Minus, Plus } from "lucide-react";

import { TILE_SIZE, latToWorld, lonToWorld, worldToLat, worldToLon } from "../graph/geo";
import { euro, numero } from "../../remuneracoesApi";

export type MapaPonto = {
  id: number;
  nome: string;
  lat: number;
  lon: number;
  eleitores?: number | null;
  votantes?: number | null;
  escalao?: string | null;
  remuneracao_mensal?: number | null;
  /** Linha secundária do balão (distrito, ou concelho no mapa das freguesias). */
  contexto?: string | null;
  /** Foto da câmara municipal (Wikimedia Commons), com créditos. */
  foto?: string | null;
  foto_autor?: string | null;
  foto_licenca?: string | null;
  foto_pagina?: string | null;
};

export type MetricaMapa = "eleitores" | "votantes" | "remuneracao";

const LARGURA = 900;
const ALTURA = 560;
const ZOOM_MAXIMO = 13;

/**
 * Caixa que envolve Portugal continental, a Madeira e os Açores. A navegação
 * fica presa a ela: o mapa mostra Portugal, não o Atlântico nem os países
 * vizinhos.
 */
const LIMITES_PORTUGAL = { minLat: 28.8, maxLat: 42.2, minLon: -31.6, maxLon: -6.0 };

/** Acima deste nível o OpenStreetMap deixa de ter *tiles*. */
const NIVEL_MAXIMO_TILES = 19;

/** Zoom mínimo: aquele em que o país ainda cabe todo no mapa. */
function zoomMinimoPais(altura: number): number {
  for (let z = ZOOM_MAXIMO; z > 3; z -= 0.1) {
    const largura =
      lonToWorld(LIMITES_PORTUGAL.maxLon, z) - lonToWorld(LIMITES_PORTUGAL.minLon, z);
    const alt = latToWorld(LIMITES_PORTUGAL.minLat, z) - latToWorld(LIMITES_PORTUGAL.maxLat, z);
    if (largura <= LARGURA && alt <= altura) return Number(z.toFixed(2));
  }
  return 3;
}

/**
 * Prende o centro a Portugal. Quando a vista é maior do que o país (no zoom
 * mínimo, por exemplo) centra-o em vez de o encostar a um canto.
 */
function limitarCentro(lat: number, lon: number, zoom: number, altura: number) {
  const prender = (valor: number, minimo: number, maximo: number, meiaVista: number) => {
    if (maximo - minimo <= meiaVista * 2) return (minimo + maximo) / 2;
    return Math.min(maximo - meiaVista, Math.max(minimo + meiaVista, valor));
  };
  const x = prender(
    lonToWorld(lon, zoom),
    lonToWorld(LIMITES_PORTUGAL.minLon, zoom),
    lonToWorld(LIMITES_PORTUGAL.maxLon, zoom),
    LARGURA / 2,
  );
  const y = prender(
    latToWorld(lat, zoom),
    latToWorld(LIMITES_PORTUGAL.maxLat, zoom),
    latToWorld(LIMITES_PORTUGAL.minLat, zoom),
    altura / 2,
  );
  return { lat: worldToLat(y, zoom), lon: worldToLon(x, zoom) };
}

/** Paleta do menos para o mais, do azul profundo ao âmbar. */
const CORES = ["#134e5a", "#0e7490", "#0891b2", "#14b8a6", "#5eead4", "#bef264", "#fcd34d"];

function valorDaMetrica(ponto: MapaPonto, metrica: MetricaMapa): number {
  if (metrica === "votantes") return ponto.votantes ?? 0;
  if (metrica === "remuneracao") return ponto.remuneracao_mensal ?? 0;
  return ponto.eleitores ?? 0;
}

function corPorPosicao(t: number): string {
  const indice = Math.min(CORES.length - 1, Math.max(0, Math.round(t * (CORES.length - 1))));
  return CORES[indice];
}

function escalaDoValor(valor: number, minimo: number, maximo: number): number {
  if (!Number.isFinite(valor) || maximo <= minimo) return 0.5;
  if (minimo <= 0) {
    // Sem mínimo positivo (o abono do município ainda não está importado) a
    // escala é linear.
    return (valor - minimo) / (maximo - minimo);
  }
  // Logarítmica: os concelhos vão de ~380 a ~460 mil eleitores e, numa escala
  // linear, todos os pequenos ficariam com a mesma cor.
  return (Math.log(valor) - Math.log(minimo)) / (Math.log(maximo) - Math.log(minimo));
}

export default function MapaOSM({
  pontos,
  selecionado,
  onSelecionar,
  metrica = "eleitores",
  altura = ALTURA,
  semCoordenadas = [],
  legenda,
}: {
  pontos: MapaPonto[];
  selecionado?: number | null;
  onSelecionar?: (ponto: MapaPonto) => void;
  metrica?: MetricaMapa;
  altura?: number;
  /** Territórios que a georreferenciação não cobre — ditos, para não faltarem em silêncio. */
  semCoordenadas?: string[];
  legenda?: string;
}) {
  const [zoom, setZoom] = useState(6.4);
  const [centro, setCentro] = useState<{ lat: number; lon: number }>({ lat: 39.6, lon: -8.2 });
  const [arrasto, setArrasto] = useState<{ x: number; y: number; lat: number; lon: number } | null>(null);
  const [sobre, setSobre] = useState<MapaPonto | null>(null);
  const caixa = useRef<HTMLDivElement | null>(null);
  const zoomMinimo = useMemo(() => zoomMinimoPais(altura), [altura]);

  const localizados = useMemo(
    () => pontos.filter((ponto) => Number.isFinite(ponto.lat) && Number.isFinite(ponto.lon)),
    [pontos],
  );

  /** Zoom e centro que põem todos os pontos no ecrã, com folga nas margens. */
  const enquadrar = useCallback(
    (lista: MapaPonto[]) => {
      if (!lista.length) return;
      const lats = lista.map((ponto) => ponto.lat);
      const lons = lista.map((ponto) => ponto.lon);
      const minLat = Math.min(...lats);
      const maxLat = Math.max(...lats);
      const minLon = Math.min(...lons);
      const maxLon = Math.max(...lons);
      let escolhido = zoomMinimo;
      for (let z = ZOOM_MAXIMO; z > zoomMinimo; z -= 0.2) {
        const extensaoX = Math.abs(lonToWorld(maxLon, z) - lonToWorld(minLon, z));
        const extensaoY = Math.abs(latToWorld(minLat, z) - latToWorld(maxLat, z));
        if (extensaoX <= LARGURA - 70 && extensaoY <= altura - 70) {
          escolhido = z;
          break;
        }
      }
      setCentro(limitarCentro((minLat + maxLat) / 2, (minLon + maxLon) / 2, escolhido, altura));
      setZoom(escolhido);
    },
    [altura, zoomMinimo],
  );

  // Enquadra quando muda o conjunto de pontos (muda de mapa, de concelho ou de
  // filtro de distrito) — mas não a cada mudança de seleção.
  const assinatura = useMemo(
    () => `${localizados.length}:${localizados[0]?.id ?? ""}:${localizados[localizados.length - 1]?.id ?? ""}`,
    [localizados],
  );
  const assinaturaAnterior = useRef("");
  useEffect(() => {
    if (assinaturaAnterior.current === assinatura) return;
    assinaturaAnterior.current = assinatura;
    enquadrar(localizados);
  }, [assinatura, localizados, enquadrar]);

  // O centro pedido pode cair fora de Portugal (arrasto ou mudança de zoom):
  // o que se desenha é sempre o centro limitado ao país.
  const centroEfetivo = useMemo(
    () => limitarCentro(centro.lat, centro.lon, zoom, altura),
    [altura, centro.lat, centro.lon, zoom],
  );

  const centroX = lonToWorld(centroEfetivo.lon, zoom);
  const centroY = latToWorld(centroEfetivo.lat, zoom);

  const projectar = useCallback(
    (lat: number, lon: number) => ({
      x: LARGURA / 2 + (lonToWorld(lon, zoom) - centroX),
      y: altura / 2 + (latToWorld(lat, zoom) - centroY),
    }),
    [altura, centroX, centroY, zoom],
  );

  const tiles = useMemo(() => {
    // Os *tiles* existem só em níveis inteiros, mas o mapa usa zoom fracionário
    // (é o que permite enquadrar seja o que for). Desenham-se por isso
    // escalados por `2 ** (zoom - nivel)`, senão a geografia do mapa ficaria
    // desalinhada dos pontos.
    const nivel = Math.max(0, Math.min(NIVEL_MAXIMO_TILES, Math.round(zoom)));
    const escala = 2 ** (zoom - nivel);
    const lado = TILE_SIZE * escala;
    const mundo = 2 ** nivel;
    const primeiroX = Math.floor((centroX - LARGURA / 2) / lado);
    const ultimoX = Math.floor((centroX + LARGURA / 2) / lado);
    const primeiroY = Math.max(0, Math.floor((centroY - altura / 2) / lado));
    const ultimoY = Math.min(mundo - 1, Math.floor((centroY + altura / 2) / lado));
    const lista: { chave: string; url: string; x: number; y: number; lado: number }[] = [];
    for (let y = primeiroY; y <= ultimoY; y += 1) {
      for (let x = primeiroX; x <= ultimoX; x += 1) {
        const envolvido = ((x % mundo) + mundo) % mundo;
        lista.push({
          chave: `${nivel}/${envolvido}/${y}`,
          url: `https://tile.openstreetmap.org/${nivel}/${envolvido}/${y}.png`,
          x: LARGURA / 2 + (x * lado - centroX),
          y: altura / 2 + (y * lado - centroY),
          lado,
        });
      }
    }
    return lista;
  }, [altura, centroX, centroY, zoom]);

  const valores = localizados.map((ponto) => valorDaMetrica(ponto, metrica)).filter((valor) => valor > 0);
  const minimo = valores.length ? Math.min(...valores) : 0;
  const maximo = valores.length ? Math.max(...valores) : 1;

  const rotuloMetrica =
    metrica === "votantes" ? "Votantes" : metrica === "remuneracao" ? "Abono mensal" : "Eleitores";

  useEffect(() => {
    const elemento = caixa.current;
    if (!elemento) return;
    const aoRodar = (evento: WheelEvent) => {
      evento.preventDefault();
      setZoom((valor) =>
        Math.min(ZOOM_MAXIMO, Math.max(zoomMinimo, valor - evento.deltaY / 500)),
      );
    };
    elemento.addEventListener("wheel", aoRodar, { passive: false });
    return () => elemento.removeEventListener("wheel", aoRodar);
  }, [zoomMinimo]);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#04121a]" data-context-scope>
      <div ref={caixa} className="relative">
        <svg
          viewBox={`0 0 ${LARGURA} ${altura}`}
          className="w-full cursor-grab select-none active:cursor-grabbing"
          style={{ height: altura }}
          role="img"
          aria-label={`Mapa OpenStreetMap dos territórios por ${rotuloMetrica.toLowerCase()}`}
          onMouseDown={(evento) =>
            setArrasto({
              x: evento.clientX,
              y: evento.clientY,
              lat: centroEfetivo.lat,
              lon: centroEfetivo.lon,
            })
          }
          onMouseMove={(evento) => {
            if (!arrasto) return;
            const mundoX = lonToWorld(arrasto.lon, zoom) - (evento.clientX - arrasto.x);
            const mundoY = latToWorld(arrasto.lat, zoom) - (evento.clientY - arrasto.y);
            setCentro({ lat: worldToLat(mundoY, zoom), lon: worldToLon(mundoX, zoom) });
          }}
          onMouseUp={() => setArrasto(null)}
          onMouseLeave={() => {
            setArrasto(null);
            setSobre(null);
          }}
        >
          {tiles.map((tile) => (
            <image
              key={tile.chave}
              href={tile.url}
              x={tile.x}
              y={tile.y}
              // O meio píxel a mais evita a costura entre *tiles* escalados.
              width={tile.lado + 0.6}
              height={tile.lado + 0.6}
              opacity={0.72}
              preserveAspectRatio="none"
            />
          ))}

          {localizados.map((ponto) => {
            const posicao = projectar(ponto.lat, ponto.lon);
            const t = escalaDoValor(valorDaMetrica(ponto, metrica), minimo, maximo);
            const raio = 4 + 9 * Math.min(1, Math.max(0, t));
            const ativo = selecionado === ponto.id;
            return (
              <g
                key={ponto.id}
                className="cursor-pointer"
                onClick={() => onSelecionar?.(ponto)}
                onMouseEnter={() => setSobre(ponto)}
              >
                <circle
                  cx={posicao.x}
                  cy={posicao.y}
                  r={raio}
                  fill={corPorPosicao(t)}
                  fillOpacity={ativo ? 0.95 : 0.7}
                  stroke={ativo ? "#fbbf24" : "#0f172a"}
                  strokeWidth={ativo ? 2.6 : 1}
                />
                <circle cx={posicao.x} cy={posicao.y} r={1.6} fill="#f8fafc" fillOpacity={0.9} />
                {t > 0.55 || ativo ? (
                  <text
                    x={posicao.x + raio + 3}
                    y={posicao.y + 3.5}
                    className="fill-slate-100 text-[10px]"
                    style={{ paintOrder: "stroke", stroke: "#04121a", strokeWidth: 2.4 }}
                  >
                    {ponto.nome}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>

        <div className="absolute right-3 top-3 z-20 flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setZoom((valor) => Math.min(ZOOM_MAXIMO, valor + 0.7))}
            className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-xs text-foreground transition hover:bg-white/10"
            title="Aproximar"
          >
            <Plus size={13} />
          </button>
          <button
            type="button"
            onClick={() => setZoom((valor) => Math.max(zoomMinimo, valor - 0.7))}
            className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-xs text-foreground transition hover:bg-white/10"
            title="Afastar"
          >
            <Minus size={13} />
          </button>
          <button
            type="button"
            onClick={() => enquadrar(localizados)}
            className="rounded-lg border border-white/10 bg-[#07151b]/90 px-2 py-1 text-xs text-foreground transition hover:bg-white/10"
            title="Enquadrar todos os territórios"
          >
            <Crosshair size={13} />
          </button>
        </div>

        {sobre ? (
          <div className="pointer-events-none absolute left-3 top-3 z-20 max-w-[280px] rounded-xl border border-white/10 bg-[#04121a]/95 p-3 text-[11px] shadow-lg">
            {sobre.foto ? (
              <figure className="mb-2 overflow-hidden rounded-lg">
                <img src={sobre.foto} alt={`Câmara municipal de ${sobre.nome}`} className="h-28 w-full object-cover" />
                <figcaption className="mt-1 text-[9px] leading-tight text-muted-foreground">
                  {sobre.foto_autor ? `© ${sobre.foto_autor}` : null}
                  {sobre.foto_licenca ? ` · ${sobre.foto_licenca}` : null}
                  {sobre.foto_pagina ? (
                    <>
                      {" "}
                      · <span className="underline">Commons</span>
                    </>
                  ) : null}
                </figcaption>
              </figure>
            ) : null}
            <p className="text-sm font-semibold">{sobre.nome}</p>
            {sobre.contexto ? <p className="text-muted-foreground">{sobre.contexto}</p> : null}
            <dl className="mt-2 space-y-0.5">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Eleitores</dt>
                <dd className="tabular-nums">{numero(sobre.eleitores)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Votantes</dt>
                <dd className="tabular-nums">{numero(sobre.votantes)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Escalão</dt>
                <dd className="text-right">{sobre.escalao ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Abono mensal</dt>
                <dd className="tabular-nums">{euro(sobre.remuneracao_mensal)}</dd>
              </div>
            </dl>
          </div>
        ) : null}

        {localizados.length === 0 ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-muted-foreground">
            <Loader2 size={14} className="mr-2 animate-spin" /> A carregar o mapa…
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-white/5 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="font-medium text-foreground">{rotuloMetrica}:</span>
          {numero(Math.round(minimo))} → {numero(Math.round(maximo))}
        </span>
        <span className="inline-flex items-center gap-1" title="Tamanho e cor do ponto">
          {CORES.map((cor) => (
            <span key={cor} className="h-2.5 w-5 rounded-sm" style={{ background: cor }} />
          ))}
        </span>
        <span>{localizados.length} territórios no mapa</span>
        {semCoordenadas.length ? (
          <span className="text-amber-300/90">
            {semCoordenadas.length} sem coordenadas conhecidas: {semCoordenadas.slice(0, 4).join(", ")}
            {semCoordenadas.length > 4 ? "…" : ""}
          </span>
        ) : null}
        <span className="ml-auto">
          Arraste para navegar dentro de Portugal · roda do rato ou +/− para o zoom · © OpenStreetMap
        </span>
      </div>
      {legenda ? <p className="px-3 pb-2 text-[10px] text-muted-foreground">{legenda}</p> : null}
    </div>
  );
}
