/**
 * Cliente das peças do procedimento da Vortal (`/vortal/*`).
 *
 * O módulo resolve o **token público** de uma página de peças do procedimento
 * da plataforma Vortal, lista as peças, descarrega-as para disco, extrai o texto
 * (PDF/DOCX/XLSX/XML) e indexa-as em `finance_vortal_pecas` — onde ficam
 * pesquisáveis por dentro dos documentos.
 *
 * Além da recolha aviso a aviso, o módulo recolhe **em lote por mês e ano**: as
 * ligações das peças já estão nos contratos (`contratos.linkPecasProc`), pelo
 * que basta escolher o período e o servidor avança em lotes.
 *
 * A monitorização (`/vortal/admin/*`) exige papel `admin` no servidor.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type VortalMeta = {
  modulo: string;
  titulo: string;
  descricao: string;
  base: string;
  endpoints_api: string[];
  destino: string;
  indice: string;
  hosts_permitidos: string[];
  tipos: Record<string, string>;
  extensoes_texto: string[];
  limites: { bytes_por_peca: number; chars_por_peca: number; timeout_s: number };
  lotes?: {
    indice_contratos: string;
    campo_ligacao: string;
    lote_padrao: number;
    lote_maximo: number;
    lotes_por_vez: number;
    escanear_padrao: number;
    escanear_maximo: number;
  };
  notas: string[];
};

export type VortalPeca = {
  uid: string;
  doc_id?: number | null;
  file_id?: string | null;
  nome: string;
  descricao?: string | null;
  url: string;
  extensao: string;
  tipo: string;
  tipo_label?: string;
  bytes?: number;
  sha256?: string | null;
  texto_chars?: number;
  texto_metodo?: string | null;
  paginas?: number | null;
  precisa_ocr?: boolean;
  erro?: string | null;
  descarregado_em?: string;
};

export type VortalAviso = {
  uid: string;
  token?: string | null;
  url_aviso?: string | null;
  publicado?: boolean;
  idioma?: string;
  recolhido_em?: string;
  pasta?: string;
  pecas: VortalPeca[];
  totais?: { pecas: number; bytes: number; com_texto?: number; erros?: number };
};

export type VortalRecolha = {
  avisos: number;
  pecas: number;
  bytes: number;
  erros: string[];
  detalhe: VortalAviso[];
  destino: string;
  duracao_s?: number;
  indice?: { ok: boolean; index: string; indexados: number; falhas?: number; erros?: string[] };
};

export type VortalIndice = {
  index: string;
  disponivel: boolean;
  documentos?: number;
  avisos?: number;
  bytes?: number;
  erro?: string;
};

export type VortalDisco = {
  raiz: string;
  ficheiros: number;
  bytes: number;
  avisos: number;
  pecas: number;
  com_texto: number;
  por_tipo: Record<string, number>;
};

export type VortalEstado = {
  disco: VortalDisco;
  indice: VortalIndice;
  ultimos: {
    uid: string;
    url_aviso?: string | null;
    recolhido_em?: string;
    pecas?: number;
    bytes?: number;
  }[];
};

export type VortalRecolhaRegisto = {
  em: string;
  tipo: string;
  autor?: string | null;
  urls: string[];
  avisos: number;
  pecas: number;
  bytes: number;
  erros: string[];
  indexados: number;
  destino?: string;
  duracao_s?: number;
};

export type VortalMonitorizacao = VortalEstado & {
  historico: VortalRecolhaRegisto[];
  avisos: VortalAviso[];
};

export type VortalResultadoPeca = VortalPeca & {
  score?: number;
  trechos?: string[];
  tipo_label?: string;
  pasta?: string;
  recolhido_em?: string;
};

export type VortalPeriodos = {
  disponivel: boolean;
  total: number;
  anos: { ano: number; avisos: number }[];
  meses: { mes: string; avisos: number }[];
  erro?: string;
};

export type VortalAvisoPeriodo = {
  token: string;
  url: string;
  uid?: string | null;
  data_publicacao?: string | null;
  em_disco: boolean;
  contratos: { idcontrato?: string | null; data_publicacao?: string | null; ano?: number | null; objecto?: string | null }[];
};

export type VortalPeriodo = {
  ano: number;
  mes?: number | null;
  inicio: string;
  fim: string;
  disponivel: boolean;
  total: number;
  lidos?: number;
  truncado?: boolean;
  unicos: number;
  em_disco: number;
  pendentes: number;
  avisos: VortalAvisoPeriodo[];
  erro?: string;
};

export type VortalLote = {
  ok: boolean;
  erro?: string;
  periodo: { ano: number; mes?: number | null; inicio: string; fim: string };
  total_periodo: number;
  unicos_periodo: number;
  em_disco_periodo: number;
  truncado?: boolean;
  lote: number;
  lotes: { n: number; avisos: number; pecas: number; bytes: number; indexados: number; erros: number; urls: string[] }[];
  candidatos: number;
  processados: number;
  restantes: number;
  avisos: number;
  pecas: number;
  bytes: number;
  indexados: number;
  erros: string[];
  detalhe: VortalAviso[];
  indice?: { ok: boolean; index: string; indexados: number; falhas?: number };
  destino: string;
  duracao_s: number;
};

/* ----------------------------------------------------------------- pedidos */

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(`${API_BASE}${caminho}`, init);
  const texto = await resposta.text();
  let dados: unknown = null;
  try {
    dados = texto ? JSON.parse(texto) : null;
  } catch {
    dados = null;
  }
  if (!resposta.ok) {
    const detalhe = (dados as { detail?: unknown } | null)?.detail;
    const mensagem = typeof detalhe === "string" ? detalhe : Array.isArray(detalhe) ? JSON.stringify(detalhe) : `Erro ${resposta.status}`;
    const erro = new Error(mensagem) as Error & { estado?: number };
    erro.estado = resposta.status;
    throw erro;
  }
  return dados as T;
}

