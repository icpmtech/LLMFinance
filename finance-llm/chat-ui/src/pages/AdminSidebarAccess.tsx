/**
 * Administração · **Menu lateral** (módulos da solução por perfil).
 *
 * Uma matriz «perfil × módulo»: uma marca significa que o perfil **vê** o módulo
 * na barra lateral, o dock e o menu Iniciar; desmarcar esconde-o.
 *
 * Os perfis são os papéis da plataforma (`admin`, `member`) e os perfis de CRM
 * (comercial, marketing, convidado…). As regras somam-se: um módulo escondido no
 * papel da plataforma **ou** no perfil de CRM do utilizador desaparece para ele.
 *
 * Alguns módulos são intocáveis (chat, Finder, definições e administração) —
 * escondê-los trancaria o utilizador fora da plataforma.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { BadgeCheck, Eye, EyeOff, Loader2, Lock, RefreshCw, RotateCcw, Save, ShieldCheck } from "lucide-react";

import { Button } from "../components/ui/Button";
import { RESERVED_MODULES, sidebarCatalog, type SidebarModuleGroup } from "../sidebarCatalog";
import {
  getSidebarAccessAdmin,
  resetSidebarAccess,
  saveSidebarAccess,
  type SidebarAccessAdmin,
  type SidebarProfileOption,
} from "../sidebarAccess";

const KIND_LABELS: Record<string, string> = {
  plataforma: "Papel da plataforma",
  crm: "Perfil de CRM",
};

type Rules = Record<string, string[]>;

/** Converte a lista de escondidos numa lista de visíveis por perfil. */
function hiddenSet(rules: Rules, profile: string): Set<string> {
  return new Set(rules[profile] || []);
}

function toRules(hidden: Rules): Rules {
  const clean: Rules = {};
  for (const key of Object.keys(hidden).sort()) {
    const modules = [...new Set(hidden[key])].sort();
    if (modules.length) clean[key] = modules;
  }
  return clean;
}

function sameRules(a: Rules, b: Rules): boolean {
  return JSON.stringify(toRules(a)) === JSON.stringify(toRules(b));
}

