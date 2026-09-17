/**
 * Janelas de detalhe: as fichas (entidade/contrato) e o «Quick Look» deixam de
 * ser modais sobrepostas e passam a ser janelas do gestor — arrastáveis,
 * redimensionáveis, minimizáveis e encaixáveis como qualquer aplicação.
 *
 * Convenção das vistas: `company-detail:<NIF>`, `contract-detail:<id>` e
 * `quicklook:<kind>:<id>`. O conteúdo é carregado pela API a partir do id, para
 * as janelas poderem ser repostas ao recarregar a página.
 */
import { useEffect, useState } from "react";
import { ExternalLink, GitCompare, Loader2, Star, StarOff } from "lucide-react";
import {
  getCompanyAnalytics,
  getCompanyContracts,
  getContract,
  getEntityDetail,
  getRagDocument,
  getTickerInfo,
} from "../api";
import type { ContractAnalyticsRow, ContractItem } from "../types";
import { useFavorites } from "../favorites";
import {
  KIND_LABEL,
  appHref,
  formatFinderDate,
  formatFinderSize,
  formatFinderValue,
} from "../finder";
import type { FinderItem, FinderKind } from "../finder";
import { EntityDetailPanel, ContractDetailPanel, nifsFromParty, parseCompetitors } from "../pages/EmpresasIQPage";
import { CompareButton } from "../pages/CompareWindow";
import { SeeAllContractsButton } from "../pages/EntityContractsWindow";
import { openCompareWindow } from "../compare";
import { closeWindow, openWindow, windowFor } from "../windows";

/* --------------------------------------------------------------- fichas */

/** Ficha de entidade dentro de uma janela. */
export function EntityDetailWindow({ nif }: { nif: string }) {
  const view = `company-detail:${nif}`;
  return (
    <EntityDetailPanel
      nif={nif}
      onBack={() => closeWindow(view)}
      onContract={(id) => openWindow(`contract-detail:${id}`, undefined, { title: "Ficha do contrato" })}
      onAllContracts={(entity, name) =>
        openWindow(`entity-contracts:${entity}`, undefined, {
          title: name ? `Contratos · ${name}` : "Contratos da entidade",
          rect: { width: 1100, height: 720 },
        })
      }
    />
  );
}

/** Ficha de contrato dentro de uma janela. */
export function ContractDetailWindow({ id }: { id: string }) {
  const view = `contract-detail:${id}`;
  const [, setTick] = useState(0);
  return (
    <ContractDetailPanel
      id={id}
      onBack={() => closeWindow(view)}
      onEntity={(nif) => {
        const target = `company-detail:${nif}`;
        openWindow(target, undefined, { title: "Ficha da entidade" });
        // Re-render para o título da janela acompanhar a entidade aberta.
        if (windowFor(target)) setTick((value) => value + 1);
      }}
    />
  );
}

/* ------------------------------------------------------------ quick look */

type AnalyticsSlice = { key: string; count: number; value: number };

