/**
 * Editor de Markdown do Office IQ OS.
 *
 * Uma área de escrita (com tabulação por Tab), uma barra de ferramentas que
 * aplica as marcas no texto selecionado e três modos de vista: **escrever**,
 * **dividido** (escrita + leitura em direto) e **ler**. O ícone de estatística
 * mostra palavras, caracteres e linhas — útil para relatórios com limite.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Bold,
  Code2,
  Eye,
  Heading1,
  Heading2,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  PencilLine,
  Quote,
  Table2,
  Columns2,
} from "lucide-react";
import { MarkdownView } from "./MarkdownView";

export type EditorMode = "write" | "split" | "read";

const TOOLS: { id: string; label: string; icon: React.ReactNode; before: string; after: string; prefix?: boolean; block?: string }[] = [
  { id: "h1", label: "Título 1", icon: <Heading1 size={14} />, before: "# ", after: "", prefix: true },
  { id: "h2", label: "Título 2", icon: <Heading2 size={14} />, before: "## ", after: "", prefix: true },
  { id: "bold", label: "Negrito", icon: <Bold size={14} />, before: "**", after: "**" },
  { id: "italic", label: "Itálico", icon: <Italic size={14} />, before: "*", after: "*" },
  { id: "list", label: "Lista", icon: <List size={14} />, before: "- ", after: "", prefix: true },
  { id: "ordered", label: "Lista numerada", icon: <ListOrdered size={14} />, before: "1. ", after: "", prefix: true },
  { id: "quote", label: "Citação", icon: <Quote size={14} />, before: "> ", after: "", prefix: true },
  { id: "code", label: "Código", icon: <Code2 size={14} />, before: "```\n", after: "\n```" },
  { id: "link", label: "Ligação", icon: <Link2 size={14} />, before: "[", after: "](https://)" },
  { id: "table", label: "Tabela", icon: <Table2 size={14} />, before: "", after: "", block: "| Coluna | Coluna |\n| --- | --- |\n|  |  |\n" },
  { id: "hr", label: "Separador", icon: <Minus size={14} />, before: "", after: "", block: "\n---\n" },
];

export function MarkdownEditor({
  value,
  onChange,
  mode,
  onModeChange,
  placeholder = "Comece a escrever…",
  readOnly = false,
  heightClass = "h-[calc(100vh-360px)] min-h-[420px]",
}: {
  value: string;
  onChange: (next: string) => void;
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  placeholder?: string;
  readOnly?: boolean;
  heightClass?: string;
}) {
  const areaRef = useRef<HTMLTextAreaElement | null>(null);

  const stats = useMemo(() => {
    const words = value.split(/\s+/).filter((word) => word.trim()).length;
    const lines = value ? value.split("\n").length : 0;
    const characters = value.length;
    // Tempo de leitura a ~200 palavras por minuto.
    const minutes = Math.max(1, Math.round(words / 200));
    return { words, lines, characters, minutes };
  }, [value]);

  const apply = useCallback(
    (tool: (typeof TOOLS)[number]) => {
      const area = areaRef.current;
      if (!area) return;
      const start = area.selectionStart;
      const end = area.selectionEnd;
      const selected = value.slice(start, end);
      let next: string;
      let caret = start;
      if (tool.block) {
        next = `${value.slice(0, start)}${value.slice(start, end)}${tool.block}${value.slice(end)}`;
        caret = end + tool.block.length;
      } else if (tool.prefix) {
        // Aplica a marca no início de cada linha selecionada.
        const lineStart = value.lastIndexOf("\n", start - 1) + 1;
        const lineEnd = value.indexOf("\n", end) === -1 ? value.length : value.indexOf("\n", end);
        const chunk = value.slice(lineStart, lineEnd) || selected || "texto";
        const prefixed = chunk
          .split("\n")
          .map((line) => `${tool.before}${line}`)
          .join("\n");
        next = `${value.slice(0, lineStart)}${prefixed}${value.slice(lineEnd)}`;
        caret = lineStart + prefixed.length;
      } else {
        const content = selected || "texto";
        next = `${value.slice(0, start)}${tool.before}${content}${tool.after}${value.slice(end)}`;
        caret = start + tool.before.length + content.length + tool.after.length;
      }
      onChange(next);
      window.requestAnimationFrame(() => {
        area.focus();
        area.setSelectionRange(caret, caret);
      });
    },
    [onChange, value],
  );

  /* Tab escreve uma tabulação em vez de mudar de campo. */
  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      event.preventDefault();
      const start = area.selectionStart;
      const end = area.selectionEnd;
      const next = `${value.slice(0, start)}  ${value.slice(end)}`;
      onChange(next);
      window.requestAnimationFrame(() => area.setSelectionRange(start + 2, start + 2));
    };
    const onSave = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      area.dispatchEvent(new CustomEvent("office-save", { bubbles: true }));
    };
    area.addEventListener("keydown", onKeyDown);
    area.addEventListener("keydown", onSave);
    return () => {
      area.removeEventListener("keydown", onKeyDown);
      area.removeEventListener("keydown", onSave);
    };
  }, [onChange, value]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-1.5">
        <div className="flex flex-wrap items-center gap-0.5 rounded-xl border border-white/10 bg-white/5 p-0.5">
          {TOOLS.map((tool) => (
            <button
              key={tool.id}
              type="button"
              onClick={() => apply(tool)}
              disabled={readOnly}
              title={tool.label}
              className="grid h-7 w-7 place-items-center rounded-lg text-slate-300 transition hover:bg-white/10 hover:text-foreground disabled:opacity-40"
            >
              {tool.icon}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-0.5 rounded-xl border border-white/10 bg-white/5 p-0.5">
          {(
            [
              ["write", "Escrever", <PencilLine size={13} key="w" />],
              ["split", "Dividido", <Columns2 size={13} key="s" />],
              ["read", "Ler", <Eye size={13} key="r" />],
            ] as const
          ).map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => onModeChange(id)}
              title={label}
              aria-pressed={mode === id}
              className={[
                "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] transition",
                mode === id ? "bg-white/10 text-foreground" : "text-muted-foreground hover:bg-white/5",
              ].join(" ")}
            >
              {icon} {label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[10.5px] text-muted-foreground">
          {stats.words} palavras · {stats.characters} caracteres · {stats.lines} linhas · ~{stats.minutes} min de leitura
        </span>
      </div>

      <div className={["mt-2 grid min-h-0 flex-1 gap-3", mode === "split" ? "lg:grid-cols-2" : "grid-cols-1"].join(" ")}>
        {mode !== "read" ? (
          <textarea
            ref={areaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            spellCheck
            className={`w-full resize-none rounded-2xl border border-white/10 bg-[#08131c] p-4 font-mono text-[13px] leading-relaxed text-slate-100 outline-none transition placeholder:text-muted-foreground focus:border-sky-300/40 ${heightClass}`}
          />
        ) : null}
        {mode !== "write" ? (
          <div className={`overflow-auto rounded-2xl border border-white/10 bg-white/[0.02] p-4 ${heightClass}`}>
            {value.trim() ? (
              <MarkdownView markdown={value} compact={mode === "split"} />
            ) : (
              <p className="text-[12.5px] text-muted-foreground">Sem conteúdo para ler.</p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
