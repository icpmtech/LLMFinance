<template>
  <!--
    Histórico de simulações do IQ OS: cartões, tabela e detalhe.

    Usa `/api/simulation/history` (o mesmo endpoint que a home antiga usava via
    `HistoryDatabase.vue`) e acrescenta o que faltava: vista de tabela, pesquisa,
    filtro por estado, ordenação e progresso visual.
  -->
  <section class="history">
    <header class="history-head">
      <div class="head-left">
        <h2>Histórico de simulações</h2>
        <p class="head-sub">
          {{ filtered.length }} de {{ items.length }} simulações
          <span v-if="loading"> · a carregar…</span>
          <span v-else-if="lastUpdated"> · atualizado às {{ lastUpdated }}</span>
        </p>
      </div>
      <div class="head-controls">
        <button type="button" class="mini refresh" :disabled="loading" @click="emit('refresh')">
          {{ loading ? 'A atualizar…' : '↻ Atualizar' }}
        </button>
        <label class="auto-refresh">
          <span>Auto</span>
          <select v-model.number="autoRefresh" class="select" aria-label="Atualização automática">
            <option :value="0">desligado</option>
            <option :value="15">15 s</option>
            <option :value="30">30 s</option>
            <option :value="60">60 s</option>
            <option :value="300">5 min</option>
          </select>
        </label>
        <input v-model="query" class="search" type="search" placeholder="Procurar por requisito, id ou ficheiro…" />
        <select v-model="statusFilter" class="select">
          <option value="">Todos os estados</option>
          <option v-for="option in statusOptions" :key="option.key" :value="option.key">
            {{ option.label }} ({{ option.count }})
          </option>
        </select>
        <select v-model="sortBy" class="select">
          <option value="recent">Mais recentes</option>
          <option value="oldest">Mais antigas</option>
          <option value="rounds">Mais rondas</option>
          <option value="entities">Mais entidades</option>
        </select>
        <button type="button" class="mini" :disabled="busy || items.length === 0" @click="exportAll('xlsx')">
          Excel (todas)
        </button>
        <button type="button" class="mini" :disabled="busy || items.length === 0" @click="exportAll('csv')">
          CSV
        </button>
        <div class="view-toggle" role="group" aria-label="Modo de apresentação">
          <button type="button" :class="{ active: view === 'cards' }" @click="view = 'cards'">Cartões</button>
          <button type="button" :class="{ active: view === 'table' }" @click="view = 'table'">Tabela</button>
        </div>
      </div>
    </header>

    <p v-if="error" class="history-error">{{ error }}</p>
    <p v-if="notice" class="history-notice">{{ notice }}</p>

    <p v-else-if="!loading && items.length === 0" class="history-empty">
      Ainda não há simulações. Crie a primeira em «Nova simulação».
    </p>

    <p v-else-if="!loading && filtered.length === 0" class="history-empty">
      Nenhuma simulação corresponde ao filtro.
    </p>

    <!-- Vista de cartões -->
    <div v-else-if="view === 'cards'" class="cards">
      <article
        v-for="item in filtered"
        :key="item.simulation_id"
        class="card"
        :class="`is-${statusOf(item)}`"
        @click="open(item)"
      >
        <header class="card-top">
          <span class="card-id">{{ shortId(item.simulation_id) }}</span>
          <span class="pill" :class="`pill-${statusOf(item)}`">{{ statusLabel(item) }}</span>
        </header>

        <h3 class="card-title" :title="item.simulation_requirement">
          {{ titleOf(item) }}
        </h3>

        <div class="progress" :title="`${item.current_round || 0} de ${item.total_rounds || 0} rondas`">
          <span class="progress-fill" :style="{ width: progressPct(item) + '%' }"></span>
        </div>
        <div class="progress-meta">
          <span>{{ item.current_round || 0 }}/{{ item.total_rounds || 0 }} rondas</span>
          <span v-if="item.total_simulation_hours">{{ item.total_simulation_hours }} h simuladas</span>
        </div>

        <dl class="card-stats">
          <div>
            <dt>Entidades</dt>
            <dd>{{ item.entities_count || 0 }}</dd>
          </div>
          <div>
            <dt>Personas</dt>
            <dd>{{ item.profiles_count || 0 }}</dd>
          </div>
          <div>
            <dt>Ficheiros</dt>
            <dd>{{ (item.files || []).length }}</dd>
          </div>
        </dl>

        <footer class="card-foot">
          <time :datetime="item.created_at || ''">{{ formatDate(item.created_at) }}</time>
          <span class="card-actions">
            <button type="button" class="mini" :disabled="!item.project_id" @click.stop="goProject(item)">Grafo</button>
            <button type="button" class="mini" :disabled="!item.simulation_id" @click.stop="goSimulation(item)">Passos</button>
            <button
              type="button"
              class="mini mini-report"
              :disabled="!item.report_id"
              :title="item.report_id ? 'Abrir relatório' : 'Sem relatório (a simulação tem de terminar)'"
              @click.stop="goReport(item)"
            >
              Relatório
            </button>
          </span>
        </footer>

        <footer class="card-tools">
          <button type="button" class="mini" @click.stop="exportOne(item, 'xlsx')">Excel</button>
          <button type="button" class="mini" @click.stop="exportOne(item, 'pdf')">Ficha PDF</button>
          <button
            type="button"
            class="mini"
            :disabled="!item.report_id"
            @click.stop="exportOneReport(item)"
          >
            Relatório PDF
          </button>
          <button
            type="button"
            class="mini mini-danger"
            :disabled="busy"
            @click.stop="askDelete(item)"
          >
            Apagar
          </button>
        </footer>
      </article>
    </div>

    <!-- Vista de tabela -->
    <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Simulação</th>
            <th scope="col">Requisito</th>
            <th scope="col">Estado</th>
            <th scope="col">Progresso</th>
            <th scope="col">Entidades</th>
            <th scope="col">Personas</th>
            <th scope="col">Criada</th>
            <th scope="col">Relatório</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filtered" :key="item.simulation_id" @click="open(item)">
            <td class="mono">{{ shortId(item.simulation_id) }}</td>
            <td class="req" :title="item.simulation_requirement">{{ titleOf(item) }}</td>
            <td><span class="pill" :class="`pill-${statusOf(item)}`">{{ statusLabel(item) }}</span></td>
            <td class="mono">{{ item.current_round || 0 }}/{{ item.total_rounds || 0 }}</td>
            <td class="mono">{{ item.entities_count || 0 }}</td>
            <td class="mono">{{ item.profiles_count || 0 }}</td>
            <td class="mono">{{ formatDate(item.created_at) }}</td>
            <td>
              <button
                type="button"
                class="mini mini-report"
                :disabled="!item.report_id"
                :title="item.report_id ? 'Abrir relatório' : 'Sem relatório (a simulação tem de terminar)'"
                @click.stop="goReport(item)"
              >
                {{ item.report_id ? 'Ver' : '—' }}
              </button>
            </td>
            <td class="row-actions">
              <button type="button" class="mini" title="Excel com os detalhes" @click.stop="exportOne(item, 'xlsx')">XLSX</button>
              <button type="button" class="mini" title="Ficha em PDF" @click.stop="exportOne(item, 'pdf')">PDF</button>
              <button type="button" class="mini mini-danger" title="Apagar" :disabled="busy" @click.stop="askDelete(item)">Apagar</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Detalhe -->
    <Teleport to="body">
      <div v-if="selected" class="modal-overlay" @click.self="selected = null">
        <div class="modal" role="dialog" aria-modal="true" aria-label="Detalhe da simulação">
          <header class="modal-head">
            <div>
              <span class="card-id">{{ shortId(selected.simulation_id) }}</span>
              <span class="pill" :class="`pill-${statusOf(selected)}`">{{ statusLabel(selected) }}</span>
            </div>
            <button type="button" class="modal-close" aria-label="Fechar" @click="selected = null">×</button>
          </header>

          <p class="modal-req">{{ selected.simulation_requirement || 'Sem requisito registado.' }}</p>

          <dl class="modal-grid">
            <div><dt>Projeto</dt><dd class="mono">{{ selected.project_id || '—' }}</dd></div>
            <div><dt>Grafo</dt><dd class="mono">{{ selected.graph_id || '—' }}</dd></div>
            <div><dt>Relatório</dt><dd class="mono">{{ selected.report_id || 'não gerado' }}</dd></div>
            <div><dt>Rondas</dt><dd class="mono">{{ selected.current_round || 0 }}/{{ selected.total_rounds || 0 }}</dd></div>
            <div><dt>Horas simuladas</dt><dd class="mono">{{ selected.total_simulation_hours || '—' }}</dd></div>
            <div><dt>Entidades</dt><dd class="mono">{{ selected.entities_count || 0 }}</dd></div>
            <div><dt>Personas</dt><dd class="mono">{{ selected.profiles_count || 0 }}</dd></div>
            <div><dt>Criada</dt><dd class="mono">{{ formatDate(selected.created_at) }}</dd></div>
          </dl>

          <div v-if="(selected.entity_types || []).length" class="modal-section">
            <h4>Tipos de entidade</h4>
            <p class="chips">
              <span v-for="type in selected.entity_types" :key="type" class="chip">{{ type }}</span>
            </p>
          </div>

          <div v-if="(selected.files || []).length" class="modal-section">
            <h4>Ficheiros de origem</h4>
            <ul class="file-list">
              <li v-for="(file, index) in selected.files" :key="index">
                <span class="file-tag">{{ fileType(file.filename) }}</span>
                <span class="mono">{{ file.filename }}</span>
              </li>
            </ul>
          </div>

          <p v-if="selected.error" class="modal-error">Erro registado: {{ selected.error }}</p>

          <footer class="modal-actions">
            <button type="button" :disabled="!selected.project_id" @click="goProject(selected)">
              Grafo e recolha (Passo 1)
            </button>
            <button type="button" :disabled="!selected.simulation_id" @click="goSimulation(selected)">
              Ambiente e perfis (Passo 2)
            </button>
            <button type="button" class="primary" :disabled="!selected.report_id" @click="goReport(selected)">
              {{ selected.report_id ? 'Ver relatório' : 'Sem relatório' }}
            </button>
          </footer>

          <footer class="modal-actions secondary">
            <button type="button" @click="exportOne(selected, 'xlsx')">Excel (detalhes)</button>
            <button type="button" @click="exportOne(selected, 'pdf')">Ficha em PDF</button>
            <button type="button" :disabled="!selected.report_id" @click="exportOneReport(selected)">
              Relatório em PDF
            </button>
            <button type="button" class="danger" @click="askDelete(selected)">Apagar simulação</button>
          </footer>
        </div>
      </div>
    </Teleport>

    <!--
      Confirmação de apagar.

      Modal da aplicação, **não** `window.prompt`/`window.confirm`: em webviews
      e iframes com `sandbox` (a app do IQ OS incorpora esta página) os diálogos
      nativos não existem, a chamada lança `prompt() is not supported` e o Vue
      limita-se a registar um erro de handler — o clique não fazia nada.
    -->
    <Teleport to="body">
      <div v-if="deleteTarget" class="modal-overlay" @click.self="cancelDelete">
        <div class="modal modal-danger" role="dialog" aria-modal="true" aria-label="Confirmar apagar">
          <header class="modal-head">
            <div>
              <span class="card-id">{{ shortId(deleteTarget.simulation_id) }}</span>
              <span class="pill" :class="`pill-${statusOf(deleteTarget)}`"
                >{{ statusLabel(deleteTarget) }}</span
              >
            </div>
            <button type="button" class="modal-close" aria-label="Fechar" @click="cancelDelete">×</button>
          </header>

          <p class="modal-req">
            Apagar remove a pasta da simulação e os relatórios associados. Não há forma de
            desfazer.
          </p>

          <p v-if="statusOf(deleteTarget) === 'running'" class="modal-warn">
            A corrida está marcada como em execução: será parada antes de apagar.
          </p>

          <label class="delete-field">
            <span>
              Escreva o identificador <b class="mono">{{ deleteTarget.simulation_id }}</b> para
              confirmar:
            </span>
            <input
              v-model="deleteTyped"
              type="text"
              class="mono"
              autocomplete="off"
              spellcheck="false"
              :placeholder="deleteTarget.simulation_id"
              @keyup.enter="confirmDelete"
            />
          </label>

          <label v-if="deleteTarget.project_id" class="delete-check">
            <input v-model="deleteProject" type="checkbox" />
            <span>
              Apagar também o projeto <b class="mono">{{ deleteTarget.project_id }}</b> (documentos
              e grafo)
            </span>
          </label>

          <p v-if="deleteError" class="modal-error">{{ deleteError }}</p>

          <footer class="modal-actions secondary">
            <button type="button" @click="cancelDelete">Cancelar</button>
            <button
              type="button"
              class="danger"
              :disabled="busy || !idMatches(deleteTarget, deleteTyped)"
              @click="confirmDelete"
            >
              {{ busy ? 'A apagar…' : 'Apagar definitivamente' }}
            </button>
          </footer>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { deleteSimulation, exportReport, exportSimulation, exportSimulations } from '../api/iqosAdmin'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['deleted', 'notice', 'refresh'])

