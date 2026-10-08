/**
 * Widget de apoio ao cliente (Tawk.to) da landing page pública.
 *
 * O snippet oficial do Tawk.to foi adaptado a uma SPA:
 *
 * - o `<script>` é injetado **uma única vez** (identificado por `id`), mesmo que o
 *   componente volte a montar ao navegar para fora e para dentro da landing page
 *   — a SPA não recarrega o documento;
 * - o widget fica **só na landing page**: ao desmontar esconde-se a bolha
 *   (`hideWidget`), sem apagar o script (o `Tawk_API` não tem «destroy»);
 * - se a página sair antes de o script carregar, o estado desejado é aplicado no
 *   `onLoad` (a chamada direta a `hideWidget`/`showWidget` ainda não existiria).
 *
 * O carregamento continua sujeito ao **autoblocking do iubenda** (`index.html`):
 * o widget só aparece depois de haver consentimento para o fim a que está
 * associado em iubenda → *Integrações → Tawk.to*. Sem isso, o script é bloqueado.
 */
import { useEffect } from "react";

const TAWK_PROPERTY = "6ac786035f2ded34cbd1cbeb/1k4dm7048";
const TAWK_SRC = `https://embed.tawk.to/${TAWK_PROPERTY}`;
/** Marca o `<script>` para não o injetar duas vezes. */
const TAWK_SCRIPT_ID = "tawk-to-widget";

interface TawkApi {
  onLoad?: () => void;
  onChatMaximized?: () => void;
  hideWidget?: () => void;
  showWidget?: () => void;
  maximize?: () => void;
  [key: string]: unknown;
}

declare global {
  interface Window {
    Tawk_API?: TawkApi;
    Tawk_LoadStart?: Date;
  }
}

/**
 * O widget é global (vive fora do React): este módulo guarda se a página que o
 * pediu ainda está montada, para o `onLoad`/remontagem saber o que aplicar.
 */
let pedidoVisivel = false;

function injetarScript(): void {
  if (document.getElementById(TAWK_SCRIPT_ID)) return;
  const script = document.createElement("script");
  script.id = TAWK_SCRIPT_ID;
  script.async = true;
  script.src = TAWK_SRC;
  script.charset = "UTF-8";
  script.setAttribute("crossorigin", "*");
  document.head.appendChild(script);
}

export function TawkChat() {
  useEffect(() => {
    const api = (window.Tawk_API = window.Tawk_API ?? {});
    window.Tawk_LoadStart = window.Tawk_LoadStart ?? new Date();
    pedidoVisivel = true;

    const aplicar = () => {
      if (pedidoVisivel) api.showWidget?.();
      else api.hideWidget?.();
    };

    // O Tawk chama `onLoad` uma vez, quando o widget fica pronto.
    const onLoadAnterior = api.onLoad;
    api.onLoad = () => {
      onLoadAnterior?.();
      aplicar();
    };

    if (document.getElementById(TAWK_SCRIPT_ID)) aplicar();
    else injetarScript();

    return () => {
      pedidoVisivel = false;
      api.hideWidget?.();
    };
  }, []);

  return null;
}

export default TawkChat;
