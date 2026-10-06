/**
 * Tema claro/escuro da área IQ OS (home + histórico + gráficos).
 *
 * O tema vive num atributo do `<html>` (`data-iqos-theme`) e não apenas numa
 * `ref` do componente: os modais do histórico são `Teleport` para o `<body>`,
 * fora da árvore do `Home.vue`, e só variáveis definidas em `:root` os
 * alcançam.
 *
 * A escolha persiste em `localStorage`; quando não há escolha guardada segue a
 * preferência do sistema (`prefers-color-scheme`). Tudo dentro de `try`: em
 * iframes com `sandbox` o `localStorage` lança ao ser lido ou escrito.
 *
 * Âmbito: as variáveis `--iq-*` são usadas pela home, pelo histórico e pelos
 * gráficos. As restantes vistas do MiroFish ficam como estavam — o tema não
 * lhes mexe.
 */

import { computed, ref, watch } from 'vue'

const STORAGE_KEY = 'iqos-theme'
const ATTR = 'data-iqos-theme'

function readStored() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // sem `localStorage`: decide-se pela preferência do sistema
  }
  return null
}

function systemTheme() {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

const theme = ref(readStored() || systemTheme())
const isDark = computed(() => theme.value === 'dark')

watch(
  theme,
  (value) => {
    document.documentElement.setAttribute(ATTR, value)
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // Sem persistência: o tema continua a funcionar nesta sessão.
    }
  },
  { immediate: true }
)

export function useIqosTheme() {
  return {
    theme,
    isDark,
    setTheme: (value) => {
      theme.value = value === 'dark' ? 'dark' : 'light'
    },
    toggleTheme: () => {
      theme.value = isDark.value ? 'light' : 'dark'
    }
  }
}
