/**
 * Seletoras partilhadas pelo módulo **Benchmark**: entidade do sistema (uma ou
 * várias, até `MAX_COMPARE`), código CPV e ano.
 *
 * A pesquisa de entidades é **por país**: Portugal usa o diretório
 * `/companies/search`; Espanha os órgãos adjudicantes/empresas adjudicatárias de
 * `/contracts-es/entities`; França os acheteurs/titulaires de
 * `/contracts-fr/entities`. O papel escolhido decide que lado do mercado se
 * procura (quem compra ou quem vende).
 */
import { useEffect, useRef, useState } from "react";
import { Building2, Loader2, Search, X } from "lucide-react";

import { getBenchmarkCpv, searchBenchmarkEntities } from "../../benchmarkApi";
import type { BenchmarkCpv, BenchmarkCountry, BenchmarkRole } from "../../benchmarkApi";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";

/** Entidade escolhida no seletor (forma comum aos três países). */
export type EmpresaBenchmark = {
  /** NIF (PT), NIF/DIR3 (ES) ou SIRET (FR). */
  nif: string;
  name: string;
  contracts: number;
  total_value?: number | null;
};

interface EmpresaAutocompleteProps {
  country: BenchmarkCountry;
  role: BenchmarkRole;
  /** Empresa escolhida (quando existe, o campo mostra o nome dela). */
  value?: EmpresaBenchmark | null;
  onSelect: (empresa: EmpresaBenchmark) => void;
  onClear?: () => void;
  label?: string;
  placeholder?: string;
  /** Limpa o texto depois de escolher (modo «adicionar à lista»). */
  limparAposEscolher?: boolean;
  id?: string;
}

/** Campo de pesquisa de entidades do país, no papel escolhido. */
export function EmpresaAutocomplete({
  country,
  role,
  value,
  onSelect,
  onClear,
  label = "Entidade do sistema",
  placeholder = "Nome, NIF ou SIRET…",
  limparAposEscolher = false,
  id,
}: EmpresaAutocompleteProps) {
  const [texto, setTexto] = useState(value?.name ?? "");
  const [sugestoes, setSugestoes] = useState<EmpresaBenchmark[]>([]);
  const [aProcurar, setAProcurar] = useState(false);
  const anterior = useRef<EmpresaBenchmark | null>(null);

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
      searchBenchmarkEntities(country, role, termo, 8)
        .then((itens) => {
          if (ativo) setSugestoes(itens.filter((item) => item.name));
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
  }, [texto, value, country, role]);

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
                {empresa.nif && empresa.nif !== empresa.name ? `${empresa.nif} · ` : ""}
                {empresa.contracts.toLocaleString("pt-PT")} contr.
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
  country: BenchmarkCountry;
  label?: string;
  placeholder?: string;
  id?: string;
}

/** Campo de pesquisa de CPV do país (sugestões com descrição e volume). */
export function CpvAutocomplete({
  value,
  onChange,
  country,
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
      getBenchmarkCpv(termo, 10, country)
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
  }, [texto, country]);

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
              <span className="line-clamp-2 text-xs text-muted-foreground">
                {opcao.description || "—"} · {opcao.count.toLocaleString("pt-PT")} contratos
              </span>
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
