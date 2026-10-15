import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // A SPA usa `/api` como base relativa (funciona em qualquer origem); no
      // servidor de desenvolvimento o prefixo é encaminhado para o backend local.
      // IMPORTANTE: em `vite preview` os proxies só funcionam quando o URL
      // solicitado não corresponde a um ficheiro físico no `dist`. Como o
      // build coloca `index.html` na raiz, o Vite devolve-o para qualquer
      // caminho desconhecido, pelo que precisamos de reescrita ativa para
      // `/api`, `/people` e `/auth` caírem no backend.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // O site público (CMS) vive em `/site/...`, servido pelo backend. Sem esta
      // regra, no servidor de desenvolvimento os endereços do site caíam no
      // `index.html` da SPA e a página abria "A validar a sessão…".
      '/site': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/companies': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/contracts': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/tickers': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/forecast': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/elastic': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/import': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/people': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/translate': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/providers': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
