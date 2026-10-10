/**
 * **Relatório PDF do benchmark** — pedido pago por MB Way.
 *
 * Aparece no fundo de cada página do benchmark e leva o âmbito que está no ecrã
 * (a empresa e o CPV, o quadro por CPV dos três países, ou o cruzamento entre
 * países). O preço é o que estiver configurado no backoffice de relatórios
 * (pacote «Relatório de Benchmark»), pelo que a página não tem preços próprios.
 *
 * O percurso é o da área «Relatórios»: cria-se o pedido, pede-se o pagamento MB
 * Way (automático quando há chave de API; à mão, com confirmação do backoffice,
 * quando não há), o PDF é gerado automaticamente após o pagamento e fica
 * disponível para descarregar aqui mesmo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, FileText, Loader2, Smartphone } from "lucide-react";

import { Button } from "../ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { Input } from "../ui/Input";
import { Label } from "../ui/Label";
import { requestBenchmarkReport, type BenchmarkReportParams, type BenchmarkReportOrder } from "../../benchmarkApi";
import {
  declareReportPayment,
  downloadReportFile,
  getReportPaymentStatus,
  getReportsCatalogue,
  money,
} from "../../reportsApi";

type Estado = "inicial" | "criado" | "aguarda" | "pago" | "pronto";

function estadoDoPedido(pedido: BenchmarkReportOrder): Estado {
  if (pedido.files?.length) return "pronto";
  if (pedido.payment?.status === "confirmado" || ["pagamento_confirmado", "em_producao"].includes(pedido.status)) {
    return "pago";
  }
  if (pedido.payment?.provider_request_id || pedido.payment?.status === "aguarda_confirmacao") return "aguarda";
  return "criado";
}

export default function BenchmarkReportCard({
  params,
  resumo,
  pronto,
  aviso,
}: {
  /** Âmbito do relatório (o que está no ecrã). */
  params: BenchmarkReportParams;
  /** Descrição curta do que vai no PDF. */
  resumo: string;
  /** `false` enquanto a página não tem dados suficientes para o pedido. */
  pronto: boolean;
  /** Nota sobre o que falta para poder pedir (mostrada quando `pronto` é falso). */
  aviso?: string;
}) {
  const [preco, setPreco] = useState<{ price: number; title: string; vat_rate: number } | null>(null);
  const [telefone, setTelefone] = useState("");
  const [pedido, setPedido] = useState<BenchmarkReportOrder | null>(null);
  const [automatico, setAutomatico] = useState<{ configured: boolean; ok: boolean; message?: string } | null>(null);
  const [instrucoes, setInstrucoes] = useState("");
  const [aCarregar, setACarregar] = useState(false);
  const [aVerificar, setAVerificar] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [pagamentoIndicado, setPagamentoIndicado] = useState(false);
  const temporizador = useRef<number | null>(null);

  const chave = useMemo(() => JSON.stringify(params), [params]);

  useEffect(() => {
    getReportsCatalogue()
      .then((catalogo) => {
        const pacote = catalogo.packages.find((item) => item.id === "benchmark");
        if (pacote) {
          setPreco({ price: pacote.price, title: pacote.title, vat_rate: catalogo.settings.vat_rate });
        }
        setInstrucoes(
          `${catalogo.settings.payment_instructions}${
            catalogo.settings.mbway_number ? ` Número MB Way: ${catalogo.settings.mbway_number}.` : ""
          }`,
        );
      })
      .catch(() => setPreco(null));
  }, []);

  // Cada mudança de âmbito invalida o pedido anterior (é outro relatório).
  useEffect(() => {
    setPedido(null);
    setErro(null);
    setAutomatico(null);
  }, [chave]);

  useEffect(() => {
    return () => {
      if (temporizador.current) window.clearTimeout(temporizador.current);
    };
  }, []);

  const verificar = useCallback(
    async (id: string) => {
      setAVerificar(true);
      try {
        const resultado = await getReportPaymentStatus(id);
        setPedido(resultado.request);
        return resultado.request;
      } catch (err) {
        setErro(err instanceof Error ? err.message : String(err));
        return null;
      } finally {
        setAVerificar(false);
      }
    },
    [],
  );

  // Enquanto o pagamento estiver pendente, pergunta-se de tempos a tempos se já
  // foi aprovado: no automático, à espera da app MB Way; no manual, à espera de
  // o backoffice confirmar (o PDF é gerado nesse momento).
  useEffect(() => {
    if (!pedido) return;
    if (estadoDoPedido(pedido) !== "aguarda") return;
    const id = pedido.id;
    const espera = automatico?.ok && pedido.payment.provider_request_id ? 6000 : 12000;
    temporizador.current = window.setTimeout(() => {
      void verificar(id);
    }, espera);
    return () => {
      if (temporizador.current) window.clearTimeout(temporizador.current);
    };
  }, [pedido, automatico, verificar]);

  const pedir = async () => {
    setACarregar(true);
    setErro(null);
    try {
      const resposta = await requestBenchmarkReport({ ...params, mbway_phone: telefone.trim() });
      setPedido(resposta.request);
      setAutomatico(resposta.automatic);
      setInstrucoes(resposta.settings.payment_instructions);
      setPagamentoIndicado(false);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregar(false);
    }
  };

  const jaPaguei = async () => {
    if (!pedido) return;
    setACarregar(true);
    setErro(null);
    try {
      const resultado = await declareReportPayment(pedido.id, {
        method: "mbway",
        mbway_phone: telefone.trim(),
        note: "Pagamento indicado na página do benchmark.",
      });
      setPedido(resultado.request);
      setAutomatico(resultado.automatic ?? null);
      setPagamentoIndicado(true);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregar(false);
    }
  };

  const descarregar = async () => {
    if (!pedido?.files?.length) return;
    const ficheiro = pedido.files[0];
    setACarregar(true);
    try {
      await downloadReportFile(pedido.id, ficheiro.id, ficheiro.name);
      const atualizado = await verificar(pedido.id);
      if (atualizado) setPedido(atualizado);
    } catch (err) {
      setErro(err instanceof Error ? err.message : String(err));
    } finally {
      setACarregar(false);
    }
  };

  const estado = pedido ? estadoDoPedido(pedido) : "inicial";

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center gap-2 pb-2">
        <FileText size={16} className="text-muted-foreground" />
        <CardTitle className="text-sm">Relatório PDF</CardTitle>
        {preco ? (
          <span className="rounded-full border border-border px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
            {money(preco.price)} · entrega automática
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">{resumo}</span>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {!pronto ? (
          <p className="text-sm text-muted-foreground">{aviso || "Complete os dados para poder pedir o relatório."}</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {preco
                ? `O PDF é gerado a partir dos mesmos dados desta página (${preco.title}) e fica disponível para descarregar depois do pagamento.`
                : "O PDF é gerado a partir dos mesmos dados desta página, depois do pagamento."}
            </p>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_auto]">
              <div>
                <Label htmlFor="bench-report-telefone">Telemóvel MB Way</Label>
                <Input
                  id="bench-report-telefone"
                  className="mt-1"
                  inputMode="tel"
                  autoComplete="off"
                  placeholder="9xx xxx xxx"
                  value={telefone}
                  onChange={(e) => setTelefone(e.target.value)}
                  disabled={Boolean(pedido && estado !== "inicial")}
                />
              </div>
              <div className="flex items-end">
                <Button
                  onClick={() => void pedir()}
                  loading={aCarregar && !pedido}
                  disabled={Boolean(pedido) || !telefone.trim()}
                  icon={<Smartphone size={16} />}
                >
                  Pedir relatório
                </Button>
              </div>
              {estado === "aguarda" && pedido ? (
                <div className="flex items-end">
                  <Button variant="outline" size="md" onClick={() => void verificar(pedido.id)} loading={aVerificar}>
                    Verificar estado
                  </Button>
                </div>
              ) : null}
              {estado === "criado" ? (
                <div className="flex items-end">
                  <Button variant="outline" size="md" onClick={() => void jaPaguei()} loading={aCarregar}>
                    Já paguei
                  </Button>
                </div>
              ) : null}
              {estado === "pronto" ? (
                <div className="flex items-end">
                  <Button onClick={() => void descarregar()} loading={aCarregar} icon={<Download size={16} />}>
                    Descarregar PDF
                  </Button>
                </div>
              ) : null}
            </div>

            {pedido ? (
              <div className="space-y-2 rounded-xl border border-border/60 bg-white/[0.02] px-3 py-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">Pedido {pedido.reference}</span>
                  <span className="text-muted-foreground">
                    {money(pedido.amounts?.total)} (IVA {pedido.amounts?.vat_rate?.toFixed(0) ?? "23"}% incluído)
                  </span>
                  <span className="ml-auto flex items-center gap-1 text-muted-foreground">
                    {estado === "pronto" ? (
                      <CheckCircle2 size={13} className="text-emerald-300" />
                    ) : (
                      <Loader2 size={13} className={estado === "aguarda" || estado === "pago" ? "animate-spin" : ""} />
                    )}
                    {estado === "criado"
                      ? "Falta o pagamento"
                      : estado === "aguarda"
                        ? automatico?.ok
                          ? "Aguarda aprovação no MB Way"
                          : "Aguarda confirmação do backoffice"
                        : estado === "pago"
                          ? "Pagamento confirmado — a gerar o PDF"
                          : "Pronto para descarregar"}
                  </span>
                </div>
                {estado === "criado" && instrucoes ? <p className="text-muted-foreground">{instrucoes}</p> : null}
                {estado === "aguarda" && automatico?.ok ? (
                  <p className="text-muted-foreground">
                    Abra a app MB Way no telemóvel {pedido.payment.mbway_phone || "indicado"} e aprove o pedido. Esta
                    página verifica sozinha.
                  </p>
                ) : null}
                {pagamentoIndicado && estado === "aguarda" ? (
                  <p className="text-muted-foreground">
                    Obrigado — o backoffice confirma o pagamento e o PDF é gerado a seguir.
                  </p>
                ) : null}
                {estado === "pago" ? <p className="text-muted-foreground">O PDF está a ser gerado…</p> : null}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Sem chave de API do MB Way configurada, o pagamento é feito para o número da plataforma e confirmado
                pelo backoffice; com a chave, o pedido aparece na app MB Way e o PDF sai sozinho.
              </p>
            )}

            {erro ? (
              <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span className="flex-1">{erro}</span>
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
