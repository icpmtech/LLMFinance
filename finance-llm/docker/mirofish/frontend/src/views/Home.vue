<template>
  <!--
    Home do simulador IQ OS (`/`).

    Substitui a landing original do MiroFish (hero + formulário) por um painel:
    indicadores, gráficos e histórico de simulações — mantendo a criação de uma
    nova simulação, que era a única ação que a página tinha.

    Os dados vêm de `/api/simulation/history` (mesmo endpoint do MiroFish).
  -->
  <div class="iqos-home">
    <nav class="topbar">
      <div class="brand">
        <span class="brand-mark">IQ OS</span>
        <span class="brand-divider">/</span>
        <span class="brand-section">Simulações</span>
      </div>
      <div class="topbar-right">
        <!--
          Tema claro/escuro. O botão mostra o que vai *acontecer*, não o estado
          atual (evita o "modo escuro" que já está ligado e não parece clicável).
        -->
        <button
          type="button"
          class="theme-toggle"
          :title="isDark ? 'Passar a modo claro' : 'Passar a modo escuro'"
          :aria-label="isDark ? 'Ativar modo claro' : 'Ativar modo escuro'"
          :aria-pressed="isDark"
          @click="toggleTheme"
        >
          <span class="theme-icon" aria-hidden="true">{{ isDark ? '☀' : '☾' }}</span>
          <span class="theme-text">{{ isDark ? 'Claro' : 'Escuro' }}</span>
        </button>
        <button type="button" class="ghost" :class="{ active: showNew }" @click="showNew = !showNew">
          {{ showNew ? 'Fechar' : '+ Nova simulação' }}
        </button>
        <LanguageSwitcher />
      </div>
    </nav>

    <main class="page">
      <header class="page-head">
        <h1>Simulações IQ OS</h1>
        <p class="lede">
          Multiagentes sobre os dados da plataforma (contratos, empresas, pessoas) para testar
          cenários: cada simulação constrói um grafo, distribui personas e produz um relatório.
        </p>
      </header>

      <!-- Indicadores gerais -->
      <section class="kpis" aria-label="Indicadores das simulações">
        <article class="kpi">
          <span class="kpi-label">Simulações</span>
          <strong class="kpi-value">{{ items.length }}</strong>
          <span class="kpi-hint">{{ kpi.failed ? `${kpi.failed} com falha` : 'sem falhas' }}</span>
        </article>
        <article class="kpi accent">
          <span class="kpi-label">Em execução</span>
          <strong class="kpi-value">{{ kpi.running }}</strong>
          <span class="kpi-hint">{{ kpi.running ? 'a correr agora' : 'nenhuma ativa' }}</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">Com relatório</span>
          <strong class="kpi-value">{{ kpi.withReport }}</strong>
          <span class="kpi-hint">de {{ items.length }} simulações</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">Entidades</span>
          <strong class="kpi-value">{{ kpi.entities.toLocaleString('pt-PT') }}</strong>
          <span class="kpi-hint">nos grafos construídos</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">Personas</span>
          <strong class="kpi-value">{{ kpi.profiles.toLocaleString('pt-PT') }}</strong>
          <span class="kpi-hint">agentes distribuídos</span>
        </article>
        <article class="kpi">
          <span class="kpi-label">Horas simuladas</span>
          <strong class="kpi-value">{{ kpi.hours.toLocaleString('pt-PT') }}</strong>
          <span class="kpi-hint">somatório dos cenários</span>
        </article>
      </section>

      <!-- Nova simulação -->
      <Transition name="collapse">
        <section v-if="showNew" class="new-run">
          <header class="new-head">
            <h2>Nova simulação</h2>
            <p>Junte os documentos de contexto (PDF, MD ou TXT) e descreva o cenário a simular.</p>
          </header>

          <div class="new-grid">
            <div
              class="dropzone"
              :class="{ 'is-over': isDragOver, 'has-files': files.length > 0 }"
              @dragover.prevent="isDragOver = true"
              @dragleave.prevent="isDragOver = false"
              @drop.prevent="handleDrop"
              @click="fileInput?.click()"
            >
              <input
                ref="fileInput"
                type="file"
                multiple
                accept=".pdf,.md,.txt"
                class="hidden-input"
                @change="handleFileSelect"
              />
              <template v-if="files.length === 0">
                <span class="drop-icon">↑</span>
                <span class="drop-title">Arraste os ficheiros para aqui</span>
                <span class="drop-hint">ou clique para escolher · PDF, MD, TXT</span>
              </template>
              <ul v-else class="drop-files">
                <li v-for="(file, index) in files" :key="index">
                  <span class="file-tag">{{ fileType(file.name) }}</span>
                  <span class="file-name">{{ file.name }}</span>
                  <button type="button" class="remove" aria-label="Remover" @click.stop="removeFile(index)">×</button>
                </li>
              </ul>
            </div>

            <div class="prompt-box">
              <label for="rel">Cenário a simular</label>
              <textarea
                id="rel"
                v-model="requirement"
                rows="6"
                placeholder="Ex.: Como reage o mercado da saúde em Portugal se a Janssen perder o contrato com o maior hospital público?"
              ></textarea>
              <div class="prompt-foot">
                <span class="prompt-hint">
                  {{ files.length }} ficheiro(s) · rota para «Grafo e recolha»
                </span>
                <button type="button" class="primary" :disabled="!canSubmit" @click="startSimulation">
                  Iniciar simulação →
                </button>
              </div>
              <p v-if="formError" class="form-error">{{ formError }}</p>
            </div>
          </div>
        </section>
      </Transition>

      <!-- Gráficos -->
      <section class="block">
        <header class="block-head">
          <h2>Visão geral</h2>
        </header>
        <IqosCharts :items="items" />
      </section>

      <!-- Histórico (o `refresh` é preciso aqui: a lista é o que muda com as simulações a correr) -->
      <section class="block">
        <IqosHistory
          :items="items"
          :loading="loading"
          :error="error"
          @deleted="loadHistory"
          @refresh="loadHistory"
        />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import IqosCharts from '../components/IqosCharts.vue'
