/**
 * **Benchmark · cruzar empresas de países diferentes** — `/benchmark/cruzar`.
 *
 * Página própria (e não um separador das páginas por país) porque o eixo da
 * análise é outro: nas páginas por país compara-se tudo dentro do mesmo
 * mercado; aqui cruzam-se empresas de registos diferentes e compara-se o que é
 * comparável entre eles — o CPV, as contrapartes e a posição relativa.
 */
import { GitCompare, Scale } from "lucide-react";

import BenchmarkCross from "../components/benchmark/BenchmarkCross";

export default function BenchmarkCrossPage({ onSwitchView }: { onSwitchView?: () => void }) {
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 fade-in">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <GitCompare size={22} className="text-sky-400" />
            Benchmark · Entre países
          </h1>
          <p className="text-sm text-muted-foreground">
            Cruze empresas de Portugal, Espanha e França pelo CPV: onde se encontram, quem lhes compra (ou vende) em
            comum e como se posicionam cada uma no seu próprio mercado.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {onSwitchView ? (
            <button
              type="button"
              onClick={onSwitchView}
              className="rounded-xl border border-border px-3 py-2 text-sm transition hover:bg-accent"
            >
              Fechar
            </button>
          ) : null}
        </div>
      </header>

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-sky-400/20 bg-sky-400/5 px-3 py-2 text-xs text-sky-200">
        <Scale size={14} className="mt-0.5 shrink-0" />
        <span>
          Os preços absolutos não se comparam entre países (mercados e práticas de contratação diferentes). O que se
          compara é a posição de cada empresa no seu mercado e o que as empresas têm em comum.
        </span>
      </div>

      <BenchmarkCross
        onOpenCountry={(pais, cpv) => {
          const caminho = `/benchmark/${pais === "pt" ? "portugal" : pais === "es" ? "espanha" : "franca"}`;
          window.location.assign(`${caminho}?cpv=${encodeURIComponent(cpv)}`);
        }}
      />
    </div>
  );
}
