/**
 * Cliente do módulo **Remunerações dos Eleitos Locais** (`/remuneracoes/*`).
 *
 * O módulo cruza a **tabela oficial dos abonos** (Lei n.º 11/96 — a remuneração
 * do presidente da junta/câmara é uma percentagem da remuneração do Presidente
 * da República, por escalão de eleitores) com o **recenseamento**: quantos
 * eleitores inscritos tem cada concelho e cada freguesia e o polígono de cada um
 * para o mapa (`eleicoes.mai.gov.pt/autarquicas2025`).
 *
 * Sem a segunda metade não se sabe em que escalão cai o território — logo não se
 * sabe quanto é que ele recebe. É isso que `GET /remuneracoes/concelhos/{id}`
 * devolve já calculado, para o concelho e para cada uma das suas freguesias.
 */
import { API_BASE } from "./api";

/* ------------------------------------------------------------------- tipos */

export type RemuneracoesEscalao = {
  id: string;
  designacao: string;
  ordem?: number | null;
  min_eleitores?: number | null;
  max_eleitores?: number | null;
  percentagem_pr?: number | null;
};

export type RemuneracoesRubrica = {
  id: string;
  regime?: string | null;
  grupo?: string | null;
  cargo?: string | null;
  modalidade?: string | null;
  natureza?: string | null;
  /** Percentagem por escalão (ex.: 25% da remuneração do PR). */
  percentagens?: Record<string, number | null> | null;
  /** Valor em euros por escalão. */
  valores?: Record<string, number | null> | null;
};

export type RemuneracoesTabela = {
  ano: number;
  nivel: "municipio" | "freguesia" | string;
  titulo?: string | null;
  /** `verificada`, `importada` ou `por_importar`. */
  estado?: string | null;
  nota?: string | null;
  escaloes: RemuneracoesEscalao[];
  rubricas: RemuneracoesRubrica[];
};

export type RemuneracoesFonte = {
  documento?: string | null;
  ficheiro?: string | null;
  base_legal?: string | null;
  atualizacao?: string | null;
  unidade?: string | null;
  referencias?: RemuneracoesReferencias | null;
};

export type RemuneracoesReferencias = {
  remuneracao_presidente_republica?: number | null;
  remuneracao_presidente_camara_municipio_10mil_ou_menos_eleitores?: number | null;
  subsidio_refeicao?: number | null;
};

export type RemuneracoesMeta = {
  recolhido_em?: string | null;
  fonte_territorios?: string | null;
  fonte_territorios_url?: string | null;
  eleicao?: string | null;
  /** Proveniência da georreferenciação (Wikidata/OpenStreetMap). */
  fonte_geo?: string | null;
  fonte_geo_url?: string | null;
  licenca_geo?: string | null;
  tabela: RemuneracoesFonte;
  niveis: string[];
};

/** Uma verba da tabela já resolvida para um território concreto. */
export type RemuneracoesVerba = {
  id: string;
  regime?: string | null;
  grupo?: string | null;
  cargo?: string | null;
  modalidade?: string | null;
  natureza?: string | null;
  percentagem?: number | null;
  valor?: number | null;
};

export type RemuneracoesResumo = {
  eleitores?: number | null;
  escalao_id?: string | null;
  escalao?: string | null;
  percentagem_pr?: number | null;
  remuneracao_mensal?: number | null;
  verbas: RemuneracoesVerba[];
};

export type RemuneracoesConcelho = {
  id: number;
  nome: string;
  distrito: string;
  eleitores?: number | null;
  votantes?: number | null;
  mandatos?: number | null;
  escalao_id?: string | null;
  escalao?: string | null;
  remuneracao_mensal?: number | null;
  lat?: number | null;
  lon?: number | null;
  total_freguesias: number;
  total_eleitores_freguesias: number;
};

export type RemuneracoesFreguesia = RemuneracoesResumo & {
  id: number;
  nome: string;
  distrito?: string | null;
  concelho?: string | null;
  concelho_id?: number | null;
  votantes?: number | null;
  mandatos?: number | null;
  /** Quem preside a junta e quantos membros tem a assembleia (Mapa Oficial da CNE). */
  presidente_nome?: string | null;
  presidente_sigla?: string | null;
  votos_presidente?: number | null;
  total_membros_assembleia?: number;
  /** Quanto recebe cada pessoa da freguesia, pela tabela oficial (papel → valor). */
  pessoas_valores?: Record<string, number | null>;
  /** Coordenadas geográficas (Wikidata/OSM) — para o mapa. */
  lat?: number | null;
  lon?: number | null;
  wikidata?: string | null;
};

