/**
 * **Pesquisa PessoasIQ** — pesquisa Google-like de pessoas no IQ OS.
 *
 * Uma caixa de pesquisa devolve resultados agregados de várias fontes:
 * Pessoas (cadastro), Políticos, Devedores, Municípios, Governo e Entidade
 * para a Transparência. Cada fonte tem o seu cartão, contagem e abertura de
 * ficha no módulo correto.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  ChevronLeft,
  Landmark,
  Loader2,
  PersonStanding,
  Search,
  Shield,
  University,
  Users,
  X,
} from "lucide-react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { useWindowMode } from "../layout";
import { openWindow } from "../windows";
import {
  getPesquisaPessoasFontes,
  pesquisarPessoas,
  suggestPessoas,
  type PesquisaPessoasFonte,
  type PesquisaPessoasGrupo,
  type PesquisaPessoasItem,
  type PesquisaPessoasResponse,
  type PesquisaPessoasSuggestItem,
} from "../pessoasIQPesquisaApi";

/* ------------------------------------------------------------------ estilo */

const FONTE_ICON: Record<string, React.ElementType> = {
  pessoas: PersonStanding,
  politicos: Landmark,
  devedores: AlertTriangle,
  municipios: University,
  governo: Building2,
  ept: Shield,
};

const FONTE_TONE: Record<string, { border: string; bg: string; text: string; badge: string }> = {
  pessoas: {
    border: "border-rose-500/30",
    bg: "bg-rose-500/10",
    text: "text-rose-200",
    badge: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  },
  politicos: {
    border: "border-sky-500/30",
    bg: "bg-sky-500/10",
    text: "text-sky-200",
    badge: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  },
  devedores: {
    border: "border-amber-500/30",
    bg: "bg-amber-500/10",
    text: "text-amber-200",
    badge: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  },
  municipios: {
    border: "border-emerald-500/30",
    bg: "bg-emerald-500/10",
    text: "text-emerald-200",
    badge: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  },
  governo: {
    border: "border-violet-500/30",
    bg: "bg-violet-500/10",
    text: "text-violet-200",
    badge: "border-violet-500/30 bg-violet-500/10 text-violet-200",
  },
  ept: {
    border: "border-teal-500/30",
    bg: "bg-teal-500/10",
    text: "text-teal-200",
    badge: "border-teal-500/30 bg-teal-500/10 text-teal-200",
  },
};

const TUDO_ID = "todas";

function fonteTone(fonte: string) {
  return FONTE_TONE[fonte] ?? {
    border: "border-white/10",
    bg: "bg-white/5",
    text: "text-muted-foreground",
    badge: "border-white/10 bg-white/5 text-muted-foreground",
  };
}

/* ------------------------------------------------------------------ página */

interface PessoasIQPesquisaPageProps {
  initialQuery?: string;
}

