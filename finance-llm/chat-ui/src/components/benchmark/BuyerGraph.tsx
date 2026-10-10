/**
 * **Grafo do comprador** (SVG radial).
 *
 * O comprador fica no centro, os fornecedores no primeiro anel (raio pelo valor
 * da relação, cor pela leitura força/fraqueza) e, no anel exterior, os
 * **clientes comuns** — os outros compradores que usam os mesmos fornecedores.
 *
 * Tudo é DOM (cada nó é um `<g>`), para se poder clicar, passar o rato e abrir o
 * **menu de contexto** com o botão direito — é o que permite saltar para a ficha
 * da empresa, para o benchmark dela ou para o mapa.
 */
import { useMemo, useState } from "react";

import type { BenchmarkBuyerGraphResponse, BenchmarkBuyerSupplier } from "../../benchmarkApi";
import { urlLogoAbsoluto } from "../../empresasPerfil";
import type { EmpresaPerfil } from "../../empresasPerfil";
import { corDaEmpresa, iniciais, limparNome } from "./texto";
import { chaveEmpresa } from "./usePerfisEmpresas";

export type BuyerNodeRef =
  | { kind: "buyer" }
  | { kind: "supplier"; supplier: BenchmarkBuyerSupplier }
  | { kind: "client"; nif: string; name: string };

const LARGURA = 720;
const ALTURA = 460;
const RAIO_FORNECEDOR = 150;
const RAIO_CLIENTE = 205;

/** Cor do nó do fornecedor: verde = posição favorável ao comprador. */
export function corDoScore(score: number): string {
  if (score >= 70) return "#34d399";
  if (score >= 45) return "#38bdf8";
  if (score >= 30) return "#fbbf24";
  return "#fb7185";
}

function valorRelativo(valor: number, maximo: number): number {
  if (!maximo || valor <= 0) return 14;
  return 14 + 26 * Math.min(1, valor / maximo);
}

