/**
 * Página **MiroFish** — simulações de previsão por enxame de agentes
 * alimentadas com os dados do sistema.
 *
 * O utilizador escolhe uma fonte de dados (ficha de empresa, tema do Pesquisa
 * 360, notícias, documento do Office ou o panorama global), escreve o pedido de
 * previsão e a plataforma compõe o documento-semente e conduz a simulação no
 * MiroFish (projeto → grafo no Zep → personas → execução → relatório).
 *
 * A app do MiroFish abre-se na página iframe «MiroFish» (ou pelo botão
 * «Abrir MiroFish», que usa o proxy de incorporação).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Database,
  ExternalLink,
  FileText,
  Fish,
  KeyRound,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  mirofishApi,
  mirofishPublicUrl,
  type MiroFishApplyResult,
  type MiroFishDiagnose,
  type MiroFishJob,
  type MiroFishMeta,
  type MiroFishSeed,
  type MiroFishSettingsView,
  type MiroFishSource,
  type MiroFishStatus,
  type OfficeDocumentSummary,
} from "../mirofishApi";

const STEP_LABELS: Record<string, string> = {
  graph: "Construir o grafo (Zep)",
  prepare: "Gerar personas e ambiente",
  run: "Correr a simulação",
  report: "Escrever o relatório",
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat("pt-PT").format(value);
}

function StatusPill({ status }: { status: MiroFishJob["status"] }) {
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-sky-950/60 px-2 py-0.5 text-xs text-sky-300">
        <Loader2 size={12} className="animate-spin" /> a correr
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950/60 px-2 py-0.5 text-xs text-emerald-300">
        <CheckCircle2 size={12} /> concluído
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-950/60 px-2 py-0.5 text-xs text-red-300">
      <XCircle size={12} /> falhou
    </span>
  );
}

export default function MiroFishPage() {
  const [meta, setMeta] = useState<MiroFishMeta | null>(null);
  const [status, setStatus] = useState<MiroFishStatus | null>(null);
  const [jobs, setJobs] = useState<MiroFishJob[]>([]);
  const [documents, setDocuments] = useState<OfficeDocumentSummary[]>([]);
  const [sourceId, setSourceId] = useState<string>("sistema");
  const [params, setParams] = useState<Record<string, string>>({});
  const [requirement, setRequirement] = useState("");
  const [steps, setSteps] = useState<Record<string, boolean>>({ graph: true, prepare: true, run: true, report: false });
  const [maxRounds, setMaxRounds] = useState("");
  const [platform, setPlatform] = useState("parallel");
  const [seed, setSeed] = useState<MiroFishSeed | null>(null);
  const [diagnose, setDiagnose] = useState<MiroFishDiagnose | null>(null);
  const [settings, setSettings] = useState<MiroFishSettingsView | null>(null);
  const [llmProvider, setLlmProvider] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [zepKey, setZepKey] = useState("");
  const [applied, setApplied] = useState<MiroFishApplyResult["applied"]>(null);
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const sources = meta?.sources ?? [];
  const source: MiroFishSource | undefined = useMemo(
    () => sources.find((item) => item.id === sourceId) ?? sources[0],
    [sourceId, sources],
  );
  const serviceAvailable = Boolean(meta?.service?.available);
  const publicUrl = mirofishPublicUrl(meta?.public_url);

  const refreshJobs = useCallback(async () => {
    try {
      const payload = await mirofishApi.jobs(8);
      setJobs(payload.jobs);
      return payload.jobs;
    } catch {
      return [];
    }
  }, []);

  const loadAll = useCallback(async () => {
    setBusy("load");
    setError(null);
    try {
      const [metaPayload, statusPayload, diagnosePayload, settingsPayload] = await Promise.all([
        mirofishApi.meta(),
        mirofishApi.status().catch(() => null),
        mirofishApi.diagnose().catch(() => null),
        mirofishApi.settings().catch(() => null),
      ]);
      setMeta(metaPayload);
      if (statusPayload) setStatus(statusPayload);
      if (diagnosePayload) setDiagnose(diagnosePayload);
      if (settingsPayload) {
        setSettings(settingsPayload);
        setLlmProvider((current) => current || settingsPayload.settings.llm_provider || "");
        setLlmModel((current) => current || settingsPayload.settings.llm_model || "");
        setLlmBaseUrl((current) => current || settingsPayload.settings.llm_base_url || "");
      }
      await refreshJobs();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  }, [refreshJobs]);

  useEffect(() => {
    void loadAll();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [loadAll]);

  // Aplica os valores por omissão da fonte escolhida.
  useEffect(() => {
    if (!source) return;
    const next: Record<string, string> = {};
    for (const param of source.params) {
      next[param.name] = params[param.name] ?? (param.default !== undefined ? String(param.default) : "");
    }
    setParams(next);
    setRequirement((current) => current || source.requirement);
    if (source.params.some((param) => param.type === "document") && !documents.length) {
      void mirofishApi.documents().then((payload) => setDocuments(payload.items || []));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source?.id]);

  // Enquanto houver um trabalho a correr, consulta o progresso.
  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const running = jobs.find((job) => job.status === "running");
    if (!running) return;
    pollRef.current = window.setInterval(() => {
      void refreshJobs();
    }, 4000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [jobs, refreshJobs]);

  const runAction = useCallback(
    async (label: string, action: () => Promise<void>) => {
      setBusy(label);
      setError(null);
      setNotice(null);
      try {
        await action();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const payload = useCallback(
    () => ({
      source: source?.id ?? sourceId,
      params: Object.fromEntries(Object.entries(params).filter(([, value]) => String(value).trim() !== "")),
      requirement: requirement.trim() || undefined,
    }),
    [params, requirement, source?.id, sourceId],
  );

  const handlePreview = useCallback(
    () =>
      runAction("preview", async () => {
        const result = await mirofishApi.seed(payload());
        setSeed(result);
        setNotice(`Semente composta: ${result.title} — ${formatNumber(result.chars)} caracteres.`);
      }),
    [payload, runAction],
  );

  const handleSaveSeed = useCallback(
    () =>
      runAction("save", async () => {
        const result = await mirofishApi.saveSeed(payload());
        setNotice(`Semente guardada no Office: «${result.document.title}» (${result.document.id}).`);
      }),
    [payload, runAction],
  );

  const handleSimulate = useCallback(
    () =>
      runAction("simulate", async () => {
        const job = await mirofishApi.simulate({
          ...payload(),
          title: `${source?.label ?? sourceId}`,
          project_name: seed?.title,
          max_rounds: maxRounds ? Number(maxRounds) : undefined,
          platform,
          steps,
        });
        setActiveJob(job.id);
        setNotice(`Simulação iniciada (trabalho ${job.id}). Acompanhe o progresso abaixo.`);
        await refreshJobs();
      }),
    [maxRounds, payload, platform, refreshJobs, runAction, seed?.title, source?.label, sourceId, steps],
  );

  const handleSaveSettings = useCallback(
    (apply: boolean) =>
      runAction(apply ? "apply" : "save", async () => {
        const result = await mirofishApi.saveSettings({
          llm_provider: llmProvider || undefined,
          llm_model: llmModel || undefined,
          llm_base_url: llmBaseUrl || undefined,
          llm_api_key: llmKey || undefined,
          zep_api_key: zepKey || undefined,
          apply,
          recreate: true,
        });
        setApplied(result.applied);
        setLlmKey("");
        setZepKey("");
        const refreshed = await mirofishApi.settings();
        setSettings(refreshed);
        if (result.applied?.recreate?.ok) {
          setNotice("Chaves escritas e contentor do MiroFish recriado. Verifique o estado acima.");
        } else if (result.applied) {
          setNotice(
            result.applied.recreate?.detail
              ? `Chaves escritas em ${result.applied.env_path}. O contentor não foi recriado: ${result.applied.recreate.detail}`
              : `Chaves escritas em ${result.applied.env_path}. Recrie o contentor para as aplicar.`,
          );
        } else {
          setNotice("Definições guardadas. Use «Guardar e recriar» para as passar ao serviço.");
        }
      }),
    [llmBaseUrl, llmKey, llmModel, llmProvider, runAction, zepKey],
  );

  const handleDiagnose = useCallback(
    () =>
      runAction("diagnose", async () => {
        const payload = await mirofishApi.diagnose();
        setDiagnose(payload);
        setNotice(
          payload.service.available
            ? "Serviço a responder. Se as simulações falharem, veja o último erro abaixo."
            : "Serviço indisponível — confira as chaves indicadas abaixo.",
        );
      }),
    [runAction],
  );

  const selected = jobs.find((job) => job.id === activeJob) ?? jobs[0];
  const canSimulate = serviceAvailable && !busy;

  return (
    <div className="h-full w-full overflow-auto bg-zinc-950 text-zinc-100 p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <Fish className="text-cyan-400" size={22} />
              MiroFish — simulações com os dados do sistema
            </h1>
            <p className="mt-1 text-sm text-zinc-400">
              Escolha a fonte de dados, escreva o pedido de previsão e a plataforma compõe a semente, constrói o grafo de
              conhecimento e corre a simulação de agentes.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void handleDiagnose()}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white"
            >
              {busy === "diagnose" ? <Loader2 size={16} className="animate-spin" /> : <AlertTriangle size={16} />}
              Verificar chaves
            </button>
            <button
              onClick={() => void loadAll()}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white"
            >
              <RefreshCw size={16} className={busy === "load" ? "animate-spin" : ""} />
              Atualizar
            </button>
            <a
              href={`${publicUrl}/`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-cyan-500"
            >
              <ExternalLink size={16} />
              Abrir MiroFish
            </a>
          </div>
        </header>

        <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="flex items-center gap-2 text-zinc-300">
              <Database size={16} className="text-zinc-500" />
              Serviço MiroFish:
            </span>
            {meta?.service.available ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-950/60 px-2 py-0.5 text-emerald-300">
                <CheckCircle2 size={14} /> disponível em {meta.service.base_url}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-950/60 px-2 py-0.5 text-amber-300">
                <AlertTriangle size={14} /> indisponível
              </span>
            )}
            {status?.projects?.length ? <span className="text-xs text-zinc-500">{status.projects.length} projeto(s) no MiroFish</span> : null}
            {status?.simulations?.length ? <span className="text-xs text-zinc-500">{status.simulations.length} simulação(ões)</span> : null}
          </div>
          {!meta?.service.available && (
            <p className="mt-3 text-xs text-amber-200/80">
              {meta?.service.detail ? `${meta.service.detail}. ` : ""}
              Arranque o serviço com <code className="rounded bg-zinc-800 px-1">docker compose --profile mirofish up -d</code> e confirme as
              chaves <code className="rounded bg-zinc-800 px-1">MIROFISH_ZEP_API_KEY</code> e{" "}
              <code className="rounded bg-zinc-800 px-1">MIROFISH_LLM_API_KEY</code> no <code className="rounded bg-zinc-800 px-1">.env</code>{" "}
              (sem elas o backend do MiroFish não arranca).
            </p>
          )}
          {meta?.notes?.length ? (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-zinc-500">
              {meta.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}

          {diagnose && (
            <div className="mt-4 space-y-3 border-t border-zinc-800 pt-4">
              <p className="text-xs font-medium text-zinc-300">Chaves de que o MiroFish precisa</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {diagnose.keys.map((key) => {
                  const alternative = key.aliases.find((alias) => Boolean(diagnose.host_env[alias]));
                  return (
                    <div key={key.name} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                      <p className="flex items-center gap-2 text-xs text-zinc-200">
                        <code className="rounded bg-zinc-800 px-1 py-0.5">{key.name}</code>
                        {alternative ? (
                          <span className="inline-flex items-center gap-1 text-emerald-300">
                            <CheckCircle2 size={12} /> {alternative} presente na plataforma
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-amber-300">
                            <AlertTriangle size={12} /> por definir
                          </span>
                        )}
                      </p>
                      <p className="mt-1 text-xs text-zinc-400">{key.role}</p>
                      <p className="mt-1 text-[11px] text-zinc-500">{key.detail}</p>
                    </div>
                  );
                })}
              </div>
              <p className="text-[11px] text-zinc-500">{diagnose.note}</p>
              <div className="space-y-1 text-[11px] text-zinc-400">
                {Object.entries(diagnose.commands).map(([label, command]) => (
                  <p key={label} className="flex flex-wrap items-center gap-2">
                    <span className="text-zinc-500">{label}:</span>
                    <code className="select-all rounded bg-zinc-800 px-1 py-0.5 text-zinc-200">{command}</code>
                  </p>
                ))}
              </div>
              {diagnose.last_error?.error && (
                <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-3 text-xs text-red-200">
                  <p className="font-medium">Último erro ({diagnose.last_error.at})</p>
                  <p className="mt-1">{diagnose.last_error.error}</p>
                  {diagnose.last_error.hint && <p className="mt-1 text-red-300/90">{diagnose.last_error.hint}</p>}
                </div>
              )}
            </div>
          )}
        </section>

        <section className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
            <KeyRound size={16} className="text-cyan-400" /> Chaves do motor (LLM e Zep)
          </h2>
          <p className="text-xs text-zinc-400">
            O contentor do MiroFish lê as chaves do <code className="rounded bg-zinc-800 px-1">.env</code> do projeto. Aqui pode
            passar a chave de um fornecedor já configurado na plataforma e atualizar a chave do Zep Cloud (obrigatória para
            o serviço arrancar).
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <p className="text-xs font-medium text-zinc-300">LLM — fornecedor da plataforma</p>
              <select
                value={llmProvider}
                onChange={(event) => setLlmProvider(event.target.value)}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              >
                <option value="">— escolher fornecedor —</option>
                {(settings?.providers ?? []).map((provider) => (
                  <option key={provider.id} value={provider.id} disabled={!provider.usable}>
                    {provider.label}
                    {provider.key_hint ? ` · chave ${provider.key_hint}` : " · sem chave"}
                  </option>
                ))}
              </select>
              <input
                value={llmModel}
                onChange={(event) => setLlmModel(event.target.value)}
                placeholder="Modelo (vazio = o predefinido do fornecedor)"
                autoComplete="off"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              />
              <input
                value={llmBaseUrl}
                onChange={(event) => setLlmBaseUrl(event.target.value)}
                placeholder="Base URL (opcional)"
                autoComplete="off"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              />
              <input
                type="password"
                value={llmKey}
                onChange={(event) => setLlmKey(event.target.value)}
                placeholder="Chave personalizada (opcional)"
                autoComplete="new-password"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              />
              {settings?.settings.llm_key_hint ? (
                <p className="text-[11px] text-emerald-300">
                  em uso: {settings.settings.llm_key_hint} · {settings.settings.llm_provider} · {settings.settings.llm_key_source}
                </p>
              ) : (
                <p className="text-[11px] text-amber-300">ainda sem chave de LLM</p>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-zinc-300">Zep Cloud</p>
              <input
                type="password"
                value={zepKey}
                onChange={(event) => setZepKey(event.target.value)}
                placeholder={
                  settings?.settings.zep_key_set
                    ? `guardada (${settings.settings.zep_key_hint}) — cole outra para substituir`
                    : "chave do Zep Cloud (app.getzep.com)"
                }
                autoComplete="new-password"
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              />
              <p className="text-[11px] text-zinc-500">
                Grafo de conhecimento e memória de longo prazo dos agentes. Sem esta chave o MiroFish não arranca
                (<code className="rounded bg-zinc-800 px-1">run.py</code> valida a configuração).
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => void handleSaveSettings(false)}
              disabled={Boolean(busy)}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white disabled:opacity-50"
            >
              {busy === "save" ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              Guardar
            </button>
            <button
              onClick={() => void handleSaveSettings(true)}
              disabled={Boolean(busy)}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
            >
              {busy === "apply" ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              Guardar e recriar o serviço
            </button>
            {settings?.env.exists && (
              <span className="text-[11px] text-zinc-500">
                {settings.env.path} · llm {settings.env.llm_key_hint || "—"} · zep {settings.env.zep_key_hint || "—"} ·{" "}
                {settings.env.in_sync ? "em sincronia" : "recriar para aplicar"}
              </span>
            )}
          </div>
          {applied && (
            <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-[11px] text-zinc-400">
              <p>
                Escritas: {applied.written.join(", ")} → <code className="text-zinc-300">{applied.env_path}</code>
              </p>
              {applied.recreate && (
                <p>
                  Recriação do contentor: {applied.recreate.ok ? "ok" : "não aplicada"} —{" "}
                  <code className="text-zinc-300">{applied.recreate.command}</code>
                </p>
              )}
              {applied.recreate?.output?.length ? (
                <pre className="max-h-40 overflow-auto text-zinc-500">{applied.recreate.output.join("\n")}</pre>
              ) : null}
              {applied.recreate?.detail ? <p className="text-amber-300">{applied.recreate.detail}</p> : null}
            </div>
          )}
        </section>

        <section className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
            <Sparkles size={16} className="text-cyan-400" /> 1. Fonte de dados
          </h2>          <div className="flex flex-wrap gap-2">
            {sources.map((item) => (
              <button
                key={item.id}
                onClick={() => setSourceId(item.id)}
                className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                  item.id === sourceId
                    ? "border-cyan-500/70 bg-cyan-950/40 text-white"
                    : "border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-white"
                }`}
              >
                <span className="block font-medium">{item.label}</span>
                <span className="mt-0.5 block max-w-xs text-xs text-zinc-400">{item.hint}</span>
              </button>
            ))}
          </div>

          {source?.params?.length ? (
            <div className="grid gap-3 sm:grid-cols-3">
              {source.params.map((param) => (
                <label key={param.name} className="flex flex-col gap-1 text-xs text-zinc-400">
                  {param.label}
                  {param.type === "select" ? (
                    <select
                      value={params[param.name] ?? ""}
                      onChange={(event) => setParams((current) => ({ ...current, [param.name]: event.target.value }))}
                      className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    >
                      {(param.options ?? []).map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : param.type === "document" ? (
                    <select
                      value={params[param.name] ?? ""}
                      onChange={(event) => setParams((current) => ({ ...current, [param.name]: event.target.value }))}
                      className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    >
                      <option value="">— escolher documento —</option>
                      {documents.map((document) => (
                        <option key={document.id} value={document.id}>
                          {document.title || document.id}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={param.type === "number" ? "number" : "text"}
                      value={params[param.name] ?? ""}
                      placeholder={param.placeholder}
                      min={param.min}
                      max={param.max}
                      autoComplete="off"
                      onChange={(event) => setParams((current) => ({ ...current, [param.name]: event.target.value }))}
                      className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
                    />
                  )}
                </label>
              ))}
            </div>
          ) : null}
        </section>

        <section className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
            <BrainCircuit size={16} className="text-cyan-400" /> 2. Pedido de previsão
          </h2>
          <textarea
            value={requirement}
            onChange={(event) => setRequirement(event.target.value)}
            rows={4}
            placeholder="O que quer que o mundo simulado antecipe? (ex.: evolução da empresa no mercado de contratação pública nos próximos 12 meses)"
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
              {Object.entries(STEP_LABELS).map(([key, label]) => (
                <label key={key} className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(steps[key])}
                    onChange={(event) => setSteps((current) => ({ ...current, [key]: event.target.checked }))}
                    className="h-4 w-4 rounded border-zinc-600 bg-zinc-900"
                  />
                  {label}
                </label>
              ))}
            </div>
            <label className="flex flex-col gap-1 text-xs text-zinc-400">
              Rondas (opcional)
              <input
                type="number"
                min={1}
                max={500}
                value={maxRounds}
                onChange={(event) => setMaxRounds(event.target.value)}
                placeholder="ex.: 10"
                className="w-28 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-zinc-400">
              Plataforma
              <select
                value={platform}
                onChange={(event) => setPlatform(event.target.value)}
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
              >
                <option value="parallel">parallel</option>
                <option value="twitter">twitter</option>
                <option value="reddit">reddit</option>
              </select>
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => void handlePreview()}
              disabled={Boolean(busy)}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white disabled:opacity-50"
            >
              {busy === "preview" ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
              Pré-visualizar semente
            </button>
            <button
              onClick={() => void handleSaveSeed()}
              disabled={Boolean(busy)}
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-500 hover:text-white disabled:opacity-50"
            >
              {busy === "save" ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              Guardar no Office
            </button>
            <button
              onClick={() => void handleSimulate()}
              disabled={!canSimulate}
              title={serviceAvailable ? undefined : "O serviço MiroFish não está disponível"}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
            >
              {busy === "simulate" ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              Simular com estes dados
            </button>
          </div>

          {error && <p className="rounded-lg border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-200">{error}</p>}
          {notice && <p className="rounded-lg border border-emerald-900/50 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-200">{notice}</p>}
        </section>

        {seed && (
          <section className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
            <h2 className="flex items-center justify-between text-sm font-semibold text-zinc-200">
              <span>Documento-semente «{seed.title}»</span>
              <span className="text-xs font-normal text-zinc-500">
                {formatNumber(seed.chars)} caracteres · {formatNumber(seed.words)} palavras · {seed.filename}
              </span>
            </h2>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-300">
              {seed.markdown}
            </pre>
          </section>
        )}

        <section className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
            <Play size={16} className="text-cyan-400" /> Trabalhos de simulação
          </h2>
          {!jobs.length && <p className="text-xs text-zinc-500">Ainda não há trabalhos nesta sessão.</p>}
          <div className="space-y-2">
            {jobs.map((job) => (
              <button
                key={job.id}
                onClick={() => setActiveJob(job.id)}
                className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                  selected?.id === job.id ? "border-cyan-700/70 bg-cyan-950/20" : "border-zinc-800 hover:border-zinc-700"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-zinc-200">
                    {job.title} <span className="text-xs text-zinc-500">· {job.id}</span>
                  </span>
                  <StatusPill status={job.status} />
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className={`h-full rounded-full ${job.status === "failed" ? "bg-red-500" : "bg-cyan-500"}`}
                    style={{ width: `${Math.max(2, Math.min(100, job.progress || 0))}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-zinc-500">
                  passo <span className="text-zinc-400">{job.step}</span> · {job.progress}% · atualizado{" "}
                  {new Date(job.updated_at).toLocaleTimeString("pt-PT")}
                </p>
              </button>
            ))}
          </div>

          {selected && (
            <div className="space-y-2">
              {selected.error && (
                <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-200">
                  <p>{selected.error}</p>
                  {selected.hint && <p className="mt-1 text-red-300/90">{selected.hint}</p>}
                </div>
              )}
              {Object.keys(selected.result || {}).length > 0 && (
                <p className="text-xs text-zinc-400">
                  Projeto: <span className="text-zinc-200">{String(selected.result.project_id ?? "—")}</span> · Simulação:{" "}
                  <span className="text-zinc-200">{String(selected.result.simulation_id ?? "—")}</span>
                  {selected.result.report_id ? (
                    <>
                      {" "}
                      · Relatório: <span className="text-zinc-200">{String(selected.result.report_id)}</span>
                    </>
                  ) : null}
                </p>
              )}
              <pre className="max-h-72 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs leading-relaxed text-zinc-400">
                {(selected.log || []).map((entry) => `${entry.at}  ${entry.message}`).join("\n") || "sem registo"}
              </pre>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