import IqosHistory from '../components/IqosHistory.vue'
import { useIqosTheme } from '../composables/useIqosTheme'
import { getSimulationHistory } from '../api/simulation'

const router = useRouter()

// Tema claro/escuro: o estado vive no `<html>` (`useIqosTheme`), para chegar
// também aos modais que o histórico envia por `Teleport` para o `<body>`.
const { isDark, toggleTheme } = useIqosTheme()

const items = ref([])
const loading = ref(true)
const error = ref('')

const showNew = ref(false)
const files = ref([])
const requirement = ref('')
const isDragOver = ref(false)
const formError = ref('')
const fileInput = ref(null)

const canSubmit = computed(() => files.value.length > 0 && requirement.value.trim() !== '')

const kpi = computed(() => {
  const status = (item) => {
    const raw = String(item.runner_status || item.status || '').toLowerCase()
    if (raw.includes('run') || raw === 'active' || raw === 'in_progress') return 'running'
    if (raw.includes('fail') || raw.includes('error') || raw.includes('abort')) return 'failed'
    if (raw.includes('complet') || raw.includes('done') || raw.includes('finish')) return 'completed'
    return 'pending'
  }
  return items.value.reduce(
    (acc, item) => {
      const state = status(item)
      acc[state] = (acc[state] || 0) + 1
      if (item.report_id) acc.withReport += 1
      acc.entities += Number(item.entities_count) || 0
      acc.profiles += Number(item.profiles_count) || 0
      acc.hours += Number(item.total_simulation_hours) || 0
      return acc
    },
    { running: 0, failed: 0, completed: 0, pending: 0, withReport: 0, entities: 0, profiles: 0, hours: 0 }
  )
})

const fileType = (name) => String(name || '').split('.').pop().toUpperCase().slice(0, 4) || 'FILE'

function addFiles(list) {
  const valid = list.filter((file) => ['pdf', 'md', 'txt'].includes(String(file.name).split('.').pop().toLowerCase()))
  if (valid.length !== list.length) formError.value = 'Só são aceites ficheiros PDF, MD ou TXT.'
  else formError.value = ''
  files.value.push(...valid)
}