export function AdminSidebarAccessTab({ onError }: { onError: (message: string | null) => void }) {
  const catalog = useMemo<SidebarModuleGroup[]>(() => sidebarCatalog(), []);
  const [state, setState] = useState<SidebarAccessAdmin | null>(null);
  const [hidden, setHidden] = useState<Rules>({});
  const [saved, setSaved] = useState<Rules>({});
  const [busy, setBusy] = useState<"load" | "save" | "reset" | null>("load");
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy("load");
    try {
      const result = await getSidebarAccessAdmin();
      setState(result);
      setHidden(result.rules || {});
      setSaved(result.rules || {});
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao carregar o acesso à barra lateral.");
    } finally {
      setBusy(null);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const profiles: SidebarProfileOption[] = state?.profiles ?? [];
  const platformCount = profiles.filter((profile) => profile.kind === "plataforma").length;

  const toggle = (profile: string, module: string, visible: boolean) => {
    if (RESERVED_MODULES.includes(module)) return;
    setHidden((current) => {
      const set = new Set(current[profile] || []);
      if (visible) set.delete(module);
      else set.add(module);
      return { ...current, [profile]: [...set] };
    });
  };

  const setProfileAll = (profile: string, visible: boolean) => {
    const all = catalog.flatMap((group) => group.items.map((item) => item.id)).filter((id) => !RESERVED_MODULES.includes(id));
    setHidden((current) => ({ ...current, [profile]: visible ? [] : all }));
  };

  const save = async () => {
    setBusy("save");
    try {
      const result = await saveSidebarAccess(toRules(hidden));
      setState(result);
      setSaved(result.rules || {});
      setHidden(result.rules || {});
      setNotice(`Matriz gravada (${result.rules ? Object.keys(result.rules).length : 0} perfil(es) com restrições).`);
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao gravar a matriz.");
    } finally {
      setBusy(null);
    }
  };

  const resetAll = async () => {
    setBusy("reset");
    try {
      const result = await resetSidebarAccess();
      setState(result);
      setHidden(result.rules || {});
      setSaved(result.rules || {});
      setNotice("Todos os módulos voltaram a estar visíveis para todos os perfis.");
      onError(null);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Erro ao repor os acessos.");
    } finally {
      setBusy(null);
    }
  };

  const dirty = !sameRules(hidden, saved);
  const totalHidden = Object.values(hidden).reduce((total, modules) => total + modules.length, 0);

  if (busy === "load" && !state) {
    return (
      <p className="flex items-center gap-2 p-6 text-[12.5px] text-muted-foreground">
        <Loader2 size={14} className="animate-spin" /> A carregar os acessos da barra lateral…
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <section className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-white/[0.02] p-2">
        <span className="flex items-center gap-1.5 text-[12px] text-foreground">
          <ShieldCheck size={13} className="text-teal-300" /> Módulos visíveis por perfil
        </span>
        <span className="text-[11px] text-muted-foreground">
          {profiles.length} perfil(es) · {catalog.reduce((total, group) => total + group.items.length, 0)} módulo(s) ·{" "}
          {totalHidden} escondido(s)
        </span>
        {state?.updated_at && (
          <span className="text-[10.5px] text-muted-foreground/80">
            Última alteração: {String(state.updated_at).replace("T", " ").replace("Z", "")} · {state.updated_by || "—"}
          </span>
        )}
        <div className="min-w-0 flex-1" />
        {notice && <span className="text-[11px] text-teal-200">{notice}</span>}
        <Button size="sm" variant="outline" icon={<RefreshCw size={12} />} onClick={() => void load()} loading={busy === "load"}>
          Recarregar
        </Button>
        <Button size="sm" variant="outline" icon={<RotateCcw size={12} />} onClick={() => void resetAll()} loading={busy === "reset"}>
          Repor tudo visível
        </Button>
        <Button size="sm" icon={<Save size={12} />} onClick={() => void save()} loading={busy === "save"} disabled={!dirty}>
          {dirty ? "Guardar alterações" : "Sem alterações"}
        </Button>
      </section>

      <p className="shrink-0 text-[11px] leading-snug text-muted-foreground">
        Uma marca significa que o perfil <strong className="font-medium text-foreground">vê</strong> o módulo na barra lateral, no dock
        e no menu Iniciar. As regras somam-se: se o módulo estiver escondido no papel da plataforma <em>ou</em> no perfil de CRM, o
        utilizador não o vê. Esconder um módulo não retira permissões de CRM (essas são geridas em «Perfis de acesso»).
      </p>

      <section className="min-h-0 flex-1 overflow-auto rounded-xl border border-white/10">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-10 bg-[#0a1c24]">
            <tr>
              <th className="sticky left-0 z-20 min-w-[220px] bg-[#0a1c24] px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Módulo
              </th>
              {profiles.map((profile) => {
                const count = (hidden[profile.key] || []).length;
                const modules = catalog.reduce((total, group) => total + group.items.length, 0);
                return (
                  <th key={profile.key} className="min-w-[104px] border-l border-white/8 px-2 py-1.5 align-top">
                    <div className="flex flex-col items-start gap-0.5">
                      <span className="text-[11px] font-medium text-foreground" title={`${profile.label} (${profile.key})`}>
                        {profile.label}
                      </span>
                      <span className="text-[9.5px] text-muted-foreground">
                        {KIND_LABELS[profile.kind] ?? profile.kind}
                        {profile.area ? ` · ${profile.area}` : ""}
                      </span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setProfileAll(profile.key, true)}
                          className="rounded px-1 text-[9.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
                          title="Mostrar tudo"
                        >
                          tudo
                        </button>
                        <button
                          type="button"
                          onClick={() => setProfileAll(profile.key, false)}
                          className="rounded px-1 text-[9.5px] text-muted-foreground hover:bg-white/10 hover:text-foreground"
                          title="Esconder tudo"
                        >
                          nada
                        </button>
                        <span className={`text-[9.5px] ${count ? "text-amber-200" : "text-muted-foreground/70"}`}>
                          {count ? `${modules - count}/${modules}` : "—"}
                        </span>
                      </span>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {catalog.map((group) => (
              <Fragment key={`group-${group.id}`}>
                <tr className="border-t border-white/8 bg-white/[0.04]">
                  <td
                    className="sticky left-0 bg-[#0b1f28] px-3 py-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground"
                    colSpan={profiles.length + 1}
                  >
                    {group.label}
                  </td>
                </tr>
                {group.items.map((item) => {
                  const reserved = RESERVED_MODULES.includes(item.id);
                  return (
                    <tr key={item.id} className="border-t border-white/6 hover:bg-white/[0.02]">
                      <td className="sticky left-0 bg-[#08181f] px-3 py-1">
                        <span className="flex items-center gap-1.5">
                          {reserved && (
                            <span title="Módulo intocável">
                              <Lock size={10} className="text-muted-foreground" />
                            </span>
                          )}
                          <span className="text-foreground">{item.label}</span>
                          <span className="font-mono text-[9.5px] text-muted-foreground/70">{item.id}</span>
                        </span>
                        <span className="block truncate text-[10px] text-muted-foreground/70">{item.hint}</span>
                      </td>
                      {profiles.map((profile) => {
                        const visible = !hiddenSet(hidden, profile.key).has(item.id);
                        return (
                          <td key={profile.key} className="border-l border-white/8 px-2 py-1 text-center">
                            <input
                              type="checkbox"
                              className="h-3.5 w-3.5 cursor-pointer accent-teal-400 disabled:cursor-not-allowed disabled:opacity-40"
                              checked={visible}
                              disabled={reserved}
                              title={reserved ? "Este módulo nunca pode ser escondido" : `${item.label} · ${profile.label}`}
                              onChange={(event) => toggle(profile.key, item.id, event.target.checked)}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>

      <section className="flex shrink-0 flex-wrap items-center gap-3 text-[10.5px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Eye size={11} className="text-teal-300" /> visível
        </span>
        <span className="flex items-center gap-1">
          <EyeOff size={11} className="text-amber-300" /> escondido
        </span>
        <span className="flex items-center gap-1">
          <Lock size={11} /> {RESERVED_MODULES.join(", ")} — nunca escondidos
        </span>
        <span className="flex items-center gap-1">
          <BadgeCheck size={11} /> {platformCount} papel(éis) da plataforma · {profiles.length - platformCount} perfil(éis) de CRM
        </span>
      </section>
    </div>
  );
}
