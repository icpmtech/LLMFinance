/**
 * Página **Estúdio de relatórios** (`/report-studio`).
 *
 * Página própria para a equipa (administradores e gestores de relatórios)
 * criar, publicar e vender relatórios: escolhe um modelo, junta indicadores,
 * gráficos, tabelas e grafos sobre as fontes da plataforma, pede ajuda à IA,
 * gera o PDF e publica-o no catálogo da plataforma ou na loja, com preço.
 *
 * O corpo do estúdio é o mesmo componente usado dentro de «Relatórios»
 * (`ReportsStudioTab`); o que esta página acrescenta é a casca: cabeçalho, o
 * atalho de volta, o aviso de acesso e as notificações.
 *
 * O acesso é decidido pela API (`GET /reports/studio/me`): sem ele a página
 * explica o que fazer em vez de mostrar um ecrã vazio.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Loader2, ReceiptText, ShieldAlert } from "lucide-react";
import { Badge, Button, Card, CardContent } from "../components/ui";
import { ReportsStudioTab } from "./ReportsStudio";
import { getStudioMe, type StudioAccess } from "../reportsStudioApi";

type Toast = { id: number; message: string; tone: "info" | "ok" | "error" };

export default function ReportStudioPage({ onNavigate }: { onNavigate?: (view: string) => void }) {
  const [access, setAccess] = useState<StudioAccess | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<number[]>([]);

  const notify = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { ...toast, id }]);
    timers.current.push(window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4600));
  }, []);

  useEffect(() => () => timers.current.forEach((timer) => window.clearTimeout(timer)), []);

  useEffect(() => {
    let vivo = true;
    void getStudioMe()
      .then((me) => {
        if (vivo) setAccess(me);
      })
      .catch((err: Error) => {
        if (vivo) setError(err.message);
      })
      .finally(() => {
        if (vivo) setLoading(false);
      });
    return () => {
      vivo = false;
    };
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="border-b px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow-lg shadow-violet-500/25">
              <ReceiptText size={20} />
            </div>
            <div>
              <h1 className="flex items-center gap-2 text-lg font-semibold">
                Estúdio de relatórios
                {access?.studio ? <Badge variant="info">criação e publicação</Badge> : null}
              </h1>
              <p className="text-sm text-muted-foreground">
                Monte relatórios com as fontes da plataforma, gere o PDF e ponha-os à venda — no catálogo ou na loja
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {access?.studio && (
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {access.email} · {access.role}
                {access.manager ? " · gestor de relatórios" : ""}
              </span>
            )}
            {onNavigate && (
              <Button variant="outline" size="sm" onClick={() => onNavigate("reports")} title="Ir para os relatórios a pedido">
                <ArrowLeft size={14} /> Relatórios
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" /> A validar o acesso ao estúdio…
          </div>
        )}

        {!loading && (error || !access?.studio) && (
          <Card className="max-w-2xl">
            <CardContent className="space-y-3 pt-6">
              <p className="flex items-center gap-2 text-sm font-medium">
                <ShieldAlert size={16} className="text-amber-400" /> O estúdio está reservado a administradores e gestores de relatórios
              </p>
              <p className="text-sm text-muted-foreground">
                {error
                  ? error
                  : "Peça a um administrador para o autorizar em Administração → Relatórios → Definições, na lista «Gestores de relatórios». Os administradores e os gestores de plataforma têm acesso automático."}
              </p>
              {onNavigate && (
                <Button variant="outline" size="sm" onClick={() => onNavigate("reports")}>
                  <ArrowLeft size={14} /> Voltar aos relatórios
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        {!loading && access?.studio && (
          <>
            {error && <p className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{error}</p>}
            <ReportsStudioTab onError={setError} onToast={notify} />
          </>
        )}
      </main>

      <div className="pointer-events-none fixed bottom-6 right-4 z-[140] flex flex-col items-end gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto rounded-xl border px-3 py-2 text-xs shadow-2xl ${
              toast.tone === "ok"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : toast.tone === "error"
                  ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                  : "border-border bg-card text-muted-foreground"
            }`}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