function handleFileSelect(event) {
  addFiles(Array.from(event.target.files || []))
  event.target.value = ''
}

function handleDrop(event) {
  isDragOver.value = false
  addFiles(Array.from(event.dataTransfer?.files || []))
}

function removeFile(index) {
  files.value.splice(index, 1)
}

async function loadHistory() {
  loading.value = true
  error.value = ''
  try {
    const response = await getSimulationHistory(50)
    // O backend devolve `{success, data: [...]}`; o interceptor já rejeita
    // respostas com `success: false`.
    items.value = Array.isArray(response?.data) ? response.data : []
  } catch (err) {
    error.value = err?.message || 'Não foi possível carregar o histórico de simulações.'
    items.value = []
  } finally {
    loading.value = false
  }
}

function startSimulation() {
  if (!canSubmit.value) return
  // O envio dos ficheiros acontece no passo seguinte, como na home original.
  import('../store/pendingUpload.js').then(({ setPendingUpload }) => {
    setPendingUpload(files.value, requirement.value)
    router.push({ name: 'Process', params: { projectId: 'new' } })
  })
}

onMounted(loadHistory)
</script>

<style scoped>
.iqos-home {
  min-height: 100vh;
  background: var(--iq-bg);
  color: var(--iq-fg);
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 32px;
  border-bottom: 1px solid var(--iq-border);
  background: var(--iq-topbar);
  backdrop-filter: blur(6px);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  letter-spacing: 0.14em;
}
.brand-mark {
  font-weight: 700;
}
.brand-divider {
  color: var(--iq-accent);
}
.brand-section {
  color: var(--iq-muted);
  text-transform: uppercase;
  font-size: 11px;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: inherit;
  font-size: 12px;
  padding: 8px 12px;
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  color: var(--iq-fg);
  cursor: pointer;
}
.theme-toggle:hover {
  border-color: var(--iq-fg);
}
.theme-icon {
  font-size: 13px;
  line-height: 1;
  color: var(--iq-accent);
}
@media (max-width: 620px) {
  .theme-text {
    display: none;
  }
}
.ghost {
  font-family: inherit;
  font-size: 12px;
  padding: 8px 14px;
  border: 1px solid var(--iq-fg);
  background: var(--iq-surface);
  cursor: pointer;
}
.ghost.active {
  background: var(--iq-fg);
  color: var(--iq-bg);
}
.page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 34px 32px 72px;
}
.page-head h1 {
  font-size: 30px;
  letter-spacing: -0.01em;
}
.lede {
  max-width: 720px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--iq-muted);
  margin-top: 10px;
}

