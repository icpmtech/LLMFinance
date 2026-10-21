/**
 * Mapa ESG — onde estão as empresas e como se distribui o score por região.
 *
 * Duas leituras sobre o mesmo fundo OpenStreetMap:
 *
 * - **Regiões** — um círculo por distrito (PT) ou província (ES), com o número
 *   de empresas e a cor do nível do score médio;
 * - **Empresas** — um ponto por empresa, com a cor do seu nível.
 *
 * A posição vem do `location.distrito`/`location.concelho` do cadastro, pelo que
 * é sempre o centro da região e nunca um endereço. Uma empresa sem distrito não
 * é colocada num sítio inventado: conta para «sem localização» e o painel diz
 * quantas ficaram de fora.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Building2, Crosshair, Globe2, Layers, Loader2, MapPin, Minus, Plus, RefreshCw, X } from "lucide-react";

import { getEsgMapa } from "../../esgApi";
import type { EsgEmpresaResumo, EsgMapaEmpresa, EsgMapaRegiao, EsgMapaResposta, EsgMeta } from "../../esgApi";
import { allIberiaRegions, foldIberiaText, isOffshoreRegion, resolveIberiaRegion } from "../geo/iberia";
import { TILE_SIZE, jitterAround, latToWorld, lonToWorld, worldToLat, worldToLon } from "../graph/geo";
import { EmptyState, Loading, SectionCard } from "../padroes/padroesKit";
import { EsgBadge, compactEuro, esgCor, num, pct } from "./esgKit";

const VISTA_INICIAL = { lat: 39.4, lon: -8.9, zoom: 6 };
const ZOOM_MIN = 4;
const ZOOM_MAX = 11;

type Modo = "regioes" | "empresas";

type Ponto = { lat: number; lon: number };

type EmpresaNoMapa = EsgMapaEmpresa & Ponto;

type RegiaoNoMapa = EsgMapaRegiao & Ponto & { nome: string; approx: boolean };

type Dica = { x: number; y: number; titulo: string; linhas: string[]; cor: string };

/** Resolve o distrito/província numa posição conhecida (nunca inventa). */
function resolverRegiao(pais: string, distrito: string): { lat: number; lon: number; nome: string; approx: boolean } | null {
  const codigo = pais === "ES" ? "ES" : "PT";
  const direto = resolveIberiaRegion(codigo, distrito);
  if (direto) return { lat: direto.lat, lon: direto.lon, nome: direto.name, approx: direto.approx };
  const alvo = foldIberiaText(distrito);
  if (!alvo) return null;
  const porNome = allIberiaRegions().find(
    (regiao) => regiao.pais === codigo && (foldIberiaText(regiao.name) === alvo || foldIberiaText(regiao.code) === alvo),
  );
  return porNome ? { lat: porNome.lat, lon: porNome.lon, nome: porNome.name, approx: porNome.approx } : null;
}

/** Nível do cartão do modelo a que um score pertence (cor e etiqueta). */
function nivelDoScore(meta: EsgMeta | null, score?: number | null) {
  if (score === null || score === undefined) return null;
  const niveis = [...(meta?.cartao_modelo.niveis || [])].sort((a, b) => b.min - a.min);
  return niveis.find((nivel) => score >= nivel.min) ?? null;
}

function comoResumo(empresa: EsgMapaEmpresa): EsgEmpresaResumo {
  return {
    nif: empresa.nif,
    nome: empresa.nome,
    pais: empresa.pais,
    setor: null,
    setor_label: empresa.setor_label,
    dimensao: null,
    dimensao_label: empresa.dimensao_label,
    score: empresa.score,
    nivel: empresa.nivel,
    nivel_label: empresa.nivel_label || "",
    cor: empresa.cor || esgCor(empresa.nivel),
    cobertura: empresa.cobertura ?? 0,
    confianca: "—",
    pilares: {},
    contratos: empresa.contratos,
    valor: empresa.valor,
  };
}