// --- atualização ------------------------------------------------------------
// A hora da última atualização é derivada do **fim** de cada carregamento
// (`loading` a descer) e não de um relógio a correr: um contador a cada segundo
// re-renderiza a lista toda de graça — e chega a bloquear cliques em automação.
const lastUpdated = ref('')
const stamp = () => new Date().toLocaleTimeString('pt-PT', { hour12: false })
if (!props.loading) lastUpdated.value = stamp()
watch(
  () => props.loading,
  (isLoading, wasLoading) => {
    if (wasLoading && !isLoading) lastUpdated.value = stamp()
  }
)

const REFRESH_KEY = 'iqos-auto-refresh'
const REFRESH_STEPS = [0, 15, 30, 60, 300]

function readAutoRefresh() {
  try {
    const saved = Number(localStorage.getItem(REFRESH_KEY))
    if (REFRESH_STEPS.includes(saved)) return saved
  } catch {
    // sem `localStorage` (iframe com sandbox): fica desligado por omissão
  }
  return 0
}

const autoRefresh = ref(readAutoRefresh())
let autoRefreshTimer = null

/**
 * Um refresh automático só é pedido quando não estraga nada: nada a carregar,
 * nenhum modal aberto (o utilizador pode estar a confirmar um apagar, e a lista
 * a mudar por baixo seria confuso) e a página visível.
 */
