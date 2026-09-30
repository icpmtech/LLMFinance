/**
 * Painel **Motor do Hermes Agent** — liga o container autónomo aos fornecedores
 * de IA do IQ OS.
 *
 * O Hermes Agent vive do seu próprio volume e, sem configuração, arranca sem
 * modelo nenhum (o `config.yaml` de exemplo aponta para um modelo que não tem
 * chave). Este painel resolve isso: escolhe-se o fornecedor que a plataforma já
 * tem, vê-se exatamente o que vai ser escrito (plano) e aplica-se — a plataforma
 * escreve no volume do container e recria-o.
 *
 * O diagnóstico mostra sempre o que está **dentro** do container, para não haver
 * dúvida entre o que a plataforma quer e o que o agente tem.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Cpu, Loader2, RefreshCw, Server, Zap } from "lucide-react";

import {
  applyHermesAgentSettings,
  getHermesAgentSettings,
  saveHermesAgentSettings,
  type HermesAgentView,
} from "../../hermesAgentApi";

const SOURCE_LABEL: Record<string, string> = {
  user: "chave da conta",
  env: "variável de ambiente",
  custom: "chave personalizada",
  none: "sem chave",
};

export default function HermesAgentPanel() {
  const [view, setView] = useState<HermesAgentView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "save" | "apply">("");
  const [result, setResult] = useState<string[] | null>(null);
  const [open, setOpen] = useState(false);

  // Campos editáveis (inicializados a partir do servidor).
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [customKey, setCustomKey] = useState("");
  const [search, setSearch] = useState("");
  const [searxngUrl, setSearxngUrl] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await getHermesAgentSettings();
      setView(data);
      setProvider(data.settings.llm_provider);
      setModel(data.settings.llm_model);
      setBaseUrl(data.settings.llm_base_url);
      setSearch(data.settings.search_provider);
      setSearxngUrl(data.settings.searxng_url);
      setCustomKey("");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao ler as definições do Hermes Agent.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = view?.providers.find((item) => item.id === provider);

  const payload = () => ({
    llm_provider: provider,
    llm_model: model,
    llm_base_url: baseUrl,
    // A chave personalizada só é enviada quando escrita: enviar uma string vazia
    // apagaria a que lá está.
    ...(customKey ? { llm_custom_key: customKey } : {}),
    search_provider: search,
    searxng_url: searxngUrl,
  });

  const save = async () => {
    setBusy("save");
    setError(null);
    setResult(null);
    try {
      const data = await saveHermesAgentSettings(payload());
      setView(data);
      setCustomKey("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao gravar.");
    } finally {
      setBusy("");
    }
  };

  const apply = async () => {
    setBusy("apply");
    setError(null);
    setResult(null);
    try {
      const out = await applyHermesAgentSettings({ ...payload(), recreate: true });
      setResult([
        `Escrito no container: ${out.config.join(", ") || "—"}`,
        `Variáveis: ${out.env_written.join(", ") || "—"}${out.env_removed.length ? ` · removidas: ${out.env_removed.join(", ")}` : ""}`,
        out.recreated ? "Container recriado." : "Sem recriação.",
        ...out.notes,
      ]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao aplicar.");
    } finally {
      setBusy("");
    }
  };

  const diagnose = view?.diagnose;

  return (
    <section className="glass-card rounded-2xl p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Cpu size={12} /> Motor do Hermes Agent
        </h2>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="text-[11px] text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
        >
          {open ? "fechar" : "configurar"}
        </button>
      </div>

      {/* Estado resumido — sempre visível */}
      <div className="space-y-1 text-[11.5px]">
        {!view ? (
          <p className="text-muted-foreground">A ler o estado do container…</p>
        ) : (
          <>
            <p className="flex items-center gap-1.5">
              {diagnose?.in_sync ? (
                <Check size={12} className="text-emerald-300" />
              ) : (
                <AlertTriangle size={12} className="text-amber-300" />
              )}
              <span className={diagnose?.in_sync ? "text-emerald-200" : "text-amber-200"}>
                {diagnose?.in_sync ? "Ligado aos fornecedores da plataforma" : "Por configurar"}
              </span>
            </p>
            <p className="text-muted-foreground">
              {diagnose?.running ? (
                <>
                  {view.resolved.label} · <code className="text-teal-200">{view.resolved.model || "sem modelo"}</code>
                  {view.resolved.hermes_provider ? (
                    <> · perfil <code>{view.resolved.hermes_provider}</code></>
                  ) : (
                    <> · <code>custom</code></>
                  )}
                </>
              ) : (
                "Container não está a correr."
              )}
            </p>
            {view.settings.applied_at ? (
              <p className="text-[10.5px] text-muted-foreground/80">Aplicado em {view.settings.applied_at}</p>
            ) : null}
          </>
        )}
      </div>

      {open && view ? (
        <div className="mt-3 space-y-2.5 border-t border-white/8 pt-3">
          <p className="text-[11px] leading-snug text-muted-foreground">{view.about.note}</p>

          {/* Fornecedor */}
          <label className="block text-[11px] text-muted-foreground">
            Fornecedor de IA
            <select
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value);
                setModel("");
                setBaseUrl("");
              }}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            >
              {view.providers.map((item) => (
                <option key={item.id} value={item.id} disabled={!item.usable && !item.hermes_provider}>
                  {item.label}
                  {item.usable ? ` · ${item.key_hint || "chave do ambiente"}` : " · sem chave"}
                </option>
              ))}
            </select>
          </label>

          {selected ? (
            <p className="text-[10.5px] leading-snug text-muted-foreground/80">
              {selected.mode}
              {selected.hermes_env ? (
                <>
                  {" "}· chave em <code className="text-teal-200/90">{selected.hermes_env}</code>
                </>
              ) : null}
              {" "}· origem: {SOURCE_LABEL[view.resolved.source] ?? view.resolved.source}
            </p>
          ) : null}

          {/* Modelo */}
          <label className="block text-[11px] text-muted-foreground">
            Modelo
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              list="hermes-agent-models"
              placeholder={selected?.default_model || "modelo do fornecedor"}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            />
          </label>
          <datalist id="hermes-agent-models">
            {(selected?.models ?? []).map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>

          {/* Base URL (só faz sentido para endpoints próprios) */}
          {selected && !selected.hermes_provider ? (
            <label className="block text-[11px] text-muted-foreground">
              Endpoint (OpenAI-compatível)
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={selected.base_url}
                className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
              />
            </label>
          ) : null}

          {/* Chave personalizada */}
          <label className="block text-[11px] text-muted-foreground">
            Chave personalizada {view.settings.llm_custom_key_set ? "(já definida)" : "(opcional)"}
            <input
              type="password"
              value={customKey}
              onChange={(event) => setCustomKey(event.target.value)}
              placeholder="vazio usa a chave da plataforma"
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            />
          </label>

          {/* Pesquisa web */}
          <label className="block text-[11px] text-muted-foreground">
            Pesquisa web do agente
            <select
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            >
              {view.search_providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {search === "searxng" ? (
            <label className="block text-[11px] text-muted-foreground">
              URL do SearXNG
              <input
                value={searxngUrl}
                onChange={(event) => setSearxngUrl(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[12px] text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
              />
            </label>
          ) : null}

          {/* Plano */}
          <div className="rounded-xl border border-white/8 bg-white/[0.02] p-2">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground/80">
              Vai ser escrito no container
            </p>
            <ul className="space-y-0.5 text-[11px] text-muted-foreground">
              {Object.entries(view.plan.config)
                .filter(([, value]) => value !== null && value !== "")
                .map(([key, value]) => (
                  <li key={key} className="flex items-start gap-1.5">
                    <Server size={10} className="mt-0.5 shrink-0 text-teal-300" />
                    <code className="break-all">
                      {key}={String(value)}
                    </code>
                  </li>
                ))}
              {Object.entries(view.plan.config)
                .filter(([, value]) => value === null || value === "")
                .map(([key]) => (
                  <li key={key} className="flex items-start gap-1.5 text-muted-foreground/70">
                    <span className="mt-0.5 shrink-0">−</span>
                    <code>remover {key}</code>
                  </li>
                ))}
              {view.plan.env.map((name) => (
                <li key={name} className="flex items-start gap-1.5">
                  <Zap size={10} className="mt-0.5 shrink-0 text-amber-300" />
                  <code>.env → {name}</code>
                </li>
              ))}
            </ul>
            {view.plan.notes.length ? (
              <ul className="mt-1.5 space-y-0.5 border-t border-white/8 pt-1.5 text-[10.5px] text-muted-foreground/80">
                {view.plan.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </div>

          {/* Diagnóstico do container */}
          <div className="rounded-xl border border-white/8 bg-white/[0.02] p-2 text-[11px]">
            <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground/80">
              No container agora
            </p>
            <ul className="space-y-0.5 text-muted-foreground">
              <li>
                <code>model.provider={diagnose?.config["model.provider"] ?? "—"}</code>
              </li>
              <li>
                <code>model.default={diagnose?.config["model.default"] ?? "—"}</code>
              </li>
              <li>
                <code>
                  chave:{" "}
                  {diagnose?.config_has_api_key
                    ? "no config.yaml"
                    : diagnose?.env_keys.length
                      ? `em ${diagnose.env_keys.join(", ")}`
                      : "ausente"}
                </code>
              </li>
            </ul>
            {diagnose?.problems.length ? (
              <ul className="mt-1.5 space-y-0.5 border-t border-white/8 pt-1.5 text-amber-200/90">
                {diagnose.problems.map((problem) => (
                  <li key={problem}>• {problem}</li>
                ))}
              </ul>
            ) : null}
          </div>

          {/* Ações */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={busy !== ""}
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            >
              {busy === "save" ? <Loader2 size={13} className="animate-spin" /> : null}
              Guardar
            </button>
            <button
              type="button"
              onClick={apply}
              disabled={busy !== ""}
              className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-600 px-2.5 py-1.5 text-[12px] font-medium text-white transition hover:from-violet-400 hover:to-fuchsia-500 disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/40"
            >
              {busy === "apply" ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              Aplicar e recriar
            </button>
            <button
              type="button"
              onClick={() => void load()}
              disabled={busy !== ""}
              title="Reler o estado"
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/[0.08] hover:text-foreground disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40"
            >
              <RefreshCw size={13} />
            </button>
          </div>

          {error ? (
            <p className="rounded-xl border border-rose-400/30 bg-rose-400/10 p-2 text-[11.5px] text-rose-200">{error}</p>
          ) : null}
          {result ? (
            <ul className="space-y-0.5 rounded-xl border border-emerald-400/25 bg-emerald-400/10 p-2 text-[11.5px] text-emerald-100">
              {result.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