/** Concatena nome + valor num cartão compacto (valores e analítica). */
function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="truncate text-[13.5px] font-medium tabular-nums">{value}</p>
      {hint && <p className="truncate text-[10.5px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** Lista de fatias (por ano, CPV, tipo) com barra proporcional. */
function SliceList({
  title,
  slices,
  emptyHint,
}: {
  title: string;
  slices: AnalyticsSlice[];
  emptyHint: string;
}) {
  const max = Math.max(1, ...slices.map((slice) => slice.value || slice.count));
  return (
    <div>
      <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{title}</p>
      {slices.length === 0 ? (
        <p className="mt-1 text-[11.5px] text-muted-foreground/80">{emptyHint}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {slices.map((slice) => (
            <li key={slice.key} className="text-[11.5px]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate">{slice.key || "—"}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {slice.count.toLocaleString("pt-PT")} · {formatFinderValue(slice.value)}
                </span>
              </div>
              <span className="mt-0.5 block h-1 rounded-full bg-white/8">
                <span
                  className="block h-1 rounded-full bg-teal-400/70"
                  style={{ width: `${Math.max(3, Math.round(((slice.value || slice.count) / max) * 100))}%` }}
                />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Conteúdo do Quick Look numa janela (dossier compacto do item). */
export function QuickLookWindow({ kind, id }: { kind: FinderKind; id: string }) {
  const { isFavorite, toggle } = useFavorites();
  const [item, setItem] = useState<FinderItem | null>(null);
  const [rows, setRows] = useState<[string, string][]>([]);
  const [related, setRelated] = useState<[string, string][]>([]);
  const [metrics, setMetrics] = useState<{ label: string; value: string; hint?: string }[]>([]);
  const [contracts, setContracts] = useState<ContractItem[]>([]);
  const [competitors, setCompetitors] = useState<{ name: string; nif?: string; count: number; value: number }[]>([]);
  const [analytics, setAnalytics] = useState<{
    byYear: AnalyticsSlice[];
    byCpv: AnalyticsSlice[];
    byProcedure: AnalyticsSlice[];
    byContractType: AnalyticsSlice[];
  }>({ byYear: [], byCpv: [], byProcedure: [], byContractType: [] });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItem(null);
    setError(null);
    setRows([]);
    setRelated([]);
    setMetrics([]);
    setContracts([]);
    setCompetitors([]);
    setAnalytics({ byYear: [], byCpv: [], byProcedure: [], byContractType: [] });
    const load = async () => {
      try {
        if (kind === "entity") {
          const [entity, analyticsResponse, asAdjudicante, asAdjudicatario, adjudicanteStats, adjudicatarioStats] =
            await Promise.all([
              getEntityDetail(id),
              getCompanyAnalytics(id, "all").catch(() => null),
              getCompanyContracts(id, "adjudicante", 0, 40).catch(() => null),
              getCompanyContracts(id, "adjudicatario", 0, 40).catch(() => null),
              getCompanyAnalytics(id, "adjudicante").catch(() => null),
              getCompanyAnalytics(id, "adjudicatario").catch(() => null),
            ]);
          if (cancelled) return;

          const totalValue = analyticsResponse?.total_value ?? entity.total_value;
          setItem({
            id,
            kind: "entity",
            name: entity.name,
            subtitle: [entity.nif ? `NIF ${entity.nif}` : "sem NIF", entity.country].filter(Boolean).join(" · "),
            date: entity.ingested_at,
            size: entity.contracts_count,
            value: totalValue,
          });

          const byYear = (analyticsResponse?.by_year ?? [])
            .map((row) => ({ key: row.key, count: row.count, value: row.total_value ?? 0 }))
            .sort((a, b) => b.key.localeCompare(a.key))
            .slice(0, 8);
          const topSlice = (source: ContractAnalyticsRow[] | undefined, size: number): AnalyticsSlice[] =>
            (source ?? [])
              .map((row) => ({ key: row.key, count: row.count, value: row.total_value ?? 0 }))
              .sort((a, b) => b.value - a.value || b.count - a.count)
              .slice(0, size);

          setAnalytics({
            byYear,
            byCpv: topSlice(analyticsResponse?.by_cpv, 5),
            byProcedure: topSlice(analyticsResponse?.by_procedure_type, 4),
            byContractType: topSlice(analyticsResponse?.by_contract_type, 4),
          });

          setMetrics([
            { label: "Total de contratos", value: (analyticsResponse?.total_contracts ?? entity.contracts_count ?? 0).toLocaleString("pt-PT") },
            { label: "Valor contratado", value: formatFinderValue(totalValue) },
            { label: "Valor médio / contrato", value: formatFinderValue(analyticsResponse?.avg_value) },
            { label: "Maior contrato", value: formatFinderValue(analyticsResponse?.max_value) },
            {
              label: "Como adjudicante",
              value: formatFinderValue(adjudicanteStats?.total_value ?? entity.as_adjudicante_value),
              hint: `${(adjudicanteStats?.total_contracts ?? entity.as_adjudicante_count).toLocaleString("pt-PT")} contratos`,
            },
            {
              label: "Como adjudicatário",
              value: formatFinderValue(adjudicatarioStats?.total_value ?? entity.total_value),
              hint: `${(adjudicatarioStats?.total_contracts ?? entity.as_adjudicatario_count).toLocaleString("pt-PT")} contratos`,
            },
          ]);

          const all = [...(asAdjudicante?.items ?? []), ...(asAdjudicatario?.items ?? [])];
          const seen = new Set<string>();
          const uniqueContracts = all.filter((contract) => {
            const key = String(contract.idcontrato ?? contract.doc_id ?? "");
            if (!key || seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          setContracts(uniqueContracts);

          // Concorrentes: agrega quem aparece nos mesmos procedimentos.
          const map = new Map<string, { name: string; nif?: string; count: number; value: number }>();
          for (const contract of uniqueContracts) {
            for (const competitor of parseCompetitors(contract.concorrentes)) {
              const key = competitor.nif ?? competitor.name.toLowerCase();
              const current = map.get(key) ?? { name: competitor.name, nif: competitor.nif, count: 0, value: 0 };
              current.count += 1;
              current.value += contract.precoContratual ?? 0;
              map.set(key, current);
            }
          }
          setCompetitors([...map.values()].sort((a, b) => b.count - a.count || b.value - a.value).slice(0, 12));

          setRows([
            ["País", entity.country || "—"],
            ["Marcas INPI", String(entity.trademarks_total ?? 0)],
            ["Firmas RNPC", String(entity.firmas_total ?? 0)],
          ]);
          setRelated(
            entity.trademarks
              .slice(0, 8)
              .map((mark) => [mark.mark_name ?? mark.process_number ?? "marca", mark.current_phase ?? "marca"] as [string, string]),
          );
        } else if (kind === "contract") {
          const contract: ContractItem = await getContract(id);
          const parties = (value: ContractItem["adjudicantes"]) =>
            (Array.isArray(value) ? value : value ? [value] : [])
              .map((party) => String((party as { nome?: string }).nome ?? ""))
              .filter(Boolean)
              .join(", ");
          const value = contract.precoContratual ?? contract.PrecoTotalEfetivo;
          if (cancelled) return;
          setItem({
            id,
            kind: "contract",
            name: contract.objectoContrato?.trim() || contract.descContrato?.trim() || `Contrato ${id}`,
            subtitle: contract.Ano ? String(contract.Ano) : undefined,
            date: contract.dataCelebracaoContrato ?? contract.dataPublicacao,
            value,
          });
          setRows([
            ["Tipo", contract.tipoContrato ?? "—"],
            ["Procedimento", contract.tipoprocedimento ?? "—"],
            ["Adjudicantes", parties(contract.adjudicantes) || "—"],
            ["Adjudicatários", parties(contract.adjudicatarios) || "—"],
            ["Preço contratual", formatFinderValue(contract.precoContratual)],
            ["Preço base", formatFinderValue(contract.precoBaseProcedimento)],
            ["Local de execução", contract.localExecucao ?? "—"],
            ["CPV", (contract.cpv ?? []).map((entry) => entry.code ?? entry.description ?? "").filter(Boolean).slice(0, 3).join(" · ") || "—"],
          ]);
        } else if (kind === "document") {
          const document = await getRagDocument(id);
          if (cancelled) return;
          setItem({
            id,
            kind: "document",
            name: document.title || document.filename,
            subtitle: document.filename,
            date: document.updated_at ? new Date(document.updated_at * 1000).toISOString() : undefined,
            size: document.pages,
          });
          setRows([
            ["Ficheiro", document.filename],
            ["Páginas", String(document.pages ?? 0)],
            ["Indexado", document.indexed ? "Sim" : "Não"],
            ["Conversor", document.converter ?? "auto"],
            ["Tamanho", document.size_bytes ? `${Math.round(document.size_bytes / 1024)} KB` : "—"],
          ]);
        } else if (kind === "ticker") {
          const info = await getTickerInfo(id).catch(() => null);
          if (cancelled) return;
          setItem({ id, kind: "ticker", name: info?.name || id, subtitle: info?.exchange });
          setRows([
            ["Símbolo", id],
            ["Nome", info?.name ?? "—"],
            ["Sector", info?.sector ?? "—"],
            ["Moeda", info?.currency ?? "—"],
            ["Bolsa", info?.exchange ?? "—"],
            ["Preço", info?.price !== undefined ? String(info.price) : "—"],
          ]);
        } else {
          if (cancelled) return;
          setItem({ id, kind: "index", name: id, subtitle: "Índice do Elasticsearch" });
          setRows([["Índice", id]]);
        }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Erro ao carregar o item.");
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [kind, id]);

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-[13px] text-rose-300">{error}</p>
        <p className="text-[11.5px] text-muted-foreground">Item #{id}</p>
      </div>
    );
  }

  if (!item) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 size={15} className="animate-spin" /> A carregar…
      </div>
    );
  }

  const hasTags = item.kind === "entity" || item.kind === "contract";
  const favorite = hasTags && isFavorite(item.kind === "entity" ? "entity" : "contract", item.id);

  /** Papel da entidade em cada contrato (para a coluna «Papel»). */
  const roleOf = (contract: ContractItem): string => {
    const asAdjudicante = nifsFromParty(contract.adjudicantes).includes(id);
    const asAdjudicatario = nifsFromParty(contract.adjudicatarios).includes(id);
    if (asAdjudicante && asAdjudicatario) return "Ambos";
    if (asAdjudicante) return "Adjudicante";
    if (asAdjudicatario) return "Adjudicatário";
    return "—";
  };

  return (
    <div className="h-full overflow-y-auto p-5">
      <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{KIND_LABEL[item.kind]}</p>
      <h2 className="text-lg font-semibold leading-tight">{item.name}</h2>
      {item.subtitle && <p className="text-[12.5px] text-muted-foreground">{item.subtitle}</p>}

      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        <Row label="Data" value={formatFinderDate(item.date)} />
        <Row label="Tamanho" value={formatFinderSize(item)} />
        <Row label="Valor" value={formatFinderValue(item.value)} />
        {rows.map(([label, value]) => (
          <Row key={label} label={label} value={value} />
        ))}
      </dl>

      {related.length > 0 && (
        <div className="mt-4">
          <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Relacionados</p>
          <ul className="mt-1 space-y-0.5">
            {related.map(([label, value]) => (
              <li key={label} className="truncate text-[11.5px]">
                <span className="text-muted-foreground">{value}</span> {label}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Valores */}
      {metrics.length > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {metrics.map((metric) => (
            <Metric key={metric.label} label={metric.label} value={metric.value} hint={metric.hint} />
          ))}
        </div>
      )}

      {/* Analítica */}
      {(analytics.byYear.length > 0 || analytics.byCpv.length > 0) && (
        <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SliceList title="Analítica por ano" slices={analytics.byYear} emptyHint="Sem dados por ano." />
          <div className="space-y-3">
            <SliceList title="Top CPV" slices={analytics.byCpv} emptyHint="Sem dados de CPV." />
            <SliceList title="Tipo de procedimento" slices={analytics.byProcedure} emptyHint="Sem dados." />
            <SliceList title="Tipo de contrato" slices={analytics.byContractType} emptyHint="Sem dados." />
          </div>
        </div>
      )}

      {/* Contratos associados */}
      {contracts.length > 0 && (
        <div className="mt-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
                Contratos associados ({contracts.length})
              </p>
              <p className="text-[10.5px] text-muted-foreground/80">
                {item.kind === "entity"
                  ? "Os mais recentes como adjudicante ou adjudicatário."
                  : "Contratos do mesmo procedimento."}
              </p>
            </div>
            {item.kind === "entity" && <SeeAllContractsButton nif={item.id} name={item.name} compact />}
          </div>
          <div className="mt-1 overflow-hidden rounded-xl border border-white/8">
            <table className="w-full text-[11.5px]">
              <thead className="bg-white/[0.04] text-[10px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 text-left font-medium">Nº</th>
                  <th className="px-2 py-1 text-left font-medium">Objeto</th>
                  <th className="px-2 py-1 text-left font-medium">Papel</th>
                  <th className="px-2 py-1 text-left font-medium">Data</th>
                  <th className="px-2 py-1 text-right font-medium">Valor</th>
                </tr>
              </thead>
              <tbody>
                {contracts.slice(0, 25).map((contract) => {
                  const key = String(contract.idcontrato ?? contract.doc_id ?? contract.objectoContrato ?? "");
                  return (
                    <tr key={key} className="border-t border-white/6 transition hover:bg-white/[0.04]">
                      <td className="px-2 py-1 align-top">
                        {contract.idcontrato ? (
                          <button
                            type="button"
                            onClick={() =>
                              openWindow(`contract-detail:${contract.idcontrato}`, undefined, {
                                title: "Ficha do contrato",
                              })
                            }
                            className="font-medium text-teal-300 hover:underline"
                          >
                            {contract.idcontrato}
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-2 py-1 align-top">
                        <span className="line-clamp-2">{contract.objectoContrato?.trim() || "—"}</span>
                      </td>
                      <td className="px-2 py-1 align-top text-muted-foreground">{roleOf(contract)}</td>
                      <td className="px-2 py-1 align-top text-muted-foreground">
                        {formatFinderDate(contract.dataCelebracaoContrato ?? contract.dataPublicacao)}
                      </td>
                      <td className="px-2 py-1 align-top text-right tabular-nums">
                        {formatFinderValue(contract.precoContratual ?? contract.PrecoTotalEfetivo)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[10.5px] text-muted-foreground/70">
            A mostrar os contratos mais recentes em que a entidade participa.
          </p>
        </div>
      )}

      {/* Concorrentes */}
      {(item.kind === "entity" || item.kind === "contract") && contracts.length > 0 && (
        <div className="mt-5">
          <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
            Concorrentes ({competitors.length})
          </p>
          {competitors.length === 0 ? (
            <p className="mt-1 text-[11.5px] text-muted-foreground/80">
              Sem concorrentes publicados nos {contracts.length} contratos carregados — o portal só publica a
              lista de concorrentes em alguns procedimentos.
            </p>
          ) : (
            <>
              <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {competitors.map((competitor) => (
              <li key={competitor.nif ?? competitor.name}>
                <button
                  type="button"
                  disabled={!competitor.nif}
                  onClick={() =>
                    competitor.nif &&
                    openWindow(`company-detail:${competitor.nif}`, undefined, { title: competitor.name })
                  }
                  className={[
                    "flex w-full items-center gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-2 py-1.5 text-left text-[11.5px] transition",
                    competitor.nif ? "hover:bg-white/[0.08]" : "cursor-default opacity-80",
                  ].join(" ")}
                >
                  <span className="min-w-0 flex-1 truncate">{competitor.name}</span>
                  <span className="shrink-0 tabular-nums text-[10.5px] text-muted-foreground">
                    {competitor.count}× · {formatFinderValue(competitor.value)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[10.5px] text-muted-foreground/70">
            Co-ocorrência nos mesmos procedimentos (dos {contracts.length} contratos carregados).
          </p>
            </>
          )}
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <CompareButton
          item={{ kind: item.kind === "entity" ? "entity" : "contract", id: item.id, name: item.name, subtitle: item.subtitle }}
        />
        {hasTags && (
          <button
            type="button"
            onClick={() =>
              toggle({
                kind: item.kind === "entity" ? "entity" : "contract",
                id: item.id,
                label: item.name,
                sublabel: item.subtitle,
                value: item.value ?? null,
              })
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
          >
            {favorite ? <StarOff size={13} /> : <Star size={13} />}
            {favorite ? "Remover dos favoritos" : "Adicionar aos favoritos"}
          </button>
        )}
        <a
          href={appHref(item)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
        >
          <ExternalLink size={13} /> Abrir na aplicação
        </a>
        <button
          type="button"
          onClick={() => openCompareWindow()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12px] transition hover:bg-white/[0.1]"
        >
          <GitCompare size={13} /> Ver comparação
        </button>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-white/6 py-1">
      <dt className="shrink-0 text-[11px] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-[12.5px] font-medium">{value}</dd>
    </div>
  );
}
