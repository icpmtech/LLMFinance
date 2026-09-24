/**
 * Janela própria do grafo de pessoas/cargos (`pessoas-graph:*`).
 *
 * Permite ter **vários grafos abertos ao mesmo tempo** (uma janela por
 * pessoa/empresa/modo) e traz a pesquisa e os filtros para dentro da janela:
 * elegendo uma pessoa/entidade, o grafo carrega sem se perder o que estava
 * aberto no PessoasIQ.
 *
 * Ids suportados:
 * - `pessoas-graph`            → vazio, com a pesquisa à espera;
 * - `pessoas-graph:p:<NIF>`    → grafo de uma pessoa;
 * - `pessoas-graph:e:<NIF>`    → grafo de uma empresa;
 * - `pessoas-graph:c:<NIF>`    → grafo combinado (cargos + contratos).
 */
import { parseGraphWindowView } from "../components/people/peopleKit";
import { GraphSection } from "./PessoasIQPage";

export function PessoasGraphWindow({ target }: { target?: string | null }) {
  const parsed = parseGraphWindowView(target);
  const isCompanySide = parsed ? parsed.mode !== "person" : false;

  return (
    <div className="h-full overflow-y-auto p-3">
      <GraphSection
        person={null}
        withPicker
        standalone
        className="h-full"
        initialMode={parsed?.mode ?? "person"}
        initialNif={parsed && !isCompanySide ? parsed.nif : ""}
        initialCompanyNif={parsed && isCompanySide ? parsed.nif : ""}
        heightClass="h-[40vh] min-h-[260px] xl:h-[52vh] max-h-[560px]"
        detailHeightClass="max-h-[34vh] xl:max-h-[46vh]"
      />
    </div>
  );
}

export default PessoasGraphWindow;
