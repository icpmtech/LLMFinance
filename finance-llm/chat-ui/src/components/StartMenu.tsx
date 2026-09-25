/**
 * Menu Iniciar (aspeto Windows 11).
 *
 * Painel **flutuante** por cima do ambiente de trabalho, encostado ao botão
 * Iniciar da barra de tarefas — não é a barra lateral: aparece e desaparece
 * sem mexer na disposição da plataforma. Tem a disposição do menu Iniciar do
 * Windows 11: pesquisa arredondada, **Afixadas** (grelha das aplicações do
 * dock), **Recomendadas** (vistas recentes) e **Todas** — em cartões de
 * categoria ou em lista — com o rodapé da conta e o botão de energia.
 *
 * Fecha com `Esc`, com um clique fora ou com o próprio botão Iniciar.
 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ChevronDown, Power, Search, X } from "lucide-react";
import { useDock } from "../dock";
import { useAuth } from "../auth";
import { useSidebarAccess } from "../sidebarAccess";
import { recordRecentView, useRecentViews } from "../layout";
import { Avatar } from "../pages/SettingsPage";
import { groupsFor, isActive, itemsFor, normalize, type AppView, type NavItem } from "./AppNav";
import { getIframeRevision, subscribeIframePages } from "../iframePages";

interface StartMenuProps {
  /** Vista ativa (para marcar o item «Aberto agora»). */
  active: string;
  onClose: () => void;
  /** Abre (ou foca) uma aplicação. */
  onOpenView: (id: string) => void;
}