/** Vista que enquadra todos os pontos (com um mínimo, para não colar o zoom). */
function vistaPara(pontos: Ponto[], largura: number, altura: number, incluirIlhas = false) {
  if (!pontos.length) return VISTA_INICIAL;
  // As ilhas ficam fora do enquadramento continental — como nos mapas de
  // contratos, aparecem na lista (e o foco leva até elas).
  const continente = incluirIlhas ? pontos : pontos.filter((ponto) => !isOffshoreRegion(ponto));
  const base = continente.length ? continente : pontos;
  const lats = base.map((ponto) => ponto.lat);
  const lons = base.map((ponto) => ponto.lon);
  const centro = { lat: (Math.min(...lats) + Math.max(...lats)) / 2, lon: (Math.min(...lons) + Math.max(...lons)) / 2 };
  const spanLat = Math.max(Math.max(...lats) - Math.min(...lats), 0.5);
  const spanLon = Math.max(Math.max(...lons) - Math.min(...lons), 0.5);
  let zoom = ZOOM_MAX;
  while (zoom > ZOOM_MIN) {
    const larguraMundo = lonToWorld(centro.lon + spanLon / 2, zoom) - lonToWorld(centro.lon - spanLon / 2, zoom);
    const alturaMundo = latToWorld(centro.lat - spanLat / 2, zoom) - latToWorld(centro.lat + spanLat / 2, zoom);
    if (larguraMundo <= largura * 0.78 && alturaMundo <= altura * 0.78) break;
    zoom -= 1;
  }
  return { ...centro, zoom };
}

/** Nome curto para as etiquetas do mapa (as regiões autónomas não cabem). */
function rotuloCurto(nome: string) {
  return nome.replace(/^Região Autónoma d[oa]s?\s+/i, "");
}

function dicaDaRegiao(regiao: RegiaoNoMapa, cor: string): Omit<Dica, "x" | "y"> {
  return {
    titulo: regiao.distrito,
    linhas: [
      `${regiao.n} empresa(s) · score médio ${regiao.score_medio?.toFixed(1) ?? "—"}`,
      regiao.nivel_label ? `Nível dominante: ${regiao.nivel_label}` : "Sem nível dominante",
      `Cobertura média ${pct(regiao.cobertura_media, 0)}`,
    ],
    cor,
  };
}

function dicaDaEmpresa(empresa: EsgMapaEmpresa, cor: string): Omit<Dica, "x" | "y"> {
  return {
    titulo: empresa.nome,
    linhas: [
      `Score ${empresa.score?.toFixed(1) ?? "—"} · ${empresa.nivel_label || "sem nível"}`,
      [empresa.concelho, empresa.distrito].filter(Boolean).join(" · ") || "Sem localização",
      empresa.setor_label || "Setor n/d",
    ],
    cor,
  };
}

function BarraNiveis({ niveis, total }: { niveis: EsgMapaRegiao["niveis"]; total: number }) {
  if (!niveis.length) return null;
  return (
    <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-white/5" title={niveis.map((item) => `${item.label}: ${item.n}`).join(" · ")}>
      {niveis.map((item) => (
        <span key={item.id} style={{ width: `${(item.n / Math.max(1, total)) * 100}%`, backgroundColor: item.cor }} />
      ))}
    </div>
  );
}