function canAutoRefresh() {
  return !props.loading && !selected.value && !deleteTarget.value && !document.hidden
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
}

function startAutoRefresh(seconds) {
  stopAutoRefresh()
  if (!seconds) return
  autoRefreshTimer = setInterval(() => {
    if (canAutoRefresh()) emit('refresh')
  }, seconds * 1000)
}

watch(
  autoRefresh,
  (seconds) => {
    try {
      localStorage.setItem(REFRESH_KEY, String(seconds))
    } catch {
      // sem persistência: a escolha vale para esta sessão
    }
    startAutoRefresh(seconds)
  },
  { immediate: true }
)

onBeforeUnmount(stopAutoRefresh)

const router = useRouter()

const view = ref('cards')
const query = ref('')
const statusFilter = ref('')
const sortBy = ref('recent')
const selected = ref(null)
// Estado das operações demoradas: evita duplo clique e dá retorno ao utilizador.
const busy = ref(false)
const notice = ref('')

const STATUS_LABEL = {
  running: 'Em execução',
  completed: 'Concluída',
  failed: 'Falhada',
  pending: 'Por iniciar'
}

/** Estado normalizado (o runner envia `status` e `runner_status`, por vezes diferentes). */
function statusOf(item) {
  const raw = String(item.runner_status || item.status || '').toLowerCase()
  if (raw.includes('run') || raw === 'active' || raw === 'in_progress') return 'running'
  if (raw.includes('fail') || raw.includes('error') || raw.includes('abort')) return 'failed'
  if (raw.includes('complet') || raw.includes('done') || raw.includes('finish')) return 'completed'
  return 'pending'
}

