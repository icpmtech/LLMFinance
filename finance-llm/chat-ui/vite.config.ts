import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/chat': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/companies': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/contracts': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/tickers': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/forecast': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/elastic': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
      '/import': {
        target: 'http://127.0.0.1:8007',
        changeOrigin: true,
      },
    },
  },
})