export function EsgMapa({
  meta,
  onAbrir,
  pais = "",
  setor = "",
  dimensao = "",
  ano = "",
  contagens,
}: {
  meta: EsgMeta | null;
  onAbrir: (item: EsgEmpresaResumo) => void;
  pais?: string;
  setor?: string;
  dimensao?: string;
  ano?: string;
  /** Quantas empresas por nível nos filtros do painel (sem filtro de nível). */
  contagens?: Record<string, number>;
}) {
  const [dados, setDados] = useState<EsgMapaResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [nivel, setNivel] = useState("");
  const [modo, setModo] = useState<Modo>("regioes");
  const [selecionada, setSelecionada] = useState<string | null>(null);
  const [dica, setDica] = useState<Dica | null>(null);

  const caixaRef = useRef<HTMLDivElement | null>(null);
  const [tamanho, setTamanho] = useState({ largura: 720, altura: 460 });
  const [centro, setCentro] = useState({ lat: VISTA_INICIAL.lat, lon: VISTA_INICIAL.lon });
  const [zoom, setZoom] = useState(VISTA_INICIAL.zoom);
  const arrastarRef = useRef<{ x: number; y: number; lat: number; lon: number } | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const enquadradoRef = useRef(false);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro("");
    getEsgMapa({
      pais: pais || undefined,
      setor: setor || undefined,
      dimensao: dimensao || undefined,
      nivel: nivel || undefined,
      ano: ano ? Number(ano) : undefined,
    })
      .then(setDados)
      .catch((exc: unknown) => setErro(exc instanceof Error ? exc.message : "Não foi possível carregar o mapa ESG."))
      .finally(() => setCarregando(false));
  }, [pais, setor, dimensao, nivel, ano]);

  useEffect(() => {
    enquadradoRef.current = false;
    setSelecionada(null);
    carregar();
  }, [carregar]);

  /** Tamanho real do contentor (a grelha de tiles parte daqui, sem offsets fixos). */
  useEffect(() => {
    const elemento = caixaRef.current;
    if (!elemento) return;
    const medir = () => setTamanho({ largura: elemento.clientWidth, altura: elemento.clientHeight });
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(elemento);
    return () => observador.disconnect();
  }, [dados?.disponivel]);

  const porRegiao = useMemo(() => {
    const mapa = new Map<string, { lat: number; lon: number; nome: string; approx: boolean }>();
    for (const regiao of dados?.regioes || []) {
      const ponto = resolverRegiao(regiao.pais, regiao.distrito);
      if (ponto) mapa.set(`${regiao.pais}|${regiao.distrito}`, ponto);
    }
    return mapa;
  }, [dados]);

  const regioesNoMapa = useMemo<RegiaoNoMapa[]>(
    () =>
      (dados?.regioes || []).flatMap((regiao) => {
        const ponto = porRegiao.get(`${regiao.pais}|${regiao.distrito}`);
        return ponto ? [{ ...regiao, ...ponto }] : [];
      }),
    [dados, porRegiao],
  );

  const regioesForaDoMapa = useMemo(
    () => (dados?.regioes || []).filter((regiao) => !porRegiao.has(`${regiao.pais}|${regiao.distrito}`)),
    [dados, porRegiao],
  );

  const empresasNoMapa = useMemo<EmpresaNoMapa[]>(
    () =>
      (dados?.empresas || []).flatMap((empresa) => {
        if (!empresa.distrito) return [];
        const regiao = porRegiao.get(`${empresa.pais}|${empresa.distrito}`);
        if (!regiao) return [];
        return [{ ...empresa, ...jitterAround(regiao, empresa.nif, 0.16) }];
      }),
    [dados, porRegiao],
  );

  const pontosParaEnquadrar = modo === "empresas" ? empresasNoMapa : regioesNoMapa;

  useEffect(() => {
    if (enquadradoRef.current || !dados || carregando) return;
    const pontos = [...empresasNoMapa, ...regioesNoMapa];
    if (!pontos.length) return;
    const vista = vistaPara(pontos, tamanho.largura, tamanho.altura);
    setCentro({ lat: vista.lat, lon: vista.lon });
    setZoom(vista.zoom);
    enquadradoRef.current = true;
  }, [carregando, dados, empresasNoMapa, regioesNoMapa, tamanho.altura, tamanho.largura]);

  const enquadrar = useCallback(() => {
    const vista = vistaPara(pontosParaEnquadrar, tamanho.largura, tamanho.altura, true);
    setCentro({ lat: vista.lat, lon: vista.lon });
    setZoom(vista.zoom);
  }, [pontosParaEnquadrar, tamanho.altura, tamanho.largura]);

  /** Selecionar uma região leva o mapa até ela (as ilhas ficam fora do enquadramento inicial). */
  const focarRegiao = useCallback((regiao: RegiaoNoMapa) => {
    setCentro({ lat: regiao.lat, lon: regiao.lon });
    setZoom((atual) => Math.min(ZOOM_MAX, Math.max(atual, 7)));
  }, []);

  const projecao = useMemo(() => {
    const largura = tamanho.largura || 720;
    const altura = tamanho.altura || 460;
    const centroX = lonToWorld(centro.lon, zoom);
    const centroY = latToWorld(centro.lat, zoom);
    const mundo = 2 ** zoom;

    const primeiroX = Math.floor((centroX - largura / 2) / TILE_SIZE);
    const ultimoX = Math.floor((centroX + largura / 2) / TILE_SIZE);
    const primeiroY = Math.max(0, Math.floor((centroY - altura / 2) / TILE_SIZE));
    const ultimoY = Math.min(mundo - 1, Math.floor((centroY + altura / 2) / TILE_SIZE));

    const tiles: { key: string; url: string; left: number; top: number }[] = [];
    for (let tileY = primeiroY; tileY <= ultimoY; tileY++) {
      for (let tileX = primeiroX; tileX <= ultimoX; tileX++) {
        const x = ((tileX % mundo) + mundo) % mundo;
        tiles.push({
          key: `${zoom}/${x}/${tileY}`,
          url: `https://tile.openstreetmap.org/${zoom}/${x}/${tileY}.png`,
          left: largura / 2 + (tileX * TILE_SIZE - centroX),
          top: altura / 2 + (tileY * TILE_SIZE - centroY),
        });
      }
    }

    return {
      tiles,
      project: (lat: number, lon: number) => ({
        left: largura / 2 + (lonToWorld(lon, zoom) - centroX),
        top: altura / 2 + (latToWorld(lat, zoom) - centroY),
      }),
    };
  }, [centro.lat, centro.lon, tamanho.altura, tamanho.largura, zoom]);

  /** Zoom com o ponto sob o cursor (ou o centro) fixo. */
  const zoomEm = useCallback(
    (delta: number, ancora?: { x: number; y: number }) => {
      const seguinte = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom + delta));
      if (seguinte === zoom) return;
      const caixa = caixaRef.current?.getBoundingClientRect();
      const desvioX = ancora && caixa ? ancora.x - caixa.left - tamanho.largura / 2 : 0;
      const desvioY = ancora && caixa ? ancora.y - caixa.top - tamanho.altura / 2 : 0;
      const lonAncora = worldToLon(lonToWorld(centro.lon, zoom) + desvioX, zoom);
      const latAncora = worldToLat(latToWorld(centro.lat, zoom) + desvioY, zoom);
      setCentro({
        lat: worldToLat(latToWorld(latAncora, seguinte) - desvioY, seguinte),
        lon: worldToLon(lonToWorld(lonAncora, seguinte) - desvioX, seguinte),
      });
      setZoom(seguinte);
    },
    [centro.lat, centro.lon, tamanho.altura, tamanho.largura, zoom],
  );

  useEffect(() => {
    const elemento = caixaRef.current;
    if (!elemento) return;
    const aoRodar = (evento: WheelEvent) => {
      evento.preventDefault();
      zoomEm(evento.deltaY > 0 ? -1 : 1, { x: evento.clientX, y: evento.clientY });
    };
    elemento.addEventListener("wheel", aoRodar, { passive: false });
    return () => elemento.removeEventListener("wheel", aoRodar);
  }, [zoomEm, dados?.disponivel]);

  const aoPremir = (evento: React.PointerEvent<HTMLDivElement>) => {
    if ((evento.target as HTMLElement).closest("[data-mapa-chrome]")) return;
    arrastarRef.current = { x: evento.clientX, y: evento.clientY, lat: centro.lat, lon: centro.lon };
    setArrastando(true);
    evento.currentTarget.setPointerCapture(evento.pointerId);
  };

  const aoMover = (evento: React.PointerEvent<HTMLDivElement>) => {
    const inicio = arrastarRef.current;
    if (!inicio) return;
    setCentro({
      lat: worldToLat(latToWorld(inicio.lat, zoom) - (evento.clientY - inicio.y), zoom),
      lon: worldToLon(lonToWorld(inicio.lon, zoom) - (evento.clientX - inicio.x), zoom),
    });
  };

  const aoSoltar = (evento: React.PointerEvent<HTMLDivElement>) => {
    arrastarRef.current = null;
    setArrastando(false);
    if (evento.currentTarget.hasPointerCapture(evento.pointerId)) evento.currentTarget.releasePointerCapture(evento.pointerId);
  };

  const mostrarDica = (evento: React.MouseEvent, conteudo: Omit<Dica, "x" | "y">) => {
    const caixa = caixaRef.current?.getBoundingClientRect();
    setDica({ ...conteudo, x: evento.clientX - (caixa?.left ?? 0), y: evento.clientY - (caixa?.top ?? 0) });
  };

  const maxEmpresasRegiao = useMemo(() => Math.max(1, ...regioesNoMapa.map((regiao) => regiao.n)), [regioesNoMapa]);

  const regiaoSelecionada = useMemo(
    () => (dados?.regioes || []).find((regiao) => `${regiao.pais}|${regiao.distrito}` === selecionada) ?? null,
    [dados, selecionada],
  );

  const empresasDaRegiao = useMemo(
    () =>
      regiaoSelecionada
        ? (dados?.empresas || [])
            .filter((empresa) => regiaoSelecionada.empresas.includes(empresa.nif))
            .sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
        : [],
    [dados, regiaoSelecionada],
  );

  const contagemNiveis = useMemo(() => {
    if (contagens) return new Map(Object.entries(contagens));
    const contagem = new Map<string, number>();
    for (const empresa of dados?.empresas || []) {
      if (!empresa.nivel) continue;
      contagem.set(empresa.nivel, (contagem.get(empresa.nivel) || 0) + 1);
    }
    return contagem;
  }, [contagens, dados]);

  const niveisCartao = meta?.cartao_modelo.niveis || [];

  return (
    <SectionCard
      title="Mapa ESG · empresas e regiões"
      subtitle="Cada empresa no centro do distrito do cadastro; os círculos agregam o distrito (PT) ou a província (ES) pelo score médio."
      icon={Globe2}
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          {(["regioes", "empresas"] as Modo[]).map((valor) => (
            <button
              key={valor}
              onClick={() => setModo(valor)}
              aria-pressed={modo === valor}
              className={`flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs transition ${
                modo === valor ? "border border-emerald-400/30 bg-emerald-400/10 text-emerald-200" : "border border-white/10 text-muted-foreground hover:text-foreground"
              }`}
            >
              {valor === "regioes" ? <Layers size={13} /> : <MapPin size={13} />}
              {valor === "regioes" ? "Regiões" : "Empresas"}
            </button>
          ))}
          <button
            onClick={carregar}
            className="flex items-center gap-1.5 rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            {carregando ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Atualizar
          </button>
        </div>
      }
    >
      {erro && (
        <div className="space-y-3">
          <EmptyState tone="warn">{erro}</EmptyState>
          <button onClick={carregar} className="rounded-xl border border-white/10 px-3 py-2 text-sm hover:text-foreground">
            Tentar novamente
          </button>
        </div>
      )}

      {!erro && carregando && !dados && <Loading label="A carregar o mapa ESG…" />}

      {!erro && dados && !dados.disponivel && (
        <EmptyState tone="warn">
          {dados.motivo || "Ainda não há empresas no índice ESG."}
          {dados.como_popular && <span className="mt-1 block">{dados.como_popular}</span>}
        </EmptyState>
      )}

      {!erro && dados?.disponivel && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setNivel("")}
                aria-pressed={nivel === ""}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                  nivel === "" ? "border-white/30 bg-white/10 text-foreground" : "border-white/10 text-muted-foreground hover:text-foreground"
                }`}
              >
                Todos os níveis
              </button>
              {niveisCartao.map((faixa) => (
                <button
                  key={faixa.id}
                  onClick={() => setNivel(faixa.id)}
                  aria-pressed={nivel === faixa.id}
                  className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition"
                  style={{
                    borderColor: nivel === faixa.id ? faixa.cor : "rgba(255,255,255,0.1)",
                    backgroundColor: nivel === faixa.id ? `${faixa.cor}22` : "transparent",
                    color: nivel === faixa.id ? faixa.cor : undefined,
                  }}
                >
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: faixa.cor }} />
                  {faixa.label}
                  <span className="font-mono text-muted-foreground">{contagemNiveis.get(faixa.id) ?? 0}</span>
                </button>
              ))}
            </div>
            <p className="ml-auto text-[11px] text-muted-foreground">
              {num(dados.total)} empresa(s) · {num(empresasNoMapa.length)} no mapa · {num(dados.sem_localizacao)} sem localização
              {dados.truncado ? " · amostra limitada" : ""}
            </p>
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(240px,1fr)]">
            <div
              ref={caixaRef}
              role="application"
              aria-label="Mapa ESG de empresas e regiões"
              onPointerDown={aoPremir}
              onPointerMove={aoMover}
              onPointerUp={aoSoltar}
              onPointerCancel={aoSoltar}
              className={`relative h-[460px] touch-none select-none overflow-hidden rounded-2xl border border-white/10 bg-[#0a1f29] ${
                arrastando ? "cursor-grabbing" : "cursor-grab"
              }`}
            >
              {projecao.tiles.map((tile) => (
                <img
                  key={tile.key}
                  src={tile.url}
                  alt=""
                  draggable={false}
                  loading="lazy"
                  decoding="async"
                  className="pointer-events-none absolute opacity-60"
                  style={{ left: tile.left, top: tile.top, width: TILE_SIZE, height: TILE_SIZE }}
                />
              ))}
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#06131a]/55 via-transparent to-[#06131a]/60" />

              {/* Regiões: círculos por distrito/província, dimensionados pelo n.º de empresas. */}
              {modo === "regioes" &&
                regioesNoMapa.map((regiao) => {
                  const posicao = projecao.project(regiao.lat, regiao.lon);
                  const raio = 11 + 20 * Math.sqrt(regiao.n / maxEmpresasRegiao);
                  const faixa = nivelDoScore(meta, regiao.score_medio);
                  const cor = faixa?.cor || regiao.cor || esgCor(regiao.nivel);
                  const ativa = selecionada === `${regiao.pais}|${regiao.distrito}`;
                  return (
                    <div key={`${regiao.pais}|${regiao.distrito}`}>
                      <button
                        data-mapa-chrome
                        aria-label={`${regiao.distrito}: ${regiao.n} empresa(s), score médio ${regiao.score_medio?.toFixed(1) ?? "sem dados"}`}
                        onPointerDown={(evento) => evento.stopPropagation()}
                        onClick={() => {
                          const chave = `${regiao.pais}|${regiao.distrito}`;
                          setSelecionada(ativa ? null : chave);
                          if (!ativa) focarRegiao(regiao);
                        }}
                        onMouseEnter={(evento) => mostrarDica(evento, dicaDaRegiao(regiao, cor))}
                        onMouseMove={(evento) => mostrarDica(evento, dicaDaRegiao(regiao, cor))}
                        onMouseLeave={() => setDica(null)}
                        className="absolute flex items-center justify-center rounded-full border-2 font-mono text-[11px] font-semibold transition"
                        style={{
                          left: posicao.left,
                          top: posicao.top,
                          width: raio * 2,
                          height: raio * 2,
                          transform: "translate(-50%, -50%)",
                          borderColor: cor,
                          backgroundColor: `${cor}3d`,
                          color: "#e8f6f4",
                          boxShadow: ativa ? `0 0 0 4px ${cor}33` : "0 6px 18px rgba(0,0,0,0.35)",
                        }}
                      >
                        {regiao.n}
                      </button>
                      <span
                        className="pointer-events-none absolute -translate-x-1/2 whitespace-nowrap text-[10px] font-medium text-white/85"
                        style={{ left: posicao.left, top: posicao.top + raio + 3, textShadow: "0 1px 3px rgba(0,0,0,0.9)" }}
                      >
                        {rotuloCurto(regiao.distrito)}
                      </span>
                    </div>
                  );
                })}

              {/* Empresas: um ponto por empresa, com a cor do seu nível. */}
              {modo === "empresas" &&
                empresasNoMapa.map((empresa) => {
                  const posicao = projecao.project(empresa.lat, empresa.lon);
                  const cor = empresa.cor || esgCor(empresa.nivel);
                  return (
                    <button
                      key={`${empresa.pais}|${empresa.nif}`}
                      data-mapa-chrome
                      aria-label={`${empresa.nome}: score ${empresa.score?.toFixed(1) ?? "sem dados"} (${empresa.nivel_label || "sem nível"})`}
                      onPointerDown={(evento) => evento.stopPropagation()}
                      onClick={() => onAbrir(comoResumo(empresa))}
                      onMouseEnter={(evento) => mostrarDica(evento, dicaDaEmpresa(empresa, cor))}
                      onMouseMove={(evento) => mostrarDica(evento, dicaDaEmpresa(empresa, cor))}
                      onMouseLeave={() => setDica(null)}
                      className="absolute rounded-full border-2 transition hover:scale-125"
                      style={{
                        left: posicao.left,
                        top: posicao.top,
                        width: 13,
                        height: 13,
                        transform: "translate(-50%, -50%)",
                        backgroundColor: cor,
                        borderColor: "#06131a",
                        boxShadow: `0 0 0 3px ${cor}33`,
                      }}
                    />
                  );
                })}

              {modo === "empresas" && !empresasNoMapa.length && (
                <p className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-xl bg-black/60 px-3 py-2 text-xs text-white/80">
                  Nenhuma empresa com distrito conhecido.
                </p>
              )}

              <div data-mapa-chrome className="absolute right-2 top-2 flex flex-col gap-1">
                <button
                  onClick={() => zoomEm(1)}
                  aria-label="Aproximar"
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/15 bg-[#0b1116]/85 text-white/80 hover:text-white"
                >
                  <Plus size={15} />
                </button>
                <button
                  onClick={() => zoomEm(-1)}
                  aria-label="Afastar"
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/15 bg-[#0b1116]/85 text-white/80 hover:text-white"
                >
                  <Minus size={15} />
                </button>
                <button
                  onClick={enquadrar}
                  aria-label="Enquadrar todas as empresas"
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/15 bg-[#0b1116]/85 text-white/80 hover:text-white"
                >
                  <Crosshair size={15} />
                </button>
              </div>

              {dica && (
                <div
                  className="pointer-events-none absolute z-20 w-56 rounded-xl border border-white/15 bg-[#06131a]/95 px-2.5 py-2 text-[11px] shadow-xl"
                  style={{
                    left: Math.min(dica.x + 12, Math.max(0, tamanho.largura - 232)),
                    top: Math.min(dica.y + 12, Math.max(0, tamanho.altura - 92)),
                  }}
                >
                  <p className="flex items-center gap-1.5 font-medium text-white">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: dica.cor }} />
                    <span className="truncate">{dica.titulo}</span>
                  </p>
                  {dica.linhas.map((linha) => (
                    <p key={linha} className="truncate text-white/70">
                      {linha}
                    </p>
                  ))}
                </div>
              )}

              <div className="pointer-events-none absolute bottom-1 right-2 text-[9px] text-white/50">© OpenStreetMap</div>
            </div>

            <aside className="flex min-h-[240px] max-h-[340px] flex-col rounded-2xl border border-white/10 bg-white/[0.02] p-3 lg:min-h-[460px] lg:max-h-none">
              {regiaoSelecionada ? (
                <>
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Região</p>
                      <h3 className="text-sm font-semibold">{regiaoSelecionada.distrito}</h3>
                      <p className="text-[11px] text-muted-foreground">
                        {regiaoSelecionada.n} empresa(s) · score médio {regiaoSelecionada.score_medio?.toFixed(1) ?? "—"} ·{" "}
                        {compactEuro(regiaoSelecionada.valor)}
                      </p>
                      <BarraNiveis niveis={regiaoSelecionada.niveis} total={regiaoSelecionada.n} />
                    </div>
                    <button
                      onClick={() => setSelecionada(null)}
                      aria-label="Voltar às regiões"
                      className="rounded-lg border border-white/10 p-1 text-muted-foreground hover:text-foreground"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
                    {empresasDaRegiao.map((empresa) => (
                      <li key={empresa.nif}>
                        <button
                          onClick={() => onAbrir(comoResumo(empresa))}
                          className="flex w-full items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-left transition hover:border-emerald-400/30 hover:bg-emerald-400/5"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-xs">{empresa.nome}</span>
                            <span className="block truncate text-[10px] text-muted-foreground">
                              {[empresa.concelho, empresa.setor_label].filter(Boolean).join(" · ") || "Sem setor"}
                            </span>
                          </span>
                          <EsgBadge score={empresa.score} nivel={empresa.nivel} nivelLabel={empresa.nivel_label} cor={empresa.cor} compact />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Regiões com empresas</p>
                    <span className="text-[10px] text-muted-foreground">{regioesNoMapa.length}</span>
                  </div>
                  <ul className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
                    {regioesNoMapa.map((regiao) => {
                      const cor = nivelDoScore(meta, regiao.score_medio)?.cor || regiao.cor || esgCor(regiao.nivel);
                      return (
                        <li key={`${regiao.pais}|${regiao.distrito}`}>
                          <button
                            onClick={() => {
                              setSelecionada(`${regiao.pais}|${regiao.distrito}`);
                              focarRegiao(regiao);
                            }}
                            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-left transition hover:border-emerald-400/30 hover:bg-emerald-400/5"
                          >
                            <span className="flex items-center justify-between gap-2">
                              <span className="flex min-w-0 items-center gap-1.5">
                                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: cor }} />
                                <span className="truncate text-xs">{regiao.distrito}</span>
                              </span>
                              <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                                {regiao.score_medio?.toFixed(1) ?? "—"} · {regiao.n}
                              </span>
                            </span>
                            <BarraNiveis niveis={regiao.niveis} total={regiao.n} />
                          </button>
                        </li>
                      );
                    })}
                    {!regioesNoMapa.length && <li className="px-2 py-3 text-xs text-muted-foreground">Sem regiões para mostrar.</li>}
                  </ul>
                  {regioesForaDoMapa.length > 0 && (
                    <div className="mt-2 border-t border-white/10 pt-2">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Sem coordenadas</p>
                      <p className="text-[11px] text-muted-foreground">
                        {regioesForaDoMapa.map((regiao) => `${regiao.distrito} (${regiao.n})`).join(" · ")}
                      </p>
                    </div>
                  )}
                </>
              )}
            </aside>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Building2 size={12} /> {num(dados.sem_localizacao)} empresa(s) sem distrito no cadastro não aparecem no mapa.
            </span>
            <span>Posições = centro do distrito/província (nunca um endereço); em Espanha pode ser o centro da NUTS.</span>
            <button onClick={enquadrar} className="ml-auto text-emerald-300 hover:underline">
              Enquadrar tudo
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}
