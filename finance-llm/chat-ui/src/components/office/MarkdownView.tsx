/**
 * Leitura de Markdown com a tipografia do IQ OS.
 *
 * Usa `react-markdown` + `remark-gfm` (já usados no chat), com estilos próprios
 * para leitura longa: títulos hierárquicos, tabelas, código, citações e ligações
 * que abrem no **Browser interno** em vez de saltarem para o browser do sistema.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownView({
  markdown,
  onOpenLink,
  compact = false,
}: {
  markdown: string;
  onOpenLink?: (url: string) => void;
  compact?: boolean;
}) {
  const handleLink = (url: string) => {
    // O Office não depende de outra aplicação: as ligações abrem no browser do sistema.
    if (onOpenLink) onOpenLink(url);
    else window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className={`office-prose ${compact ? "office-prose--compact" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mt-6 mb-3 text-2xl font-semibold tracking-tight text-foreground first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-6 mb-2 border-b border-white/10 pb-1 text-lg font-semibold text-foreground">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-5 mb-2 text-[15px] font-semibold text-foreground">{children}</h3>,
          h4: ({ children }) => <h4 className="mt-4 mb-1.5 text-[13.5px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h4>,
          p: ({ children }) => <p className="my-2.5 text-[13.5px] leading-relaxed text-slate-200/95">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic text-slate-200">{children}</em>,
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 text-[13.5px] text-slate-200/95">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 text-[13.5px] text-slate-200/95">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              onClick={(event) => {
                if (!href) return;
                event.preventDefault();
                handleLink(String(href));
              }}
              title="Abrir a ligação"
              className="text-sky-300 underline decoration-sky-400/40 underline-offset-2 transition hover:text-sky-200"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) => {
            const inline = !className;
            if (inline) return <code className="rounded bg-white/10 px-1 py-0.5 font-mono text-[12px] text-sky-100">{children}</code>;
            return (
              <code className="block overflow-x-auto rounded-xl border border-white/10 bg-[#08131c] p-3 font-mono text-[12px] leading-relaxed text-slate-200">
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="my-3 overflow-x-auto rounded-xl border border-white/10 bg-[#08131c] p-3">{children}</pre>,
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l-2 border-sky-400/50 bg-white/[0.03] px-3 py-1.5 text-[13px] italic text-slate-300">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full border-collapse text-[12.5px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5 text-left text-[11px] uppercase tracking-wide text-muted-foreground">{children}</thead>,
          th: ({ children }) => <th className="border-b border-white/10 px-3 py-2 font-medium">{children}</th>,
          td: ({ children }) => <td className="border-b border-white/5 px-3 py-2 align-top text-slate-200/95">{children}</td>,
          hr: () => <hr className="my-5 border-white/10" />,
          img: ({ src, alt }) => <img src={src} alt={alt ?? ""} className="my-3 max-w-full rounded-xl border border-white/10" />,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