const statusLabel = (item) => STATUS_LABEL[statusOf(item)] || 'Por iniciar'

const statusOptions = computed(() => {
  const counts = new Map()
  props.items.forEach((item) => {
    const key = statusOf(item)
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return Object.entries(STATUS_LABEL)
    .map(([key, label]) => ({ key, label, count: counts.get(key) || 0 }))
    .filter((row) => row.count > 0)
})

const shortId = (id) => (id ? String(id).replace('sim_', 'SIM_').toUpperCase().slice(0, 12) : 'SEM ID')

const titleOf = (item) => {
  const text = String(item.simulation_requirement || '').replace(/\s+/g, ' ').trim()
  if (!text) return 'Simulação sem requisito'
  return text.length > 90 ? `${text.slice(0, 90)}…` : text
}

const progressPct = (item) => {
  const total = Number(item.total_rounds) || 0
  const current = Number(item.current_round) || 0
  if (!total) return 0
  return Math.min(100, Math.round((current / total) * 100))
}

const formatDate = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const fileType = (filename) => {
  const ext = String(filename || '').split('.').pop()
  return ext ? ext.toUpperCase().slice(0, 4) : 'FILE'
}

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  let rows = props.items.filter((item) => {
    if (statusFilter.value && statusOf(item) !== statusFilter.value) return false
    if (!needle) return true
    const haystack = [
      item.simulation_id,
      item.project_id,
      item.report_id,
      item.simulation_requirement,
      ...(item.files || []).map((file) => file.filename),
      ...(item.entity_types || [])
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(needle)
  })

  rows = [...rows]
  if (sortBy.value === 'oldest') {
    rows.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0))
  } else if (sortBy.value === 'rounds') {
    rows.sort((a, b) => (b.total_rounds || 0) - (a.total_rounds || 0))
  } else if (sortBy.value === 'entities') {
    rows.sort((a, b) => (b.entities_count || 0) - (a.entities_count || 0))
  } else {
    rows.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
  }
  return rows
})

