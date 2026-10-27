/**
 * Widget de apoio ao cliente nas páginas públicas da SPA.
 *
 * A interface (botão flutuante, conversa, tickets) é o mesmo widget autocontido
 * que o site do CMS e a loja carregam — `api/support_widget.js`, servido em
 * `/support/widget.js`. Aqui só se instala o script uma vez; a base da API vem
 * de `API_BASE` (relativa ou absoluta, conforme `VITE_API_URL`).
 */
import { useEffect } from "react";

import { API_BASE } from "../api";

const SCRIPT_ID = "iqos-support-widget-script";

declare global {
  interface Window {
    __IQOS_SUPPORT_API__?: string;
    __IQOS_SUPPORT_WIDGET__?: boolean;
    IQOSSupport?: {
      open: () => void;
      close: () => void;
      reset: () => void;
      config: () => Record<string, unknown>;
    };
  }
}

export function SupportChat() {
  useEffect(() => {
    const base = API_BASE.replace(/\/+$/, "");
    window.__IQOS_SUPPORT_API__ = base;
    if (document.getElementById(SCRIPT_ID)) return;
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    script.src = `${base}/support/widget.js`;
    script.setAttribute("data-iqos-support", "true");
    script.setAttribute("data-api-base", base);
    document.head.appendChild(script);
  }, []);

  return null;
}

export default SupportChat;