export type RemuneracoesConcelhoAgregado = {
  escalao_id: string;
  escalao?: string | null;
  freguesias: number;
  eleitores: number;
  remuneracao_mensal?: number | null;
  total_mensal: number;
};

/** Presidente de câmara eleito (Autárquicas 2025). */
export type RemuneracoesPresidente = {
  nome: string;
  sigla?: string | null;
  partido?: string | null;
  posicao?: number | null;
  votos?: number | null;
  percentagem?: number | null;
  mandatos?: number | null;
  vereadores?: number | null;
};

/** Um partido com assento na Câmara Municipal. */
export type RemuneracoesCamaraPartido = {
  sigla?: string | null;
  votos?: number | null;
  percentagem?: number | null;
  mandatos?: number | null;
  presidentes?: number | null;
  vereadores?: number | null;
  /** Quem foi eleito por esta lista (Mapa Oficial da CNE). */
  nomes?: (string | null)[] | null;
};

export type RemuneracoesEleitos = {
  presidente?: RemuneracoesPresidente | null;
  vereadores: {
    total: number;
    total_mandatos: number;
    por_partido: RemuneracoesCamaraPartido[];
  };
  /** Presidente e vereadores, com nome, lista e o que cada um recebe. */
  pessoas?: RemuneracoesPessoa[];
  /** De onde vêm os nomes dos eleitos (Mapa Oficial da CNE). */
  nomes?: {
    fonte?: string | null;
    fonte_url?: string | null;
    recolhido_em?: string | null;
    total_eleitos?: number | null;
    total_mandatos?: number | null;
    /** Municípios em que o mapa oficial não publica todos os nomes. */
    lacuna?: { concelho?: string; mandatos?: number; nomes?: number; faltam?: number } | null;
    /** Divergências entre o MAI e o Mapa Oficial. */
    divergencia?: { concelho?: string; aviso?: string; nome_no_mai?: string; nome_no_mapa?: string } | null;
  } | null;
  fonte?: string | null;
  fonte_url?: string | null;
  eleicao?: string | null;
  /** O MAI não publica os nomes dos vereadores — os nomes vêm do Mapa Oficial. */
  nota?: string | null;
  recolhido_em?: string | null;
};

export type RemuneracoesConcelhoDetail = RemuneracoesResumo & {
  id: number;
  nome: string;
  distrito: string;
  votantes?: number | null;
  mandatos?: number | null;
  lat?: number | null;
  lon?: number | null;
  wikidata?: string | null;
  freguesias: RemuneracoesFreguesia[];
  total_freguesias: number;
  freguesias_sem_coordenadas: string[];
  total_eleitores_freguesias: number;
  remuneracoes_freguesias: {
    por_escalao: RemuneracoesConcelhoAgregado[];
    total_mensal_presidentes: number;
  };
  eleitos?: RemuneracoesEleitos | null;
  fonte?: string | null;
  fonte_url?: string | null;
  fonte_geo?: string | null;
  recolhido_em?: string | null;
  error?: string;
};

export type RemuneracoesMapaFeature = {
  id: number;
  nome: string;
  distrito: string;
  /** No mapa dos concelhos é o próprio concelho; no das freguesias, o concelho dela. */
  concelho?: string | null;
  nivel: "concelho" | "freguesia";
  eleitores?: number | null;
  votantes?: number | null;
  mandatos?: number | null;
  escalao_id?: string | null;
  escalao?: string | null;
  remuneracao_mensal?: number | null;
  /** Coordenadas geográficas (Wikidata/OpenStreetMap). */
  lat?: number | null;
  lon?: number | null;
  wikidata?: string | null;
};

export type RemuneracoesMapa = {
  nivel: "concelho" | "freguesia";
  total: number;
  /** Territórios que a georreferenciação não cobre (não aparecem no mapa). */
  sem_coordenadas: string[];
  min_eleitores?: number | null;
  max_eleitores?: number | null;
  tabela?: Omit<RemuneracoesTabela, "rubricas"> | null;
  features: RemuneracoesMapaFeature[];
  fonte?: string | null;
  fonte_geo?: string | null;
};

export type RemuneracoesLista<T> = {
  total: number;
  page?: number;
  size?: number;
  items: T[];
  facets?: { distritos?: string[]; escaloes?: (string | null)[] };
  tabela?: Omit<RemuneracoesTabela, "rubricas"> | null;
};