const open = (item) => { selected.value = item }

/** Corre uma operação demorada com aviso de erro e sem bloquear a lista. */
async function run(action, successMessage) {
  busy.value = true
  notice.value = ''
  try {
    await action()
    notice.value = successMessage
    return true
  } catch (err) {
    notice.value = `Falhou: ${err?.message || err}`
    return false
  } finally {
    busy.value = false
  }
}

const exportAll = (format) =>
  run(
    () => exportSimulations(format),
    format === 'csv' ? 'Exportação CSV gerada.' : 'Exportação Excel gerada.'
  )

const exportOne = (item, format) =>
  run(
    () => exportSimulation(item.simulation_id, format),
    `Ficheiro ${format.toUpperCase()} de ${shortId(item.simulation_id)} gerado.`
  )

const exportOneReport = (item) =>
  run(
    () => exportReport(item.report_id),
    `Relatório de ${shortId(item.simulation_id)} gerado em PDF.`
  )

/**
 * Apagar pede confirmação nominal escrita pelo utilizador.
 *
 * A confirmação é um modal da própria aplicação e **não** `window.prompt` /
 * `window.confirm`: em webviews e iframes com `sandbox` (esta página é
 * incorporada na app do IQ OS) os diálogos nativos não existem — a chamada
 * lança `prompt() is not supported`, o Vue só registra o erro de handler e o
 * clique parecia não fazer nada.
 */
const deleteTarget = ref(null)
const deleteTyped = ref('')
const deleteProject = ref(false)
const deleteError = ref('')

const norm = (value) => String(value || '').trim().toLowerCase()

/**
 * Aceita o identificador completo (`sim_b0b9529a38d1`) ou a forma curta que a
 * interface mostra (`SIM_B0B9529A`), mas só quando essa forma curta não é
 * ambígua entre as simulações listadas.
 */
function idMatches(item, typed) {
  if (!item) return false
  const needle = norm(typed)
  if (!needle) return false
  if (needle === norm(item.simulation_id)) return true
  const short = norm(shortId(item.simulation_id))
  if (needle !== short) return false
  return !props.items.some(
    (row) =>
      norm(row.simulation_id) !== norm(item.simulation_id) &&
      norm(shortId(row.simulation_id)) === short
  )
}

function askDelete(item) {
  selected.value = null
  deleteTarget.value = item
  deleteTyped.value = ''
  deleteProject.value = false
  deleteError.value = ''
}

function cancelDelete() {
  deleteTarget.value = null
  deleteTyped.value = ''
  deleteError.value = ''
}