function comCorpo(metodo: "POST" | "PUT" | "DELETE", corpo?: unknown): RequestInit {
  return {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  };
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const busca = new URLSearchParams();
  Object.entries(params).forEach(([chave, valor]) => {
    if (valor === undefined || valor === null || valor === "") return;
    busca.set(chave, String(valor));
  });
  const texto = busca.toString();
  return texto ? `?${texto}` : "";
}

/* ------------------------------------------------------------------ módulo */

export function getVortalMeta() {
  return pedir<VortalMeta>("/vortal/meta");
}

export function getVortalEstado() {
  return pedir<VortalEstado>("/vortal/estado");
}

export function getVortalAvisos() {
  return pedir<{ total: number; itens: { uid: string; url_aviso?: string | null; recolhido_em?: string; totais?: VortalAviso["totais"]; pasta?: string }[] }>(
    "/vortal/avisos",
  );
}

/** Resolve um aviso (URL/token/UID) e lista as peças, sem descarregar nada. */
export function reverVortalAviso(url: string, idioma = "pt-PT") {
  return pedir<{ uid: string; token?: string | null; url_aviso?: string | null; publicado?: boolean; pecas: VortalPeca[]; total: number; em_disco: boolean }>(
    `/vortal/aviso${query({ url, idioma })}`,
  );
}

/** Descarrega as peças para disco e, se pedido, indexa-as. */
export function recolherVortal(payload: { urls: string[]; indexar?: boolean; extrair?: boolean; forcar?: boolean; idioma?: string }) {
  return pedir<VortalRecolha>("/vortal/recolha", comCorpo("POST", payload));
}

/** Anos e meses com avisos Vortal publicados (para escolher o período do lote). */
export function getVortalPeriodos() {
  return pedir<VortalPeriodos>("/vortal/periodos");
}

/** O que há num mês/ano: avisos, o que já está em disco e o que falta (sem descarregar nada). */
export function getVortalPeriodo(params: { ano: number; mes?: number; limite?: number; escanear?: number }) {
  return pedir<VortalPeriodo>(`/vortal/periodo${query(params)}`);
}

/** Recolhe (e indexa) em lotes os avisos Vortal publicados num mês/ano. */
export function recolherVortalLote(payload: {
  ano: number;
  mes?: number;
  lote?: number;
  lotes?: number;
  indexar?: boolean;
  extrair?: boolean;
  forcar?: boolean;
  saltar_em_disco?: boolean;
  escanear?: number;
}) {
  return pedir<VortalLote>("/vortal/lote", comCorpo("POST", payload));
}

export function indexarVortal(payload: { uid?: string; recriar?: boolean } = {}) {
  return pedir<{ ok: boolean; index: string; avisos?: number; indexados: number; falhas?: number; erros?: string[]; erro?: string }>(
    "/vortal/indexar",
    comCorpo("POST", payload),
  );
}

export function getVortalPecas(params: { uid?: string; limite?: number } = {}) {
  return pedir<{ itens: VortalResultadoPeca[]; total: number; uid?: string; erro?: string }>(`/vortal/pecas${query(params)}`);
}

export function pesquisarVortal(params: { q: string; uid?: string; limite?: number }) {
  return pedir<{ itens: VortalResultadoPeca[]; total: number; termo: string; erro?: string }>(`/vortal/pesquisa${query(params)}`);
}

export function apagarVortalAviso(uid: string, disco = false) {
  return pedir<{ ok: boolean; uid: string; apagados: number; disco_apagado: boolean; erro?: string }>(
    `/vortal/aviso/${encodeURIComponent(uid)}${query({ disco })}`,
    comCorpo("DELETE"),
  );
}

/* ------------------------------------------------------------ administração */

export function getVortalMonitorizacao(limite = 20) {
  return pedir<VortalMonitorizacao>(`/vortal/admin/monitorizacao${query({ limite })}`);
}

export function getVortalRecolhas(limite = 20) {
  return pedir<{ itens: VortalRecolhaRegisto[] }>(`/vortal/admin/recolhas${query({ limite })}`);
}
