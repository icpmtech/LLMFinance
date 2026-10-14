/**
 * Administração · **Chaves e integrações**.
 *
 * As credenciais dos serviços externos (a **2captcha**, que resolve o reCAPTCHA
 * da recolha societária do MJ) ficam guardadas no Elasticsearch — documento
 * `service-keys` do índice `finance_settings` — e são lidas em cada utilização,
 * pela ordem **índice → ambiente → `.env` → valor por omissão**. Alterar aqui a
 * chave passa a valer de imediato, sem reiniciar o backend; deixar o campo vazio
 * devolve o serviço ao valor do ambiente/`.env`/padrão.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, KeyRound, Loader2, PlugZap, Save, ShieldCheck, X } from "lucide-react";

import { Button } from "../components/ui/Button";
import {
  getServiceKeys,
  saveServiceKeys,
  testServiceKey,
  type ServiceKey,
  type ServiceKeysState,
} from "../adminApi";

const ORIGEM_LABELS: Record<string, string> = {
  indice: "guardada na plataforma",
  ambiente: "variável de ambiente",
  env_file: "ficheiro .env",
  padrao: "valor por omissão da aplicação",
  ausente: "não definida",
  indisponivel: "índice indisponível",
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const data = new Date(value);
  if (Number.isNaN(data.getTime())) return value;
  return data.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

export function AdminServiceKeysTab({ onError }: { onError: (message: string | null) => void }) {
  const [state, setState] = useState<ServiceKeysState | null>(null);
  const [valores, setValores] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"load" | "save" | null>("load");
  const [aTestar, setATestar] = useState<string | null>(null);
  const [testes, setTestes] = useState<Record<string, { ok: boolean; mensagem: string }>>({});
  const [aviso, setAviso] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setBusy("load");
    try {
      const resultado = await getServiceKeys();
      setState(resultado);
      setValores({});
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao carregar as chaves de serviços.");
    } finally {
      setBusy(null);
    }
  }, [onError]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const todas = useMemo<ServiceKey[]>(() => state?.chaves ?? [], [state]);
  /* Filtro rápido: ver só o que falta configurar é o caso mais frequente. */
  const [soPendentes, setSoPendentes] = useState(false);
  const chaves = useMemo(
    () => (soPendentes ? todas.filter((chave) => !chave.definida) : todas),
    [todas, soPendentes],
  );
  const grupos = useMemo(() => {
    const mapa = new Map<string, ServiceKey[]>();
    chaves.forEach((chave) => {
      mapa.set(chave.grupo, [...(mapa.get(chave.grupo) || []), chave]);
    });
    return [...mapa.entries()];
  }, [chaves]);

  const guardar = async () => {
    setBusy("save");
    setAviso(null);
    try {
      const resultado = await saveServiceKeys(valores);
      setState(resultado);
      setValores({});
      setAviso(
        resultado.alteradas?.length
          ? `Chaves gravadas no Elasticsearch: ${resultado.alteradas.join(", ")}.`
          : "Nada para alterar (sem valores novos).",
      );
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao gravar as chaves.");
    } finally {
      setBusy(null);
    }
  };

  const testar = async (chave: ServiceKey) => {
    setATestar(chave.id);
    try {
      const resultado = await testServiceKey(chave.id);
      setTestes((prev) => ({ ...prev, [chave.id]: resultado }));
      onError(null);
    } catch (caught) {
      setTestes((prev) => ({
        ...prev,
        [chave.id]: { ok: false, mensagem: caught instanceof Error ? caught.message : "Erro no teste" },
      }));
    } finally {
      setATestar(null);
    }
  };

  const porGravar = Object.values(valores).some((valor) => valor !== undefined);

  /* Resumo por origem: torna evidente o que está configurado e onde, já que um
     valor pode vir do índice (gravado aqui), do ambiente do contentor ou do
     `.env` — e só a combinação dos três é que conta. */
  const resumo = useMemo(() => {
    const contagem = { indice: 0, ambiente: 0, env_file: 0, padrao: 0, ausente: 0 } as Record<string, number>;
    todas.forEach((chave) => {
      const origem = chave.definida ? chave.origem : "ausente";
      contagem[origem] = (contagem[origem] ?? 0) + 1;
    });
    return contagem;
  }, [todas]);

  return (
    /* `overflow-y-auto` é obrigatório: o pai é `overflow-hidden`, e sem isto os
       grupos de chaves que não cabem no ecrã ficavam cortados sem forma de lá chegar. */
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
      <div className="glass-card gradient-border shrink-0 rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <KeyRound size={16} /> Chaves e integrações
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              {state?.notas ??
                "As chaves dos serviços externos ficam guardadas no Elasticsearch e são usadas de imediato."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => void carregar()} disabled={busy !== null}>
              {busy === "load" ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />} Recarregar
            </Button>
            <Button onClick={() => void guardar()} disabled={busy !== null || !porGravar}>
              {busy === "save" ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Guardar
            </Button>
          </div>
        </div>

        {state && (
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span>
              Índice: <span className="font-mono text-foreground">{state.index}</span> · documento{" "}
              <span className="font-mono text-foreground">{state.doc_id}</span>
            </span>
            <span>
              Última alteração: {formatDate(state.atualizado_em)}
              {state.atualizado_por ? ` por ${state.atualizado_por}` : ""}
            </span>
          </p>
        )}

        {state && (
          <div className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[11px] text-muted-foreground">
              <strong className="text-foreground">
                {todas.filter((chave) => chave.definida).length} de {todas.length}
              </strong>{" "}
              chaves configuradas · a resolução é{" "}
              <span className="font-mono">índice → ambiente → .env → padrão</span>, pelo que uma chave marcada como{" "}
              <em>definida</em> já está a ser usada, mesmo que não tenha sido gravada aqui.
            </p>
            <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px]">
              <span className="text-teal-200">
                {resumo.indice ?? 0} guardada(s) na plataforma
              </span>
              <span className="text-sky-200">
                {(resumo.ambiente ?? 0) + (resumo.env_file ?? 0)} vinda(s) do ambiente/.env
              </span>
              {resumo.padrao ? (
                <span className="text-violet-200">{resumo.padrao} com valor por omissão</span>
              ) : null}
              <span className={resumo.ausente ? "text-amber-200" : "text-muted-foreground"}>
                {resumo.ausente ?? 0} por definir
              </span>
            </p>
            {(resumo.ausente ?? 0) > 0 && (
              <button
                type="button"
                onClick={() => setSoPendentes((atual) => !atual)}
                className="mt-2 rounded-lg border border-white/10 px-2.5 py-1 text-[10.5px] text-muted-foreground transition hover:border-white/25 hover:text-foreground"
              >
                {soPendentes ? "Mostrar todas as chaves" : "Mostrar apenas as que faltam configurar"}
              </button>
            )}
          </div>
        )}

        {aviso && (
          <p className="mt-3 flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-[11.5px] text-emerald-200">
            <CheckCircle2 size={13} /> {aviso}
          </p>
        )}
      </div>

      {busy === "load" && !state && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar as chaves…
        </p>
      )}

      {soPendentes && grupos.length === 0 && (
        <p className="rounded-2xl border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-[12px] text-emerald-200">
          Todas as chaves estão configuradas.
        </p>
      )}

      {grupos.map(([grupo, itens]) => (
        <div key={grupo} className="glass-card gradient-border shrink-0 rounded-2xl p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ShieldCheck size={14} className="text-teal-300" /> {grupo}
          </h3>

          <div className="mt-3 space-y-4">
            {itens.map((chave) => {
              const teste = testes[chave.id];
              return (
                <div key={chave.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-foreground">{chave.label}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{chave.descricao}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px] text-muted-foreground">
                        <span
                          className={
                            chave.definida
                              ? "rounded-full border border-emerald-400/25 bg-emerald-400/10 px-1.5 py-0.5 text-emerald-200"
                              : "rounded-full border border-amber-400/25 bg-amber-400/10 px-1.5 py-0.5 text-amber-200"
                          }
                        >
                          {chave.definida ? "definida" : "por definir"}
                        </span>
                        {chave.definida && (
                          <span>
                            vem de: {ORIGEM_LABELS[chave.origem] ?? chave.origem}
                            {chave.variavel ? ` (${chave.variavel})` : ""}
                          </span>
                        )}
                        {chave.definida && chave.valor_mascarado ? (
                          <span className="font-mono">{chave.valor_mascarado}</span>
                        ) : null}
                        <span className="font-mono">env: {chave.env.join(" / ")}</span>
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {chave.testavel && (
                        <Button variant="ghost" onClick={() => void testar(chave)} disabled={aTestar !== null}>
                          {aTestar === chave.id ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />} Testar
                        </Button>
                      )}
                      {chave.onde && (
                        <a
                          href={chave.onde.startsWith("http") ? chave.onde : undefined}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-1 text-[11px] text-teal-300 hover:underline"
                        >
                          <ExternalLink size={11} /> onde obter
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      type={chave.secreto ? "password" : "text"}
                      value={valores[chave.id] ?? ""}
                      onChange={(event) =>
                        setValores((prev) => ({ ...prev, [chave.id]: event.target.value }))
                      }
                      placeholder={
                        chave.definida
                          ? "Escreva o novo valor (apagar o campo devolve a chave ao ambiente/.env/padrão)"
                          : chave.exemplo || "Novo valor"
                      }
                      autoComplete="off"
                      className="min-h-[40px] min-w-[280px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
                    />
                    {valores[chave.id] !== undefined && (
                      <button
                        type="button"
                        onClick={() => setValores((prev) => {
                          const copia = { ...prev };
                          delete copia[chave.id];
                          return copia;
                        })}
                        className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] text-muted-foreground transition hover:text-foreground"
                      >
                        <X size={12} /> limpar campo
                      </button>
                    )}
                  </div>

                  {teste && (
                    <p
                      className={[
                        "mt-2 flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[11px]",
                        teste.ok
                          ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                          : "border-rose-400/25 bg-rose-400/10 text-rose-200",
                      ].join(" ")}
                    >
                      {teste.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />} {teste.mensagem}
                    </p>
                  )}

                  {chave.erro && (
                    <p className="mt-2 flex items-center gap-2 text-[11px] text-amber-200">
                      <AlertTriangle size={12} /> {chave.erro}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        As chaves nunca são devolvidas em claro por esta página (só o valor mascarado). A resolução usada pela
        plataforma é <span className="text-foreground">índice → variável de ambiente → .env</span>, pelo que gravar
        aqui substitui o valor do ambiente sem reiniciar o backend; limpar a chave devolve o serviço ao ambiente/` .env`.
      </p>
    </div>
  );
}
