/**
 * Seletoras partilhadas pelo módulo **Benchmark**: entidade do sistema (uma ou
 * várias, até `MAX_COMPARE`) e código CPV.
 *
 * Vivem aqui para a análise de uma empresa e a comparação de várias usarem os
 * mesmos controlos (autocomplete com `AbortController`-like guardas para não
 * aceitar respostas fora de ordem).
 */
import { useEffect, useRef, useState } from "react";
import { Building2, Loader2, Search, X } from "lucide-react";

import { searchCompanies } from "../../api";
import { getBenchmarkCpv, type BenchmarkCpv } from "../../benchmarkApi";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";
import type { CompanySummary } from "../../types";

interface EmpresaAutocompleteProps {
  /** Empresa escolhida (quando existe, o campo mostra o nome dela). */
  value?: CompanySummary | null;
  onSelect: (empresa: CompanySummary) => void;
  onClear?: () => void;
  label?: string;
  placeholder?: string;
  /** Limpa o texto depois de escolher (modo «adicionar à lista»). */
  limparAposEscolher?: boolean;
  /** Sugestões por baixo do campo (modo «uma empresa») ou por cima (lista). */
  id?: string;
}

/** Campo de pesquisa de empresas do sistema (`/companies/search`). */
export function EmpresaAutocomplete({
  value,
  onSelect,
  onClear,
  label = "Entidade do sistema",
  placeholder = "Nome ou NIF da empresa…",
  limparAposEscolher = false,
  id,
}: EmpresaAutocompleteProps) {
  const [texto, setTexto] = useState(value?.name ?? "");
  const [sugestoes, setSugestoes] = useState<CompanySummary[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const anterior = useRef<CompanySummary | null>(null);

  // O valor externo manda: escolher preenche o campo; limpar fora daqui
  // esvazia-o (sem tocar no que o utilizador está a escrever).
  useEffect(() => {
    if (value) setTexto(value.name);
    else if (anterior.current) setTexto("");
    anterior.current = value ?? null;
  }, [value]);

  useEffect(() => {
    const termo = texto.trim();
    if (value) {
      setSugestoes([]);
      return;
    }
    if (termo.length < 2) {
      setSugestoes([]);
      return;
    }
    let ativo = true;
    const timer = setTimeout(() => {
      setAProcurar(true);
      searchCompanies({ q: termo, size: 8 })
        .then((resposta) => {
          if (ativo) setSugestoes(resposta.items ?? []);
        })
        .catch(() => {
          if (ativo) setSugestoes([]);
        })
        .finally(() => {
          if (ativo) setAProcurar(false);
        });
    }, 250);
    return () => {
      ativo = false;
      clearTimeout(timer);
    };
  }, [texto, value]);

  return (
    <div className="relative">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative mt-1">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          autoComplete="off"
          className="pl-9"
          placeholder={placeholder}
          value={texto}
          onChange={(e) => {
            setTexto(e.target.value);
            if (onClear) onClear();
          }}
        />
        {aProcurar ? (
          <Loader2 size={15} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : texto ? (
          <button
            type="button"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => {
              setTexto("");
              onClear?.();
            }}
            aria-label="Limpar"
          >
            <X size={15} />
          </button>
        ) : null}
      </div>
      {sugestoes.length > 0 ? (
        <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-border bg-background shadow-xl">
          {sugestoes.map((empresa) => (
            <button
              key={`${empresa.nif}-${empresa.name}`}
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
              onClick={() => {
                onSelect(empresa);
                setSugestoes([]);
                if (limparAposEscolher) setTexto("");
                else setTexto(empresa.name);
              }}
            >
              <Building2 size={14} className="shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{empresa.name}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {empresa.nif ? `${empresa.nif} · ` : ""}
                {empresa.contracts_total.toLocaleString("pt-PT")} contr.
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

interface CpvAutocompleteProps {
  value: string;
  onChange: (codigo: string) => void;
  label?: string;
  placeholder?: string;
  id?: string;
}

/** Campo de pesquisa de CPV (sugestões com descrição e volume). */
export function CpvAutocomplete({
  value,
  onChange,
  label = "CPV do segmento (opcional)",
  placeholder = "ex.: 90511000 ou 90511",
  id,
}: CpvAutocompleteProps) {
  const [texto, setTexto] = useState("");
  const [opcoes, setOpcoes] = useState<BenchmarkCpv[]>([]);

  useEffect(() => {
    const termo = texto.trim();
    if (termo.length < 2) {
      setOpcoes([]);
      return;
    }
    let ativo = true;
    const timer = setTimeout(() => {
      getBenchmarkCpv(termo, 10)
        .then((resposta) => {
          if (ativo) setOpcoes(resposta.items ?? []);
        })
        .catch(() => {
          if (ativo) setOpcoes([]);
        });
    }, 250);
    return () => {
      ativo = false;
      clearTimeout(timer);
    };
  }, [texto]);

  return (
    <div className="relative">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative mt-1">
        <Input
          id={id}
          autoComplete="off"
          placeholder={placeholder}
          value={value || texto}
          onChange={(e) => {
            onChange("");
            setTexto(e.target.value);
          }}
        />
        {value ? (
          <button
            type="button"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => {
              onChange("");
              setTexto("");
            }}
            aria-label="Limpar CPV"
          >
            <X size={15} />
          </button>
        ) : null}
      </div>
      {opcoes.length > 0 && texto.trim().length >= 2 ? (
        <div className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-border bg-background shadow-xl">
          {opcoes.map((opcao) => (
            <button
              key={opcao.code}
              type="button"
              className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm hover:bg-accent"
              onClick={() => {
                onChange(opcao.code);
                setTexto("");
                setOpcoes([]);
              }}
            >
              <span className="font-medium">{opcao.code}</span>
              <span className="line-clamp-2 text-xs text-muted-foreground">{opcao.description || "—"}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Seletor de ano (usado na janela do segmento). */
export function SeletorAno({
  id,
  label,
  anos,
  value,
  onChange,
}: {
  id: string;
  label: string;
  anos: number[];
  value: number | "";
  onChange: (ano: number | "") => void;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
      >
        <option value="">Todos</option>
        {anos.map((ano) => (
          <option key={ano} value={ano}>
            {ano}
          </option>
        ))}
      </select>
    </div>
  );
}
