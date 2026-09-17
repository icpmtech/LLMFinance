/**
 * Browser do IQ OS.
 *
 * Um browser dentro da plataforma: separadores, barra de endereço com pesquisa,
 * voltar/avançar, favoritos, histórico e atalhos para as páginas do IQ OS e para
 * fontes de mercado.
 *
 * Notas de arquitetura:
 * - O conteúdo é mostrado num `iframe`. Muitos sites recusam ser incorporados
 *   (`X-Frame-Options`/CSP): nesses casos mostramos um aviso com a opção de abrir
 *   numa aba nova ou tentar mesmo assim.
 * - Ligações internas (`/dashboard`, `/tickers`, ...) não são incorporadas por
 *   omissão — abrem a aplicação do IQ OS (evita janelas dentro de janelas).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bookmark,
  BookmarkPlus,
  Clock,
  ExternalLink,
  Globe2,
  History,
  Info,
  Loader2,
  Lock,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Star,
  Trash2,
  X,
} from "lucide-react";
import {
  QUICK_GROUPS,
  SEARCH_ENGINES,
  blocksFraming,
  engineLabel,
  hostOf,
  initBrowserSession,
  internalPath,
  isSearchUrl,
  proxyUrl,
  queryFromSearchUrl,
  siteLabel,
  useBrowser,
  useProxyFor,
  viewForPath,
  type BrowserTab,
  type SearchEngine,
} from "../browser";
import { API_BASE } from "../api";

interface BrowserPageProps {
  /** Abre uma aplicação do IQ OS (rotas internas). */
  onOpenInternal?: (view: string) => void;
  /** Pesquisa global do IQ OS (query livre). */
  onGlobalSearch?: (query: string) => void;
}

/** Rótulo curto de um separador. */
function tabTitle(tab: BrowserTab) {
  if (!tab.url) return tab.title || "Nova aba";
  return tab.title && tab.title !== siteLabel(tab.url) ? tab.title : siteLabel(tab.url);
}

function iconFor(url: string) {
  if (!url) return <Globe2 size={13} className="text-zinc-400" />;
  if (internalPath(url)) return <Lock size={13} className="text-teal-300" />;
  return <Globe2 size={13} className="text-sky-300" />;
}

