"""Registo da ontologia do IQ OS (camada semântica ao estilo Palantir Foundry).

A ontologia descreve *o que existe* na plataforma — tipos de objeto, as suas
propriedades, as ligações entre eles e as ações que se podem executar — e como
cada um se liga às fontes de dados reais (Elasticsearch, resolvedores derivados).

Três domínios são modelados a partir dos dados já existentes:

- **contratacao** (EmpresasIQ): Empresa, Entidade Pública, Contrato, CPV, Região,
  Marca (INPI), Firma (RNPC).
- **mercados** (Financeiro): Instrumento/Ticker, Cotação, Notícia, Sentimento
  diário, Tópico.
- **crm**: Conta, Contacto, Oportunidade, Atividade.
- **pessoas** (Pessoas/Cargos): Pessoa — cargos do CRM + pessoas mencionadas
  nas notícias.

O registo base (semente) vive neste módulo e é copiado para
`data/ontology/ontology.json` na primeira utilização. A partir daí, esse
ficheiro é a fonte de verdade: guarda os tipos personalizados, as alterações
aos tipos base e os elementos desativados. Quando `ONTOLOGY_VERSION` sobe, as
definições base são atualizadas a partir da semente, preservando as alterações
do utilizador.

Cada tipo de objeto tem uma **ligação a dados** (`bindings`), com um de três
tipos:

- `es` — documento de um índice Elasticsearch (mapeamento declarativo de
  propriedades para campos).
- `aggregation` — valor agregado de um índice (ex.: CPV, Região, Tópico), em que
  cada "objeto" é um bucket de termos.
- `derived` — resolvedor Python que combina várias fontes em memória (ex.:
  Empresa, que é derivada dos contratos; Pessoa, que junta CRM e notícias).
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_PATH = ROOT / "data" / "ontology" / "ontology.json"

# Sobe quando as definições base mudarem de forma incompatível com o ficheiro.
ONTOLOGY_VERSION = 1


def _p(
    pid: str,
    label: str,
    ptype: str,
    field: Optional[str] = None,
    **kw: Any,
) -> Dict[str, Any]:
    """Constrói a definição de uma propriedade (evita repetição no registo)."""
    prop: Dict[str, Any] = {"id": pid, "label": label, "type": ptype}
    if field:
        prop["field"] = field
    prop.update({key: value for key, value in kw.items() if value is not None})
    return prop


# --------------------------------------------------------------------------
# Domínios
# --------------------------------------------------------------------------
DOMAINS: List[Dict[str, str]] = [
    {"id": "contratacao", "label": "Contratação Pública", "description": "Empresas, entidades públicas, contratos, CPV, regiões e registos INPI/RNPC.", "accent": "14,165,233"},
    {"id": "mercados", "label": "Mercados Financeiros", "description": "Instrumentos, cotações, notícias, sentimento e tópicos.", "accent": "244,63,94"},
    {"id": "crm", "label": "CRM", "description": "Contas, contactos, oportunidades e atividades do trabalho comercial.", "accent": "245,158,11"},
    {"id": "pessoas", "label": "Pessoas e Cargos", "description": "Pessoas ligadas a empresas: cargos do CRM e menções nas notícias.", "accent": "167,139,250"},
]


# --------------------------------------------------------------------------
# Tipos de objeto
# --------------------------------------------------------------------------
SEED_OBJECT_TYPES: List[Dict[str, Any]] = [
    # ---------------------------------------------------------- contratação
    {
        "id": "empresa",
        "label": "Empresa",
        "plural": "Empresas",
        "description": "Entidade que adjudica ou é adjudicatária em contratos públicos. Agrega os dois papéis por NIF.",
        "domain": "contratacao",
        "icon": "building",
        "primary_key": "nif",
        "title_field": "nome",
        "subtitle_fields": ["nif", "regiao", "papel"],
        "resolvable": True,
        "binding": {"kind": "derived", "resolver": "companies", "sources": ["contratos"]},
        "query_hint": "Pesquisa por nome parcial (sem acentos), NIF ou região.",
        "properties": [
            _p("nif", "NIF", "keyword", searchable=True, filterable=True, pk=True),
            _p("nome", "Nome", "text", searchable=True, filterable=True),
            _p("regiao", "Região (NUTS)", "keyword", filterable=True, values_from="regiao"),
            _p("papel", "Papel", "enum", enum=["ambos", "adjudicante", "adjudicatario"], filterable=True),
            _p("contratos", "Contratos", "number", unit="contratos", sortable=True, filter_as="min_contratos"),
            _p("valor_total", "Valor total", "number", unit="€", sortable=True, filter_as="valor"),
            _p("contratos_adjudicante", "Contratos como adjudicante", "number", unit="contratos"),
            _p("contratos_adjudicatario", "Contratos como adjudicatário", "number", unit="contratos"),
            _p("valor_adjudicante", "Valor como adjudicante", "number", unit="€"),
            _p("primeiro_ano", "Primeiro ano", "number"),
            _p("ultimo_ano", "Último ano", "number"),
        ],
    },
    {
        "id": "entidade_publica",
        "label": "Entidade Pública",
        "plural": "Entidades Públicas",
        "description": "Entidade que adjudica contratos (Estado, municípios, hospitais, empresas públicas).",
        "domain": "contratacao",
        "icon": "landmark",
        "primary_key": "nif",
        "title_field": "nome",
        "subtitle_fields": ["nif", "regiao", "contratos"],
        "resolvable": True,
        "binding": {"kind": "derived", "resolver": "public_entities", "sources": ["contratos"]},
        "query_hint": "Pesquisa por nome parcial (sem acentos) ou NIF.",
        "properties": [
            _p("nif", "NIF", "keyword", searchable=True, filterable=True, pk=True),
            _p("nome", "Nome", "text", searchable=True, filterable=True),
            _p("regiao", "Região (NUTS)", "keyword", filterable=True, values_from="regiao"),
            _p("contratos", "Contratos", "number", unit="contratos", sortable=True, filter_as="min_contratos"),
            _p("valor_total", "Valor total", "number", unit="€", sortable=True, filter_as="valor"),
            _p("primeiro_ano", "Primeiro ano", "number"),
            _p("ultimo_ano", "Último ano", "number"),
        ],
    },
    {
        "id": "contrato",
        "label": "Contrato Público",
        "plural": "Contratos Públicos",
        "description": "Contrato publicado no portal base (objeto, valor, partes, CPV, região e datas).",
        "domain": "contratacao",
        "icon": "file-text",
        "primary_key": "idcontrato",
        "title_field": "objecto",
        "subtitle_fields": ["idcontrato", "adjudicante", "adjudicatario", "preco"],
        "resolvable": False,
        "binding": {
            "kind": "es",
            "index": "contratos",
            "id_field": "idcontrato",
            "search_fields": ["search_text", "objectoContrato", "descContrato"],
            "default_sort": {"field": "dataCelebracaoContrato", "order": "desc"},
            "sources": ["contratos"],
        },
        "query_hint": "Pesquisa por objeto, descrição, adjudicante/adjudicatário ou NIF.",
        "properties": [
            _p("idcontrato", "ID contrato", "keyword", "idcontrato", pk=True, filterable=True, searchable=True),
            _p("objecto", "Objeto", "text", "objectoContrato", searchable=True),
            _p("descricao", "Descrição", "text", "descContrato", searchable=True),
            _p("preco", "Preço contratual", "number", "precoContratual", unit="€", sortable=True, filterable=True),
            _p("preco_total_efetivo", "Preço total efetivo", "number", "PrecoTotalEfetivo", unit="€", sortable=True),
            _p("ano", "Ano", "number", "Ano", sortable=True, filterable=True),
            _p("tipo_contrato", "Tipo de contrato", "keyword", "tipoContrato", filterable=True),
            _p("procedimento", "Tipo de procedimento", "text", "tipoprocedimento", searchable=True, filterable=True),
            _p("regiao", "Região (NUTS)", "keyword", "NUTs", filterable=True, values_from="regiao"),
            _p("local_execucao", "Local de execução", "keyword", "localExecucao", filterable=True),
            _p("data_celebracao", "Data de celebração", "date", "dataCelebracaoContrato", sortable=True, filterable=True),
            _p("data_publicacao", "Data de publicação", "date", "dataPublicacao", sortable=True, filterable=True),
            _p("adjudicante", "Adjudicante", "text", "adjudicantes.parsed.nome", nested="adjudicantes.parsed", searchable=True, filterable=True),
            _p("adjudicante_nif", "NIF do adjudicante", "keyword", "adjudicantes.parsed.nif", nested="adjudicantes.parsed", filterable=True),
            _p("adjudicatario", "Adjudicatário", "text", "adjudicatarios.parsed.nome", nested="adjudicatarios.parsed", searchable=True, filterable=True),
            _p("adjudicatario_nif", "NIF do adjudicatário", "keyword", "adjudicatarios.parsed.nif", nested="adjudicatarios.parsed", filterable=True),
            _p("cpv_codigo", "CPV", "keyword", "cpv.code", nested="cpv", filterable=True, values_from="cpv"),
            _p("cpv_descricao", "Descrição CPV", "text", "cpv.description", nested="cpv", searchable=True),
            _p("pme", "Adjudicatário PME", "keyword", "adjudicatarioPMEs", filterable=True),
            _p("prazo_dias", "Prazo de execução (dias)", "number", "prazoExecucao"),
        ],
    },
    {
        "id": "cpv",
        "label": "Código CPV",
        "plural": "Códigos CPV",
        "description": "Classificação europeia de bens e serviços, agregada a partir dos contratos.",
        "domain": "contratacao",
        "icon": "tags",
        "primary_key": "codigo",
        "title_field": "descricao",
        "subtitle_fields": ["codigo", "contratos"],
        "resolvable": True,
        "binding": {
            "kind": "aggregation",
            "index": "contratos",
            "nested": "cpv",
            "field": "cpv.code",
            "label_field": "cpv.description",
            "label_agg": {"kind": "top_hits", "nested": "cpv", "size": 1, "source": ["cpv.description"], "path": ["cpv", "description"]},
            "size": 2000,
            "sources": ["contratos"],
        },
        "properties": [
            _p("codigo", "Código", "keyword", pk=True, searchable=True),
            _p("descricao", "Descrição", "text", searchable=True),
            _p("contratos", "Contratos", "number", unit="contratos", sortable=True),
            _p("valor", "Valor", "number", unit="€", sortable=True),
        ],
    },
    {
        "id": "regiao",
        "label": "Região",
        "plural": "Regiões (NUTS)",
        "description": "Região NUTS do contrato. Inclui o grupo «Não especificado» para contratos sem NUTS.",
        "domain": "contratacao",
        "icon": "map",
        "primary_key": "nome",
        "title_field": "nome",
        "subtitle_fields": ["contratos", "valor"],
        "resolvable": True,
        "binding": {
            "kind": "aggregation",
            "index": "contratos",
            "field": "NUTs",
            "missing_label": "Não especificado",
            "size": 400,
            "sources": ["contratos"],
        },
        "properties": [
            _p("nome", "Região", "keyword", pk=True, searchable=True),
            _p("contratos", "Contratos", "number", unit="contratos", sortable=True),
            _p("valor", "Valor", "number", unit="€", sortable=True),
        ],
    },
    {
        "id": "marca",
        "label": "Marca (INPI)",
        "plural": "Marcas (INPI)",
        "description": "Marca registada no INPI, ligada ao titular pelo NIF.",
        "domain": "contratacao",
        "icon": "badge-check",
        "primary_key": "nord",
        "title_field": "nome",
        "subtitle_fields": ["titular", "fase", "data_pedido"],
        "resolvable": True,
        "binding": {
            "kind": "es",
            "index": "finance_trademarks",
            "id_field": "nord",
            "search_fields": ["mark_name", "holder_name"],
            "default_sort": {"field": "application_date", "order": "desc"},
            "sources": ["finance_trademarks"],
        },
        "properties": [
            _p("nord", "Nº INPI", "number", "nord", pk=True, filterable=True),
            _p("nome", "Marca", "text", "mark_name", searchable=True, filterable=True),
            _p("tipo", "Tipo", "keyword", "mark_type", filterable=True),
            _p("modalidade", "Modalidade", "keyword", "modality", filterable=True),
            _p("titular", "Titular", "text", "holder_name", searchable=True, filterable=True),
            _p("titular_nif", "NIF do titular", "keyword", "holder_nif", filterable=True),
            _p("nif_empresa", "NIF (empresa pesquisada)", "keyword", "company_nif", filterable=True),
            _p("data_pedido", "Data do pedido", "date", "application_date", sortable=True, filterable=True),
            _p("fase", "Fase atual", "keyword", "current_phase", filterable=True),
            _p("classes_nice", "Classes de Nice", "keyword", "nice_classes", filterable=True),
        ],
    },
    {
        "id": "firma",
        "label": "Firma (RNPC)",
        "plural": "Firmas (RNPC)",
        "description": "Firma ou denominação obtida na Pesquisa de Nomes Existentes do RNPC.",
        "domain": "contratacao",
        "icon": "scroll-text",
        "primary_key": "nipc",
        "title_field": "nome",
        "subtitle_fields": ["nipc", "concelho", "situacao"],
        "resolvable": True,
        "binding": {
            "kind": "es",
            "index": "finance_firmas",
            "id_field": "nipc",
            "search_fields": ["nome", "nipc"],
            "default_sort": {"field": "score", "order": "desc"},
            "sources": ["finance_firmas"],
        },
        "properties": [
            _p("nipc", "NIPC", "keyword", "nipc", pk=True, searchable=True, filterable=True),
            _p("nome", "Firma", "text", "nome", searchable=True, filterable=True),
            _p("nif_empresa", "NIF (empresa pesquisada)", "keyword", "company_nif", filterable=True),
            _p("certificado", "Certificado de admissibilidade", "keyword", "certificado_admissibilidade"),
            _p("concelho", "Concelho", "keyword", "concelho_sede", filterable=True),
            _p("situacao", "Situação", "keyword", "situacao", filterable=True),
            _p("cae", "CAE principal", "keyword", "cae_principal", filterable=True),
            _p("score", "Score de semelhança", "number", "score", sortable=True),
        ],
    },
    # ------------------------------------------------------------- mercados
    {
        "id": "ticker",
        "label": "Instrumento Financeiro",
        "plural": "Instrumentos Financeiros",
        "description": "Ticker com cotações indexadas na plataforma (finance_prices).",
        "domain": "mercados",
        "icon": "trending-up",
        "primary_key": "simbolo",
        "title_field": "simbolo",
        "subtitle_fields": ["ultimo_preco", "ultima_data"],
        "resolvable": True,
        "binding": {
            "kind": "aggregation",
            "index": "finance_prices",
            "field": "ticker",
            "size": 1000,
            "metrics": {
                "cotacoes": {"kind": "count"},
                "volume_total": {"kind": "sum", "field": "volume"},
                "primeira_data": {"kind": "min", "field": "date"},
                "ultima_data": {"kind": "max", "field": "date"},
                "ultimo_preco": {"kind": "top_hits", "size": 1, "sort": [{"date": "desc"}], "source": ["close", "date"], "path": ["close"]},
            },
            "sources": ["finance_prices"],
        },
        "properties": [
            _p("simbolo", "Símbolo", "keyword", pk=True, searchable=True),
            _p("cotacoes", "Cotações", "number", unit="registos", sortable=True),
            _p("ultimo_preco", "Último fecho", "number", unit="€", sortable=True),
            _p("ultima_data", "Última data", "date", sortable=True),
            _p("primeira_data", "Primeira data", "date", sortable=True),
            _p("volume_total", "Volume total", "number", sortable=True),
        ],
    },
    {
        "id": "cotacao",
        "label": "Cotação",
        "plural": "Cotações",
        "description": "Ponto OHLCV diário de um instrumento.",
        "domain": "mercados",
        "icon": "candlestick-chart",
        "primary_key": "id",
        "title_field": "ticker",
        "subtitle_fields": ["data", "fecho"],
        "resolvable": False,
        "binding": {
            "kind": "es",
            "index": "finance_prices",
            "id_field": "_id",
            "search_fields": ["ticker"],
            "default_sort": {"field": "date", "order": "desc"},
            "sources": ["finance_prices"],
        },
        "properties": [
            _p("id", "ID", "keyword", pk=True),
            _p("ticker", "Ticker", "keyword", "ticker", searchable=True, filterable=True, sortable=True, values_from="ticker"),
            _p("data", "Data", "date", "date", sortable=True, filterable=True),
            _p("abertura", "Abertura", "number", "open", unit="€"),
            _p("maximo", "Máximo", "number", "high", unit="€"),
            _p("minimo", "Mínimo", "number", "low", unit="€"),
            _p("fecho", "Fecho", "number", "close", unit="€", sortable=True),
            _p("volume", "Volume", "number", "volume", sortable=True),
            _p("periodo", "Período", "keyword", "period", filterable=True),
        ],
    },
    {
        "id": "noticia",
        "label": "Notícia",
        "plural": "Notícias",
        "description": "Notícia financeira indexada, com sentimento, tópicos e entidades mencionadas.",
        "domain": "mercados",
        "icon": "newspaper",
        "primary_key": "id",
        "title_field": "titulo",
        "subtitle_fields": ["ticker", "publicado", "sentimento"],
        "resolvable": False,
        "binding": {
            "kind": "es",
            "index": "finance_news",
            "id_field": "_id",
            "search_fields": ["title", "summary", "translated_title", "summary_pt"],
            "default_sort": {"field": "published", "order": "desc"},
            "sources": ["finance_news"],
        },
        "properties": [
            _p("id", "ID", "keyword", pk=True),
            _p("titulo", "Título", "text", "title", searchable=True),
            _p("resumo", "Resumo", "text", "summary", searchable=True),
            _p("ticker", "Ticker", "keyword", "ticker", searchable=True, filterable=True, values_from="ticker"),
            _p("publicador", "Publicador", "keyword", "publisher", filterable=True),
            _p("publicado", "Publicado", "date", "published", sortable=True, filterable=True),
            _p("url", "URL", "keyword", "url"),
            _p("sentimento", "Sentimento", "keyword", "sentiment", filterable=True),
            _p("topicos", "Tópicos", "keyword", "topics", filterable=True, values_from="topico"),
            _p("pessoas", "Pessoas mencionadas", "text", "entities.name", nested="entities", where={"type": "pessoa"}, filterable=True),
            _p("entidades", "Entidades mencionadas", "text", "entities.name", nested="entities", filterable=True),
        ],
    },
    {
        "id": "sentimento_diario",
        "label": "Sentimento Diário",
        "plural": "Sentimentos Diários",
        "description": "Agregado diário de sentimento das notícias de um instrumento.",
        "domain": "mercados",
        "icon": "gauge",
        "primary_key": "id",
        "title_field": "ticker",
        "subtitle_fields": ["data", "media"],
        "resolvable": False,
        "binding": {
            "kind": "es",
            "index": "finance_sentiment_daily",
            "id_field": "_id",
            "search_fields": ["ticker"],
            "default_sort": {"field": "date", "order": "desc"},
            "sources": ["finance_sentiment_daily"],
        },
        "properties": [
            _p("id", "ID", "keyword", pk=True),
            _p("ticker", "Ticker", "keyword", "ticker", searchable=True, filterable=True, values_from="ticker"),
            _p("data", "Data", "date", "date", sortable=True, filterable=True),
            _p("noticias", "Notícias", "number", "news_count"),
            _p("media", "Sentimento médio", "number", "sentiment_mean", sortable=True),
            _p("desvio", "Desvio-padrão", "number", "sentiment_std"),
            _p("positivas", "Positivas", "number", "positive_count"),
            _p("negativas", "Negativas", "number", "negative_count"),
        ],
    },
    {
        "id": "topico",
        "label": "Tópico",
        "plural": "Tópicos",
        "description": "Tópico de notícias (agregado do campo `topics`).",
        "domain": "mercados",
        "icon": "hash",
        "primary_key": "nome",
        "title_field": "nome",
        "subtitle_fields": ["noticias"],
        "resolvable": True,
        "binding": {
            "kind": "aggregation",
            "index": "finance_news",
            "field": "topics",
            "size": 500,
            "sources": ["finance_news"],
        },
        "properties": [
            _p("nome", "Tópico", "keyword", pk=True, searchable=True),
            _p("noticias", "Notícias", "number", unit="notícias", sortable=True),
        ],
    },
    # ------------------------------------------------------------------ crm
    {
        "id": "conta",
        "label": "Conta",
        "plural": "Contas (CRM)",
        "description": "Conta comercial do CRM, opcionalmente ligada a uma empresa do EmpresasIQ pelo NIF.",
        "domain": "crm",
        "icon": "briefcase",
        "primary_key": "id",
        "title_field": "nome",
        "subtitle_fields": ["nif", "sector", "estado"],
        "resolvable": True,
        "requires_session": True,
        "binding": {"kind": "es", "index": "finance_crm", "id_field": "id", "filter": {"term": {"kind": "account"}}, "search_fields": ["name", "nif", "email", "sector"], "scoped": True, "default_sort": {"field": "updated_at", "order": "desc"}, "sources": ["finance_crm"]},
        "properties": [
            _p("id", "ID", "keyword", "id", pk=True),
            _p("nome", "Nome", "text", "name", searchable=True, filterable=True),
            _p("nif", "NIF", "keyword", "nif", searchable=True, filterable=True),
            _p("sector", "Setor", "keyword", "sector", filterable=True),
            _p("estado", "Estado", "keyword", "status", filterable=True),
            _p("website", "Website", "keyword", "website"),
            _p("email", "Email", "keyword", "email", searchable=True),
            _p("telefone", "Telefone", "keyword", "phone"),
            _p("localidade", "Localidade", "keyword", "city", filterable=True),
            _p("pais", "País", "keyword", "country", filterable=True),
            _p("funcionarios", "Funcionários", "number", "employees"),
            _p("receita_anual", "Receita anual", "number", "annual_revenue", unit="€"),
            _p("etiquetas", "Etiquetas", "keyword", "tags", filterable=True),
            _p("criado_em", "Criado em", "date", "created_at", sortable=True),
            _p("atualizado_em", "Atualizado em", "date", "updated_at", sortable=True),
        ],
    },
    {
        "id": "contacto",
        "label": "Contacto",
        "plural": "Contactos (CRM)",
        "description": "Pessoa de contacto de uma conta, com cargo e dados de comunicação.",
        "domain": "crm",
        "icon": "users",
        "primary_key": "id",
        "title_field": "nome",
        "subtitle_fields": ["cargo", "email"],
        "resolvable": True,
        "requires_session": True,
        "binding": {"kind": "es", "index": "finance_crm", "id_field": "id", "filter": {"term": {"kind": "contact"}}, "search_fields": ["name", "email", "title"], "scoped": True, "default_sort": {"field": "updated_at", "order": "desc"}, "sources": ["finance_crm"]},
        "properties": [
            _p("id", "ID", "keyword", "id", pk=True),
            _p("nome", "Nome", "text", "name", searchable=True, filterable=True),
            _p("conta_id", "Conta", "keyword", "account_id", filterable=True),
            _p("cargo", "Cargo", "text", "title", searchable=True, filterable=True),
            _p("funcao", "Função", "keyword", "role", filterable=True),
            _p("email", "Email", "keyword", "email", searchable=True),
            _p("telefone", "Telefone", "keyword", "phone"),
            _p("telemovel", "Telemóvel", "keyword", "mobile"),
            _p("linkedin", "LinkedIn", "keyword", "linkedin"),
            _p("principal", "Contacto principal", "boolean", "is_primary", filterable=True),
        ],
    },
    {
        "id": "oportunidade",
        "label": "Oportunidade",
        "plural": "Oportunidades (CRM)",
        "description": "Oportunidade do pipeline comercial de uma conta.",
        "domain": "crm",
        "icon": "target",
        "primary_key": "id",
        "title_field": "nome",
        "subtitle_fields": ["valor", "fase"],
        "resolvable": True,
        "requires_session": True,
        "binding": {"kind": "es", "index": "finance_crm", "id_field": "id", "filter": {"term": {"kind": "deal"}}, "search_fields": ["name"], "scoped": True, "default_sort": {"field": "expected_close_date", "order": "desc"}, "sources": ["finance_crm"]},
        "properties": [
            _p("id", "ID", "keyword", "id", pk=True),
            _p("nome", "Oportunidade", "text", "name", searchable=True, filterable=True),
            _p("conta_id", "Conta", "keyword", "account_id", filterable=True),
            _p("valor", "Valor", "number", "amount", unit="€", sortable=True, filterable=True),
            _p("valor_ponderado", "Valor ponderado", "number", "weighted_amount", unit="€", sortable=True),
            _p("moeda", "Moeda", "keyword", "currency"),
            _p("fase", "Fase", "keyword", "stage", filterable=True),
            _p("probabilidade", "Probabilidade", "number", "probability"),
            _p("fecho_previsto", "Fecho previsto", "date", "expected_close_date", sortable=True, filterable=True),
            _p("fechado_em", "Fechado em", "date", "closed_at", sortable=True),
            _p("origem", "Origem", "keyword", "source", filterable=True),
        ],
    },
    {
        "id": "atividade",
        "label": "Atividade",
        "plural": "Atividades (CRM)",
        "description": "Compromisso, tarefa ou nota do trabalho comercial.",
        "domain": "crm",
        "icon": "calendar-clock",
        "primary_key": "id",
        "title_field": "assunto",
        "subtitle_fields": ["tipo", "data", "concluida"],
        "resolvable": True,
        "requires_session": True,
        "binding": {"kind": "es", "index": "finance_crm", "id_field": "id", "filter": {"term": {"kind": "activity"}}, "search_fields": ["subject", "notes"], "scoped": True, "default_sort": {"field": "due_at", "order": "desc"}, "sources": ["finance_crm"]},
        "properties": [
            _p("id", "ID", "keyword", "id", pk=True),
            _p("assunto", "Assunto", "text", "subject", searchable=True, filterable=True),
            _p("tipo", "Tipo", "keyword", "type", filterable=True),
            _p("conta_id", "Conta", "keyword", "account_id", filterable=True),
            _p("contacto_id", "Contacto", "keyword", "contact_id", filterable=True),
            _p("oportunidade_id", "Oportunidade", "keyword", "deal_id", filterable=True),
            _p("notas", "Notas", "text", "notes", searchable=True),
            _p("data", "Data", "date", "due_at", sortable=True, filterable=True),
            _p("concluida", "Concluída", "boolean", "done", filterable=True),
            _p("prioridade", "Prioridade", "keyword", "priority", filterable=True),
            _p("concluida_em", "Concluída em", "date", "done_at"),
        ],
    },
    # -------------------------------------------------------------- pessoas
    {
        "id": "pessoa",
        "label": "Pessoa",
        "plural": "Pessoas e Cargos",
        "description": "Pessoa ligada a empresas: contactos do CRM (com cargo) e pessoas mencionadas nas notícias.",
        "domain": "pessoas",
        "icon": "user-round",
        "primary_key": "id",
        "title_field": "nome",
        "subtitle_fields": ["cargo", "organizacao", "origem"],
        "resolvable": True,
        "binding": {
            "kind": "derived",
            "resolver": "people",
            "sources": ["finance_crm", "finance_news"],
            "scoped": True,
            "optional_scope": True,
        },
        "query_hint": "Pesquisa por nome. Com sessão, inclui cargos do CRM; sem sessão, apenas menções nas notícias.",
        "properties": [
            _p("id", "ID", "keyword", pk=True),
            _p("nome", "Nome", "text", searchable=True, filterable=True),
            _p("cargo", "Cargo", "text", searchable=True, filterable=True),
            _p("organizacao", "Organização", "text", searchable=True, filterable=True),
            _p("email", "Email", "keyword", searchable=True),
            _p("telefone", "Telefone", "keyword"),
            _p("linkedin", "LinkedIn", "keyword"),
            _p("conta_id", "Conta (CRM)", "keyword", filterable=True),
            _p("origem", "Origem", "enum", enum=["CRM", "Notícias"], filterable=True),
            _p("mencoes", "Menções em notícias", "number", sortable=True),
            _p("primeira_mencao", "Primeira menção", "date", sortable=True),
            _p("ultima_mencao", "Última menção", "date", sortable=True),
        ],
    },
]


# --------------------------------------------------------------------------
# Tipos de ligação
# --------------------------------------------------------------------------
SEED_LINK_TYPES: List[Dict[str, Any]] = [
    # --- contratos
    {
        "id": "empresa_adjudica",
        "label": "adjudica",
        "description": "Contratos em que a empresa é adjudicante.",
        "from": "empresa",
        "to": "contrato",
        "cardinality": "1:N",
        "binding": {"kind": "nested_terms", "index": "contratos", "nested": "adjudicantes.parsed", "field": "adjudicantes.parsed.nif", "size": 25},
    },
    {
        "id": "empresa_contratada",
        "label": "é adjudicatária em",
        "description": "Contratos em que a empresa é adjudicatária.",
        "from": "empresa",
        "to": "contrato",
        "cardinality": "1:N",
        "binding": {"kind": "nested_terms", "index": "contratos", "nested": "adjudicatarios.parsed", "field": "adjudicatarios.parsed.nif", "size": 25},
    },
    {
        "id": "empresa_contratos",
        "label": "tem contratos",
        "description": "Contratos da empresa em qualquer papel (união dos dois papéis, sem duplicados).",
        "from": "empresa",
        "to": "contrato",
        "cardinality": "1:N",
        "binding": {
            "kind": "union",
            "size": 25,
            "parts": [
                {"kind": "nested_terms", "index": "contratos", "nested": "adjudicantes.parsed", "field": "adjudicantes.parsed.nif"},
                {"kind": "nested_terms", "index": "contratos", "nested": "adjudicatarios.parsed", "field": "adjudicatarios.parsed.nif"},
            ],
        },
    },
    {
        "id": "entidade_publica_adjudica",
        "label": "adjudica",
        "description": "Contratos adjudicados pela entidade pública.",
        "from": "entidade_publica",
        "to": "contrato",
        "cardinality": "1:N",
        "binding": {"kind": "nested_terms", "index": "contratos", "nested": "adjudicantes.parsed", "field": "adjudicantes.parsed.nif", "size": 25},
    },
    {
        "id": "contrato_partes",
        "label": "tem partes",
        "description": "Empresas envolvidas no contrato (adjudicante e adjudicatários).",
        "from": "contrato",
        "to": "empresa",
        "cardinality": "N:M",
        "binding": {
            "kind": "union",
            "size": 20,
            "parts": [
                {"kind": "field_values", "field": "adjudicantes.parsed", "value_path": "nif", "index": "contratos"},
                {"kind": "field_values", "field": "adjudicatarios.parsed", "value_path": "nif", "index": "contratos"},
            ],
        },
    },
    {
        "id": "contrato_regiao",
        "label": "está na região",
        "description": "Região NUTS do contrato.",
        "from": "contrato",
        "to": "regiao",
        "cardinality": "N:1",
        "binding": {"kind": "field_values", "field": "NUTs", "index": "contratos", "missing_label": "Não especificado"},
        "reverse": {"kind": "term_value", "index": "contratos", "field": "NUTs", "size": 25},
    },
    {
        "id": "contrato_cpv",
        "label": "classificado em",
        "description": "Códigos CPV do contrato.",
        "from": "contrato",
        "to": "cpv",
        "cardinality": "N:M",
        "binding": {"kind": "field_values", "field": "cpv", "value_path": "code", "index": "contratos"},
        "reverse": {"kind": "term_value", "index": "contratos", "nested": "cpv", "field": "cpv.code", "size": 25},
    },
    {
        "id": "empresa_marcas",
        "label": "tem marcas",
        "description": "Marcas do INPI ligadas à empresa (NIF da empresa pesquisada ou do titular).",
        "from": "empresa",
        "to": "marca",
        "cardinality": "1:N",
        "binding": {
            "kind": "union",
            "size": 25,
            "parts": [
                {"kind": "term", "index": "finance_trademarks", "field": "company_nif"},
                {"kind": "term", "index": "finance_trademarks", "field": "holder_nif"},
            ],
        },
        "reverse": {"kind": "cross_ref", "from_field": "holder_nif", "to": "empresa"},
    },
    {
        "id": "empresa_firmas",
        "label": "tem firmas",
        "description": "Firmas / nomes existentes do RNPC ligados à empresa.",
        "from": "empresa",
        "to": "firma",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_firmas", "field": "company_nif", "size": 25},
        "reverse": {"kind": "cross_ref", "from_field": "company_nif", "to": "empresa"},
    },
    # --- mercados
    {
        "id": "ticker_cotacoes",
        "label": "tem cotações",
        "description": "Cotações diárias do instrumento.",
        "from": "ticker",
        "to": "cotacao",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_prices", "field": "ticker", "size": 25},
        "reverse": {"kind": "term_value", "index": "finance_prices", "field": "ticker", "size": 25},
    },
    {
        "id": "ticker_noticias",
        "label": "tem notícias",
        "description": "Notícias indexadas para o instrumento.",
        "from": "ticker",
        "to": "noticia",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_news", "field": "ticker", "size": 25},
        "reverse": {"kind": "term_value", "index": "finance_news", "field": "ticker", "size": 25},
    },
    {
        "id": "ticker_sentimento",
        "label": "tem sentimento diário",
        "description": "Série de sentimento diário das notícias do instrumento.",
        "from": "ticker",
        "to": "sentimento_diario",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_sentiment_daily", "field": "ticker", "size": 25},
        "reverse": {"kind": "term_value", "index": "finance_sentiment_daily", "field": "ticker", "size": 25},
    },
    {
        "id": "noticia_topicos",
        "label": "aborda",
        "description": "Tópicos da notícia.",
        "from": "noticia",
        "to": "topico",
        "cardinality": "N:M",
        "binding": {"kind": "field_values", "field": "topics", "index": "finance_news"},
        "reverse": {"kind": "term_value", "index": "finance_news", "field": "topics", "size": 25},
    },
    {
        "id": "noticia_pessoas",
        "label": "menciona pessoas",
        "description": "Pessoas mencionadas no texto da notícia.",
        "from": "noticia",
        "to": "pessoa",
        "cardinality": "N:M",
        "binding": {"kind": "field_values", "field": "entities", "value_path": "name", "where": {"type": "pessoa"}, "index": "finance_news"},
    },
    {
        "id": "pessoa_noticias",
        "label": "é mencionada em",
        "description": "Notícias que mencionam a pessoa.",
        "from": "pessoa",
        "to": "noticia",
        "cardinality": "1:N",
        "binding": {"kind": "nested_terms", "index": "finance_news", "nested": "entities", "field": "entities.name", "where": {"type": "pessoa"}, "size": 25},
    },
    # --- crm
    {
        "id": "conta_contactos",
        "label": "tem contactos",
        "description": "Contactos (pessoas) da conta.",
        "from": "conta",
        "to": "contacto",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_crm", "field": "account_id", "filter": {"term": {"kind": "contact"}}, "size": 25},
        "reverse": {"kind": "cross_ref", "from_field": "account_id", "to": "conta"},
    },
    {
        "id": "conta_oportunidades",
        "label": "tem oportunidades",
        "description": "Oportunidades do pipeline da conta.",
        "from": "conta",
        "to": "oportunidade",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_crm", "field": "account_id", "filter": {"term": {"kind": "deal"}}, "size": 25},
        "reverse": {"kind": "cross_ref", "from_field": "account_id", "to": "conta"},
    },
    {
        "id": "conta_atividades",
        "label": "tem atividades",
        "description": "Atividades e compromissos da conta.",
        "from": "conta",
        "to": "atividade",
        "cardinality": "1:N",
        "binding": {"kind": "term", "index": "finance_crm", "field": "account_id", "filter": {"term": {"kind": "activity"}}, "size": 25},
        "reverse": {"kind": "cross_ref", "from_field": "account_id", "to": "conta"},
    },
    {
        "id": "conta_empresa",
        "label": "corresponde à empresa",
        "description": "Empresa do EmpresasIQ com o mesmo NIF — liga o CRM aos dados públicos de contratação.",
        "from": "conta",
        "to": "empresa",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "nif", "to": "empresa"},
        "reverse": {"kind": "term", "index": "finance_crm", "field": "nif", "filter": {"term": {"kind": "account"}}, "size": 10},
    },
    {
        "id": "atividade_contacto",
        "label": "envolve",
        "description": "Contacto associado à atividade.",
        "from": "atividade",
        "to": "contacto",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "contact_id", "to": "contacto"},
    },
    {
        "id": "atividade_oportunidade",
        "label": "relaciona-se com",
        "description": "Oportunidade associada à atividade.",
        "from": "atividade",
        "to": "oportunidade",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "deal_id", "to": "oportunidade"},
    },
    {
        "id": "pessoa_conta",
        "label": "trabalha na conta",
        "description": "Conta do CRM onde a pessoa tem um cargo.",
        "from": "pessoa",
        "to": "conta",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "conta_id", "to": "conta"},
        "requires_session": True,
    },
    {
        "id": "cotacao_ticker",
        "label": "é cotação de",
        "description": "Instrumento a que pertence a cotação.",
        "from": "cotacao",
        "to": "ticker",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "ticker", "to": "ticker"},
    },
    {
        "id": "noticia_ticker",
        "label": "é notícia de",
        "description": "Instrumento a que a notícia se refere.",
        "from": "noticia",
        "to": "ticker",
        "cardinality": "N:1",
        "binding": {"kind": "cross_ref", "from_field": "ticker", "to": "ticker"},
    },
]


# --------------------------------------------------------------------------
# Ações
# --------------------------------------------------------------------------
SEED_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "empresa.abrir_dossier",
        "label": "Abrir dossier da empresa",
        "description": "Abre o EmpresasIQ focado na empresa (favoritos, contratos, grafo).",
        "object_type": "empresa",
        "kind": "navigate",
        "target": "/empresas-iq",
        "params": [{"id": "nif", "from": "primary_key"}],
    },
    {
        "id": "empresa.contratos",
        "label": "Ver contratos da empresa",
        "description": "Navega para os contratos em que a empresa participa (qualquer papel), via ligação da ontologia.",
        "object_type": "empresa",
        "kind": "ontology_links",
        "link": "empresa_contratos",
        "params": [{"id": "nif", "from": "primary_key"}],
    },
    {
        "id": "empresa.enriquecer",
        "label": "Enriquecer (INPI + RNPC)",
        "description": "Consulta marcas do INPI e firmas do RNPC para a empresa. Requer sessão.",
        "object_type": "empresa",
        "kind": "http",
        "method": "POST",
        "url": "/companies/{nif}/enrich",
        "requires_session": True,
        "params": [{"id": "nif", "from": "primary_key"}],
    },
    {
        "id": "empresa.criar_conta_crm",
        "label": "Criar conta no CRM",
        "description": "Cria uma conta de CRM a partir desta empresa. Requer sessão.",
        "object_type": "empresa",
        "kind": "http",
        "method": "POST",
        "url": "/crm/accounts/from-entity",
        "body_params": ["nif"],
        "requires_session": True,
        "params": [{"id": "nif", "from": "primary_key"}],
    },
    {
        "id": "empresa.comparar",
        "label": "Comparar empresas",
        "description": "Abre a vista de comparação com esta empresa.",
        "object_type": "empresa",
        "kind": "navigate",
        "target": "/compare",
        "params": [{"id": "nif", "from": "primary_key"}],
    },
    {
        "id": "contrato.abrir",
        "label": "Abrir contrato",
        "description": "Abre a pesquisa de contratos focada neste contrato.",
        "object_type": "contrato",
        "kind": "navigate",
        "target": "/contracts/search",
        "params": [{"id": "idcontrato", "from": "primary_key"}],
    },
    {
        "id": "contrato.analise_regional",
        "label": "Análise regional",
        "description": "Abre a análise de contratação pública por região.",
        "object_type": "contrato",
        "kind": "http",
        "method": "GET",
        "url": "/contracts/analytics/regional",
        "params": [{"id": "ano", "from": "property", "property": "ano"}],
    },
    {
        "id": "ticker.abrir_ficha",
        "label": "Abrir ficha do instrumento",
        "description": "Abre a página do ticker com preços, notícias e indicadores.",
        "object_type": "ticker",
        "kind": "navigate",
        "target": "/tickers/{simbolo}",
        "params": [{"id": "simbolo", "from": "primary_key"}],
    },
    {
        "id": "ticker.previsao",
        "label": "Gerar previsão",
        "description": "Corre o modelo de previsão (ARIMA/Kronos) para o instrumento.",
        "object_type": "ticker",
        "kind": "http",
        "method": "POST",
        "url": "/forecast",
        "body_params": ["ticker"],
        "params": [{"id": "ticker", "from": "primary_key"}],
    },
    {
        "id": "noticia.analisar_sentimento",
        "label": "Analisar notícias (NLP)",
        "description": "Corre a análise de sentimento/tópicos para o ticker da notícia.",
        "object_type": "noticia",
        "kind": "http",
        "method": "POST",
        "url": "/elastic/analyze/news/{ticker}",
        "params": [{"id": "ticker", "from": "property", "property": "ticker"}],
    },
    {
        "id": "conta.abrir",
        "label": "Abrir conta no CRM",
        "description": "Abre a ficha da conta no CRM. Requer sessão.",
        "object_type": "conta",
        "kind": "navigate",
        "target": "/crm/contas",
        "requires_session": True,
        "params": [{"id": "id", "from": "primary_key"}],
    },
    {
        "id": "conta.sincronizar_empresa",
        "label": "Sincronizar com EmpresasIQ",
        "description": "Atualiza o resumo de contratação pública desta conta. Requer sessão.",
        "object_type": "conta",
        "kind": "http",
        "method": "POST",
        "url": "/crm/accounts/{id}/sync-entity",
        "requires_session": True,
        "params": [{"id": "id", "from": "primary_key"}],
    },
    {
        "id": "ontology.perguntar",
        "label": "Perguntar à ontologia",
        "description": "Responde a uma pergunta com objetos e relações da ontologia como contexto (sem inferir o que não está nos dados).",
        "object_type": None,
        "kind": "ai",
        "url": "/ontology/ai/context",
    },
    {
        "id": "ontology.validar",
        "label": "Validar resposta",
        "description": "Verifica se as entidades e valores de uma resposta existem nos dados (anti-alucinação).",
        "object_type": None,
        "kind": "ai",
        "url": "/ontology/ai/validate",
    },
]


# --------------------------------------------------------------------------
# Persistência
# --------------------------------------------------------------------------
_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _seed_document() -> Dict[str, Any]:
    return {
        "version": ONTOLOGY_VERSION,
        "object_types": copy.deepcopy(SEED_OBJECT_TYPES),
        "link_types": copy.deepcopy(SEED_LINK_TYPES),
        "actions": copy.deepcopy(SEED_ACTIONS),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> Dict[str, Any]:
    return {
        "version": ONTOLOGY_VERSION,
        "custom_object_types": [],
        "custom_link_types": [],
        "patches": {"object_types": {}, "link_types": {}, "actions": {}},
        "disabled": {"object_types": [], "link_types": [], "actions": []},
        "updated_at": _now(),
    }


def _read_store() -> Dict[str, Any]:
    if not ONTOLOGY_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # ficheiro corrompido: recomeça
        logger.warning("Ontologia ilegível (%s); a recomeçar a partir da semente.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for key, default in store.items():
        value = raw.get(key)
        if isinstance(default, dict) and isinstance(value, dict):
            store[key] = {**default, **value}
        elif isinstance(default, list) and isinstance(value, list):
            store[key] = value
        elif key == "version" and isinstance(value, int):
            store["version"] = value
        elif key == "updated_at" and isinstance(value, str):
            store["updated_at"] = value
    for kind in ("object_types", "link_types", "actions"):
        store["patches"].setdefault(kind, {})
        store["disabled"].setdefault(kind, [])
    return store


def _write_store(store: Dict[str, Any]) -> None:
    store["version"] = ONTOLOGY_VERSION
    store["updated_at"] = _now()
    ONTOLOGY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ONTOLOGY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ONTOLOGY_PATH)


def _merge_patch(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica uma alteração a uma definição base (propriedades fundidas por id)."""
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key == "properties" and isinstance(value, list):
            by_id = {prop["id"]: prop for prop in merged.get("properties", [])}
            for prop in value:
                pid = prop.get("id")
                if not pid:
                    continue
                if pid in by_id:
                    by_id[pid].update({k: v for k, v in prop.items() if v is not None})
                else:
                    by_id[pid] = prop
            merged["properties"] = list(by_id.values())
        else:
            merged[key] = value
    return merged


