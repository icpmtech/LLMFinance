/**
 * Módulo **Permissões** (`/permissoes`).
 *
 * Responde a uma regra simples: um **utilizador comum só lê dados**; criar e
 * alterar conteúdo é de **administradores** e **gestores de plataforma**. Aqui
 * vê-se e ajusta-se essa matriz, por papel e por área de rotas.
 *
 * A leitura aparece sempre ativa e não é editável: o que limita a leitura é o
 * plano de subscrição e o «Menu lateral», não esta matriz. O que se decide aqui
 * é a **escrita**.
 *
 * Só um administrador grava (o servidor recusa a um gestor); o gestor pode
 * consultar a matriz para saber o que lhe é permitido.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCcw, Save, ShieldCheck } from "lucide-react";

import { Button } from "../components/ui/Button";
import { useAuth } from "../auth";
import {
  getPermissions,
  resetPermissions,
  savePermissions,
  type PermissionAction,
  type PermissionMatrix,
  type PermissionModule,
  type PermissionsState,
} from "../permissionsApi";

function Cell({
  ligado,
  acao,
  editavel,
  onToggle,
}: {
  ligado: boolean;
  acao: PermissionAction;
  editavel: boolean;
  onToggle: () => void;
}) {
  const rotulo = acao === "read" ? "Ler" : "Escrever";
  const cor = ligado
    ? acao === "write"
      ? "border-teal-400/30 bg-teal-400/15 text-teal-200"
      : "border-sky-400/25 bg-sky-400/10 text-sky-200"
    : "border-white/10 bg-white/[0.02] text-muted-foreground";
  return (
    <button
      type="button"
      disabled={!editavel}
      onClick={onToggle}
      title={editavel ? `${rotulo}: clicar para alternar` : `${rotulo} (não editável)`}
      className={`w-[74px] rounded-md border px-1.5 py-0.5 text-[10.5px] transition ${cor} ${
        editavel ? "hover:brightness-125" : "cursor-not-allowed opacity-70"
      }`}
    >
      {ligado ? "✓" : "—"} {rotulo}
    </button>
  );
}

export default function PermissionsPage() {
  const { user } = useAuth();
  const isAdmin = (user?.role ?? "member") === "admin";

  const [state, setState] = useState<PermissionsState | null>(null);
  const [matriz, setMatriz] = useState<PermissionMatrix>({});
  const [busy, setBusy] = useState<"load" | "save" | "reset" | null>("load");
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setBusy("load");
    try {
      const resultado = await getPermissions();
      setState(resultado);
      setMatriz(JSON.parse(JSON.stringify(resultado.matrix)) as PermissionMatrix);
      setErro(null);
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "Não foi possível carregar as permissões.");
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void carregar();
    else setBusy(null);
  }, [carregar, isAdmin]);

  const porGravar = useMemo(() => {
    if (!state) return false;
    return JSON.stringify(matriz) !== JSON.stringify(state.matrix);
  }, [matriz, state]);

  const alternar = (role: string, moduleId: string, acao: PermissionAction) => {
    setAviso(null);
    setMatriz((atual) => ({
      ...atual,
      [role]: {
        ...(atual[role] || {}),
        [moduleId]: {
          ...(atual[role]?.[moduleId] || { read: true, write: false }),
          [acao]: !(atual[role]?.[moduleId]?.[acao] ?? (acao === "read")),
        },
      },
    }));
  };

  const guardar = async () => {
    setBusy("save");
    setErro(null);
    setAviso(null);
    try {
      const resultado = await savePermissions(matriz);
      setState((atual) => (atual ? { ...atual, matrix: resultado.matrix } : atual));
      setMatriz(JSON.parse(JSON.stringify(resultado.matrix)) as PermissionMatrix);
      setAviso("Permissões guardadas. Aplicam-se de imediato, sem reiniciar o servidor.");
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "Não foi possível guardar.");
    } finally {
      setBusy(null);
    }
  };

  const repor = async () => {
    setBusy("reset");
    setErro(null);
    setAviso(null);
    try {
      const resultado = await resetPermissions();
      setState((atual) => (atual ? { ...atual, matrix: resultado.matrix } : atual));
      setMatriz(JSON.parse(JSON.stringify(resultado.matrix)) as PermissionMatrix);
      setAviso("Permissões repostas nos valores por omissão.");
    } catch (caught) {
      setErro(caught instanceof Error ? caught.message : "Não foi possível repor.");
    } finally {
      setBusy(null);
    }
  };

  const grupos = useMemo<[string, PermissionModule[]][]>(() => {
    const modulos = state?.modules ?? [];
    const mapa = new Map<string, PermissionModule[]>();
    modulos.forEach((modulo) => {
      mapa.set(modulo.group, [...(mapa.get(modulo.group) || []), modulo]);
    });
    return [...mapa.entries()];
  }, [state]);

  if (!isAdmin) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        <div className="glass-card gradient-border rounded-2xl p-5">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <ShieldCheck size={16} /> Permissões
          </h2>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            A matriz de permissões é gerida pela administração. O que se aplica à sua conta: um{" "}
            <strong className="text-foreground">utilizador comum apenas consulta dados</strong> — criar e alterar
            conteúdo é reservado a administradores e gestores de plataforma. Se uma ação de escrita lhe aparecer
            bloqueada com «a sua conta só pode consultar dados», é esta a regra em vigor.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            O papel da sua conta é <strong className="text-foreground">{user?.role ?? "member"}</strong>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <div className="glass-card gradient-border shrink-0 rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <ShieldCheck size={16} /> Permissões por papel
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
              Marque quem pode <strong className="text-foreground">escrever</strong> em cada área.{" "}
              <strong className="text-foreground">Ler</strong> está sempre permitido: o que limita a leitura é o plano
              de subscrição e o «Menu lateral». Guardar aqui vale de imediato, sem reiniciar o servidor.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => void carregar()} disabled={busy !== null}>
              {busy === "load" ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} Recarregar
            </Button>
            <Button variant="ghost" onClick={() => void repor()} disabled={busy !== null}>
              <RotateCcw size={14} /> Repor padrão
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
            <span>Última alteração: {state.atualizado_em || "—"}{state.atualizado_por ? ` por ${state.atualizado_por}` : ""}</span>
            {porGravar && <span className="text-amber-200">alterações por guardar</span>}
          </p>
        )}

        {state && (
          <p className="mt-3 flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            <Info size={13} className="mt-0.5 shrink-0" /> {state.read_like_note}
          </p>
        )}

        {erro && (
          <p className="mt-3 flex items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-[11.5px] text-rose-200">
            <AlertTriangle size={13} /> {erro}
          </p>
        )}
        {aviso && (
          <p className="mt-3 flex items-center gap-2 rounded-xl border border-emerald-400/25 bg-emerald-400/10 px-3 py-2 text-[11.5px] text-emerald-200">
            <CheckCircle2 size={13} /> {aviso}
          </p>
        )}
      </div>

      {busy === "load" && !state && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" /> A carregar a matriz…
        </p>
      )}

      {state && (
        <section className="shrink-0 overflow-hidden rounded-2xl border border-white/10">
          <table className="w-full border-collapse text-[11.5px]">
            <thead className="sticky top-0 z-10 bg-[#12141a]/95 text-[10px] uppercase tracking-wide text-muted-foreground backdrop-blur">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Área</th>
                {state.roles.map((role) => (
                  <th key={role.id} className="px-3 py-2 text-left font-medium">
                    {role.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grupos.map(([grupo, modulos]) => (
                <Fragment key={grupo}>
                  <tr className="border-t border-white/8 bg-white/[0.03]">
                    <td colSpan={state.roles.length + 1} className="px-3 py-1 text-[10.5px] font-semibold uppercase tracking-wide text-teal-200">
                      {grupo}
                    </td>
                  </tr>
                  {modulos.map((modulo) => (
                    <tr key={modulo.id} className="border-t border-white/6">
                      <td className="px-3 py-1.5">
                        <span className="block font-medium">{modulo.label}</span>
                        <span className="block font-mono text-[10px] text-muted-foreground">
                          /{modulo.id}
                          {modulo.admin_only ? " · só administração" : ""}
                          {modulo.self_service ? " · escrita pessoal" : ""}
                          {!modulo.content ? " · sem conteúdo" : ""}
                        </span>
                      </td>
                      {state.roles.map((role) => {
                        const linha = matriz[role.id]?.[modulo.id] || { read: true, write: false };
                        return (
                          <td key={`${role.id}-${modulo.id}`} className="px-3 py-1.5">
                            <div className="flex items-center gap-1.5">
                              <Cell
                                ligado={linha.read}
                                acao="read"
                                editavel={false}
                                onToggle={() => undefined}
                              />
                              <Cell
                                ligado={linha.write}
                                acao="write"
                                editavel={!modulo.admin_only || role.is_admin}
                                onToggle={() => alternar(role.id, modulo.id, "write")}
                              />
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
