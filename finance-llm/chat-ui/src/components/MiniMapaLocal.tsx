import { useMemo } from "react";
import { latToWorld, lonToWorld, lookupPlace, TILE_SIZE } from "./graph/geo";

/**
 * Normaliza `localExecucao`, que a API devolve como **lista com repetições**
 * (o mesmo local repetido dezenas de vezes): deduplica mantendo a ordem e limita
 * a `max` entradas, para o texto do cartão não sair colado.
 */
export function localTexto(valor: string | string[] | null | undefined, max = 3): string {
  const itens = (Array.isArray(valor) ? valor : valor == null ? [] : [valor])
    .map((v) => String(v ?? "").trim())
    .filter(Boolean);
  const unicos: string[] = [];
  const vistos = new Set<string>();
  for (const item of itens) {
    const chave = item.toLowerCase();
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    unicos.push(item);
  }
  if (unicos.length <= max) return unicos.join(" · ");
  return `${unicos.slice(0, max).join(" · ")} · +${unicos.length - max}`;
}

/** Lista deduplicada de locais, da mais provável (ordem da API) para a menos. */
function locaisDistintos(valor: string | string[] | null | undefined): string[] {
  const itens = (Array.isArray(valor) ? valor : valor == null ? [] : [valor])
    .map((v) => String(v ?? "").trim())
    .filter(Boolean);
  const unicos: string[] = [];
  const vistos = new Set<string>();
  for (const item of itens) {
    const chave = item.toLowerCase();
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    unicos.push(item);
  }
  return unicos;
}

/**
 * Mini-mapa da localização de um contrato.
 *
 * O campo `localExecucao` é texto livre («Portugal, Porto, Porto», «Espanha,
 * Madrid»), pelo que se resolve a parte **mais específica** (a última) contra os
 * centroides conhecidos em `graph/geo`. Quando nada resolve, não se desenha mapa
 * nenhum — é preferível não mostrar nada a apontar para o sítio errado.
 *
 * O ponto é sempre um **centroide** (concelho/distrito/região), nunca um
 * endereço: o rodapé di-lo, e quando a posição vem do NUTS pai ou do país
 * aparece «aproximado».
 */
export function MiniMapaLocal({
  local,
  largura = 224,
  altura = 124,
  zoom = 10,
}: {
  local?: string | string[] | null;
  largura?: number;
  altura?: number;
  zoom?: number;
}) {
  const resolvido = useMemo(() => {
    // Da parte mais específica para a mais genérica: «Portugal, Porto, Porto»
    // tenta primeiro «Porto» (concelho) e só depois «Portugal». Percorre os
    // locais distintos até um deles dar coordenadas.
    for (const localizacao of locaisDistintos(local)) {
      const partes = localizacao
        .split(/[,;]/)
        .map((p) => p.trim())
        .filter(Boolean)
        .reverse();
      for (const parte of partes) {
        const ponto = lookupPlace(parte);
        if (ponto) return { ...ponto, nome: parte };
      }
    }
    return null;
  }, [local]);

  const projecao = useMemo(() => {
    if (!resolvido) return null;
    const centerX = lonToWorld(resolvido.lon, zoom);
    const centerY = latToWorld(resolvido.lat, zoom);
    const mundo = 2 ** zoom;
    const primeiroX = Math.floor((centerX - largura / 2) / TILE_SIZE);
    const ultimoX = Math.floor((centerX + largura / 2) / TILE_SIZE);
    const primeiroY = Math.max(0, Math.floor((centerY - altura / 2) / TILE_SIZE));
    const ultimoY = Math.min(mundo - 1, Math.floor((centerY + altura / 2) / TILE_SIZE));
    const tiles: { key: string; url: string; left: number; top: number }[] = [];
    for (let tileY = primeiroY; tileY <= ultimoY; tileY++) {
      for (let tileX = primeiroX; tileX <= ultimoX; tileX++) {
        const x = ((tileX % mundo) + mundo) % mundo;
        tiles.push({
          key: `${zoom}/${x}/${tileY}`,
          url: `https://tile.openstreetmap.org/${zoom}/${x}/${tileY}.png`,
          left: largura / 2 + (tileX * TILE_SIZE - centerX),
          top: altura / 2 + (tileY * TILE_SIZE - centerY),
        });
      }
    }
    return { tiles };
  }, [altura, largura, resolvido, zoom]);

  if (!resolvido || !projecao) return null;

  return (
    <figure
      className="relative overflow-hidden rounded-xl border border-white/10 bg-[#0a1f29] pointer-events-none select-none"
      style={{ width: largura, height: altura }}
      aria-label={`Mapa da localização ${resolvido.nome}`}
    >
      {projecao.tiles.map((tile) => (
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

      {/* Alfinete no centro da caixa (o mapa está centrado na localização). */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="8" fill="rgba(45,212,191,.35)" />
          <circle cx="12" cy="12" r="4.5" fill="#2dd4bf" stroke="#0f172a" strokeWidth="1.5" />
        </svg>
      </div>

      <figcaption className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-black/55 px-2 py-0.5 text-[9.5px] leading-tight text-white/80">
        <span className="truncate">
          ≈ {resolvido.nome}
          {resolvido.exact ? "" : " (aproximado)"}
        </span>
        <span className="shrink-0 text-white/55">© OpenStreetMap</span>
      </figcaption>
    </figure>
  );
}