function euroCurto(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  const abs = Math.abs(valor);
  if (abs >= 1_000_000_000) return `${(valor / 1_000_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 2 })} G€`;
  if (abs >= 1_000_000) return `${(valor / 1_000_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} M€`;
  if (abs >= 10_000) return `${(valor / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} k€`;
  return valor.toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

export default function BuyerGraph({
  dados,
  selecionado,
  perfis,
  onSelect,
  onContexto,
}: {
  dados: BenchmarkBuyerGraphResponse;
  selecionado: BuyerNodeRef | null;
  /** Sites e logótipos das empresas (por NIF/nome), para marcar os nós. */
  perfis?: Record<string, EmpresaPerfil>;
  onSelect: (no: BuyerNodeRef) => void;
  onContexto: (
    evento: { clientX: number; clientY: number; currentTarget: Element; preventDefault: () => void },
    no: BuyerNodeRef,
  ) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [realcado, setRealcado] = useState<string | null>(null);

  /** Logótipo (URL absoluto) de uma empresa, se já for conhecido. */
  const logotipo = (alvo: { nif?: string | null; nome?: string | null }): string | null => {
    if (!perfis) return null;
    const chave = chaveEmpresa(alvo);
    const perfil = perfis[chave] || perfis[`n:${String(alvo.nome || "").trim().toLowerCase()}`];
    return urlLogoAbsoluto(perfil?.logo_url);
  };

  const { fornecedores, clientes, raioMax } = useMemo(() => {
    const lista = dados.suppliers.slice(0, 14);
    const maximo = lista.reduce((maior, linha) => Math.max(maior, linha.value || 0), 0);
    return { fornecedores: lista, clientes: dados.clients.slice(0, 8), raioMax: maximo };
  }, [dados]);

  const centro = { x: LARGURA / 2, y: ALTURA / 2 };

  const posicaoFornecedor = (indice: number, total: number) => {
    const angulo = (indice / Math.max(1, total)) * Math.PI * 2 - Math.PI / 2;
    return {
      x: centro.x + Math.cos(angulo) * RAIO_FORNECEDOR,
      y: centro.y + Math.sin(angulo) * RAIO_FORNECEDOR,
      angulo,
    };
  };

  const posicaoCliente = (indice: number, total: number) => {
    const angulo = (indice / Math.max(1, total)) * Math.PI * 2 - Math.PI / 2 + Math.PI / Math.max(2, total);
    return {
      x: centro.x + Math.cos(angulo) * RAIO_CLIENTE,
      y: centro.y + Math.sin(angulo) * RAIO_CLIENTE,
      angulo,
    };
  };

  const selecionadoId = selecionado?.kind === "supplier" ? `s:${selecionado.supplier.nif}` : selecionado?.kind === "client" ? `c:${selecionado.nif}` : selecionado?.kind === "buyer" ? "buyer" : null;

  const marcaComprador = logotipo({ nif: dados.buyer.nif, nome: dados.buyer.name });

  return (
    <div className="relative" data-context-scope>
      <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
        <button
          type="button"
          className="rounded-lg border border-border bg-background/70 px-2 py-1 text-xs transition hover:bg-accent"
          onClick={() => setZoom((valor) => Math.max(0.6, Number((valor - 0.15).toFixed(2))))}
          title="Reduzir"
        >
          −
        </button>
        <button
          type="button"
          className="rounded-lg border border-border bg-background/70 px-2 py-1 text-xs transition hover:bg-accent"
          onClick={() => setZoom(1)}
          title="Tamanho original"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          type="button"
          className="rounded-lg border border-border bg-background/70 px-2 py-1 text-xs transition hover:bg-accent"
          onClick={() => setZoom((valor) => Math.min(1.6, Number((valor + 0.15).toFixed(2))))}
          title="Aumentar"
        >
          +
        </button>
      </div>
      <svg
        viewBox={`0 0 ${LARGURA} ${ALTURA}`}
        className="h-[460px] w-full select-none"
        style={{ transform: `scale(${zoom})` }}
        onContextMenu={(evento) => {
          // nas zonas vazias abre o menu do comprador; sobre um nó, deixa passar o do nó
          if ((evento.target as Element).closest?.("[data-no-grafo]")) return;
          onContexto(evento, { kind: "buyer" });
        }}
      >
        <defs>
          <radialGradient id="buyer-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#0ea5e9" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#0f172a" stopOpacity="0.9" />
          </radialGradient>
        </defs>

        {/* anéis de referência */}
        <circle cx={centro.x} cy={centro.y} r={RAIO_FORNECEDOR} fill="none" stroke="#1e293b" strokeDasharray="4 6" />
        {clientes.length ? (
          <circle cx={centro.x} cy={centro.y} r={RAIO_CLIENTE} fill="none" stroke="#1e293b" strokeDasharray="2 8" />
        ) : null}

        {/* ligações comprador → fornecedor */}
        {fornecedores.map((fornecedor, indice) => {
          const posicao = posicaoFornecedor(indice, fornecedores.length);
          const activo = realcado === `s:${fornecedor.nif}` || selecionadoId === `s:${fornecedor.nif}`;
          return (
            <line
              key={`l-${fornecedor.nif}`}
              x1={centro.x}
              y1={centro.y}
              x2={posicao.x}
              y2={posicao.y}
              stroke={activo ? corDoScore(fornecedor.score) : "#334155"}
              strokeWidth={activo ? 3 : 1.5}
            />
          );
        })}

        {/* ligações fornecedor → cliente (anel exterior) */}
        {clientes.map((cliente, indice) => {
          const posicao = posicaoCliente(indice, clientes.length);
          const alvo = fornecedores[Math.min(fornecedores.length - 1, indice % Math.max(1, fornecedores.length))];
          if (!alvo) return null;
          const origem = posicaoFornecedor(fornecedores.indexOf(alvo), fornecedores.length);
          const activo = realcado === `c:${cliente.nif}` || selecionadoId === `c:${cliente.nif}`;
          return (
            <line
              key={`lc-${cliente.nif}`}
              x1={origem.x}
              y1={origem.y}
              x2={posicao.x}
              y2={posicao.y}
              stroke={activo ? "#a78bfa" : "#1e293b"}
              strokeWidth={activo ? 2.4 : 1}
              strokeDasharray="5 4"
            />
          );
        })}

        {/* clientes comuns */}
        {clientes.map((cliente, indice) => {
          const posicao = posicaoCliente(indice, clientes.length);
          const activo = realcado === `c:${cliente.nif}` || selecionadoId === `c:${cliente.nif}`;
          const marca = logotipo({ nif: cliente.nif, nome: cliente.name });
          return (
            <g
              key={`cli-${cliente.nif}`}
              data-no-grafo
              transform={`translate(${posicao.x} ${posicao.y})`}
              className="cursor-pointer"
              onMouseEnter={() => setRealcado(`c:${cliente.nif}`)}
              onMouseLeave={() => setRealcado(null)}
              onClick={() => onSelect({ kind: "client", nif: cliente.nif, name: cliente.name })}
              onContextMenu={(evento) => onContexto(evento, { kind: "client", nif: cliente.nif, name: cliente.name })}
            >
              {marca ? (
                <>
                  <circle r={11} fill="#f8fafc" stroke={activo ? "#c4b5fd" : "#7c3aed"} strokeWidth={activo ? 2.4 : 1.5} />
                  <image
                    href={marca}
                    x={-9}
                    y={-9}
                    width={18}
                    height={18}
                    preserveAspectRatio="xMidYMid meet"
                  />
                </>
              ) : (
                <>
                  <circle r={9} fill={activo ? "#c4b5fd" : "#7c3aed"} stroke="#0b1120" strokeWidth={1.5} />
                  <text textAnchor="middle" y={3} className="fill-white text-[8px] font-semibold">
                    {iniciais(cliente.name)}
                  </text>
                </>
              )}
              <text
                x={posicao.x > centro.x ? 16 : -16}
                textAnchor={posicao.x > centro.x ? "start" : "end"}
                y={3}
                className="fill-slate-300 text-[9px]"
              >
                {limparNome(cliente.name).slice(0, 22)}
              </text>
              <title>{`${limparNome(cliente.name)} · ${cliente.contracts} contratos · ${euroCurto(cliente.value)}`}</title>
            </g>
          );
        })}

        {/* fornecedores */}
        {fornecedores.map((fornecedor, indice) => {
          const posicao = posicaoFornecedor(indice, fornecedores.length);
          const raio = valorRelativo(fornecedor.value, raioMax);
          const activo = realcado === `s:${fornecedor.nif}` || selecionadoId === `s:${fornecedor.nif}`;
          const cor = corDoScore(fornecedor.score);
          const externo = posicao.x >= centro.x;
          const marca = logotipo({ nif: fornecedor.nif, nome: fornecedor.name });
          const contorno = corDaEmpresa(fornecedor.name);
          return (
            <g
              key={`f-${fornecedor.nif}`}
              data-no-grafo
              transform={`translate(${posicao.x} ${posicao.y})`}
              className="cursor-pointer"
              onMouseEnter={() => setRealcado(`s:${fornecedor.nif}`)}
              onMouseLeave={() => setRealcado(null)}
              onClick={() => onSelect({ kind: "supplier", supplier: fornecedor })}
              onContextMenu={(evento) => onContexto(evento, { kind: "supplier", supplier: fornecedor })}
            >
              <rect
                x={-raio}
                y={-raio}
                width={raio * 2}
                height={raio * 2}
                rx={7}
                fill={marca ? "#f8fafc" : activo ? `${cor}33` : "#0f172a"}
                stroke={cor}
                strokeWidth={activo ? 3 : 1.6}
                opacity={fornecedor.status === "histórico" ? 1 : 0.75}
              />
              {marca ? (
                <image
                  href={marca}
                  x={-raio + 3}
                  y={-raio + 3}
                  width={(raio - 3) * 2}
                  height={(raio - 3) * 2}
                  preserveAspectRatio="xMidYMid meet"
                  opacity={fornecedor.status === "histórico" ? 1 : 0.9}
                />
              ) : (
                <text
                  textAnchor="middle"
                  y={Math.max(3, raio * 0.18)}
                  style={{ fontSize: Math.max(9, Math.round(raio * 0.52)) }}
                  className="font-semibold"
                  fill={contorno}
                  opacity={fornecedor.status === "histórico" ? 1 : 0.8}
                >
                  {iniciais(fornecedor.name)}
                </text>
              )}
              <text
                x={externo ? raio + 6 : -raio - 6}
                textAnchor={externo ? "start" : "end"}
                y={-2}
                className="fill-slate-100 text-[10px] font-medium"
              >
                {limparNome(fornecedor.name).slice(0, 24)}
              </text>
              <text
                x={externo ? raio + 6 : -raio - 6}
                textAnchor={externo ? "start" : "end"}
                y={10}
                className="fill-slate-400 text-[9px]"
              >
                {euroCurto(fornecedor.value)}
                {fornecedor.price_index ? ` · ${fornecedor.price_index.toFixed(2)}×` : ""}
              </text>
              <title>
                {`${limparNome(fornecedor.name)}\ncontratos: ${fornecedor.contracts}\nvalor: ${euroCurto(fornecedor.value)}\nquota no comprador: ${
                  fornecedor.share_pct ?? "—"
                }%\ndependência deste comprador: ${fornecedor.dependency_pct ?? "—"}%\nclientes: ${fornecedor.client_count}\nforças: ${fornecedor.strengths.join(
                  "; ",
                )}\nfraquezas: ${fornecedor.weaknesses.join("; ")}`}
              </title>
            </g>
          );
        })}

        {/* comprador (centro) */}
        <g
          className="cursor-pointer"
          onClick={() => onSelect({ kind: "buyer" })}
          onContextMenu={(evento) => onContexto(evento, { kind: "buyer" })}
        >
          <circle cx={centro.x} cy={centro.y} r={44} fill="url(#buyer-core)" stroke="#38bdf8" strokeWidth={2} />
          {marcaComprador ? (
            <>
              <circle cx={centro.x} cy={centro.y} r={34} fill="#f8fafc" opacity={0.95} />
              <image
                href={marcaComprador}
                x={centro.x - 30}
                y={centro.y - 30}
                width={60}
                height={60}
                preserveAspectRatio="xMidYMid meet"
              />
            </>
          ) : (
            <text
              x={centro.x}
              y={centro.y + 8}
              textAnchor="middle"
              style={{ fontSize: 22 }}
              className="font-semibold"
              fill={corDaEmpresa(dados.buyer.name)}
            >
              {iniciais(dados.buyer.name)}
            </text>
          )}
          <text x={centro.x} y={centro.y + 60} textAnchor="middle" className="fill-slate-100 text-[10px] font-semibold">
            {limparNome(dados.buyer.name).slice(0, 26)}
          </text>
          <text x={centro.x} y={centro.y + 72} textAnchor="middle" className="fill-slate-400 text-[9px]">
            {euroCurto(dados.buyer.total_value)}
          </text>
          <title>{`${limparNome(dados.buyer.name)} · ${dados.buyer.contracts} contratos · ${euroCurto(dados.buyer.total_value)}`}</title>
        </g>
      </svg>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {dados.labels
          ? `Centro: ${dados.labels.entity.toLowerCase()} · 1º anel: ${dados.labels.ring1.toLowerCase()} (verde = posição favorável, vermelho = risco) · 2º anel: ${dados.labels.ring2.toLowerCase()}.`
          : "Centro: comprador · 1º anel: fornecedores (verde = posição favorável, vermelho = risco) · 2º anel: clientes comuns."}{" "}
        Clique para ver os detalhes; botão direito abre as opções.
      </p>
    </div>
  );
}
