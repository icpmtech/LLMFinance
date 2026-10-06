<template>
  <!--
    Gráficos do histórico de simulações.

    Desenhados em SVG puro (sem dependências novas): a app só traz `d3`, e para
    donut/barras as contas são triviais — fica mais leve e sem risco de versão.
    Cada gráfico é calculado a partir de `items` (a lista devolvida por
    `/api/simulation/history`).
  -->
  <div class="charts-grid">
    <!-- 1. Estado das simulações -->
    <section class="chart-card">
      <header class="chart-head">
        <h3>Estado das simulações</h3>
        <span class="chart-total">{{ items.length }} no total</span>
      </header>
      <div v-if="items.length === 0" class="chart-empty">Sem simulações para mostrar.</div>
      <div v-else class="donut-wrap">
        <svg :width="donut.size" :height="donut.size" :viewBox="`0 0 ${donut.size} ${donut.size}`" role="img"
             :aria-label="`Distribuição por estado: ${statusLegend.map((s) => s.label + ' ' + s.count).join(', ')}`">
          <g :transform="`translate(${donut.size / 2}, ${donut.size / 2})`">
            <circle r="62" fill="none" class="donut-track" stroke-width="22" />
            <circle
              v-for="slice in donut.slices"
              :key="slice.key"
              r="62"
              fill="none"
              class="slice"
              :class="`slice-${slice.key}`"
              stroke-width="22"
              :stroke-dasharray="`${slice.length} ${donut.circumference - slice.length}`"
              :stroke-dashoffset="slice.offset"
              transform="rotate(-90)"
            >
              <title>{{ slice.label }}: {{ slice.count }}</title>
            </circle>
            <text y="-4" text-anchor="middle" class="donut-value">{{ donut.centerValue }}</text>
            <text y="16" text-anchor="middle" class="donut-label">simulações</text>
          </g>
        </svg>
        <ul class="legend">
          <li v-for="slice in statusLegend" :key="slice.key">
            <span class="dot" :style="{ background: slice.color }"></span>
            <span class="legend-label">{{ slice.label }}</span>
            <span class="legend-count">{{ slice.count }}</span>
            <span class="legend-pct">{{ slice.pct }}%</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- 2. Simulações por mês -->
    <section class="chart-card">
      <header class="chart-head">
        <h3>Simulações por mês</h3>
        <span class="chart-total">{{ byMonth.length }} meses com atividade</span>
      </header>
      <div v-if="byMonth.length === 0" class="chart-empty">Sem dados de datas.</div>
      <div v-else class="bars-wrap">
        <svg :width="monthChart.width" :height="monthChart.height" :viewBox="`0 0 ${monthChart.width} ${monthChart.height}`"
             role="img" aria-label="Número de simulações criadas por mês">
          <line :x1="0" :y1="monthChart.baseY" :x2="monthChart.width" :y2="monthChart.baseY" class="axis-line" />
          <g v-for="bar in monthChart.bars" :key="bar.key">
            <rect :x="bar.x" :y="bar.y" :width="bar.width" :height="bar.height" class="bar-fill">
              <title>{{ bar.label }}: {{ bar.count }}</title>
            </rect>
            <text :x="bar.x + bar.width / 2" :y="bar.y - 6" text-anchor="middle" class="bar-value">{{ bar.count }}</text>
            <text :x="bar.x + bar.width / 2" :y="monthChart.height - 6" text-anchor="middle" class="bar-label">{{ bar.label }}</text>
          </g>
        </svg>
      </div>
    </section>

    <!-- 3. Tipos de entidade recolhidos -->
    <section class="chart-card wide">
      <header class="chart-head">
        <h3>Tipos de entidade no grafo</h3>
        <span class="chart-total">{{ entityTotal }} entidades em {{ entityChart.rows.length }} tipos</span>
      </header>
      <div v-if="entityChart.rows.length === 0" class="chart-empty">Nenhum grafo construído ainda.</div>
      <ul v-else class="hbars">
        <li v-for="row in entityChart.rows" :key="row.label">
          <span class="hbar-label" :title="row.label">{{ row.label }}</span>
          <span class="hbar-track">
            <span class="hbar-fill" :style="{ width: row.pct + '%' }"></span>
          </span>
          <span class="hbar-count">{{ row.count }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] }
})

// --- cores por estado -------------------------------------------------------
// `failed` a vermelho, `running` a laranja (a cor da marca), concluídas a preto.
//
// São nomes de variáveis de tema, e não cores literais. Nas legendas (`dot`)
// servem diretamente, porque ali o valor vai para `style` (CSS). No SVG do
// donut usa-se a classe `.slice-<estado>`: o browser não avalia um atributo de
// apresentação com variável (`stroke="var(--x)"`), mas aceita a mesma variável
// numa regra CSS.
const STATUS_STYLE = {
  running: { label: 'Em execução', color: 'var(--iq-status-running)' },
  completed: { label: 'Concluídas', color: 'var(--iq-status-completed)' },
  failed: { label: 'Falhadas', color: 'var(--iq-status-failed)' },
  pending: { label: 'Por iniciar', color: 'var(--iq-status-pending)' }
}

/** Estado normalizado de uma simulação (o runner manda `status` e `runner_status`). */
function statusOf(item) {
  const raw = String(item.runner_status || item.status || '').toLowerCase()
  if (raw.includes('run') || raw === 'active' || raw === 'in_progress') return 'running'
  if (raw.includes('fail') || raw.includes('error') || raw.includes('abort')) return 'failed'
  if (raw.includes('complet') || raw.includes('done') || raw.includes('finish')) return 'completed'
  if (raw.includes('pend') || raw.includes('wait') || raw === 'created' || raw === '') return 'pending'
  return 'pending'
}

