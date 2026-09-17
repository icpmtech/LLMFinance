/**
 * Service worker do IQ OS (PWA).
 *
 * Estratégia:
 * - Navegações (o próprio HTML): rede primeiro, com o `index.html` em cache como
 *   reserva — a aplicação abre e funciona mesmo sem ligação.
 * - Ficheiros com hash em `/assets/`: cache primeiro (são imutáveis).
 * - Restantes ficheiros do próprio domínio (ícones, manifest, favicon):
 *   cache com revalidação em segundo plano.
 * - Pedidos de outro domínio/porto (a API de dados em `:8002`): nunca passam
 *   pelo cache, para não servir dados financeiros desatualizados.
 * - Prefixos da API expostos na mesma origem (via nginx: `/api/` e
 *   `/forecast/plot/`): também nunca passam pelo cache.
 *
 * Ao alterar este ficheiro, incrementar `VERSION`.
 */
const VERSION = "v3";
/** Prefixos de cache do IQ OS (e o antigo, para limpar instalações anteriores). */
const CACHE_PREFIXES = ["iq-os-", "finance-llm-"];
const SHELL_CACHE = `iq-os-shell-${VERSION}`;
const ASSET_CACHE = `iq-os-assets-${VERSION}`;

/** Pedidos que nunca devem ser guardados (dados em tempo real). */
const BYPASS = ["/api/", "/forecast/plot/"];

const SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/favicon-32.png",
  "/apple-touch-icon.png",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // `addAll` falha por completo se um recurso faltar: guarda um a um.
      await Promise.all(
        SHELL.map((url) => cache.add(new Request(url, { cache: "reload" })).catch(() => undefined)),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) =>
              CACHE_PREFIXES.some((prefix) => key.startsWith(prefix)) && key !== SHELL_CACHE && key !== ASSET_CACHE,
          )
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put("/index.html", response.clone());
    }
    return response;
  } catch {
    const cache = await caches.open(SHELL_CACHE);
    return (await cache.match("/index.html")) || (await cache.match("/")) || Response.error();
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone());
  return response;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => undefined);
  return cached || (await network) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // API de dados (noutro porto/domínio) e recursos de terceiros ficam de fora.
  if (url.origin !== self.location.origin) return;
  if (BYPASS.some((prefix) => url.pathname.startsWith(prefix))) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }

  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(cacheFirst(request));
    return;
  }

  event.respondWith(staleWhileRevalidate(request));
});