export function StartMenu({ active, onClose, onOpenView }: StartMenuProps) {
  const { user, logout } = useAuth();
  const { visible: dockApps } = useDock();
  const recent = useRecentViews();

  const [query, setQuery] = useState("");
  const [viewMode, setViewMode] = useState<"categoria" | "lista">("categoria");
  const [viewMenuOpen, setViewMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [pinnedAll, setPinnedAll] = useState(false);
  const [recentAll, setRecentAll] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);

  /* Páginas iframe configuráveis: o menu volta a construir-se quando mudam. */
  const iframeRevision = useSyncExternalStore(subscribeIframePages, getIframeRevision, getIframeRevision);
  /* Módulos escondidos por perfil: o menu volta a construir-se quando a matriz muda. */
  const sidebarAccess = useSidebarAccess();

  const context = useMemo(
    () => {
      // `iframeRevision`/`sidebarAccess` no corpo forçam a reconstrução do menu
      // quando as páginas iframe ou os acessos por perfil mudam.
      void iframeRevision;
      void sidebarAccess;
      return { items: itemsFor(user?.role), groups: groupsFor(user?.role) };
    },
    [user?.role, iframeRevision, sidebarAccess],
  );

  /** Afixadas: as aplicações do dock, na ordem do dock. */
  const pinned = pinnedAll ? dockApps : dockApps.slice(0, 8);

  /** Recomendadas: as vistas recentes, resolvidas para os itens do menu. */
  const recentItems = useMemo(() => {
    const limit = recentAll ? 8 : 4;
    return recent
      .map((id) => context.items.find(({ item }) => item.id === id)?.item)
      .filter((item): item is NavItem => Boolean(item))
      .slice(0, limit);
  }, [context.items, recent, recentAll]);

  const totalRecent = useMemo(
    () =>
      recent
        .map((id) => context.items.find(({ item }) => item.id === id)?.item)
        .filter((item): item is NavItem => Boolean(item)).length,
    [context.items, recent],
  );

  const results = useMemo(() => {
    const term = normalize(query.trim());
    if (!term) return [];
    return context.items
      .filter(({ item, group }) =>
        `${normalize(item.label)} ${normalize(group.label)} ${normalize(item.keywords ?? "")}`.includes(term),
      )
      .slice(0, 10);
  }, [context.items, query]);

  const openView = (id: AppView) => {
    recordRecentView(id);
    onOpenView(id);
    onClose();
  };

  /* Ao abrir: limpar o estado, focar a pesquisa e ouvir o `Esc`. */
  useEffect(() => {
    const term = window.setTimeout(() => searchRef.current?.focus(), 40);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      // `/` ou Ctrl+K focam esta pesquisa (e não a da barra lateral).
      if (event.key === "/" || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k")) {
        event.preventDefault();
        event.stopPropagation();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => {
      window.clearTimeout(term);
      window.removeEventListener("keydown", onKeyDown, { capture: true });
    };
  }, [onClose]);

  return (
    <div className="start-panel">
      {/* Pesquisa */}
      <div className="shrink-0 px-3 pb-1.5 pt-3" role="search">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/75" />
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setQuery("");
                event.currentTarget.blur();
              }
              if (event.key === "Enter" && results.length > 0) {
                openView(results[0].item.id);
              }
            }}
            placeholder="Pesquisar aplicações, definições e documentos"
            aria-label="Pesquisar aplicações, definições e documentos"
            className="start-search h-9 w-full rounded-full border border-white/10 bg-white/[0.06] pl-8 pr-8 text-[12.5px] outline-none transition placeholder:text-muted-foreground/75 focus:border-white/20 focus:bg-white/[0.08]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Limpar pesquisa"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition hover:text-foreground"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="start-scroll flex-1 overflow-y-auto px-3 pb-2">
        {query.trim() ? (
          <div className="space-y-0.5 pt-1">
            {results.length === 0 && (
              <p className="px-1 py-6 text-center text-[12px] text-muted-foreground">Sem resultados para «{query.trim()}».</p>
            )}
            {results.map(({ item, group }) => (
              <button
                key={`start-result-${item.id}`}
                type="button"
                onClick={() => openView(item.id)}
                className="start-row focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
              >
                <span className="start-row-icon">{item.icon}</span>
                <span className="min-w-0 flex-1 text-left leading-tight">
                  <span className="block truncate text-[12.5px] text-white/90">{item.label}</span>
                  <span className="block truncate text-[10.5px] text-muted-foreground">{group.label}</span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <>
            {/* Afixadas */}
            <div className="flex items-center justify-between px-1 pb-1 pt-2">
              <span className="start-heading">Afixadas</span>
              {dockApps.length > 8 && (
                <button type="button" onClick={() => setPinnedAll((value) => !value)} className="start-link">
                  {pinnedAll ? "Ver menos" : "Ver tudo"}
                </button>
              )}
            </div>
            <div className="grid grid-cols-4 gap-x-1 gap-y-0.5">
              {pinned.map((app) => {
                const Icon = app.icon;
                return (
                  <button
                    key={`start-pinned-${app.id}`}
                    type="button"
                    onClick={() => openView(app.id as AppView)}
                    title={app.hint}
                    className="start-tile focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                  >
                    <span
                      className={`grid h-9 w-9 shrink-0 place-items-center rounded-[8px] bg-gradient-to-br ${app.gradient} text-white shadow-sm shadow-black/30`}
                    >
                      <Icon size={17} />
                    </span>
                    <span className="w-full truncate text-center text-[10.5px] leading-tight text-white/85">
                      {app.label}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Recomendadas */}
            {recentItems.length > 0 && (
              <>
                <div className="flex items-center justify-between px-1 pb-1 pt-3">
                  <span className="start-heading">Recomendadas</span>
                  {totalRecent > 4 && (
                    <button type="button" onClick={() => setRecentAll((value) => !value)} className="start-link">
                      {recentAll ? "Ver menos" : "Ver tudo"}
                    </button>
                  )}
                </div>
                <div className="space-y-0.5">
                  {recentItems.map((item) => (
                    <button
                      key={`start-recent-${item.id}`}
                      type="button"
                      onClick={() => openView(item.id)}
                      title={item.label}
                      className="start-row focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                    >
                      <span className="start-row-icon">{item.icon}</span>
                      <span className="min-w-0 flex-1 text-left leading-tight">
                        <span className="block truncate text-[12.5px] text-white/90">{item.label}</span>
                        <span className="block truncate text-[10.5px] text-muted-foreground">
                          {isActive(active as AppView, item) ? "Aberto agora" : "Recentemente"}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}

            {/* Todas */}
            <div className="flex items-center justify-between px-1 pb-1 pt-3">
              <span className="start-heading">Todas</span>
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setViewMenuOpen((open) => !open)}
                  aria-haspopup="menu"
                  aria-expanded={viewMenuOpen}
                  className="start-link inline-flex items-center gap-1"
                >
                  Ver: {viewMode === "categoria" ? "categoria" : "lista"}
                  <ChevronDown size={12} className={viewMenuOpen ? "rotate-180 transition" : "transition"} />
                </button>
                {viewMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-[70]" onMouseDown={() => setViewMenuOpen(false)} aria-hidden="true" />
                    <div className="start-menu absolute right-0 top-full z-[71] mt-1 w-36 p-1" role="menu" aria-label="Ver">
                      {([
                        { value: "categoria", label: "Categoria" },
                        { value: "lista", label: "Lista" },
                      ] as const).map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          role="menuitemradio"
                          aria-checked={viewMode === option.value}
                          onClick={() => {
                            setViewMode(option.value);
                            setViewMenuOpen(false);
                          }}
                          className="start-menu-item"
                        >
                          <span className={viewMode === option.value ? "text-white" : "text-transparent"}>●</span>
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            {viewMode === "categoria" ? (
              <div className="grid grid-cols-2 gap-2 pt-0.5">
                {context.groups.map((group) => (
                  <div key={`start-group-${group.id}`} className="start-card">
                    <div className="flex flex-wrap gap-1">
                      {group.items.slice(0, 4).map((item) => (
                        <button
                          key={`start-card-${group.id}-${item.id}`}
                          type="button"
                          onClick={() => openView(item.id)}
                          title={item.label}
                          aria-label={item.label}
                          className="start-mini focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                        >
                          {item.icon}
                        </button>
                      ))}
                    </div>
                    <p className="mt-1.5 truncate text-[11px] text-white/85" title={group.label}>
                      {group.label}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-1 pt-0.5">
                {context.groups.map((group) => (
                  <div key={`start-list-${group.id}`} className="space-y-0.5 pb-1">
                    <p className="start-list-title">{group.label}</p>
                    {group.items.map((item) => (
                      <button
                        key={`start-list-${group.id}-${item.id}`}
                        type="button"
                        onClick={() => openView(item.id)}
                        className="start-row focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                      >
                        <span className="start-row-icon">{item.icon}</span>
                        <span className="min-w-0 flex-1 truncate text-left text-[12.5px] text-white/90">
                          {item.label}
                        </span>
                        {isActive(active as AppView, item) && (
                          <span className="shrink-0 text-[10.5px] text-muted-foreground">Aberto agora</span>
                        )}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Rodapé: conta + energia (como o menu Iniciar do Windows) */}
      <div className="start-footer relative flex shrink-0 items-center gap-1 px-3 py-2">
        <button
          type="button"
          onClick={() => setUserMenuOpen((open) => !open)}
          aria-haspopup="menu"
          aria-expanded={userMenuOpen}
          className="start-account flex min-w-0 flex-1 items-center gap-2 px-1.5 py-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          {user ? <Avatar user={user} size={26} /> : null}
          <span className="block min-w-0 flex-1 truncate text-[12.5px] font-medium text-white/90">
            {user?.name ?? "Conta"}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setUserMenuOpen((open) => !open)}
          aria-label="Energia e sessão"
          title="Energia e sessão"
          className="start-power grid h-8 w-8 shrink-0 place-items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <Power size={15} />
        </button>

        {userMenuOpen && (
          <>
            <div className="fixed inset-0 z-[70]" onMouseDown={() => setUserMenuOpen(false)} aria-hidden="true" />
            <div
              role="menu"
              aria-label="Conta"
              className="start-menu absolute bottom-full left-2 right-2 z-[71] mb-2 p-1"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setUserMenuOpen(false);
                  openView("settings" as AppView);
                }}
                className="start-menu-item"
              >
                <span className="w-3 text-center text-transparent">●</span> Definições da conta
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setUserMenuOpen(false);
                  onClose();
                  void logout();
                }}
                className="start-menu-item text-rose-300"
              >
                <span className="w-3 text-center text-transparent">●</span> Terminar sessão
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