async function confirmDelete() {
  const item = deleteTarget.value
  if (!item || !idMatches(item, deleteTyped.value)) {
    deleteError.value = 'O identificador escrito não corresponde — nada foi apagado.'
    return
  }

  const id = shortId(item.simulation_id)
  const includeProject = deleteProject.value && !!item.project_id
  const running = statusOf(item) === 'running'

  const ok = await run(
    () => deleteSimulation(item.simulation_id, { project: includeProject, force: running }),
    `Simulação ${id} apagada${includeProject ? ' com o projeto' : ''}.`
  )
  if (!ok) {
    deleteError.value = notice.value
    return
  }
  cancelDelete()
  emit('deleted', item.simulation_id)
}

const goProject = (item) => {
  if (!item?.project_id) return
  selected.value = null
  router.push({ name: 'Process', params: { projectId: item.project_id } })
}

const goSimulation = (item) => {
  if (!item?.simulation_id) return
  selected.value = null
  router.push({ name: 'Simulation', params: { simulationId: item.simulation_id } })
}

const goReport = (item) => {
  if (!item?.report_id) return
  selected.value = null
  router.push({ name: 'Report', params: { reportId: item.report_id } })
}
</script>

<style scoped>
.history {
  margin-top: 8px;
}
.history-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--iq-border);
  padding-bottom: 14px;
  margin-bottom: 20px;
}
.history-head h2 {
  font-size: 16px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.head-sub {
  font-size: 12px;
  color: var(--iq-muted);
  margin-top: 4px;
}
.head-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
/* Atualização: o botão e o intervalo automático andam juntos, à frente dos filtros. */
.refresh {
  font-variant-numeric: tabular-nums;
}
.auto-refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--iq-muted);
}
.auto-refresh .select {
  padding: 6px 8px;
  text-transform: none;
  letter-spacing: 0;
}
.search,
.select {
  font-family: inherit;
  font-size: 12px;
  padding: 7px 10px;
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  color: var(--iq-fg);
}
.search {
  min-width: 230px;
}
.view-toggle {
  display: flex;
  border: 1px solid var(--iq-border);
}
.view-toggle button {
  font-size: 12px;
  padding: 7px 12px;
  border: 0;
  background: var(--iq-surface);
  cursor: pointer;
}
.view-toggle button.active {
  background: var(--iq-fg);
  color: var(--iq-bg);
}
.history-empty,
.history-error,
.history-notice {
  font-size: 13px;
  padding: 14px 0 20px;
  color: var(--iq-muted);
}
.history-error {
  color: var(--iq-accent);
}
.history-notice {
  color: var(--iq-fg);
  border-left: 3px solid var(--iq-accent);
  padding-left: 10px;
}
.card-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-top: 1px dashed var(--iq-border);
  margin-top: 8px;
  padding-top: 9px;
}
.mini-danger:not(:disabled) {
  border-color: var(--iq-danger);
  color: var(--iq-danger);
}
.row-actions {
  display: flex;
  gap: 5px;
  white-space: nowrap;
}

/* cartões */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 18px;
}
.card {
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  padding: 16px;
  cursor: pointer;
  transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
}
.card:hover {
  transform: translateY(-2px);
  border-color: var(--iq-fg);
  box-shadow: 0 6px 18px var(--iq-shadow);
}
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.card-id {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--iq-muted);
}
.card-title {
  font-size: 13px;
  line-height: 1.45;
  margin: 10px 0 12px;
  min-height: 38px;
}
.pill {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 3px 7px;
  border: 1px solid currentColor;
  white-space: nowrap;
}
.pill-running { color: var(--iq-accent); }
.pill-completed { color: var(--iq-fg); }
.pill-failed { color: var(--iq-danger); }
.pill-pending { color: var(--iq-muted); }

