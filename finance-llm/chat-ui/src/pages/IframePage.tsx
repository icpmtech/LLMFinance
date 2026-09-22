/**
 * Visualizador genérico de uma página iframe configurada pelo utilizador.
 *
 * Recebe a vista (`iframe:<id>`), resolve a configuração correspondente e
 * mostra o URL num `iframe` a ocupar toda a área da janela.
 */
import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Globe2, Loader2, Plus, ShieldAlert } from "lucide-react";
import { iframeIdFromView, iframePageById, type IframePageConfig } from "../iframePages";

interface IframePageProps {
  view: string;
  onConfigure?: () => void;
}

export default function IframePage({ view, onConfigure }: IframePageProps) {
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  const page = useMemo(() => {
    const id = iframeIdFromView(view);
    if (!id) return undefined;
    return iframePageById(id);
  }, [view]);

  useEffect(() => {
    setLoading(true);
    setErrored(false);
  }, [view, page?.url]);

  if (!page) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8 text-zinc-400">
        <div className="text-center max-w-md space-y-4">
          <Globe2 size={48} className="mx-auto opacity-30" />
          <p className="text-sm">A página iframe solicitada não foi encontrada.</p>
          {onConfigure && (
            <button
              onClick={onConfigure}
              className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md bg-zinc-800 text-zinc-100 hover:bg-zinc-700 transition"
            >
              <Plus size={14} />
              Configurar páginas iframe
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full bg-zinc-950 flex flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-zinc-800/60 bg-zinc-900/40">
        <div className="min-w-0 flex items-center gap-2 text-xs text-zinc-300">
          <Globe2 size={13} className="shrink-0 text-sky-400" />
          <span className="truncate font-medium" title={page.title}>{page.title}</span>
          <span className="truncate text-zinc-500" title={page.url}>— {page.url}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {errored && (
            <div className="hidden sm:flex items-center gap-1.5 text-[10px] text-amber-300 mr-1">
              <ShieldAlert size={11} />
              Pode ter sido recusada por X-Frame-Options/CSP
            </div>
          )}
          <a
            href={page.url}
            target="_blank"
            rel="noreferrer"
            title="Abrir no separador externo"
            className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-100 transition"
          >
            <ExternalLink size={13} />
          </a>
        </div>
      </div>

      <div className="relative flex-1">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-zinc-950/80 text-zinc-400">
            <Loader2 size={24} className="animate-spin" />
          </div>
        )}
        <iframe
          key={view}
          src={page.url}
          title={page.title}
          className="h-full w-full border-0"
          allow="clipboard-write; fullscreen"
          referrerPolicy="strict-origin-when-cross-origin"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
          onLoad={() => setLoading(false)}
          onError={() => {
            setLoading(false);
            setErrored(true);
          }}
        />
      </div>
    </div>
  );
}

export type { IframePageConfig };