def _is_disabled(store: Dict[str, Any], kind: str, item_id: str) -> bool:
    return item_id in (store["disabled"].get(kind) or [])


def build_ontology(store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Junta a semente, as alterações e os elementos personalizados num documento único."""
    store = store if store is not None else _read_store()
    source = _seed_document()

    def collect(kind: str) -> List[Dict[str, Any]]:
        patches = store["patches"].get(kind) or {}
        items: List[Dict[str, Any]] = []
        for base in source[kind]:
            if _is_disabled(store, kind, base["id"]):
                continue
            item = _merge_patch(base, patches.get(base["id"], {})) if base["id"] in patches else copy.deepcopy(base)
            item["builtin"] = True
            items.append(item)
        custom_key = "custom_object_types" if kind == "object_types" else "custom_link_types"
        for item in store.get(custom_key) or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if _is_disabled(store, kind, item["id"]):
                continue
            custom = copy.deepcopy(item)
            custom["builtin"] = False
            items.append(custom)
        return items

    ontology = {
        "version": ONTOLOGY_VERSION,
        "updated_at": store.get("updated_at") or _now(),
        "domains": copy.deepcopy(DOMAINS),
        "object_types": collect("object_types"),
        "link_types": collect("link_types"),
        "actions": [
            copy.deepcopy(action)
            for action in SEED_ACTIONS
            if not _is_disabled(store, "actions", action["id"])
        ],
        "limits": {
            "max_query_size": 200,
            "max_links_per_object": 50,
            "max_resolve_candidates": 10,
            "notes": [
                "Os tipos base são definidos em `api/ontology_registry.py` e podem ser alterados na Ontologia (as alterações ficam guardadas).",
                "Tipos `derived` e `aggregation` são amostras/agregados honestos: os totais exatos de contratos vivem em /contracts/analytics.",
            ],
        },
    }
    # Metadata derivada, útil para a UI e para as ferramentas da IA.
    incoming: Dict[str, int] = {}
    outgoing: Dict[str, int] = {}
    for link in ontology["link_types"]:
        outgoing[link["from"]] = outgoing.get(link["from"], 0) + 1
        incoming[link["to"]] = incoming.get(link["to"], 0) + 1
    for obj in ontology["object_types"]:
        obj["link_counts"] = {"out": outgoing.get(obj["id"], 0), "in": incoming.get(obj["id"], 0)}
        obj["action_count"] = len([a for a in ontology["actions"] if a.get("object_type") == obj["id"]])
        if obj.get("binding", {}).get("scoped"):
            obj["requires_session"] = bool(obj.get("binding", {}).get("scoped"))
    return ontology


def load_ontology(force: bool = False) -> Dict[str, Any]:
    """Devolve a ontologia efetiva (com cache em memória)."""
    global _cache
    with _lock:
        if not ONTOLOGY_PATH.exists():
            # Materializa o ficheiro na primeira utilização, para poder ser editado/versionado.
            _write_store(_empty_store())
        if _cache is None or force:
            _cache = build_ontology()
        return copy.deepcopy(_cache)


def _store_and_refresh(store: Dict[str, Any]) -> Dict[str, Any]:
    _write_store(store)
    return load_ontology(force=True)


def reset_ontology() -> Dict[str, Any]:
    """Repõe a semente (remove tipos personalizados, alterações e desativações)."""
    return _store_and_refresh(_empty_store())


def _upsert(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if kind not in ("object_types", "link_types"):
        raise ValueError("Só é possível criar/alterar tipos de objeto e tipos de ligação.")
    item_id = str(payload.get("id") or "").strip()
    if not item_id:
        raise ValueError("O campo 'id' é obrigatório.")
    store = _read_store()
    seed_ids = {item["id"] for item in _seed_document()[kind]}
    disabled = store["disabled"].setdefault(kind, [])
    if item_id in disabled:
        disabled.remove(item_id)
    body = {key: value for key, value in payload.items() if key not in ("builtin",)}
    if item_id in seed_ids:
        existing = (store["patches"][kind] or {}).get(item_id, {})
        existing.update(body)
        store["patches"][kind][item_id] = existing
    else:
        custom_key = "custom_object_types" if kind == "object_types" else "custom_link_types"
        items = store.get(custom_key) or []
        for index, item in enumerate(items):
            if item.get("id") == item_id:
                merged = {**item, **body}
                items[index] = merged
                break
        else:
            items.append(body)
        store[custom_key] = items
    _store_and_refresh(store)
    return next(item for item in load_ontology_item(kind) if item["id"] == item_id)


def load_ontology_item(kind: str) -> List[Dict[str, Any]]:
    """Lista os elementos de um tipo (`object_types`|`link_types`|`actions`)."""
    return load_ontology()[kind]


def upsert_object_type(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _upsert("object_types", payload)


def upsert_link_type(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _upsert("link_types", payload)


def delete(kind: str, item_id: str) -> bool:
    """Remove um elemento (personalizado) ou desativa-o (base)."""
    if kind not in ("object_types", "link_types", "actions"):
        raise ValueError("Tipo de elemento inválido.")
    store = _read_store()
    custom_key = "custom_object_types" if kind == "object_types" else "custom_link_types"
    removed = False
    if kind != "actions":
        items = store.get(custom_key) or []
        kept = [item for item in items if item.get("id") != item_id]
        removed = len(kept) != len(items)
        store[custom_key] = kept
    if not removed:
        disabled = store["disabled"].setdefault(kind, [])
        if item_id not in disabled:
            disabled.append(item_id)
            removed = True
        store["patches"][kind].pop(item_id, None)
    _store_and_refresh(store)
    return removed


def object_type_ids() -> List[str]:
    return [item["id"] for item in load_ontology()["object_types"]]
