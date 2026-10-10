/**
 * Menu de contexto (botão direito) reutilizável no módulo Benchmark.
 *
 * Abre junto do cursor, fecha com `Esc`, com um clique fora ou ao rolar, e
 * nunca sai do contentor onde foi pedido (é limitado ao tamanho visível).
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

export type ContextMenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  hint?: string;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

export type ContextMenuState = { x: number; y: number; title?: string; subtitle?: string; items: ContextMenuItem[] } | null;

/** Gancho que trata de abrir/fechar o menu e de o posicionar dentro do contentor. */
export function useContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState>(null);

  const abrir = useCallback(
    (
      evento: { clientX: number; clientY: number; currentTarget: Element; preventDefault: () => void },
      conteudo: { title?: string; subtitle?: string; items: ContextMenuItem[] },
    ) => {
      evento.preventDefault();
      const caixa = (evento.currentTarget as HTMLElement).closest("[data-context-scope]") as HTMLElement | null;
      const limites = (caixa ?? document.documentElement).getBoundingClientRect();
      setMenu({
        x: evento.clientX - limites.left,
        y: evento.clientY - limites.top,
        title: conteudo.title,
        subtitle: conteudo.subtitle,
        items: conteudo.items,
      });
    },
    [],
  );

  useEffect(() => {
    if (!menu) return;
    const fechar = () => setMenu(null);
    const tecla = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") setMenu(null);
    };
    window.addEventListener("click", fechar);
    window.addEventListener("scroll", fechar, true);
    window.addEventListener("keydown", tecla);
    return () => {
      window.removeEventListener("click", fechar);
      window.removeEventListener("scroll", fechar, true);
      window.removeEventListener("keydown", tecla);
    };
  }, [menu]);

  return { menu, abrir, fechar: () => setMenu(null) };
}

export function ContextMenu({ menu }: { menu: ContextMenuState }) {
  if (!menu) return null;
  const largura = 300;
  const altura = 60 + menu.items.length * 34;
  return (
    <div
      role="menu"
      className="absolute z-50 min-w-[264px] max-w-[300px] rounded-2xl border border-white/10 bg-[#07151b]/95 p-1 shadow-2xl backdrop-blur-xl"
      style={{ left: Math.max(8, menu.x), top: Math.max(8, menu.y), width: largura, maxHeight: altura }}
      onClick={(event) => event.stopPropagation()}
    >
      {menu.title ? (
        <>
          <div className="px-2 py-1.5">
            <p className="truncate text-xs font-medium">{menu.title}</p>
            {menu.subtitle ? <p className="mt-0.5 text-[10px] text-muted-foreground">{menu.subtitle}</p> : null}
          </div>
          <div className="my-1 h-px bg-white/10" />
        </>
      ) : null}
      {menu.items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          onClick={item.onSelect}
          className={`flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-xs transition disabled:opacity-40 ${
            item.danger ? "text-rose-300 hover:bg-rose-500/10" : "hover:bg-white/10"
          }`}
        >
          {item.icon ? <span className="shrink-0">{item.icon}</span> : null}
          <span className="min-w-0 flex-1 truncate">{item.label}</span>
          {item.hint ? <span className="shrink-0 text-[10px] text-muted-foreground">{item.hint}</span> : null}
        </button>
      ))}
    </div>
  );
}