export type RemuneracoesStats = {
  recolhido_em?: string | null;
  fonte?: string | null;
  fonte_geo?: string | null;
  fonte_geo_url?: string | null;
  total_distritos: number;
  total_concelhos: number;
  total_freguesias: number;
  total_eleitores_concelhos: number;
  total_eleitores_freguesias: number;
  com_poligono: number;
  /** Cobertura da georreferenciação (é o que o mapa consegue desenhar). */
  concelhos_com_coordenadas: number;
  freguesias_com_coordenadas: number;
  tabelas: {
    ano: number;
    nivel: string;
    titulo?: string | null;
    estado?: string | null;
    total_escaloes: number;
    total_rubricas: number;
  }[];
  freguesias_por_escalao: {
    escalao_id: string;
    escalao?: string | null;
    count: number;
    eleitores: number;
  }[];
  eleitos?: {
    recolhido_em?: string | null;
    total_concelhos: number;
    com_presidente: number;
    total_vereadores: number;
    partidos_com_presidente: number;
  };
  fonte_tabela?: string | null;
};

/** Um concelho no painel dos eleitos: presidente eleito e vereadores por partido. */
export type RemuneracoesEleitoConcelho = {
  id: number;
  concelho: string;
  distrito: string;
  eleitores?: number | null;
  presidente?: RemuneracoesPresidente | null;
  vereadores?: number | null;
  mandatos?: number | null;
  por_partido: RemuneracoesCamaraPartido[];
};

/** Uma pessoa eleita: presidente, vereador, presidente de junta ou assembleia. */
export type RemuneracoesPessoa = {
  nome: string;
  cargo: string;
  tipo: string;
  nivel: "municipio" | "freguesia";
  sigla?: string | null;
  concelho?: string | null;
  concelho_id?: number | null;
  freguesia?: string | null;
  distrito?: string | null;
  eleitores?: number | null;
  escalao?: string | null;
  remuneracao_mensal?: number | null;
  remuneracao_descricao?: string | null;
  despesas_representacao?: number | null;
  senhas?: number | null;
  compensacao?: number | null;
  mandato?: string | null;
  origem?: string | null;
};

/** O edifício da câmara municipal: foto (com créditos), coordenadas e património. */
export type RemuneracoesCamara = {
  wikidata: string;
  designacao?: string | null;
  imagem?: string | null;
  localizacao?: string | null;
  lat?: number | null;
  lon?: number | null;
  patrimonio?: string | null;
  sipa?: string | null;
  artigo?: string | null;
  municipio?: string | null;
  municipio_id?: number | null;
  distrito?: string | null;
  eleitores?: number | null;
  credito?: {
    url?: string | null;
    autor?: string | null;
    licenca?: string | null;
    licenca_url?: string | null;
    pagina?: string | null;
  } | null;
};

/* ------------------------------------------------------------------ pedidos */

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [chave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    search.set(chave, String(valor));
  }
  const texto = search.toString();
  return texto ? `?${texto}` : "";
}

