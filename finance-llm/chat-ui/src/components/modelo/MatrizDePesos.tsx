/**
 * Matriz de pesos do adaptador LoRA — 24 camadas × 7 projecções.
 *
 * Cada célula é a **magnitude real** da actualização que o treino impôs àquela
 * matriz (`‖A‖·‖B‖`, lida do `adapter_model.safetensors` pela API). Clicar numa
 * célula abre o recorte das matrizes A (16×d) e B (d×16) com os valores que o
 * modelo realmente aprendeu — o mesmo número que entra na conta do forward.
 */
import { useEffect, useState } from "react";
import { Loader2, Grid3x3 } from "lucide-react";
import { getAmostraDePesos, type AmostraDePesos, type MatrizAdaptador } from "../../llmModeloApi";

const COR_BAIXA = [16, 163, 127]; // teal
const COR_ALTA = [251, 191, 36]; // âmbar

function cor(valor: number, maximo: number, alfa = 1): string {
  const t = maximo > 0 ? Math.min(1, Math.max(0, valor / maximo)) : 0;
  const [r, g, b] = COR_BAIXA.map((canal, i) => Math.round(canal + (COR_ALTA[i] - canal) * t));
  return `rgba(${r}, ${g}, ${b}, ${alfa})`;
}

function MiniMatriz({ valores, titulo, forma }: { valores: number[][]; titulo: string; forma: number[] }) {
  const planos = valores.flat();
  const escala = Math.max(...planos.map((v) => Math.abs(v)), 1e-6);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[10px] text-muted-foreground">
        <span className="font-medium text-foreground">{titulo}</span>
        <span>
          {forma[0]}×{forma[1]}
        </span>
      </div>
      <div className="inline-grid gap-[2px]" style={{ gridTemplateColumns: `repeat(${valores[0]?.length ?? 0}, 9px)` }}>
        {planos.map((valor, i) => {
          const intensidade = Math.min(1, Math.abs(valor) / escala);
          const positivo = valor >= 0;
          return (
            <div
              key={i}
              title={valor.toString()}
              className="h-[9px] w-[9px] rounded-[1px]"
              style={{
                backgroundColor: positivo ? `rgba(16,163,127,${intensidade})` : `rgba(244,63,94,${intensidade})`,
                outline: "1px solid rgba(255,255,255,0.04)",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

export default function MatrizDePesos({
  matriz,
  camadaSelecionada,
  onSelecionar,
  animar,
}: {
  matriz: MatrizAdaptador | null;
  camadaSelecionada: number;
  onSelecionar: (camada: number) => void;
  animar: boolean;
}) {
  const [amostra, setAmostra] = useState<AmostraDePesos | null>(null);
  const [modulo, setModulo] = useState("q");
  const [aCarregar, setACarregar] = useState(false);

  useEffect(() => {
    let cancelado = false;
    setACarregar(true);
    getAmostraDePesos(camadaSelecionada, modulo)
      .then((dados) => {
        if (!cancelado) setAmostra(dados);
      })
      .catch(() => {
        if (!cancelado) setAmostra(null);
      })
      .finally(() => {
        if (!cancelado) setACarregar(false);
      });
    return () => {
      cancelado = true;
    };
  }, [camadaSelecionada, modulo]);

  if (!matriz?.disponivel || !matriz.valores?.length) {
    return (
      <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
        Sem adaptador: a matriz aparece depois do primeiro treino ({matriz?.motivo ?? "sem dados"}).
      </div>
    );
  }

  const camadas = matriz.camadas ?? [];
  const modulos = matriz.modulos ?? [];
  const valores = matriz.valores;
  const maximo = matriz.maximo ?? 1;

  return (
    <div className="rounded-xl border border-border bg-card/60 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Grid3x3 size={14} className="text-primary" />
          matriz de pesos · 24 camadas × 7 projeções
        </span>
        <span className="text-[10.5px] text-muted-foreground">
          ‖A‖·‖B‖ · r={matriz.lora_r} · α={matriz.lora_alpha} · média {matriz.media?.toFixed(3)} · máx{" "}
          {matriz.maximo?.toFixed(2)}
        </span>
      </div>

      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <div className="mb-1 flex gap-[3px] pl-7">
            {modulos.map((nome) => (
              <div key={nome} className="w-[34px] text-center text-[10px] uppercase tracking-wide text-muted-foreground">
                {nome}
              </div>
            ))}
          </div>
          {valores.map((linha, indiceCamada) => {
            const camada = camadas[indiceCamada];
            return (
              <div key={camada} className="mb-[3px] flex items-center gap-[3px]">
                <button
                  type="button"
                  onClick={() => onSelecionar(camada)}
                  className={`w-6 text-right text-[10px] tabular-nums transition-colors ${
                    camada === camadaSelecionada ? "text-primary" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {camada}
                </button>
                {linha.map((valor, indiceModulo) => {
                  const nome = modulos[indiceModulo];
                  const activa = camada === camadaSelecionada && nome === modulo;
                  return (
                    <button
                      key={nome}
                      type="button"
                      title={`camada ${camada} · ${nome} · ${valor.toFixed(3)}`}
                      onClick={() => {
                        onSelecionar(camada);
                        setModulo(nome);
                      }}
                      className={`h-[16px] w-[34px] rounded-[2px] transition-transform hover:scale-[1.08] ${animar ? "mc-celula" : ""}`}
                      style={{
                        backgroundColor: cor(valor, maximo, activa ? 1 : 0.85),
                        outline: activa ? "1.5px solid #e8e9ec" : "1px solid rgba(255,255,255,0.05)",
                        animationDelay: animar ? `${((indiceCamada + indiceModulo) % 12) * 0.14}s` : undefined,
                      }}
                    />
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-3 grid gap-3 rounded-lg border border-border/70 bg-muted/20 p-3 sm:grid-cols-[auto_1fr]">
        <div className="flex flex-col gap-2">
          <div className="text-[11px] text-muted-foreground">
            camada <span className="text-foreground">{camadaSelecionada}</span> · projeção{" "}
            <span className="text-foreground">{modulo}</span>
          </div>
          {aCarregar && (
            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Loader2 size={11} className="animate-spin" /> a ler os pesos…
            </span>
          )}
          {amostra && !aCarregar && (
            <div className="flex gap-4">
              <MiniMatriz valores={amostra.A} titulo="A (16 × d)" forma={amostra.formas.A} />
              <MiniMatriz valores={amostra.B} titulo="B (d × 16)" forma={amostra.formas.B} />
            </div>
          )}
        </div>
        <div className="text-[11px] leading-relaxed text-muted-foreground">
          <p>
            LoRA não guarda uma matriz nova: guarda <code className="text-foreground">A</code> (16 × d) e{" "}
            <code className="text-foreground">B</code> (d × 16). A atualização aplicada ao modelo é{" "}
            <code className="text-foreground">B·A</code>, escalada por α/r = {(matriz.escala ?? 2).toFixed(1)}. 16 é a
            única dimensão “larga” — é por isso que 8,8 M de parâmetros mexem 0,5 B.
          </p>
          {amostra && (
            <p className="mt-2">
              Normas reais: ‖A‖={amostra.norma.A} · ‖B‖={amostra.norma.B} · ‖A‖·‖B‖={amostra.norma.produto}. Verde =
              peso positivo, rosa = negativo; a intensidade é o valor absoluto.
            </p>
          )}
          <p className="mt-2 text-[10.5px]">
            Ficheiro: {((matriz.tamanho_bytes ?? 0) / 1024 / 1024).toFixed(1)} MB · adaptado em{" "}
            {matriz.adaptado_em ? new Date(matriz.adaptado_em).toLocaleString("pt-PT") : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}
