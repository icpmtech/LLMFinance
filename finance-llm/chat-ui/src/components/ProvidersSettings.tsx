/**
 * Secção «Fornecedores de IA» das Definições.
 *
 * Cada fornecedor externo (OpenAI, DeepSeek, xAI/Grok, Anthropic, Gemini, Groq,
 * Mistral, OpenRouter, Ollama local) tem aqui a sua chave de API, o modelo
 * predefinido e um botão de teste. As chaves ficam guardadas por utilizador no
 * Elasticsearch (`finance_provider_keys`) e nunca são devolvidas em claro — a
 * interface só mostra a pista mascarada (`sk-…abcd`).
 */
import { useState } from "react";
import { AlertCircle, CheckCircle2, Cpu, ExternalLink, KeyRound, Loader2, PlugZap, Trash2 } from "lucide-react";
import { useProviders, type ProviderInfo } from "../providers";

type Message = { kind: "ok" | "error"; text: string } | null;

function Badge({ tone, children }: { tone: "ok" | "warn" | "muted" | "info"; children: React.ReactNode }) {
  const tones: Record<string, string> = {
    ok: "border-teal-300/30 bg-teal-400/10 text-teal-200",
    warn: "border-amber-300/30 bg-amber-400/10 text-amber-200",
    muted: "border-white/10 bg-white/[0.04] text-muted-foreground",
    info: "border-sky-300/25 bg-sky-400/10 text-sky-200",
  };
  return <span className={`rounded-full border px-2 py-0.5 text-[10.5px] ${tones[tone]}`}>{children}</span>;
}

function ProviderRow({ provider, onChanged }: { provider: ProviderInfo; onChanged: () => Promise<void> }) {
  const { saveKey, testProvider, saveDefaults } = useProviders();
  const [key, setKey] = useState("");
  const [model, setModel] = useState(provider.default_model);
  const [busy, setBusy] = useState<"save" | "test" | "clear" | null>(null);
  const [message, setMessage] = useState<Message>(null);

  const run = async (action: "save" | "test" | "clear", fn: () => Promise<unknown>) => {
    setBusy(action);
    setMessage(null);
    try {
      await fn();
      await onChanged();
      setMessage({ kind: "ok", text: action === "test" ? "Ligação estabelecida com sucesso." : "Guardado." });
      if (action !== "test") setKey("");
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof Error ? error.message : "Erro inesperado." });
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] font-medium">{provider.label}</span>
        {provider.key_source === "user" && <Badge tone="ok">chave própria {provider.key_hint}</Badge>}
        {provider.key_source === "env" && <Badge tone="info">chave do servidor ({provider.env})</Badge>}
        {provider.key_source === "none" && provider.configured && <Badge tone="muted">sem chave necessária</Badge>}
        {provider.key_source === "none" && !provider.configured && <Badge tone="warn">sem chave</Badge>}
        {provider.docs_url && (
          <a
            href={provider.docs_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground transition hover:text-foreground"
          >
            obter chave <ExternalLink size={11} />
          </a>
        )}
      </div>

      {provider.notes && <p className="mt-1 text-[11px] text-muted-foreground">{provider.notes}</p>}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <label className="relative flex min-w-[220px] flex-1 items-center">
          <KeyRound size={12} className="pointer-events-none absolute left-2 text-muted-foreground" />
          <input
            type="password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder={provider.has_user_key ? "substituir chave guardada…" : provider.requires_key ? "cola a chave de API…" : "opcional (Ollama local)"}
            autoComplete="off"
            className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1.5 pl-7 pr-2 text-[11.5px] outline-none transition focus:border-teal-300/40"
          />
        </label>
        <select
          value={model}
          onChange={(event) => setModel(event.target.value)}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[11.5px]"
          title="Modelo deste fornecedor"
        >
          {provider.models.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void run("save", () => saveKey(provider.id, key))}
          disabled={busy !== null || (!key.trim() && provider.requires_key && provider.key_source !== "user")}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[11.5px] transition hover:bg-white/[0.1] disabled:opacity-40"
        >
          {busy === "save" ? <Loader2 size={12} className="animate-spin" /> : <KeyRound size={12} />} Guardar
        </button>
        <button
          type="button"
          onClick={() => void run("test", () => testProvider(provider.id, model, key.trim() || undefined))}
          disabled={busy !== null || (!provider.configured && !key.trim())}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 text-[11.5px] transition hover:bg-white/[0.1] disabled:opacity-40"
        >
          {busy === "test" ? <Loader2 size={12} className="animate-spin" /> : <PlugZap size={12} />} Testar
        </button>
        {provider.has_user_key && (
          <button
            type="button"
            onClick={() => void run("clear", () => saveKey(provider.id, ""))}
            disabled={busy !== null}
            title="Remover a chave guardada"
            className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-[11.5px] text-muted-foreground transition hover:text-rose-200 disabled:opacity-40"
          >
            <Trash2 size={12} />
          </button>
        )}
        <button
          type="button"
          onClick={() =>
            void saveDefaults({ provider: provider.id, model }).then(() =>
              setMessage({ kind: "ok", text: `${provider.label} · ${model} é agora o modelo predefinido do chat.` }),
            )
          }
          title="Usar como predefinição do chat"
          className="rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-[11.5px] text-muted-foreground transition hover:text-foreground"
        >
          Tornar predefinido
        </button>
      </div>

      {message && (
        <p
          className={[
            "mt-2 flex items-center gap-1.5 text-[11px]",
            message.kind === "ok" ? "text-teal-200" : "text-rose-200",
          ].join(" ")}
        >
          {message.kind === "ok" ? <CheckCircle2 size={11} /> : <AlertCircle size={11} />}
          {message.text}
        </p>
      )}
    </li>
  );
}

