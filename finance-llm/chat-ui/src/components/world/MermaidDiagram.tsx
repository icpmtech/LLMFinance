/**
 * Diagramas Mermaid na página do World Model.
 *
 * O `mermaid` é carregado **a pedido** (`import()` dinâmico): só entra no bundle
 * quando há um diagrama para desenhar, e continua a ser a biblioteca oficial a
 * fazer o *layout* (em vez de se reimplementar um motor de grafos).
 *
 * O código Mermaid fica sempre visível/exportável — é o mesmo texto que vai nos
 * relatórios (Markdown) e pode ser colado em qualquer visualizador Mermaid.
 */
import { useEffect, useRef, useState } from "react";
import { Check, Code2, Copy, Download, Loader2, RotateCw, TriangleAlert } from "lucide-react";
import { isStaleBundleError, reloadOnce } from "../../staleChunk";

let mermaidPromise: Promise<typeof import("mermaid")["default"]> | null = null;

function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid")
      .then((module) => {
        const mermaid = module.default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "dark",
          themeVariables: {
            background: "transparent",
            primaryColor: "#0b1a21",
            primaryTextColor: "#e6f6fb",
            primaryBorderColor: "#38bdf8",
            lineColor: "#64748b",
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
            fontSize: "12px",
          },
          flowchart: { curve: "basis", htmlLabels: true, useMaxWidth: true },
        });
        return mermaid;
      })
      .catch((exc) => {
        // Não guardar uma promessa rejeitada: o próximo diagrama volta a tentar
        // (por exemplo depois de a rede ou o bundle novo estarem disponíveis).
        mermaidPromise = null;
        throw exc;
      });
  }
  return mermaidPromise;
}

let counter = 0;

export function MermaidDiagram({
  code,
  title,
  height = 320,
  compact = false,
}: {
  code: string;
  title?: string;
  height?: number;
  compact?: boolean;
}) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [showSource, setShowSource] = useState(false);
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const idRef = useRef(`mermaid-${(counter += 1)}`);

  useEffect(() => {
    let cancelled = false;
    if (!code?.trim()) {
      setLoading(false);
      setError("Sem diagrama.");
      return () => {
        cancelled = true;
      };
    }
    setLoading(true);
    setError("");
    loadMermaid()
      .then(async (mermaid) => {
        const { svg: rendered } = await mermaid.render(`${idRef.current}-svg`, code);
        if (!cancelled) setSvg(rendered);
      })
      .catch((exc: unknown) => {
        if (cancelled) return;
        const message = exc instanceof Error ? exc.message : String(exc);
        // Bundle antigo (o ficheiro do chunk já não existe): recarregar resolve.
        if (isStaleBundleError(message)) {
          setError("A aplicação foi atualizada — a recarregar para desenhar o diagrama…");
          reloadOnce("mermaid: bundle antigo");
          return;
        }
        setError(message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code, attempt]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* sem permissão de clipboard */
    }
  };

  const download = () => {
    const blob = new Blob([`\`\`\`mermaid\n${code}\n\`\`\`\n`], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(title || "diagrama").replace(/\s+/g, "-").toLowerCase()}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rounded-xl border border-border bg-muted/20">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/70 px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">{title ?? "Diagrama Mermaid"}</span>
        <button type="button" onClick={() => void copy()} className="ml-auto inline-flex items-center gap-1 hover:text-foreground">
          {copied ? <Check size={12} /> : <Copy size={12} />} {copied ? "copiado" : "copiar"}
        </button>
        <button type="button" onClick={download} className="inline-flex items-center gap-1 hover:text-foreground">
          <Download size={12} /> .md
        </button>
        <button type="button" onClick={() => setShowSource((value) => !value)} className="inline-flex items-center gap-1 hover:text-foreground">
          <Code2 size={12} /> {showSource ? "ocultar" : "código"}
        </button>
      </div>
      {loading && (
        <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> a desenhar…
        </div>
      )}
      {!loading && error && (
        <div className="flex flex-wrap items-start gap-2 p-3 text-xs text-amber-300">
          <TriangleAlert size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">Não foi possível desenhar ({error}). O código Mermaid está disponível em «código».</span>
          <button
            type="button"
            onClick={() => {
              setError("");
              setAttempt((value) => value + 1);
            }}
            className="inline-flex items-center gap-1 rounded-lg border border-amber-300/40 px-2 py-0.5 hover:bg-amber-300/10"
          >
            <RotateCw size={11} /> tentar de novo
          </button>
        </div>
      )}
      {!loading && !error && (
        <div
          className="overflow-auto p-2"
          style={{ maxHeight: height, minHeight: compact ? 0 : 120 }}
          // O SVG vem do `mermaid.render` com `securityLevel: "strict"` (sem HTML de origem).
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}
      {showSource && (
        <pre className="max-h-56 overflow-auto border-t border-border/70 p-3 text-[10.5px] leading-relaxed text-muted-foreground">
          {code}
        </pre>
      )}
    </div>
  );
}
