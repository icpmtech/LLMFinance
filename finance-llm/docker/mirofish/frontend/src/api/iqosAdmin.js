import service from './index'

/**
 * Apagar e exportar simulações — extensão do IQ OS (`/api/iqos/*`).
 *
 * O `service` (axios) já aponta para a origem da página, por isso as rotas
 * relativas funcionam tanto em `127.0.0.1:8893` como através do proxy nginx do
 * IQ OS.
 */

/** Descarrega um ficheiro do backend, mostrando o erro do servidor se falhar.
 *
 * Não se usa `window.open`: quando o backend recusa (409 de simulação a correr,
 * 501 sem bibliotecas), um `window.open` abria um separador com o JSON do erro
 * ou, pior, ficava em branco — sem forma de dizer ao utilizador o que se passou.
 */
async function downloadFile(url, fallbackName) {
  const response = await fetch(url, { method: 'GET' })
  if (!response.ok) {
    let detail = `Erro ${response.status}`
    try {
      const payload = await response.json()
      detail = payload?.error || payload?.message || detail
    } catch {
      /* resposta não-JSON: fica o código */
    }
    throw new Error(detail)
  }

  const disposition = response.headers.get('Content-Disposition') || ''
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = match ? match[1] : fallbackName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

const stamp = () => new Date().toISOString().slice(0, 10)

/** Todas as simulações, em Excel (.xlsx) ou CSV. */
export const exportSimulations = (format = 'xlsx') =>
  downloadFile(`/api/iqos/export/simulations.${format}`, `iqos-simulacoes-${stamp()}.${format}`)

/** Uma simulação com detalhe (personas, execução, relatório) em Excel/PDF. */
export const exportSimulation = (simulationId, format = 'xlsx') =>
  downloadFile(
    `/api/iqos/export/simulations/${encodeURIComponent(simulationId)}.${format}`,
    `iqos-${simulationId}.${format}`
  )

/** Relatório completo em PDF. */
export const exportReport = (reportId) =>
  downloadFile(`/api/iqos/export/reports/${encodeURIComponent(reportId)}.pdf`, `iqos-${reportId}.pdf`)

/**
 * Apaga uma simulação.
 *
 * @param {string} simulationId
 * @param {{project?: boolean, reports?: boolean, force?: boolean}} options
 *        `project` apaga também o projeto; `force` pára a corrida e apaga.
 */
export const deleteSimulation = (simulationId, options = {}) => {
  const params = {}
  if (options.project) params.project = 1
  if (options.reports === false) params.reports = 0
  if (options.force) params.force = 1
  return service.delete(`/api/iqos/simulations/${encodeURIComponent(simulationId)}`, { params })
}
