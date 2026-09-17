/**
 * Terminal: executa o CLI do IQ OS a partir da interface.
 *
 * Envia a linha de comando para `POST /cli/run`, que corre o CLI num
 * subprocesso com a sessão do utilizador autenticado, e mostra o resultado
 * (stdout/stderr, código de saída e duração) numa consola com histórico.
 *
 * Só é permitido o que o CLI expõe — as operações de conta (login, registo,
 * logout, palavra-passe) fazem-se nas Definições ou no terminal local.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronRight,
  Clock,
  Copy,
  Eraser,
  Info,
  Loader2,
  Play,
  Terminal as TerminalIcon,
} from "lucide-react";
import { useAuth } from "../auth";
import { getToken } from "../authApi";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";
const HISTORY_KEY = "finance-llm-cli-history";
const MAX_HISTORY = 60;

type Entry = {
  id: string;
  command: string;
  stdout: string;
  stderr: string;
  exitCode: number;
  durationMs: number;
  timedOut: boolean;
};

type CommandInfo = { command: string; subcommands: string[] };

const SUGGESTIONS: { label: string; command: string; hint: string }[] = [
  { label: "Estado", command: "status", hint: "API, Elasticsearch e sessão" },
  { label: "Contratos", command: 'contracts search "obras" --year 2025 --size 5', hint: "pesquisar contratos públicos" },
  { label: "Empresa", command: "companies get 503140600", hint: "ficha + marcas + firmas" },
  { label: "Estatísticas", command: "entities stats", hint: "cadastro de entidades" },
  { label: "Cotação", command: "market quote AAPL", hint: "preço e variação" },
  { label: "Previsão", command: "forecast AAPL --days 5", hint: "ARIMA/Kronos" },
  { label: "Sessões", command: "auth sessions", hint: "sessões ativas da conta" },
  { label: "Ajuda", command: "help", hint: "comandos disponíveis" },
];

function loadHistory(): string[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export default function CliPage() {
  const { user } = useAuth();
  const [command, setCommand] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [history, setHistory] = useState<string[]>(loadHistory);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<CommandInfo[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [copied, setCopied] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const outputRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /* Catálogo de comandos disponíveis (para a paleta lateral). */
  useEffect(() => {
    const token = getToken();
    void fetch(`${API_BASE}/cli/commands`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { commands?: CommandInfo[] } | null) => {
        if (data?.commands) setCatalog(data.commands);
      })
      .catch(() => undefined);
  }, []);

  /* Cronómetro enquanto um comando corre. */
  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 100);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    const node = outputRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [entries, running]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const suggestions = useMemo(() => {
    const term = command.trim().toLowerCase();
    if (!term) return catalog;
    return catalog.filter((item) => item.command.startsWith(term.split(/\s+/)[0]));
  }, [catalog, command]);

  const runCommand = useCallback(
    async (raw: string) => {
      const line = raw.trim();
      if (!line || running) return;

      if (line === "help" || line === "?") {
        setEntries((previous) => [
          ...previous,
          {
            id: `${Date.now()}-help`,
            command: "help",
            stdout: [
              "Comandos disponíveis no terminal da interface:",
              "",
              ...catalog.map((item) =>
                item.subcommands.length
                  ? `  ${item.command.padEnd(10)} ${item.subcommands.join(" | ")}`
                  : `  ${item.command}`,
              ),
              "",
              "Exemplos:",
              ...SUGGESTIONS.map((item) => `  ${item.command.padEnd(48)} # ${item.hint}`),
              "",
              "Notas: --json devolve JSON; as opções --api/--token são definidas pelo servidor;",
              "      login/registo/logout/palavra-passe fazem-se nas Definições da conta.",
            ].join("\n"),
            stderr: "",
            exitCode: 0,
            durationMs: 0,
            timedOut: false,
          },
        ]);
        setCommand("");
        return;
      }

      const nextHistory = [line, ...history.filter((item) => item !== line)].slice(0, MAX_HISTORY);
      setHistory(nextHistory);
      setHistoryIndex(null);
      try {
        window.localStorage.setItem(HISTORY_KEY, JSON.stringify(nextHistory));
      } catch {
        // sem persistência
      }

      setRunning(true);
      setError(null);
      setCommand("");
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const token = getToken();
        const response = await fetch(`${API_BASE}/cli/run`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ command: line }),
          signal: controller.signal,
        });
        const payload = await response.json().catch(() => null);

        if (!response.ok) {
          // Erros de validação são mostrados no próprio histórico (não em duplicado).
          setEntries((previous) => [
            ...previous,
            {
              id: `${Date.now()}-error`,
              command: line,
              stdout: "",
              stderr: (payload as { detail?: string } | null)?.detail ?? `Erro ${response.status}`,
              exitCode: 1,
              durationMs: 0,
              timedOut: false,
            },
          ]);
          return;
        }

        const result = payload as {
          command: string;
          stdout: string;
          stderr: string;
          exit_code: number;
          duration_ms: number;
          timed_out: boolean;
        };
        setEntries((previous) => [
          ...previous,
          {
            id: `${Date.now()}-out`,
            command: result.command,
            stdout: result.stdout,
            stderr: result.stderr,
            exitCode: result.exit_code,
            durationMs: result.duration_ms,
            timedOut: result.timed_out,
          },
        ]);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          setError("Execução cancelada.");
        } else {
          setError("Não foi possível contactar a API.");
        }
      } finally {
        setRunning(false);
        abortRef.current = null;
        inputRef.current?.focus();
      }
    },
    [catalog, history, running],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void runCommand(command);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (history.length === 0) return;
      const next = historyIndex === null ? 0 : Math.min(history.length - 1, historyIndex + 1);
      setHistoryIndex(next);
      setCommand(history[next]);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (historyIndex === null) return;
      const next = historyIndex - 1;
      if (next < 0) {
        setHistoryIndex(null);
        setCommand("");
        return;
      }
      setHistoryIndex(next);
      setCommand(history[next]);
      return;
    }
    if (event.key === "Tab") {
      const first = suggestions[0];
      if (!first) return;
      event.preventDefault();
      const parts = command.trim().split(/\s+/);
      if (parts.length <= 1) {
        setCommand(first.subcommands.length ? `${first.command} ` : first.command);
      } else if (parts.length === 2 && first.command === parts[0] && first.subcommands.length) {
        setCommand(`${parts[0]} ${first.subcommands.find((sub) => sub.startsWith(parts[1])) ?? first.subcommands[0]} `);
      }
    }
  };

  const copyEntry = async (entry: Entry) => {
    const text = [entry.stdout, entry.stderr].filter(Boolean).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(entry.id);
      window.setTimeout(() => setCopied(null), 1200);
    } catch {
      // sem permissão de área de transferência
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <TerminalIcon size={13} className="text-teal-300" /> Ferramentas
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Terminal</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            O CLI da plataforma, dentro da aplicação. Corre com a sua sessão
            {user ? ` (${user.email})` : ""} e devolve a saída tal como no terminal.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEntries([])}
          className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
        >
          <Eraser size={13} /> Limpar
        </button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        {/* Consola */}
        <section className="glass-card overflow-hidden rounded-2xl">
          <div className="flex items-center gap-2 border-b border-white/8 px-4 py-2.5">
            <span className="flex gap-1.5" aria-hidden="true">
              <span className="h-2.5 w-2.5 rounded-full bg-rose-400/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400/70" />
              <span className="h-2.5 w-2.5 rounded-full bg-teal-400/70" />
            </span>
            <p className="ml-2 text-[11px] text-muted-foreground">finance-llm · python -m cli</p>
            {running && (
              <span className="ml-auto flex items-center gap-1.5 text-[11px] text-teal-200">
                <Loader2 size={12} className="animate-spin" /> {(elapsed / 1000).toFixed(1)}s
              </span>
            )}
          </div>

          <div
            ref={outputRef}
            className="h-[46vh] min-h-[280px] overflow-y-auto bg-[#0b0d11] px-4 py-3 font-mono text-[12px] leading-relaxed"
            role="log"
            aria-live="polite"
            aria-label="Saída do terminal"
          >
            {entries.length === 0 && !running && (
              <div className="space-y-2 text-muted-foreground">
                <p>
                  <span className="text-teal-300">finance-llm</span> pronto. Escreva um comando e pressione Enter.
                </p>
                <p className="text-[11px]">
                  Experimente <code className="rounded bg-white/5 px-1">status</code>,{" "}
                  <code className="rounded bg-white/5 px-1">help</code> ou clique numa sugestão ao lado. Use ↑/↓ para o
                  histórico e Tab para completar.
                </p>
              </div>
            )}

            {entries.map((entry) => (
              <div key={entry.id} className="mb-3">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="text-teal-300">❯</span>
                  <span className="text-foreground">{entry.command}</span>
                  {entry.durationMs > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      <Clock size={10} className="mr-1 inline" />
                      {entry.durationMs} ms
                    </span>
                  )}
                  <span
                    className={[
                      "rounded px-1.5 py-0.5 text-[10px]",
                      entry.exitCode === 0 ? "bg-teal-400/15 text-teal-200" : "bg-rose-500/15 text-rose-200",
                    ].join(" ")}
                  >
                    saída {entry.exitCode}
                    {entry.timedOut ? " · tempo excedido" : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => void copyEntry(entry)}
                    aria-label="Copiar saída"
                    className="rounded p-0.5 text-muted-foreground transition hover:text-foreground"
                  >
                    {copied === entry.id ? <Check size={12} className="text-teal-300" /> : <Copy size={12} />}
                  </button>
                </p>
                {entry.stdout && <pre className="mt-1 whitespace-pre-wrap text-foreground/90">{entry.stdout}</pre>}
                {entry.stderr && <pre className="mt-1 whitespace-pre-wrap text-rose-300">{entry.stderr}</pre>}
              </div>
            ))}

            {running && (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 size={12} className="animate-spin" /> a executar…
              </p>
            )}
          </div>

          <div className="border-t border-white/8 bg-[#0e1116] px-4 py-3">
            <div className="flex items-center gap-2 font-mono text-[12px]">
              <span className="text-teal-300">❯</span>
              <input
                ref={inputRef}
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                onKeyDown={onKeyDown}
                disabled={running}
                spellCheck={false}
                autoComplete="off"
                aria-label="Comando do CLI"
                placeholder="status | contracts search … | companies get 503140600 | help"
                className="w-full bg-transparent text-foreground outline-none placeholder:text-muted-foreground/60 disabled:opacity-50"
              />
              {running ? (
                <button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  className="rounded-lg border border-rose-400/30 px-2.5 py-1 text-[11px] text-rose-200 transition hover:bg-rose-400/10"
                >
                  Cancelar
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void runCommand(command)}
                  disabled={!command.trim()}
                  className="flex items-center gap-1.5 rounded-lg bg-teal-400/15 px-2.5 py-1 text-[11px] text-teal-200 transition hover:bg-teal-400/25 disabled:opacity-40"
                >
                  <Play size={11} /> Executar
                </button>
              )}
            </div>
            {error && (
              <p role="alert" className="mt-2 flex items-center gap-2 text-[11px] text-rose-300">
                <AlertCircle size={12} /> {error}
              </p>
            )}
          </div>
        </section>

        {/* Paleta */}
        <aside className="space-y-3">
          <section className="glass-card rounded-2xl p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sugestões</h2>
            <ul className="mt-2 space-y-1">
              {SUGGESTIONS.map((item) => (
                <li key={item.command}>
                  <button
                    type="button"
                    onClick={() => {
                      setCommand(item.command);
                      inputRef.current?.focus();
                    }}
                    title={item.command}
                    className="w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300/60"
                  >
                    <span className="flex items-center gap-1.5 text-xs font-medium">
                      <ChevronRight size={11} className="text-teal-300" />
                      {item.label}
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground">
                      {item.command}
                    </span>
                    <span className="block text-[10px] text-muted-foreground/70">{item.hint}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          {catalog.length > 0 && (
            <section className="glass-card rounded-2xl p-4">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Comandos</h2>
              <ul className="mt-2 space-y-1 font-mono text-[11px]">
                {catalog.map((item) => (
                  <li key={item.command}>
                    <button
                      type="button"
                      onClick={() => {
                        setCommand(item.subcommands[0] ? `${item.command} ${item.subcommands[0]} ` : `${item.command} `);
                        inputRef.current?.focus();
                      }}
                      className="w-full rounded px-1.5 py-1 text-left transition hover:bg-white/5"
                    >
                      <span className="text-foreground">{item.command}</span>
                      {item.subcommands.length > 0 && (
                        <span className="text-muted-foreground"> {item.subcommands.join(" ")}</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="glass-card rounded-2xl p-4">
            <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <Info size={12} /> Notas
            </h2>
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <li>O comando corre no servidor com a sua sessão (o token nunca aparece na linha).</li>
              <li>
                <code className="rounded bg-white/5 px-1">--json</code> devolve a resposta crua da API.
              </li>
              <li>Login, registo e alteração de palavra-passe fazem-se nas Definições da conta.</li>
              <li>Histórico de sessão: ↑/↓. Tab completa o comando.</li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