.progress {
  height: 6px;
  background: var(--iq-track);
  overflow: hidden;
}
.progress-fill {
  display: block;
  height: 100%;
  background: var(--iq-fg);
}
.card.is-running .progress-fill { background: var(--iq-accent); }
.card.is-failed .progress-fill { background: var(--iq-danger); }
.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--iq-muted);
  margin-top: 6px;
}
.card-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin: 14px 0;
}
.card-stats dt {
  font-size: 10px;
  color: var(--iq-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.card-stats dd {
  font-size: 17px;
  font-weight: 700;
  margin-top: 2px;
}
.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--iq-border);
  padding-top: 10px;
  font-size: 10px;
  color: var(--iq-muted);
}
.card-actions {
  display: flex;
  gap: 6px;
}
.mini {
  font-family: inherit;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 5px 8px;
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  cursor: pointer;
}
.mini:hover:not(:disabled) {
  border-color: var(--iq-fg);
}
.mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.mini-report:not(:disabled) {
  border-color: var(--iq-accent);
  color: var(--iq-accent);
}

/* tabela */
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--iq-border);
}
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.table th {
  text-align: left;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--iq-muted);
  padding: 11px 12px;
  border-bottom: 1px solid var(--iq-border);
  background: var(--iq-surface-2);
  white-space: nowrap;
}
.table td {
  padding: 11px 12px;
  border-bottom: 1px solid var(--iq-border);
  vertical-align: middle;
}
.table tbody tr {
  cursor: pointer;
}
.table tbody tr:hover {
  background: var(--iq-surface-2);
}
.table .req {
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono {
  font-family: var(--font-mono);
}

/* detalhe */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--iq-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 900;
}
.modal {
  background: var(--iq-surface);
  color: var(--iq-fg);
  width: min(780px, 100%);
  max-height: 88vh;
  overflow-y: auto;
  padding: 24px 26px;
  border-top: 3px solid var(--iq-accent);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.modal-close {
  border: 0;
  background: none;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.modal-req {
  font-size: 14px;
  line-height: 1.6;
  border-left: 3px solid var(--iq-accent);
  padding-left: 12px;
  margin-bottom: 18px;
}
.modal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.modal-grid dt {
  font-size: 10px;
  color: var(--iq-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.modal-grid dd {
  font-size: 12px;
  margin-top: 3px;
  word-break: break-all;
}
.modal-section {
  border-top: 1px solid var(--iq-border);
  padding-top: 14px;
  margin-top: 14px;
}
.modal-section h4 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--iq-muted);
  margin-bottom: 8px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 11px;
  border: 1px solid var(--iq-border);
  padding: 3px 8px;
}
.file-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.file-list li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.file-tag {
  font-size: 9px;
  border: 1px solid var(--iq-fg);
  padding: 2px 5px;
}
.modal-error {
  font-size: 12px;
  color: var(--iq-danger);
  border-top: 1px solid var(--iq-border);
  padding-top: 12px;
  margin-top: 14px;
}
.modal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  border-top: 1px solid var(--iq-border);
  padding-top: 16px;
  margin-top: 18px;
}
.modal-actions button {
  font-family: inherit;
  font-size: 12px;
  padding: 10px 14px;
  border: 1px solid var(--iq-fg);
  background: var(--iq-surface);
  cursor: pointer;
}
.modal-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.modal-actions .primary {
  background: var(--iq-accent);
  border-color: var(--iq-accent);
  color: #fff;
}
.modal-actions.secondary {
  border-top: 1px dashed var(--iq-border);
  margin-top: 12px;
}
.modal-actions .danger {
  border-color: var(--iq-danger);
  color: var(--iq-danger);
}
.modal-actions .danger:hover:not(:disabled) {
  background: var(--iq-danger);
  color: #fff;
}

/* Confirmação de apagar (modal próprio, sem diálogos nativos do browser). */
.modal.modal-danger {
  border-top-color: var(--iq-danger);
  width: min(560px, 100%);
}
.modal-warn {
  font-size: 12px;
  line-height: 1.5;
  background: var(--iq-accent-soft);
  border-left: 3px solid var(--iq-accent);
  padding: 10px 12px;
  margin-bottom: 14px;
}
.delete-field {
  display: block;
  font-size: 12px;
  line-height: 1.5;
  margin-bottom: 12px;
}
.delete-field input {
  display: block;
  width: 100%;
  font-family: inherit;
  font-size: 13px;
  padding: 10px 12px;
  margin-top: 7px;
  border: 1px solid var(--iq-fg);
  background: var(--iq-surface);
}
.delete-check {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
  margin-bottom: 6px;
}
.modal-danger .modal-error {
  margin-top: 10px;
}
</style>