export default function PessoasIQPesquisaPage({ initialQuery = "" }: PessoasIQPesquisaPageProps) {
  const { windowMode } = useWindowMode();
  const [q, setQ] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.trim());
  const [fonteAtiva, setFonteAtiva] = useState<string>(TUDO_ID);
  const [resultado, setResultado] = useState<PesquisaPessoasResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fontes, setFontes] = useState<PesquisaPessoasFonte[]>([]);
  const [sugestoes, setSugestoes] = useState<PesquisaPessoasSuggestItem[]>([]);
  const [showSugestoes, setShowSugestoes] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getPesquisaPessoasFontes()
      .then((res) => setFontes(res.fontes))
      .catch(() => setFontes([]));
  }, []);

  const run = useCallback(
    async (termo: string, fonte: string, pagina = 1) => {
      const t = termo.trim();
      if (!t) {
        setResultado(null);
        return;
      }
      setLoading(true);
      setError(null);
      setShowSugestoes(false);
      try {
        const res = await pesquisarPessoas({ q: t, fonte: fonte === TUDO_ID ? "todas" : fonte, page: pagina, size: 20 });
        setResultado((prev) => {
          if (prev && prev.q === t && prev.fonte === res.fonte && pagina > 1) {
            const grupos = prev.grupos.map((g) => {
              const novo = res.grupos.find((ng) => ng.id === g.id);
              if (!novo) return g;
              return { ...novo, items: [...g.items, ...novo.items] };
            });
            return { ...res, grupos };
          }
          return res;
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao pesquisar");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (initialQuery.trim()) {
      void run(initialQuery, fonteAtiva);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const termo = q.trim();
    if (!termo || termo.length < 2) {
      setSugestoes([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const res = await suggestPessoas(termo, 8);
        setSugestoes(res.items);
        setActiveIndex(res.items.length ? 0 : -1);
      } catch {
        setSugestoes([]);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setShowSugestoes(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const onSubmit = useCallback(
    (termo?: string) => {
      const t = termo ?? q;
      setSubmitted(t);
      void run(t, fonteAtiva, 1);
    },
    [q, fonteAtiva, run],
  );

  const onFonteChange = useCallback(
    (id: string) => {
      setFonteAtiva(id);
      if (submitted) void run(submitted, id, 1);
    },
    [submitted, run],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" && sugestoes.length) {
      event.preventDefault();
      setShowSugestoes(true);
      setActiveIndex((prev) => (prev + 1) % sugestoes.length);
      return;
    }
    if (event.key === "ArrowUp" && sugestoes.length) {
      event.preventDefault();
      setShowSugestoes(true);
      setActiveIndex((prev) => (prev - 1 + sugestoes.length) % sugestoes.length);
      return;
    }
    if (event.key === "Escape") {
      setShowSugestoes(false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const ativa = showSugestoes && activeIndex >= 0 ? sugestoes[activeIndex] : undefined;
      if (ativa) {
        setQ(ativa.text);
        setShowSugestoes(false);
        onSubmit(ativa.text);
      } else {
        onSubmit();
      }
    }
  };

  const abrirFicha = useCallback(
    (item: PesquisaPessoasItem) => {
      if (!item.open) return;
      const { view, arg } = item.open;
      // Navegação: o App.tsx trata das vistas conhecidas em modo página; em
      // modo janelas, abrimos a janela com o view id correto.
      if (windowMode && typeof window !== "undefined") {
        const target = view.includes(":") || !arg ? view : `${view}:${arg}`;
        openWindow(target, undefined, { title: item.nome || "Pessoa" });
        return;
      }
      const href =
        view === "pessoas-iq" && arg
          ? `/pessoas-iq?nif=${encodeURIComponent(arg)}`
          : view === "governo-ficha" && arg
            ? `/governo/ficha/${encodeURIComponent(arg)}`
            : view === "entidade-transparencia" && arg
              ? `/entidade-transparencia/titular/${encodeURIComponent(arg)}`
              : null;
      if (href) window.location.href = href;
    },
    [windowMode],
  );

  const gruposVisiveis = useMemo(() => {
    if (!resultado) return [];
    if (fonteAtiva === TUDO_ID) return resultado.grupos.filter((g) => g.total > 0 || g.error);
    return resultado.grupos.filter((g) => g.id === fonteAtiva);
  }, [resultado, fonteAtiva]);

  const totalVisivel = useMemo(
    () => gruposVisiveis.reduce((acc, g) => acc + g.total, 0),
    [gruposVisiveis],
  );

  const abas = useMemo(
    () => [{ id: TUDO_ID, label: "Tudo", icon: Search }, ...fontes.map((f) => ({ ...f, icon: FONTE_ICON[f.id] ?? Users }))],
    [fontes],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg font-semibold">
            <Users size={20} className="text-rose-400" />
            Pesquisa PessoasIQ
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div ref={boxRef} className="relative">
            <div className="flex min-h-[48px] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 focus-within:ring-2 focus-within:ring-rose-400/40">
              <Search size={18} className="shrink-0 text-muted-foreground" />
              <Input
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setShowSugestoes(true);
                }}
                onFocus={() => sugestoes.length > 0 && setShowSugestoes(true)}
                onKeyDown={onKeyDown}
                placeholder="Nome, NIF, cargo ou entidade…"
                className="min-w-0 flex-1 border-0 bg-transparent px-0 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-0"
              />
              {loading && <Loader2 size={16} className="shrink-0 animate-spin text-muted-foreground" />}
              {q && (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    setSugestoes([]);
                    setResultado(null);
                  }}
                  className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground"
                  aria-label="Limpar"
                >
                  <X size={14} />
                </button>
              )}
              <Button onClick={() => onSubmit()} disabled={loading} className="shrink-0 rounded-xl">
                Pesquisar
              </Button>
            </div>

            {showSugestoes && sugestoes.length > 0 && (
              <div className="absolute z-30 mt-1 max-h-[320px] w-full overflow-y-auto rounded-xl border border-white/10 bg-[#140f13] p-1 shadow-xl">
                {sugestoes.map((item, idx) => {
                  const Icon = FONTE_ICON[item.fonte] ?? Users;
                  return (
                    <button
                      key={`${item.text}-${idx}`}
                      type="button"
                      onMouseEnter={() => setActiveIndex(idx)}
                      onClick={() => {
                        setQ(item.text);
                        setShowSugestoes(false);
                        onSubmit(item.text);
                      }}
                      className={[
                        "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition",
                        idx === activeIndex ? "bg-white/[0.10]" : "hover:bg-white/[0.06]",
                      ].join(" ")}
                    >
                      <Icon size={15} className="shrink-0 text-rose-300" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-foreground">{item.text}</span>
                        <span className="block truncate text-muted-foreground">{item.hint || item.fonte}</span>
                      </span>
                    </button>
                  );
                })}
                <p className="px-3 py-1 text-[10px] text-muted-foreground">↑↓ navegar · Enter escolher · Esc fechar</p>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {abas.map((aba) => {
              const Icon = aba.icon ?? Users;
              const ativa = fonteAtiva === aba.id;
              return (
                <button
                  key={aba.id}
                  type="button"
                  onClick={() => onFonteChange(aba.id)}
                  className={[
                    "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition",
                    ativa
                      ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                      : "border-white/10 bg-white/5 text-muted-foreground hover:text-foreground",
                  ].join(" ")}
                >
                  <Icon size={14} />
                  {aba.label}
                  {resultado && aba.id !== TUDO_ID && (
                    <span className="ml-1 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px]">
                      {resultado.grupos.find((g) => g.id === aba.id)?.total ?? 0}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}

      {resultado && !loading && gruposVisiveis.length === 0 && !error && (
        <Card className="p-8 text-center">
          <p className="text-muted-foreground">Nenhuma pessoa encontrada para «{submitted}».</p>
        </Card>
      )}

      {resultado && (
        <div className="text-xs text-muted-foreground">
          {totalVisivel.toLocaleString("pt-PT")} resultado{totalVisivel === 1 ? "" : "s"}
          {fonteAtiva !== TUDO_ID ? ` em ${fontes.find((f) => f.id === fonteAtiva)?.label ?? fonteAtiva}` : ""}
        </div>
      )}

      <div className="space-y-4">
        {gruposVisiveis.map((grupo) => (
          <GrupoCard
            key={grupo.id}
            grupo={grupo}
            onOpen={abrirFicha}
            onMais={() => run(submitted, grupo.id, (resultado?.page ?? 1) + 1)}
            loading={loading}
          />
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- componentes */

function GrupoCard({
  grupo,
  onOpen,
  onMais,
  loading,
}: {
  grupo: PesquisaPessoasGrupo;
  onOpen: (item: PesquisaPessoasItem) => void;
  onMais: () => void;
  loading: boolean;
}) {
  const tone = fonteTone(grupo.id);
  const Icon = FONTE_ICON[grupo.id] ?? Users;
  const podeCarregarMais = grupo.items.length < grupo.total;

  return (
    <Card className={`overflow-hidden border ${tone.border}`}>
      <CardHeader className={`flex flex-row items-center justify-between ${tone.bg}`}>
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <Icon size={18} className={tone.text} />
          <span className={tone.text}>{grupo.label}</span>
          <Badge className={`${tone.badge} text-[10px]`}>{grupo.total.toLocaleString("pt-PT")}</Badge>
        </CardTitle>
        {grupo.hint && <span className="hidden text-xs text-muted-foreground sm:inline">{grupo.hint}</span>}
      </CardHeader>
      <CardContent className="p-0">
        {grupo.error && (
          <p className="border-b border-white/5 px-4 py-2 text-xs text-rose-300">{grupo.error}</p>
        )}
        <ul className="divide-y divide-white/5">
          {grupo.items.map((item) => (
            <li key={item.id} className="group">
              <button
                type="button"
                onClick={() => onOpen(item)}
                className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-white/[0.04]"
              >
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/5">
                  <Icon size={16} className={tone.text} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">{item.nome}</p>
                  {item.subtitulo && <p className="truncate text-xs text-muted-foreground">{item.subtitulo}</p>}
                  {item.snippet && (
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.snippet}</p>
                  )}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {item.badges.map((b) => (
                      <Badge key={b} className={`${tone.badge} text-[10px]`}>
                        {b}
                      </Badge>
                    ))}
                  </div>
                </div>
                <ChevronLeft size={16} className="mt-1 shrink-0 rotate-180 text-muted-foreground" />
              </button>
            </li>
          ))}
        </ul>
        {podeCarregarMais && (
          <div className="px-4 py-2">
            <Button
              variant="outline"
              onClick={onMais}
              disabled={loading}
              className="w-full text-xs"
              loading={loading}
            >
              {`Ver mais (${(grupo.total - grupo.items.length).toLocaleString("pt-PT")})`}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