const statusLegend = computed(() => {
  const counts = new Map()
  props.items.forEach((item) => {
    const key = statusOf(item)
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  const total = props.items.length || 1
  return Object.entries(STATUS_STYLE)
    .map(([key, style]) => ({
      key,
      ...style,
      count: counts.get(key) || 0,
      pct: Math.round(((counts.get(key) || 0) / total) * 100)
    }))
    .filter((row) => row.count > 0)
})

// --- donut ------------------------------------------------------------------
const donut = computed(() => {
  const size = 170
  const radius = 62
  const circumference = 2 * Math.PI * radius
  const total = props.items.length
  let offset = 0
  const slices = statusLegend.value.map((row) => {
    const length = total ? (row.count / total) * circumference : 0
    const slice = { ...row, length, offset: -offset }
    offset += length
    return slice
  })
  return { size, radius, circumference, slices, centerValue: total }
})

// --- barras por mês ---------------------------------------------------------
const MONTH_NAMES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

const byMonth = computed(() => {
  const counts = new Map()
  props.items.forEach((item) => {
    const raw = item.created_at || item.created_date
    if (!raw) return
    const date = new Date(raw)
    if (Number.isNaN(date.getTime())) return
    // Chave ano-mês: é o que agrupa sem depender do formato de entrada.
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(-12)
    .map(([key, count]) => {
      const [year, month] = key.split('-')
      return { key, count, label: `${MONTH_NAMES[Number(month) - 1]}/${year.slice(2)}` }
    })
})

const monthChart = computed(() => {
  const width = 520
  const height = 190
  const baseY = height - 26
  const max = Math.max(...byMonth.value.map((m) => m.count), 1)
  const slot = byMonth.value.length ? width / byMonth.value.length : width
  const barWidth = Math.min(46, slot * 0.6)
  const bars = byMonth.value.map((month, index) => {
    const barHeight = Math.round(((month.count / max) * (baseY - 26)) || 0)
    return {
      ...month,
      x: Math.round(index * slot + (slot - barWidth) / 2),
      y: baseY - barHeight,
      width: barWidth,
      height: Math.max(barHeight, month.count > 0 ? 3 : 0)
    }
  })
  return { width, height, baseY, bars }
})

// --- barras horizontais por tipo de entidade --------------------------------
const entityChart = computed(() => {
  const counts = new Map()
  props.items.forEach((item) => {
    (item.entity_types || []).forEach((type) => {
      const label = String(type || '').trim()
      if (!label) return
      counts.set(label, (counts.get(label) || 0) + 1)
    })
  })
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
  const max = sorted.length ? sorted[0][1] : 1
  return {
    rows: sorted.map(([label, count]) => ({ label, count, pct: Math.round((count / max) * 100) }))
  }
})

const entityTotal = computed(() =>
  props.items.reduce((sum, item) => sum + (Number(item.entities_count) || 0), 0)
)
</script>

<style scoped>
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}
.chart-card {
  border: 1px solid var(--iq-border);
  background: var(--iq-surface);
  color: var(--iq-fg);
  padding: 18px 20px 16px;
}
.chart-card.wide {
  grid-column: 1 / -1;
}
.chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.chart-head h3 {
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.chart-total {
  font-size: 11px;
  color: var(--iq-muted);
}
.chart-empty {
  font-size: 12px;
  color: var(--iq-muted);
  padding: 18px 0;
}
.donut-wrap {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
}
.donut-value {
  font-size: 30px;
  font-weight: 700;
  fill: var(--iq-fg);
}
.donut-label {
  font-size: 10px;
  fill: var(--iq-muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.legend {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 150px;
}
.legend li {
  display: grid;
  grid-template-columns: 10px 1fr auto auto;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.dot {
  width: 10px;
  height: 10px;
  display: inline-block;
}
.legend-count {
  font-weight: 700;
}
.legend-pct {
  color: var(--iq-muted);
  font-size: 11px;
  min-width: 32px;
  text-align: right;
}
.bars-wrap svg {
  width: 100%;
  height: auto;
}
.bar-value {
  font-size: 11px;
  font-weight: 700;
  fill: var(--iq-fg);
}
.bar-label {
  font-size: 10px;
  fill: var(--iq-muted);
}
.hbars {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hbars li {
  display: grid;
  grid-template-columns: minmax(120px, 220px) 1fr 48px;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.hbar-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hbar-track {
  background: var(--iq-track);
  height: 14px;
  display: block;
}
.hbar-fill {
  display: block;
  height: 100%;
  background: var(--iq-fg);
}
.hbar-count {
  text-align: right;
  font-weight: 700;
}

/*
  Cores do tema dentro do SVG.

  Têm de vir por classe (`stroke`/`fill` em CSS) e não por atributo: o browser
  não avalia `stroke="var(--x)"` em atributos de apresentação, apesar de
  aceitar a mesma variável nas regras CSS.
*/
.donut-track {
  stroke: var(--iq-track);
}
.slice-running {
  stroke: var(--iq-status-running);
}
.slice-completed {
  stroke: var(--iq-status-completed);
}
.slice-failed {
  stroke: var(--iq-status-failed);
}
.slice-pending {
  stroke: var(--iq-status-pending);
}
.axis-line {
  stroke: var(--iq-border);
}
.bar-fill {
  fill: var(--iq-accent);
}
</style>