async function pedir<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detalhe = await res.text().catch(() => "");
    throw new Error(`${res.status} — ${detalhe || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function getRemuneracoesMeta(): Promise<RemuneracoesMeta> {
  return pedir<RemuneracoesMeta>("/remuneracoes/meta");
}

export function getRemuneracoesStats(): Promise<RemuneracoesStats> {
  return pedir<RemuneracoesStats>("/remuneracoes/stats");
}

export function getRemuneracoesTabelas(params: {
  nivel?: string;
  ano?: number;
} = {}): Promise<{
  total: number;
  fonte: RemuneracoesFonte;
  referencias: RemuneracoesReferencias;
  tabelas: RemuneracoesTabela[];
}> {
  return pedir(`/remuneracoes/tabelas${queryString({ nivel: params.nivel, ano: params.ano })}`);
}

export function buscarConcelhos(params: {
  q?: string;
  distrito?: string;
  min_eleitores?: number;
  max_eleitores?: number;
  page?: number;
  size?: number;
} = {}): Promise<RemuneracoesLista<RemuneracoesConcelho>> {
  return pedir<RemuneracoesLista<RemuneracoesConcelho>>(
    `/remuneracoes/concelhos${queryString({ ...params })}`,
  );
}

export function getConcelho(id: string | number): Promise<RemuneracoesConcelhoDetail> {
  return pedir<RemuneracoesConcelhoDetail>(`/remuneracoes/concelhos/${encodeURIComponent(String(id))}`);
}

export function buscarPessoas(params: {
  q?: string;
  distrito?: string;
  concelho?: string;
  cargo?: string;
  partido?: string;
  nivel?: string;
  page?: number;
  size?: number;
} = {}): Promise<
  RemuneracoesLista<RemuneracoesPessoa> & {
    por_tipo?: Record<string, number>;
    eleicao?: string | null;
    recolhido_em?: string | null;
    fonte?: string | null;
    fonte_url?: string | null;
  }
> {
  return pedir(`/remuneracoes/pessoas${queryString({ ...params })}`);
}

export function getCamaras(params: {
  q?: string;
  distrito?: string;
  apenas_com_foto?: boolean;
} = {}): Promise<{
  total: number;
  total_edificios: number;
  com_foto: number;
  sem_municipio: number;
  fonte?: string | null;
  fonte_url?: string | null;
  pagina?: string | null;
  recolhido_em?: string | null;
  items: RemuneracoesCamara[];
}> {
  return pedir(`/remuneracoes/camaras${queryString({ ...params })}`);
}

export function buscarEleitos(params: {
  q?: string;
  distrito?: string;
  partido?: string;
  page?: number;
  size?: number;
} = {}): Promise<
  RemuneracoesLista<RemuneracoesEleitoConcelho> & {
    aviso?: string;
    eleicao?: string | null;
    nota?: string | null;
    recolhido_em?: string | null;
    fonte?: string | null;
    fonte_url?: string | null;
    facets?: { distritos?: string[]; partidos?: string[] };
  }
> {
  return pedir(`/remuneracoes/eleitos${queryString({ ...params })}`);
}

export function buscarFreguesias(params: {
  q?: string;
  concelho?: string;
  distrito?: string;
  escalao_id?: string;
  page?: number;
  size?: number;
} = {}): Promise<RemuneracoesLista<RemuneracoesFreguesia>> {
  return pedir<RemuneracoesLista<RemuneracoesFreguesia>>(
    `/remuneracoes/freguesias${queryString({ ...params })}`,
  );
}

export function getMapaRemuneracoes(params: {
  nivel?: "municipio" | "freguesia";
  distrito?: string;
  concelho?: string;
  q?: string;
} = {}): Promise<RemuneracoesMapa> {
  return pedir<RemuneracoesMapa>(`/remuneracoes/mapa${queryString({ ...params })}`);
}

export function simularRemuneracoes(params: {
  eleitores: number;
  nivel?: string;
}): Promise<RemuneracoesResumo & { nivel: string }> {
  return pedir(`/remuneracoes/simular${queryString({ ...params })}`);
}

export function recolherRemuneracoes(params: {
  incluir_freguesias?: boolean;
  reindexar?: boolean;
} = {}): Promise<Record<string, unknown>> {
  return pedir(
    `/remuneracoes/refresh${queryString({
      incluir_freguesias: params.incluir_freguesias ?? true,
      reindexar: params.reindexar ?? true,
    })}`,
    { method: "POST" },
  );
}

export function reindexarRemuneracoes(): Promise<Record<string, unknown>> {
  return pedir("/remuneracoes/reindex", { method: "POST" });
}

export function importarTabelaRemuneracoes(payload: {
  ano: number;
  nivel: string;
  titulo?: string;
  estado?: string;
  nota?: string;
  escaloes: RemuneracoesEscalao[];
  rubricas?: RemuneracoesRubrica[];
}): Promise<Record<string, unknown>> {
  return pedir("/remuneracoes/tabelas/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* ------------------------------------------------------------- formatação */

export function numero(valor?: number | null): string {
  if (valor === undefined || valor === null) return "—";
  return valor.toLocaleString("pt-PT");
}

export function euro(valor?: number | null, decimais = 2): string {
  if (valor === undefined || valor === null) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: decimais, maximumFractionDigits: decimais })} €`;
}

export function percentagem(valor?: number | null, decimais = 0): string {
  if (valor === undefined || valor === null) return "—";
  return `${valor.toLocaleString("pt-PT", { minimumFractionDigits: decimais, maximumFractionDigits: decimais })} %`;
}

/** Nível do território como a interface o escreve. */
export function nivelLabel(nivel?: string | null): string {
  if (nivel === "municipio") return "Município";
  if (nivel === "freguesia") return "Freguesia";
  if (nivel === "concelho") return "Concelho";
  return nivel ?? "—";
}
