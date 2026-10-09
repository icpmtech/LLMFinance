/**
 * Bloco «Pessoas e cargos» + «Dados societários» de uma entidade, para as fichas
 * (Quick Look do Finder e ficha da entidade).
 *
 * Os dois pedidos são independentes e falham em silêncio: uma entidade sem
 * publicações societárias indexadas não pode estragar a ficha onde o bloco é
 * usado. As pessoas vêm dos cargos extraídos das publicações do Ministério da
 * Justiça (`/societario/companies/{nif}/people`) e as publicações do índice
 * `finance_publicacoes_mj`.
 */
import { useEffect, useState } from "react";
import { Briefcase, FileText, Loader2, Users } from "lucide-react";

import { getCompanySocietarioPeople, getCompanySocietarioPublicacoes } from "../api";
import type { SocietarioPerson, SocietarioPublicacao } from "../types";

/** Data em AAAA-MM-DD (a API devolve ISO e as listas ficam mais legíveis). */
function dataCurta(valor?: string | null): string {
  const texto = String(valor ?? "").trim();
  return texto.length >= 10 ? texto.slice(0, 10) : texto || "—";
}

/** Rótulo do cargo: «Administrador Único (órgão social)» ou o que existir. */
function rotuloCargo(pessoa: SocietarioPerson): string {
  const cargo = pessoa.latest_roles?.[0] ?? pessoa.roles?.[0];
  if (!cargo) return "cargo não indicado";
  const partes = [cargo.role, cargo.role_org].filter(Boolean);
  return partes.join(" · ") || "cargo não indicado";
}

export function EntitySocietario({
  nif,
  pessoasLimite = 12,
  publicacoesLimite = 12,
  className = "mt-5",
}: {
  nif: string;
  pessoasLimite?: number;
  publicacoesLimite?: number;
  className?: string;
}) {
  const [pessoas, setPessoas] = useState<SocietarioPerson[]>([]);
  const [publicacoes, setPublicacoes] = useState<SocietarioPublicacao[]>([]);
  const [total, setTotal] = useState(0);
  const [aCarregar, setACarregar] = useState(true);

  useEffect(() => {
    let cancelado = false;
    setPessoas([]);
    setPublicacoes([]);
    setTotal(0);
    setACarregar(true);

    void Promise.allSettled([
      getCompanySocietarioPeople(nif),
      getCompanySocietarioPublicacoes(nif, 0, publicacoesLimite),
    ])
      .then(([pessoasResposta, publicacoesResposta]) => {
        if (cancelado) return;
        if (pessoasResposta.status === "fulfilled") {
          setPessoas(pessoasResposta.value.people ?? []);
        }
        if (publicacoesResposta.status === "fulfilled") {
          setPublicacoes(publicacoesResposta.value.items ?? []);
          setTotal(publicacoesResposta.value.total ?? publicacoesResposta.value.items?.length ?? 0);
        }
      })
      .finally(() => {
        if (!cancelado) setACarregar(false);
      });

    return () => {
      cancelado = true;
    };
  }, [nif, publicacoesLimite]);

  if (aCarregar) {
    return (
      <div className={`${className} flex items-center gap-2 text-[11.5px] text-muted-foreground`}>
        <Loader2 size={13} className="animate-spin" /> A carregar pessoas e dados societários…
      </div>
    );
  }

  return (
    <div className={`${className} space-y-5`}>
      {/* --- Pessoas e cargos --- */}
      <div>
        <p className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <Users size={12} /> Pessoas e cargos ({pessoas.length})
        </p>
        {pessoas.length === 0 ? (
          <p className="mt-1 text-[11.5px] text-muted-foreground/80">
            Sem pessoas/cargos extraídos das publicações societárias desta entidade.
          </p>
        ) : (
          <ul className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {pessoas.slice(0, pessoasLimite).map((pessoa) => (
              <li
                key={pessoa.nif || pessoa.name}
                className="rounded-lg border border-white/8 bg-white/[0.03] px-2 py-1.5"
              >
                <p className="flex items-center gap-1.5 text-[11.5px] font-medium">
                  <span className="min-w-0 flex-1 truncate">{pessoa.name || pessoa.nif}</span>
                  {pessoa.is_company && (
                    <span className="shrink-0 rounded-full border border-violet-400/25 bg-violet-400/10 px-1.5 text-[9.5px] text-violet-200">
                      Empresa
                    </span>
                  )}
                </p>
                <p className="truncate text-[10.5px] text-muted-foreground">
                  <Briefcase size={10} className="mr-1 inline align-[-1px]" />
                  {rotuloCargo(pessoa)}
                  {pessoa.roles_count ? ` · ${pessoa.roles_count} cargo(s)` : ""}
                  {pessoa.last_seen ? ` · último: ${dataCurta(pessoa.last_seen)}` : ""}
                </p>
                {pessoa.nif && <p className="truncate text-[10px] text-muted-foreground/70">NIF {pessoa.nif}</p>}
              </li>
            ))}
          </ul>
        )}
        {pessoas.length > pessoasLimite && (
          <p className="mt-1 text-[10.5px] text-muted-foreground/70">
            A mostrar {pessoasLimite} de {pessoas.length} pessoas.
          </p>
        )}
      </div>

      {/* --- Dados societários (publicações do MJ) --- */}
      <div>
        <p className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <FileText size={12} /> Dados societários ({total.toLocaleString("pt-PT")})
        </p>
        {publicacoes.length === 0 ? (
          <p className="mt-1 text-[11.5px] text-muted-foreground/80">
            Sem publicações de atos societários indexadas. Na ficha da entidade (EmpresasIQ) pode recolhê-las
            com «Obter dados societários».
          </p>
        ) : (
          <>
            <div className="mt-1 overflow-hidden rounded-xl border border-white/8">
              <table className="w-full text-[11.5px]">
                <thead className="bg-white/[0.04] text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1 text-left font-medium">Data</th>
                    <th className="px-2 py-1 text-left font-medium">Ato</th>
                    <th className="px-2 py-1 text-left font-medium">Concelho</th>
                  </tr>
                </thead>
                <tbody>
                  {publicacoes.slice(0, publicacoesLimite).map((publicacao, indice) => (
                    <tr
                      key={publicacao.pub_id || indice}
                      className="border-t border-white/6 transition hover:bg-white/[0.04]"
                    >
                      <td className="px-2 py-1 align-top whitespace-nowrap text-muted-foreground">
                        {dataCurta(publicacao.data_publicacao)}
                      </td>
                      <td className="px-2 py-1 align-top">
                        <span className="line-clamp-2">{publicacao.acto?.trim() || "—"}</span>
                      </td>
                      <td className="px-2 py-1 align-top text-muted-foreground">
                        {publicacao.concelho || publicacao.natureza_juridica || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {total > publicacoes.length && (
              <p className="mt-1 text-[10.5px] text-muted-foreground/70">
                A mostrar as {publicacoes.length} mais recentes de {total.toLocaleString("pt-PT")}.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
