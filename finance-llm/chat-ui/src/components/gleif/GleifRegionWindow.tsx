/**
 * Janela **empresas de uma região/país** do mapa GLEIF.
 *
 * Abre-se ao clicar num nó do mapa (`/gleif/mapa`) ou no botão de cada linha da
 * lista lateral, e lista os registos LEI com sede legal nessa divisão: contagem,
 * pesquisa dentro da divisão, estado, ordenação e paginação.
 *
 * É **mestre-detalhe**: escolher uma empresa abre a ficha do LEI (`LeiDetail`) na
 * coluna da direita (sobreposta em ecrãs estreitos). Assim a janela não depende de
 * outras janelas — funciona igual em modo janelas e em modo página, onde é também
 * servida como página (`/gleif/regiao/<nível>/<código>`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Building2, Loader2, MapPin, RefreshCw, Search, X } from "lucide-react";
import { ACTIVE_STATUSES, getGleifRecord, searchGleif, statusLabel, type GleifLei } from "../../gleifApi";
import { countryFlag, countryName } from "../geo/world";
import LeiDetail from "./LeiDetail";

export type GleifRegionLevel = "country" | "region" | "city";

interface GleifRegionWindowProps {
  level: GleifRegionLevel;
  code: string;
  /** Nome legível da divisão (o backend já o resolve nos distritos de Portugal). */
  label?: string;
  /** Fechar (em modo página volta ao mapa). */
  onClose?: () => void;
}

const numberFormat = new Intl.NumberFormat("pt-PT");
const PAGE_SIZE = 30;

