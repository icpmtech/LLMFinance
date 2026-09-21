/**
 * Editor de medidas calculadas do Visualizador.
 *
 * As fórmulas usam os nomes das medidas entre parênteses retos — `[Soma de Preço
 * contratual] / [Contagem]` — e `[@Nome]` para o total do conjunto filtrado
 * (útil para «% do total»). São avaliadas no backend sobre cada linha do
 * resultado, com uma lista branca de operações.
 */
import { useMemo } from "react";
import { Calculator, Plus, Trash2, TriangleAlert } from "lucide-react";
import type { VisualFormula } from "../../visualizadorApi";

const FORMATS = [
  { id: "number", label: "Número" },
  { id: "integer", label: "Inteiro" },
  { id: "currency", label: "Moeda (€)" },
  { id: "percent", label: "Percentagem" },
];

export function FormulaEditor({
  formulas,
  names,
  max = 12,
  onChange,
}: {
  formulas: VisualFormula[];
  /** Medidas disponíveis (rótulos), para as sugestões de escrita. */
  names: string[];
  max?: number;
  onChange: (formulas: VisualFormula[]) => void;
}) {
  const problems = useMemo(() => {
    const known = new Set(names.map((name) => normalize(name)));
    return formulas.map((formula) => {
      const used = [...formula.expression.matchAll(/\[@?([^[\]]{1,80})\]/g)].map((match) => match[1].trim());
      if (used.length === 0) return "Escreva a fórmula com medidas entre parênteses retos, por exemplo [Contagem] * 2.";
      const unknown = used.filter((name) => !known.has(normalize(name)) && !known.has(normalize(name.replace(/^total /i, ""))));
      if (unknown.length > 0) return `Medida desconhecida: ${unknown.join(", ")}.`;
      return null;
    });
  }, [formulas, names]);

  const update = (index: number, patch: Partial<VisualFormula>) => {
    onChange(formulas.map((formula, position) => (position === index ? { ...formula, ...patch } : formula)));
  };

  const add = () => {
    if (formulas.length >= max) return;
    onChange([
      ...formulas,
      { id: `f${Date.now().toString(36)}`, label: `Medida ${formulas.length + 1}`, expression: names[0] ? `[${names[0]}]` : "", format: "number" },
    ]);
  };

  return (
    <div className="space-y-2">
      {formulas.map((formula, index) => (
        <div key={formula.id} className="rounded-xl border border-border/60 bg-background/40 p-2 space-y-1.5">
          <div className="flex items-center gap-2">
            <input
              value={formula.label}
              onChange={(event) => update(index, { label: event.target.value })}
              placeholder="Nome da medida"
              aria-label="Nome da medida calculada"
              className="flex-1 min-w-0 px-2 py-1 rounded-lg glass-card text-xs"
            />
            <select
              value={formula.format || "number"}
              onChange={(event) => update(index, { format: event.target.value })}
              aria-label="Formato da medida"
              className="px-2 py-1 rounded-lg glass-card text-xs"
            >
              {FORMATS.map((format) => (
                <option key={format.id} value={format.id}>{format.label}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => onChange(formulas.filter((_, position) => position !== index))}
              className="p-1.5 rounded-lg glass-card text-muted-foreground hover:text-rose-300"
              aria-label={`Remover a medida ${formula.label}`}
              title="Remover"
            >
              <Trash2 size={13} />
            </button>
          </div>
          <input
            value={formula.expression}
            onChange={(event) => update(index, { expression: event.target.value })}
            placeholder="[Soma de Preço contratual] / [Contagem]"
            aria-label="Fórmula"
            className="w-full px-2 py-1 rounded-lg glass-card text-xs font-mono"
          />
          {problems[index] && (
            <p className="text-[11px] text-amber-300 flex items-center gap-1">
              <TriangleAlert size={11} /> {problems[index]}
            </p>
          )}
        </div>
      ))}
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={add}
          disabled={formulas.length >= max}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass-card text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
        >
          <Plus size={12} /> Medida calculada
        </button>
        <span className="text-[10px] text-muted-foreground flex items-center gap-1">
          <Calculator size={11} /> <code className="font-mono">[medida]</code> · <code className="font-mono">[@medida]</code> = total
        </span>
      </div>
      {names.length > 0 && (
        <p className="text-[10px] text-muted-foreground leading-relaxed">
          Disponíveis: {names.slice(0, 8).join(" · ")}{names.length > 8 ? ` … (+${names.length - 8})` : ""}
        </p>
      )}
    </div>
  );
}

export function normalize(value: string): string {
  return (value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}
