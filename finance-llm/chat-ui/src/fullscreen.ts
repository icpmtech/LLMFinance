/**
 * Ecrã inteiro (Fullscreen API) com estado reativo.
 *
 * Usado pelo dock e pelas preferências. A API só funciona a partir de um gesto
 * do utilizador — se o browser recusar, o erro é ignorado em silêncio.
 */
import { useCallback, useEffect, useState } from "react";

type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void>;
};

type FullscreenElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void>;
};

function currentElement(): Element | null {
  if (typeof document === "undefined") return null;
  const doc = document as FullscreenDocument;
  return doc.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
}

export function useFullscreen() {
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const sync = () => setIsFullscreen(Boolean(currentElement()));
    sync();
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("webkitfullscreenchange", sync);
    };
  }, []);

  const supported =
    typeof document !== "undefined" && (document.fullscreenEnabled || Boolean((document as FullscreenDocument).webkitExitFullscreen));

  const toggle = useCallback(async () => {
    const doc = document as FullscreenDocument;
    try {
      if (currentElement()) {
        if (doc.exitFullscreen) await doc.exitFullscreen();
        else await doc.webkitExitFullscreen?.();
      } else {
        const root = document.documentElement as FullscreenElement;
        if (root.requestFullscreen) {
          await root.requestFullscreen({ navigationUI: "hide" });
        } else {
          await root.webkitRequestFullscreen?.();
        }
      }
    } catch {
      // Recusado pelo browser (sem gesto do utilizador ou dentro de um iframe
      // sem permissão): mantém o estado atual.
    }
  }, []);

  return { isFullscreen, supported, toggle };
}