export default function GleifRegionWindow({ level, code, label, onClose }: GleifRegionWindowProps) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [status, setStatus] = useState<"" | "ACTIVE" | "INACTIVE">("ACTIVE");
  const [sort, setSort] = useState<"name" | "updated" | "registered">("name");
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<GleifLei[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Registo escolhido na lista (a ficha completa abre na coluna da direita). */
  const [selected, setSelected] = useState<GleifLei | null>(null);
  const [detail, setDetail] = useState<GleifLei | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const title = useMemo(
    () => (level === "country" ? countryName(code) : label || code),
    [code, label, level],
  );

  /** Descrição da divisão usada no cabeçalho e na caixa de pesquisa. */
  const scope = level === "country" ? "neste país" : level === "city" ? "nesta cidade" : "nesta região";

  const load = useCallback(
    async (text: string, nextPage = 0) => {
      setLoading(true);
      setError(null);
      try {
        const result = await searchGleif({
          q: text || undefined,
          ...(level === "country" ? { country: code } : level === "city" ? { city: code } : { region: code }),
          status: status || undefined,
          sort,
          size: PAGE_SIZE,
          from: nextPage * PAGE_SIZE,
        });
        setItems(result.items || []);
        setTotal(result.total || 0);
        setPage(nextPage);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Não foi possível carregar as empresas");
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [code, level, sort, status],
  );

  useEffect(() => {
    void load(submitted, 0);
  }, [load, submitted]);

  /** Mostra a ficha da empresa escolhida (a lista já traz os campos principais). */
  const openRecord = useCallback((item: GleifLei) => {
    setSelected(item);
    setDetail(item);
    setDetailError(null);
    setDetailLoading(true);
    getGleifRecord(item.lei)
      .then((record) => setDetail(record))
      .catch((err: unknown) => setDetailError(err instanceof Error ? err.message : "Ficha indisponível"))
      .finally(() => setDetailLoading(false));
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <header className="flex flex-wrap items-center gap-2 border-b border-white/10 px-4 py-2">
        <span className="text-lg leading-none">{level === "country" ? countryFlag(code) : <MapPin size={16} />}</span>
        <div className="min-w-0">
          <h2 className="truncate text-[13px] font-semibold text-foreground">{title}</h2>
          <p className="text-[10.5px] text-muted-foreground">
            Empresas com registo LEI {scope} · <span className="font-mono">{code}</span>
          </p>
        </div>

        <span className="ml-auto flex flex-wrap items-center gap-2 text-[11px]">
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-muted-foreground">
            {loading ? (
              <span className="flex items-center gap-1">
                <Loader2 size={11} className="animate-spin" /> a carregar…
              </span>
            ) : (
              <>
                <span className="text-foreground">{numberFormat.format(total)}</span> registos
              </>
            )}
          </span>
          <button
            type="button"
            onClick={() => void load(submitted, page)}
            title="Atualizar"
            className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
          >
            <RefreshCw size={11} />
            atualizar
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Fechar"
              className="rounded-full p-1 text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
            >
              <X size={13} />
            </button>
          )}
        </span>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-4 py-2 text-[11px]">
        <div className="flex min-w-[200px] flex-1 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-2.5 py-1 focus-within:border-primary/40">
          <Search size={13} className="text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") setSubmitted(query.trim());
            }}
            placeholder={`Procurar dentro de ${title}…`}
            className="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground/60"
          />
          {query && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setSubmitted("");
              }}
              title="Limpar"
              className="rounded-full p-0.5 text-muted-foreground transition hover:bg-white/10"
            >
              <X size={12} />
            </button>
          )}
        </div>

        <div className="flex items-center gap-1 rounded-xl glass-card p-1">
          {(
            [
              ["", "Todas"],
              ["ACTIVE", "Ativas"],
              ["INACTIVE", "Inativas"],
            ] as ["" | "ACTIVE" | "INACTIVE", string][]
          ).map(([value, text]) => (
            <button
              key={text}
              type="button"
              onClick={() => setStatus(value)}
              aria-pressed={status === value}
              className={`rounded-lg px-2 py-0.5 transition ${status === value ? "bg-primary/15 text-primary" : "hover:bg-white/5"}`}
            >
              {text}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-1.5 rounded-xl glass-card px-2 py-1">
          <span className="text-muted-foreground">ordenar</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as "name" | "updated" | "registered")}
            className="bg-transparent text-[11px] outline-none"
          >
            <option value="name">nome A→Z</option>
            <option value="updated">atualização recente</option>
            <option value="registered">registo recente</option>
          </select>
        </label>
      </div>

      {error && (
        <p className="border-b border-amber-400/20 bg-amber-400/5 px-4 py-1.5 text-[11px] text-amber-200">{error}</p>
      )}

      <div className="relative flex min-h-0 flex-1">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
            {!loading && items.length === 0 && !error && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-[11px] text-muted-foreground">
                <Building2 size={18} />
                Sem empresas para estes filtros.
              </div>
            )}
            <ul className="flex flex-col gap-1">
              {items.map((item) => (
                <li key={item.lei}>
                  <button
                    type="button"
                    onClick={() => openRecord(item)}
                    className={`flex w-full items-start gap-2 rounded-xl border px-2.5 py-1.5 text-left transition ${
                      selected?.lei === item.lei
                        ? "border-primary/40 bg-primary/10"
                        : "border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/5"
                    }`}
                  >
                    <span className="mt-0.5">{countryFlag(item.country)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-[12px] font-medium text-foreground">{item.legal_name}</span>
                        {item.status && (
                          <span
                            className={`rounded-full border px-1.5 py-0.5 text-[9.5px] ${
                              ACTIVE_STATUSES.has(item.status)
                                ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                                : "border-amber-400/25 bg-amber-400/10 text-amber-200"
                            }`}
                          >
                            {statusLabel(item.status)}
                          </span>
                        )}
                        {item.legal_form && (
                          <span className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[9.5px] text-muted-foreground">
                            {item.legal_form}
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10.5px] text-muted-foreground">
                        <span className="font-mono text-foreground/80">{item.lei}</span>
                        <span>{[item.city, item.region_name || item.region].filter(Boolean).join(" · ")}</span>
                        {item.registered_as ? <span>NIF registo {item.registered_as}</span> : null}
                      </span>
                    </span>
                    <ArrowRight size={13} className="mt-1 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-white/10 px-4 py-1.5 text-[11px] text-muted-foreground">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => void load(submitted, page - 1)}
                className="rounded-lg border border-white/10 px-2 py-0.5 transition hover:bg-white/5 disabled:opacity-40"
              >
                anterior
              </button>
              <span>
                página {page + 1} de {totalPages}
              </span>
              <button
                type="button"
                disabled={page + 1 >= totalPages}
                onClick={() => void load(submitted, page + 1)}
                className="rounded-lg border border-white/10 px-2 py-0.5 transition hover:bg-white/5 disabled:opacity-40"
              >
                seguinte
              </button>
            </div>
          )}
        </div>

        {/* Ficha da empresa escolhida: coluna da direita (larga) ou painel sobreposto. */}
        {selected && (
          <aside className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[min(100%,430px)] shrink-0 flex-col overflow-y-auto border-l border-white/10 bg-background/95 px-4 py-3 backdrop-blur lg:static lg:z-auto lg:w-[430px] lg:max-w-none lg:bg-transparent lg:backdrop-blur-none">
            {detailLoading && !detail ? (
              <div className="flex h-full items-center justify-center gap-2 text-[11px] text-muted-foreground">
                <Loader2 size={16} className="animate-spin" /> a carregar a ficha…
              </div>
            ) : (
              <>
                {detailError && (
                  <div className="mb-2 flex items-center gap-2 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
                    <AlertTriangle size={13} />
                    {detailError}
                  </div>
                )}
                {detail && <LeiDetail record={detail} onClose={() => setSelected(null)} />}
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