export function ProvidersSettings() {
  const { providers, defaults, refresh } = useProviders();
  const [refreshing, setRefreshing] = useState(false);
  const cloud = providers.filter((provider) => provider.kind !== "local");
  const local = providers.filter((provider) => provider.kind === "local");

  const onChanged = async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <section className="glass-card rounded-2xl p-5">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Cpu size={15} className="text-violet-300" />
          Fornecedores de IA
        </h2>
        <div className="flex items-center gap-2">
          {defaults.provider && (
            <Badge tone="info">
              predefinido: {defaults.provider}
              {defaults.model ? ` · ${defaults.model}` : ""}
            </Badge>
          )}
          <button
            type="button"
            onClick={() => void onChanged()}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1 text-[11.5px] text-muted-foreground transition hover:bg-white/5"
          >
            {refreshing ? <Loader2 size={12} className="animate-spin" /> : <PlugZap size={12} />} Atualizar estado
          </button>
        </div>
      </header>

      <p className="mb-3 text-[11.5px] leading-relaxed text-muted-foreground">
        Escolha no <strong>chat</strong> (selector «Modelo») entre os modelos locais da plataforma e os fornecedores
        abaixo. As chaves ficam guardadas na sua conta, no Elasticsearch, e nunca são apresentadas em claro; se o
        servidor tiver as variáveis <span className="font-mono">OPENAI_API_KEY</span>,{" "}
        <span className="font-mono">DEEPSEEK_API_KEY</span>, <span className="font-mono">XAI_API_KEY</span>,
        <span className="font-mono"> ANTHROPIC_API_KEY</span>, <span className="font-mono">GEMINI_API_KEY</span>,{" "}
        <span className="font-mono">GROQ_API_KEY</span> ou <span className="font-mono">MISTRAL_API_KEY</span>, a chave
        pessoal é opcional.
      </p>

      <ul className="space-y-2">
        {cloud.map((provider) => (
          <ProviderRow key={provider.id} provider={provider} onChanged={onChanged} />
        ))}
      </ul>

      {local.length > 0 && (
        <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Modelos locais (sem chave)</p>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {local.map((provider) => (
              <li key={provider.id} className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px]">
                {provider.label}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            A inferência local continua a funcionar, mas é mais limitada do que os modelos externos.
          </p>
        </div>
      )}
    </section>
  );
}