/* indicadores */
.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin: 28px 0 34px;
}
.kpi {
  border: 1px solid var(--iq-border);
  border-left: 3px solid var(--iq-fg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.kpi.accent {
  border-left-color: var(--iq-accent);
}
.kpi-label {
  font-size: 10px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--iq-muted);
}
.kpi-value {
  font-size: 26px;
  line-height: 1.1;
}
.kpi-hint {
  font-size: 10px;
  color: var(--iq-muted);
}

/* nova simulação */
.new-run {
  border: 1px solid var(--iq-border);
  border-top: 3px solid var(--iq-accent);
  padding: 20px 22px 22px;
  margin-bottom: 34px;
}
.new-head h2 {
  font-size: 14px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.new-head p {
  font-size: 12px;
  color: var(--iq-muted);
  margin-top: 5px;
}
.new-grid {
  display: grid;
  grid-template-columns: minmax(260px, 380px) 1fr;
  gap: 18px;
  margin-top: 16px;
}
@media (max-width: 860px) {
  .new-grid {
    grid-template-columns: 1fr;
  }
}
.dropzone {
  border: 1px dashed var(--iq-border);
  min-height: 190px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: border-color 140ms ease, background 140ms ease;
}
.dropzone.is-over {
  border-color: var(--iq-accent);
  background: var(--iq-accent-soft);
}
.dropzone.has-files {
  align-items: stretch;
  justify-content: flex-start;
}
.hidden-input {
  display: none;
}
.drop-icon {
  font-size: 22px;
}
.drop-title {
  font-size: 12px;
}
.drop-hint {
  font-size: 10px;
  color: var(--iq-muted);
}
.drop-files {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 11px;
}
.drop-files li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.file-tag {
  font-size: 9px;
  border: 1px solid var(--iq-fg);
  padding: 2px 5px;
}
.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.remove {
  border: 0;
  background: none;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}
.prompt-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.prompt-box label {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--iq-muted);
}
.prompt-box textarea {
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  color: var(--iq-fg);
  resize: vertical;
  min-height: 130px;
}
.prompt-box textarea:focus {
  outline: 2px solid rgba(255, 69, 0, 0.35);
  border-color: var(--iq-accent);
}
.prompt-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.prompt-hint {
  font-size: 10px;
  color: var(--iq-muted);
}
.primary {
  font-family: inherit;
  font-size: 12px;
  padding: 11px 18px;
  border: 1px solid var(--iq-accent);
  background: var(--iq-accent);
  color: #fff;
  cursor: pointer;
}
.primary:disabled {
  background: var(--iq-track);
  border-color: var(--iq-track);
  color: var(--iq-muted);
  cursor: not-allowed;
}
.form-error {
  font-size: 11px;
  color: var(--iq-accent);
}

/* blocos */
.block {
  margin-top: 37px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--iq-border);
  padding-bottom: 12px;
  margin-bottom: 18px;
}
.block-head h2 {
  font-size: 14px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.mini {
  font-family: inherit;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 6px 10px;
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  cursor: pointer;
}
.mini:disabled {
  opacity: 0.45;
  cursor: progress;
}

.collapse-enter-active,
.collapse-leave-active {
  transition: opacity 200ms ease, transform 200ms ease;
}
.collapse-enter-from,
.collapse-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>

<!--
  Tema (variáveis globais).

  Sem `scoped`: as variáveis têm de estar em `:root` para chegar aos modais do
  histórico, que são `Teleport` para o `<body>` — fora da árvore deste
  componente. Nomes `--iq-*` para não colidir com as variáveis do upstream
  (`--border`, `--gray-text`, `--orange`), que ficam como estavam nas outras
  vistas.

  Âmbito: só a home, o histórico e os gráficos usam estas variáveis. As
  restantes páginas do MiroFish não mudam de aspeto em modo escuro.
-->
<style>
:root {
  --iq-bg: #ffffff;
  --iq-surface: #ffffff;
  --iq-surface-2: #fafafa;
  --iq-fg: #111111;
  --iq-muted: #6b6b6b;
  --iq-border: #e5e5e5;
  --iq-track: #f0f0f0;
  --iq-accent: #FF4500;
  --iq-accent-soft: #fff7f4;
  --iq-danger: #D92D20;
  --iq-topbar: rgba(255, 255, 255, 0.94);
  --iq-overlay: rgba(0, 0, 0, 0.55);
  --iq-shadow: rgba(0, 0, 0, 0.07);
  --iq-status-running: #FF4500;
  --iq-status-completed: #111111;
  --iq-status-failed: #D92D20;
  --iq-status-pending: #B9B9B9;
}
:root[data-iqos-theme='dark'] {
  --iq-bg: #0e0e0e;
  --iq-surface: #161616;
  --iq-surface-2: #1b1b1b;
  --iq-fg: #f2f2f2;
  --iq-muted: #9d9d9d;
  --iq-border: #2c2c2c;
  --iq-track: #2a2a2a;
  --iq-accent: #FF5A1F;
  --iq-accent-soft: #2a160c;
  --iq-danger: #F97066;
  --iq-topbar: rgba(14, 14, 14, 0.92);
  --iq-overlay: rgba(0, 0, 0, 0.7);
  --iq-shadow: rgba(0, 0, 0, 0.55);
  --iq-status-running: #FF5A1F;
  --iq-status-completed: #f2f2f2;
  --iq-status-failed: #F97066;
  --iq-status-pending: #6b6b6b;
}
/* Campos e selects ficam com o fundo do tema (o padrão do browser é branco). */
:root[data-iqos-theme='dark'] select,
:root[data-iqos-theme='dark'] input,
:root[data-iqos-theme='dark'] textarea {
  color-scheme: dark;
}
</style>