export default function BrowserPage({ onOpenInternal, onGlobalSearch }: BrowserPageProps) {
  const { tabs, active, actions, bookmarks, history, engine, restoreSession, mutedHints, proxyEnabled, forceProxy, isBookmarked } = useBrowser();
  const [draft, setDraft] = useState(active?.url ?? "");
  const [panel, setPanel] = useState<"none" | "bookmarks" | "history">("none");
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [forceLoad, setForceLoad] = useState<Record<string, boolean>>({});
  const [stalled, setStalled] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const stallTimer = useRef<number | null>(null);

  const url = active?.url ?? "";
  const path = internalPath(url);
  /* Páginas que recusam incorporação (ou o utilizador pediu) são lidas pelo
     proxy do servidor, que remove os cabeçalhos bloqueadores. */
  const viaProxy = useProxyFor(url, proxyEnabled, forceProxy);
  const source = viaProxy ? proxyUrl(API_BASE, url) : url;
  const blocked = Boolean(url) && blocksFraming(url) && !viaProxy;
  const searchResults = Boolean(url) && isSearchUrl(url);
  /* Aviso discreto para páginas externas: muitos sites (bancos, portais
     oficiais, agregadores) recusam a incorporação e aparecem em branco sem
     qualquer erro visível. O aviso é dispensável por site. */
  const showHint =
    Boolean(url) && !path && !viaProxy && !blocked && Boolean(hostOf(url)) && !mutedHints.includes(hostOf(url));
  const forced = Boolean(forceLoad[url]);
  const starred = isBookmarked(url);

  useEffect(() => {
    initBrowserSession();
  }, []);

  useEffect(() => {
    setDraft(active?.url ?? "");
  }, [active?.id, active?.url]);

  useEffect(() => {
    setLoading(Boolean(url));
  }, [url, reloadKey, active?.id]);

  // Ao mudar de separador, esquece o "tentar mesmo assim" do endereço anterior.
  useEffect(() => {
    setForceLoad({});
  }, [active?.id]);

  const go = useCallback(
    (input: string) => {
      if (!active) return;
      actions.navigate(active.id, input);
    },
    [active, actions],
  );

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    // Rotas internas conhecidas: abrir a aplicação em vez de incorporar.
    const internal = value.startsWith("/") ? viewForPath(value) : null;
    if (internal && onOpenInternal) {
      onOpenInternal(internal);
      actions.navigate(active.id, value);
      return;
    }
    go(value);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const typing = (event.target as HTMLElement | null)?.tagName === "INPUT";
    if (event.altKey && event.key === "ArrowLeft") {
      event.preventDefault();
      actions.back(active.id);
      return;
    }
    if (event.altKey && event.key === "ArrowRight") {
      event.preventDefault();
      actions.forward(active.id);
      return;
    }
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key === "t") {
      event.preventDefault();
      event.stopPropagation();
      actions.addTab("");
      window.setTimeout(() => inputRef.current?.focus(), 60);
      return;
    }
    if (key === "l") {
      event.preventDefault();
      event.stopPropagation();
      inputRef.current?.focus();
      inputRef.current?.select();
      return;
    }
    if (key === "d") {
      event.preventDefault();
      event.stopPropagation();
      if (url && !starred) actions.toggleBookmark(url, active?.title);
      return;
    }
    if (key === "r" && !typing) {
      event.preventDefault();
      event.stopPropagation();
      setReloadKey((value) => value + 1);
    }
  };

  const onFrameLoad = () => {
    if (stallTimer.current !== null) {
      window.clearTimeout(stallTimer.current);
      stallTimer.current = null;
    }
    setStalled(false);
    setLoading(false);
    setNote(null);
    const node = iframeRef.current;
    if (!node) return;
    try {
      // Só funciona em páginas da mesma origem (páginas internas do IQ OS).
      const title = node.contentDocument?.title;
      if (title) actions.setTitle(active.id, title);
      window.localStorage.setItem("finance-llm-browser:last-title", title ?? "");
    } catch {
      // Página de outra origem: o título do separador fica com o domínio.
    }
  };

  const recent = useMemo(() => {
    const seen = new Set<string>();
    return history.filter((item) => (seen.has(item.url) ? false : (seen.add(item.url), true))).slice(0, 12);
  }, [history]);

  const topBookmarks = bookmarks.slice(0, 12);

  /*
   * A página lida pelo proxy não pode navegar sozinha (as ligações originais
   * seriam bloqueadas outra vez): o script injetado pede-nos para navegar, e é
   * a barra de endereço/separadores/histórico do IQ OS que trata disso.
   */
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { source?: string; kind?: string; url?: string; text?: string } | null;
      if (!data || data.source !== "iq-os-browser") return;
      const frame = iframeRef.current;
      if (frame && event.source !== frame.contentWindow) return;
      if (data.kind === "status") {
        setNote(typeof data.text === "string" ? data.text : null);
        return;
      }
      if (data.kind === "ready") {
        setNote(null);
        return;
      }
      if (typeof data.url !== "string" || !data.url) return;
      if (data.kind === "open") window.open(data.url, "_blank", "noopener,noreferrer");
      else if (data.kind === "navigate") actions.navigate(active.id, data.url);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [active?.id, actions]);

  const showStart = !url;

  /*
   * Nem todos os endereços respondem: o site pode estar offline, a rede pode
   * bloquear o conteúdo ou o site pode recusar a incorporação (nesse caso o
   * `load` também não chega). Se nada carregar em 8 s, mostramos um aviso com a
   * saída rápida: abrir numa aba do sistema.
   */
  useEffect(() => {
    if (stallTimer.current !== null) {
      window.clearTimeout(stallTimer.current);
      stallTimer.current = null;
    }
    setStalled(false);
    if (!url || (path && !active?.embedInternal) || (blocked && !forced)) return;
    stallTimer.current = window.setTimeout(() => {
      stallTimer.current = null;
      setStalled(true);
      setLoading(false);
    }, 12000);
    return () => {
      if (stallTimer.current !== null) {
        window.clearTimeout(stallTimer.current);
        stallTimer.current = null;
      }
    };
  }, [url, reloadKey, active?.id, active?.embedInternal, path, blocked, forced, viaProxy]);

  return (
    <div className="flex @container h-full min-h-0 w-full flex-col bg-[#0d0f13]" onKeyDown={onKeyDown}>
      {/* barra de navegação */}
      <div className="flex shrink-0 items-center gap-1.5 border-b border-white/8 bg-[#12151b] px-2.5 py-2">
        <button
          type="button"
          onClick={() => actions.back(active.id)}
          disabled={!active || active.index <= 0}
          title="Voltar (Alt+←)"
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8 disabled:opacity-30"
        >
          <ArrowLeft size={15} />
        </button>
        <button
          type="button"
          onClick={() => actions.forward(active.id)}
          disabled={!active || active.index >= active.history.length - 1}
          title="Avançar (Alt+→)"
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8 disabled:opacity-30"
        >
          <ArrowRight size={15} />
        </button>
        <button
          type="button"
          onClick={() => setReloadKey((value) => value + 1)}
          disabled={!url}
          title="Recarregar (Ctrl+R)"
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8 disabled:opacity-30"
        >
          <RefreshCw size={15} className={loading ? "animate-spin" : undefined} />
        </button>
        <button
          type="button"
          onClick={() => actions.home(active.id)}
          title="Página inicial"
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8"
        >
          <Globe2 size={15} />
        </button>

        <form onSubmit={onSubmit} className="flex min-w-0 flex-1 items-center gap-2">
          <div className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-xl border border-white/10 bg-[#0a0c10] px-3 transition focus-within:border-teal-400/50">
            {iconFor(url)}
            <input
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onFocus={(event) => event.currentTarget.select()}
              placeholder={`Pesquisar com ${engineLabel(engine as SearchEngine)} ou escrever um endereço`}
              spellCheck={false}
              className="min-w-0 flex-1 bg-transparent text-[12.5px] text-zinc-100 outline-none placeholder:text-zinc-500"
            />
            {path ? (
              <span className="shrink-0 rounded-md bg-teal-400/12 px-1.5 py-0.5 text-[10px] font-medium text-teal-200">IQ OS</span>
            ) : null}
            {viaProxy ? (
              <span
                title="Página lida pelo servidor do IQ OS (remove os cabeçalhos que impedem a incorporação; sem sessões)"
                className="shrink-0 rounded-md bg-violet-400/15 px-1.5 py-0.5 text-[10px] font-medium text-violet-200"
              >
                proxy
              </span>
            ) : null}
            {starred ? <Star size={13} className="shrink-0 fill-amber-300 text-amber-300" /> : null}
          </div>
          <button
            type="submit"
            title="Ir"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-teal-400/15 text-teal-200 transition hover:bg-teal-400/25"
          >
            <Search size={15} />
          </button>
        </form>

        <button
          type="button"
          onClick={() => url && actions.toggleBookmark(url, active?.title)}
          disabled={!url}
          title={starred ? "Remover dos favoritos" : "Adicionar aos favoritos (Ctrl+D)"}
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8 disabled:opacity-30"
        >
          {starred ? <Star size={15} className="fill-amber-300 text-amber-300" /> : <BookmarkPlus size={15} />}
        </button>
        <button
          type="button"
          onClick={() => setPanel(panel === "bookmarks" ? "none" : "bookmarks")}
          title="Favoritos"
          className={`grid h-8 w-8 place-items-center rounded-lg transition hover:bg-white/8 ${panel === "bookmarks" ? "bg-white/10 text-amber-200" : "text-zinc-300"}`}
        >
          <Bookmark size={15} />
        </button>
        <button
          type="button"
          onClick={() => setPanel(panel === "history" ? "none" : "history")}
          title="Histórico"
          className={`grid h-8 w-8 place-items-center rounded-lg transition hover:bg-white/8 ${panel === "history" ? "bg-white/10 text-sky-200" : "text-zinc-300"}`}
        >
          <History size={15} />
        </button>
        <button
          type="button"
          onClick={() => url && window.open(url, "_blank", "noopener,noreferrer")}
          disabled={!url}
          title="Abrir numa aba do sistema"
          className="grid h-8 w-8 place-items-center rounded-lg text-zinc-300 transition hover:bg-white/8 disabled:opacity-30"
        >
          <ExternalLink size={15} />
        </button>
      </div>

      {/* separadores */}
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-white/8 bg-[#0f1217] px-2 py-1.5">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`group flex h-8 max-w-[220px] shrink-0 items-center gap-2 rounded-lg border px-2.5 text-[11.5px] transition ${
              tab.id === active?.id
                ? "border-white/12 bg-[#1b2028] text-zinc-100"
                : "border-transparent text-zinc-400 hover:bg-white/5"
            }`}
          >
            <button type="button" onClick={() => actions.activateTab(tab.id)} className="flex min-w-0 items-center gap-2">
              {loading && tab.id === active?.id ? <Loader2 size={12} className="animate-spin" /> : iconFor(tab.url)}
              <span className="truncate">{tabTitle(tab)}</span>
            </button>
            <button
              type="button"
              onClick={() => actions.closeTab(tab.id)}
              title="Fechar separador"
              className="grid h-5 w-5 shrink-0 place-items-center rounded text-zinc-500 opacity-0 transition hover:bg-white/10 hover:text-zinc-200 group-hover:opacity-100"
            >
              <X size={11} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => {
            actions.addTab("");
            window.setTimeout(() => inputRef.current?.focus(), 60);
          }}
          title="Novo separador (Ctrl+T)"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-zinc-400 transition hover:bg-white/8 hover:text-zinc-100"
        >
          <Plus size={14} />
        </button>
        <div className="ml-auto flex shrink-0 items-center gap-2 pl-2">
          <select
            value={engine}
            onChange={(event) => actions.setEngine(event.target.value as SearchEngine)}
            title="Motor de pesquisa"
            className="h-7 rounded-lg border border-white/10 bg-[#0a0c10] px-1.5 text-[11px] text-zinc-300 outline-none"
          >
            {SEARCH_ENGINES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* mensagens da página lida (formulários, avisos do proxy) */}
      {note ? (
        <div className="flex shrink-0 items-center gap-2 border-b border-white/8 bg-white/4 px-3 py-1.5 text-[11px] text-zinc-300">
          <Info size={12} className="shrink-0 text-violet-300" />
          {note}
        </div>
      ) : null}

      {/* aviso de site sem resposta */}
      {stalled ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-amber-300/25 bg-amber-400/10 px-3 py-1.5 text-[11.5px] text-amber-100">
          <ShieldAlert size={13} className="shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="font-medium">{siteLabel(url)}</span> não respondeu — o site pode estar offline, bloqueado pela rede ou
            recusar ser incorporado.
          </span>
          <button
            type="button"
            onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
            className="h-7 shrink-0 rounded-lg bg-amber-300/20 px-2.5 font-medium text-amber-50 transition hover:bg-amber-300/30"
          >
            Abrir numa aba do sistema
          </button>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="h-7 shrink-0 rounded-lg border border-white/15 px-2.5 text-amber-50/90 transition hover:bg-white/10"
          >
            Tentar de novo
          </button>
        </div>
      ) : null}

      {/* aviso discreto: muitos sites externos recusam ser incorporados */}
      {showHint && !stalled ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-sky-300/20 bg-sky-400/8 px-3 py-1.5 text-[11px] text-sky-100/90">
          <Info size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">
            Se {hostOf(url)} aparecer em branco, o site recusa a incorporação em «iframe» (bancos, portais oficiais e agregadores
            fazem-no quase sempre).
          </span>
          <button
            type="button"
            onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
            className="h-7 shrink-0 rounded-lg bg-sky-300/20 px-2.5 font-medium text-sky-50 transition hover:bg-sky-300/30"
          >
            Abrir numa aba do sistema
          </button>
          <button
            type="button"
            onClick={() => actions.muteHint(hostOf(url))}
            className="h-7 shrink-0 rounded-lg border border-white/15 px-2.5 transition hover:bg-white/10"
          >
            Não avisar para este site
          </button>
        </div>
      ) : null}

      {/* conteúdo */}
      <div className="relative min-h-0 flex-1">
        {showStart ? (
          <div className="h-full overflow-y-auto px-4 py-6">
            <div className="mx-auto max-w-4xl">
              <div className="mb-5 text-center">
                <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-teal-300 via-teal-500 to-emerald-600 text-[#04120e]">
                  <Globe2 size={22} />
                </div>
                <h2 className="text-[17px] font-semibold text-zinc-100">Browser do IQ OS</h2>
                <p className="mt-1 text-[12px] text-zinc-400">
                  Escreva um endereço ou pesquise com {engineLabel(engine as SearchEngine)}. Ligações internas abrem a aplicação; a
                  pesquisa web abre numa aba do sistema (os motores não permitem incorporação).
                </p>
              </div>

              <form onSubmit={onSubmit} className="mx-auto mb-5 flex max-w-2xl items-center gap-2">
                <div className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-2xl border border-white/10 bg-[#0a0c10] px-3.5 focus-within:border-teal-400/50">
                  <Search size={15} className="text-zinc-500" />
                  <input
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="ex.: edp.pt, euronext, /contratos/search, notícias de energia"
                    spellCheck={false}
                    className="min-w-0 flex-1 bg-transparent text-[13px] text-zinc-100 outline-none placeholder:text-zinc-500"
                  />
                </div>
                <button type="submit" className="h-11 shrink-0 rounded-2xl bg-teal-400/20 px-5 text-[12.5px] font-medium text-teal-100 transition hover:bg-teal-400/30">
                  Ir
                </button>
                {onGlobalSearch ? (
                  <button
                    type="button"
                    onClick={() => onGlobalSearch(draft.trim())}
                    disabled={!draft.trim()}
                    title="Procurar nos dados do IQ OS (contratos, empresas, mercados)"
                    className="h-11 shrink-0 rounded-2xl border border-white/10 px-4 text-[12.5px] text-zinc-300 transition hover:bg-white/8 disabled:opacity-40"
                  >
                    Procurar no IQ OS
                  </button>
                ) : null}
              </form>

              {topBookmarks.length > 0 ? (
                <section className="mb-5">
                  <h3 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-zinc-400 uppercase">
                    <Bookmark size={12} /> Favoritos
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {topBookmarks.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => go(item.url)}
                        className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/4 px-3 py-1.5 text-[12px] text-zinc-200 transition hover:border-teal-400/40 hover:bg-teal-400/10"
                      >
                        {iconFor(item.url)}
                        <span className="max-w-[180px] truncate">{item.title}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              {QUICK_GROUPS.map((group) => (
                <section key={group.id} className="mb-5">
                  <h3 className="mb-2 text-[11px] font-semibold tracking-wide text-zinc-400 uppercase">{group.label}</h3>
                  <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                    {group.links.map((link) => (
                      <button
                        key={link.url}
                        type="button"
                        onClick={() => {
                          if (link.internal && onOpenInternal) {
                            onOpenInternal(link.internal);
                            actions.navigate(active.id, link.url);
                            return;
                          }
                          go(link.url);
                        }}
                        className="group flex flex-col items-start gap-0.5 rounded-xl border border-white/8 bg-white/3 px-3 py-2.5 text-left transition hover:border-teal-400/40 hover:bg-teal-400/8"
                      >
                        <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-zinc-100">
                          {link.internal ? <Lock size={12} className="text-teal-300" /> : <Globe2 size={12} className="text-sky-300" />}
                          {link.label}
                        </span>
                        <span className="text-[11px] text-zinc-500">{link.hint}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ))}

              {recent.length > 0 ? (
                <section className="mb-3">
                  <h3 className="mb-2 flex items-center justify-between text-[11px] font-semibold tracking-wide text-zinc-400 uppercase">
                    <span className="flex items-center gap-1.5">
                      <Clock size={12} /> Visitados recentemente
                    </span>
                    <button type="button" onClick={() => setPanel("history")} className="text-[10.5px] font-normal text-teal-300 normal-case hover:underline">
                      ver histórico
                    </button>
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {recent.slice(0, 8).map((item) => (
                      <button
                        key={item.url}
                        type="button"
                        onClick={() => go(item.url)}
                        className="flex items-center gap-2 rounded-xl border border-white/8 bg-white/3 px-3 py-1.5 text-[12px] text-zinc-300 transition hover:bg-white/8"
                      >
                        {iconFor(item.url)}
                        <span className="max-w-[200px] truncate">{item.title || siteLabel(item.url)}</span>
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          </div>
        ) : path && !active?.embedInternal ? (
          <div className="grid h-full place-items-center px-6">
            <div className="max-w-md rounded-2xl border border-white/10 bg-white/4 p-5 text-center">
              <Lock size={20} className="mx-auto mb-2 text-teal-300" />
              <h3 className="text-[14px] font-semibold text-zinc-100">Esta página pertence ao IQ OS</h3>
              <p className="mt-1 text-[12px] text-zinc-400">
                <span className="text-teal-200">{path}</span> é uma aplicação da plataforma. Abrir dentro do browser criaria uma
                janela dentro de outra — escolha como quer ver.
              </p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={() => onOpenInternal?.(path.replace(/^\//, ""))}
                  className="h-9 rounded-xl bg-teal-400/20 px-4 text-[12px] font-medium text-teal-100 transition hover:bg-teal-400/30"
                >
                  Abrir na aplicação
                </button>
                <button
                  type="button"
                  onClick={() => actions.setEmbedInternal(active.id, true)}
                  className="h-9 rounded-xl border border-white/12 px-4 text-[12px] text-zinc-300 transition hover:bg-white/8"
                >
                  Ver aqui dentro
                </button>
                <button
                  type="button"
                  onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
                  className="h-9 rounded-xl border border-white/12 px-4 text-[12px] text-zinc-300 transition hover:bg-white/8"
                >
                  Abrir em nova aba
                </button>
              </div>
            </div>
          </div>
        ) : blocked && !forced ? (
          <div className="grid h-full place-items-center px-6">
            <div
              className={[
                "max-w-md rounded-2xl border p-5 text-center",
                searchResults ? "border-sky-300/25 bg-sky-400/8" : "border-amber-400/25 bg-amber-400/8",
              ].join(" ")}
            >
              {searchResults ? <Search size={20} className="mx-auto mb-2 text-sky-300" /> : <ShieldAlert size={20} className="mx-auto mb-2 text-amber-300" />}
              <h3 className="text-[14px] font-semibold text-zinc-100">
                {searchResults ? "Os motores de pesquisa não permitem ser incorporados" : `${siteLabel(url)} recusa ser mostrado aqui`}
              </h3>
              <p className="mt-1 text-[12px] text-zinc-300/85">
                {searchResults
                  ? `${engineLabel(engine as SearchEngine)} envia cabeçalhos (frame-ancestors) que impedem a incorporação em «iframe» — o mesmo acontece com o Google, o Bing e o Brave. Os resultados abrem numa aba do sistema; para procurar nos dados do IQ OS use «Procurar no IQ OS».`
                  : "O site envia cabeçalhos que impedem a incorporação em «iframe» (proteção contra clickjacking). Abra numa aba do sistema para o ver."}
              </p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                {!proxyEnabled ? (
                  <button
                    type="button"
                    onClick={() => actions.setProxyEnabled(true)}
                    className="h-9 rounded-xl bg-violet-400/25 px-4 text-[12px] font-medium text-violet-50 transition hover:bg-violet-400/35"
                  >
                    Ler com proxy (servidor)
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => actions.setForceProxy(true)}
                    className="h-9 rounded-xl bg-violet-400/25 px-4 text-[12px] font-medium text-violet-50 transition hover:bg-violet-400/35"
                  >
                    Ler com proxy (servidor)
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => window.open(url, "_blank", "noopener,noreferrer")}
                  className={[
                    "h-9 rounded-xl px-4 text-[12px] font-medium transition",
                    searchResults ? "bg-sky-300/20 text-sky-50 hover:bg-sky-300/30" : "bg-amber-300/20 text-amber-100 hover:bg-amber-300/30",
                  ].join(" ")}
                >
                  {searchResults ? "Abrir pesquisa numa aba do sistema" : "Abrir em nova aba"}
                </button>
                {onGlobalSearch && searchResults ? (
                  <button
                    type="button"
                    onClick={() => onGlobalSearch(queryFromSearchUrl(url))}
                    className="h-9 rounded-xl border border-white/12 px-4 text-[12px] text-zinc-300 transition hover:bg-white/8"
                  >
                    Procurar no IQ OS
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setForceLoad((current) => ({ ...current, [url]: true }))}
                  className="h-9 rounded-xl border border-white/12 px-4 text-[12px] text-zinc-300 transition hover:bg-white/8"
                >
                  Tentar mesmo assim
                </button>
              </div>
            </div>
          </div>
        ) : (
          <>
            {loading ? (
              <div className="absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden bg-teal-400/15">
                <div className="h-full w-1/3 animate-pulse bg-teal-300" />
              </div>
            ) : null}
            <iframe
              ref={iframeRef}
              key={`${active?.id}-${reloadKey}-${source}`}
              title={siteLabel(url)}
              src={source}
              onLoad={onFrameLoad}
              referrerPolicy="no-referrer"
              allow="clipboard-write; fullscreen; geolocation"
              sandbox="allow-downloads allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts"
              className="h-full w-full border-0 bg-white"
            />
          </>
        )}

        {/* painel de favoritos/histórico */}
        {panel !== "none" ? (
          <div className="absolute inset-y-0 right-0 z-20 flex w-[300px] flex-col border-l border-white/10 bg-[#0f1319]/95 backdrop-blur-xl">
            <div className="flex shrink-0 items-center justify-between border-b border-white/8 px-3 py-2">
              <span className="flex items-center gap-1.5 text-[12px] font-semibold text-zinc-200">
                {panel === "bookmarks" ? <Bookmark size={13} /> : <History size={13} />}
                {panel === "bookmarks" ? `Favoritos (${bookmarks.length})` : `Histórico (${history.length})`}
              </span>
              <div className="flex items-center gap-1">
                {panel === "history" && history.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => actions.clearHistory()}
                    title="Limpar histórico"
                    className="grid h-7 w-7 place-items-center rounded-lg text-zinc-400 transition hover:bg-white/8 hover:text-rose-300"
                  >
                    <Trash2 size={13} />
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setPanel("none")}
                  className="grid h-7 w-7 place-items-center rounded-lg text-zinc-400 transition hover:bg-white/8"
                >
                  <X size={13} />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {panel === "bookmarks" ? (
                bookmarks.length === 0 ? (
                  <p className="px-2 py-4 text-[11.5px] text-zinc-500">
                    Sem favoritos. Use a estrela na barra de endereço (ou Ctrl+D) para guardar uma página.
                  </p>
                ) : (
                  bookmarks.map((item) => (
                    <div key={item.id} className="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/6">
                      <button type="button" onClick={() => go(item.url)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                        {iconFor(item.url)}
                        <span className="min-w-0">
                          <span className="block truncate text-[12px] text-zinc-200">{item.title}</span>
                          <span className="block truncate text-[10.5px] text-zinc-500">{item.url}</span>
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => actions.removeBookmark(item.id)}
                        title="Remover"
                        className="grid h-6 w-6 shrink-0 place-items-center rounded text-zinc-500 opacity-0 transition group-hover:opacity-100 hover:text-rose-300"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))
                )
              ) : history.length === 0 ? (
                <p className="px-2 py-4 text-[11.5px] text-zinc-500">O histórico está vazio.</p>
              ) : (
                history.map((item) => (
                  <div key={`${item.url}-${item.visitedAt}`} className="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/6">
                    <button type="button" onClick={() => go(item.url)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                      {iconFor(item.url)}
                      <span className="min-w-0">
                        <span className="block truncate text-[12px] text-zinc-200">{item.title || siteLabel(item.url)}</span>
                        <span className="block truncate text-[10.5px] text-zinc-500">
                          {new Date(item.visitedAt).toLocaleString("pt-PT")}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => actions.removeHistory(item.url)}
                      title="Remover do histórico"
                      className="grid h-6 w-6 shrink-0 place-items-center rounded text-zinc-500 opacity-0 transition group-hover:opacity-100 hover:text-rose-300"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))
              )}
            </div>
            <p className="shrink-0 border-t border-white/8 px-3 py-2 text-[10.5px] leading-relaxed text-zinc-500">
              <Info size={10} className="mr-1 inline" />
              Alguns sites (bancos, Google, redes sociais) bloqueiam a incorporação em «iframe» e só abrem numa aba do sistema.
            </p>
          </div>
        ) : null}
      </div>

      {/* rodapé */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/8 bg-[#12151b] px-3 py-1.5 text-[10.5px] text-zinc-500">
        <span className="flex min-w-0 items-center gap-1.5">
          {iconFor(url)}
          <span className="truncate text-zinc-400">{url || "Nova aba"}</span>
          {viaProxy ? <span className="shrink-0 text-violet-300">via proxy do servidor (sem sessões)</span> : null}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1">
          <label className="flex items-center gap-1.5" title="Sites que recusam incorporação são lidos pelo servidor do IQ OS">
            <input
              type="checkbox"
              checked={proxyEnabled}
              onChange={(event) => actions.setProxyEnabled(event.target.checked)}
              className="h-3 w-3 accent-violet-400"
            />
            ler bloqueadas pelo servidor
          </label>
          <label className="flex items-center gap-1.5" title="Lê todas as páginas pelo servidor (mais lento, sem sessões)">
            <input
              type="checkbox"
              checked={forceProxy}
              onChange={(event) => actions.setForceProxy(event.target.checked)}
              className="h-3 w-3 accent-violet-400"
            />
            ler tudo pelo servidor
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={restoreSession}
              onChange={(event) => actions.setRestoreSession(event.target.checked)}
              className="h-3 w-3 accent-teal-400"
            />
            retomar separadores
          </label>
          <button
            type="button"
            onClick={() => {
              actions.resetSession();
              setPanel("none");
            }}
            className="transition hover:text-zinc-300"
          >
            reiniciar sessão
          </button>
          <span className="hidden @3xl:inline">Ctrl+T nova aba · Ctrl+L endereço · Ctrl+D favorito · Alt+← voltar</span>
        </span>
      </div>
    </div>
  );
}
