"""Cliente Elasticsearch do IQ OS — **fachada** do pacote :mod:`api.es`.

O código estava todo neste ficheiro (mais de 21 mil linhas); passou a viver em
módulos por domínio (`api/es/*`), mantendo-se **toda a API pública** aqui: os
serviços, coletores e rotas continuam a importar de
``api.elasticsearch_client`` (incluindo os auxiliares com `_`).

Índices principais:
- ``finance_prices`` — histórico de preços de ações (OHLCV) por ticker.
- ``finance_news`` — notícias por ticker.
- ``finance_contracts`` / ``finance_cire`` / ``finance_people`` — módulos de dados.
"""
import json
import logging
import os
import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
import sys
import types

logger = logging.getLogger(__name__)
from api.es import (
    benchmarks,
    cire,
    citacoes,
    contratos,
    contratos_es,
    contratos_fr,
    contratos_geo,
    core,
    entidades,
    erc,
    geo,
    grafos,
    indices,
    mappings,
    mercados,
    municipios,
    pessoas,
    remuneracoes,
    resumos,
    scraping,
    massa_insolvente,
    sentimento,
    social,
    societario,
    taxonomia,
    utilizador,
    vendas,
)

# --- benchmarks (19 nomes, em api/es/benchmarks.py)
from api.es.benchmarks import (  # noqa: F401
    BENCHMARKS_INDEX,
    BENCHMARK_INDEX_PREFIX,
    _BENCHMARK_ITEM_FIELDS,
    benchmark_garment_stats,
    benchmark_items_index,
    benchmark_items_mappings,
    benchmark_offers,
    benchmark_product_comparison,
    benchmark_store_stats,
    benchmarks_mappings,
    delete_benchmark_definition,
    delete_benchmark_items,
    drop_benchmark_index,
    ensure_benchmark_items_index,
    ensure_benchmarks_index,
    get_benchmark_definition,
    index_benchmark_items,
    list_benchmark_definitions,
    save_benchmark_definition,
)

# --- cire (8 nomes, em api/es/cire.py)
from api.es.cire import (  # noqa: F401
    _cire_query,
    cire_analytics,
    cire_existing_ids,
    cire_interveniente,
    cire_runs_summary,
    cire_status,
    index_cire_items,
    search_cire,
)

# --- citacoes (11 nomes, em api/es/citacoes.py)
from api.es.citacoes import (  # noqa: F401
    _citacoes_query,
    _entidade_key,
    citacoes_existing_ids,
    citacoes_runs_summary,
    citacoes_status,
    delete_citacoes_run,
    get_citacao,
    index_citacoes_items,
    scan_citacoes,
    search_citacoes,
    search_citacoes_entidades,
)

# --- massa insolvente (5 nomes, em api/es/massa_insolvente.py)
from api.es.massa_insolvente import (  # noqa: F401
    MASSA_INSOLVENTE_INDEX,
    index_massa_insolvente_items,
    massa_insolvente_existing_ids,
    massa_insolvente_runs_summary,
    massa_insolvente_status,
    search_massa_insolvente,
)

# --- contratos (29 nomes, em api/es/contratos.py)
from api.es.contratos import (  # noqa: F401
    _AGG_FIELD_CACHE,
    _PARTE_NOME_CACHE,
    _build_contract_query,
    _build_contract_sort,
    _campo_nome_parte,
    _contract_to_flat_dict,
    _contract_type_filters,
    _cpv_description_from_hits,
    _match_pair_query,
    _resolve_agg_target,
    _top_hit_name,
    bulk_index_contracts_from_jsonl,
    contract_years_available,
    contracts_autocomplete,
    contracts_status,
    delete_contracts_by_ids,
    export_contracts_to_excel,
    export_contracts_to_pdf,
    find_contract_ids_by_idcontrato,
    get_company_analytics,
    get_company_contracts,
    get_contract_analytics,
    get_contract_by_id,
    get_contract_network,
    get_contract_regional_analytics,
    get_contract_relationships,
    index_contracts,
    list_contract_years,
    search_contracts,
)

# --- contratos_es (20 nomes, em api/es/contratos_es.py)
from api.es.contratos_es import (  # noqa: F401
    CONTRATOS_ES_ENTITY_FIELDS,
    CONTRATOS_ES_ENTITY_SAMPLE_FIELDS,
    CONTRATOS_ES_FACET_FIELDS,
    _build_contratos_es_query,
    _contratos_es_aggs,
    _contratos_es_entity_filter,
    _contratos_es_sort,
    _contratos_es_value_range,
    _contratos_es_value_source,
    _cpv_label_from_bucket,
    _top_hit_cpv_es_name,
    bulk_index_contratos_es_from_jsonl,
    contratos_es_autocomplete,
    contratos_es_status,
    contratos_es_years_available,
    get_contrato_es,
    get_contratos_es_analytics,
    index_contratos_es,
    search_contratos_es,
    search_contratos_es_entities,
)

# --- contratos_fr (18 nomes, em api/es/contratos_fr.py)
from api.es.contratos_fr import (  # noqa: F401
    CONTRATOS_FR_ENTITY_FIELDS,
    CONTRATOS_FR_ENTITY_SAMPLE_FIELDS,
    CONTRATOS_FR_FACET_FIELDS,
    _build_contratos_fr_query,
    _contratos_fr_aggs,
    _contratos_fr_entity_filter,
    _contratos_fr_sort,
    _contratos_fr_value_source,
    _top_hit_cpv_fr_name,
    bulk_index_contratos_fr_from_jsonl,
    contratos_fr_autocomplete,
    contratos_fr_status,
    contratos_fr_years_available,
    get_contrato_fr,
    get_contratos_fr_analytics,
    index_contratos_fr,
    search_contratos_fr,
    search_contratos_fr_entities,
)

# --- contratos_geo (14 nomes, em api/es/contratos_geo.py)
from api.es.contratos_geo import (  # noqa: F401
    _IBERIA_TEXT_FIELDS_ES,
    _IBERIA_TEXT_FIELDS_FR,
    _IBERIA_TEXT_FIELDS_PT,
    _es_code_level,
    _es_region_detail,
    _fr_region_detail,
    _iberia_map_espanha,
    _iberia_map_france,
    _iberia_map_portugal,
    _iberia_text_query,
    _party_names,
    _pt_region_detail,
    get_contract_region_detail,
    get_contracts_iberia_map,
)

# --- core (22 nomes, em api/es/core.py)
from api.es.core import (  # noqa: F401
    ROOT,
    UNSPECIFIED_LABEL,
    _UNSPECIFIED_KEYS,
    _and_filters,
    _apply_text_operator,
    _as_float,
    _as_int,
    _clean_flattened,
    _fold_text,
    _get_es_url,
    _is_multi_term,
    _safe_slug,
    _search_terms,
    _slug,
    _strip_accents,
    _sum_agg_value,
    _text_search,
    _today,
    _unescape_label,
    _with_required,
    get_es_client,
    is_unspecified,
)

# --- entidades (47 nomes, em api/es/entidades.py)
from api.es.entidades import (  # noqa: F401
    ENTITY_ROLE_SUMMARY_CACHE_FILE,
    ENTITY_ROLE_SUMMARY_MAX_AGE,
    ENTITY_ROLE_SUMMARY_TIMEOUT,
    ENTITY_ROLE_SUMMARY_TTL,
    _ENTITY_ROLE_SUMMARY_BUILDING,
    _ENTITY_ROLE_SUMMARY_BUILD_LOCK,
    _ENTITY_ROLE_SUMMARY_CACHE,
    _ENTITY_ROLE_SUMMARY_LOCK,
    _ENTITY_ROLE_SUMMARY_MAX,
    _bulk_index_docs,
    _cae_code_clause,
    _company_name_query,
    _company_role_filter,
    _company_window_truncated,
    _compute_entity_role_summary,
    _delete_stale_company_docs,
    _enrich_docs_with_company,
    _entity_lookup_by_nif_query,
    _entity_matches_query,
    _entity_role_summary_build,
    _entity_role_summary_cache_get,
    _entity_role_summary_cache_load,
    _entity_role_summary_cache_put,
    _entity_role_summary_cache_save,
    _entity_role_summary_key,
    _entity_role_summary_refresh,
    _normalize_cae_codes,
    _searchable_name,
    entity_nifs_for_cae,
    entity_nifs_for_cpv,
    get_company_by_nif,
    get_company_firmas,
    get_company_trademarks,
    get_entity_by_nif,
    get_entity_relations,
    get_entity_role_summary,
    get_entity_stats,
    index_company_firmas,
    index_company_trademarks,
    index_entities,
    list_entity_countries,
    save_entity_societario_timeline,
    search_companies,
    search_entities,
    search_firmas,
    search_trademarks,
    warm_entity_role_summaries,
)

# --- erc (11 nomes, em api/es/erc.py)
from api.es.erc import (  # noqa: F401
    ERC_ORDENACOES,
    _erc_search,
    _erc_valores,
    _erc_wildcard,
    erc_financeiro_painel,
    erc_status,
    index_erc_bulk,
    search_erc_analise,
    search_erc_entidades,
    search_erc_ocs,
    search_erc_pessoas,
)

# --- geo (5 nomes, em api/es/geo.py)
from api.es.geo import (  # noqa: F401
    PT_DISTRICTS,
    _PT_DISTRICT_BY_KEY,
    _district_filter,
    _pt_district_from_local,
    _region_filter,
)

# --- grafos (31 nomes, em api/es/grafos.py)
from api.es.grafos import (  # noqa: F401
    GRAPH_AGG_BUCKET_BUDGET,
    GRAPH_DIMENSIONS,
    GRAPH_MAX_AGG_BUCKETS,
    GRAPH_MAX_EDGES,
    GRAPH_MAX_NODES,
    GRAPH_MAX_SCAN,
    _COMPETITOR_RE,
    _COMPETITOR_SPLIT_RE,
    _GRAPH_AGG_FIELDS,
    _GRAPH_MAX_VALUES_PER_DOC,
    _GRAPH_SOURCE_FIELDS,
    _UNIFIED_GRAPH_MAX_CONTRACTS,
    _UNIFIED_GRAPH_MAX_PEOPLE,
    _aggregate_dimension_buckets,
    _as_list,
    _bucket_value,
    _descriptions_from_bucket,
    _dimension_values,
    _extract_buckets,
    _graph_add_edge,
    _graph_add_node,
    _graph_competitors,
    _graph_key_for,
    _graph_parties,
    _nodes_from_buckets,
    _resolve_dimension_spec,
    _terms_block,
    aggregate_graph_edges,
    aggregate_graph_nodes,
    build_contract_graph,
    combined_graph_for_company,
)

# --- indices (81 nomes, em api/es/indices.py)
from api.es.indices import (  # noqa: F401
    AGENT_CONFIGS_INDEX,
    ANALISES_EMPRESA_INDEX,
    ARQUIVO_PT_INDEX,
    AUTH_SESSIONS_INDEX,
    AUTH_USERS_INDEX,
    CIRE_INDEX,
    CITACOES_INDEX,
    CONTRACTS_INDEX,
    CONTRATOS_ES_FONTES,
    CONTRATOS_ES_INDEX,
    CONTRATOS_FR_INDEX,
    CONTRIBUINTES_INDEX,
    CRM_INDEX,
    CRM_RBAC_INDEX,
    DEVEDORES_INDEX,
    DEVEDORES_RECOLHAS_INDEX,
    DORA_CONTEUDO_INDEX,
    DORA_INCIDENTES_INDEX,
    DORA_RECOLHAS_INDEX,
    DORA_REGISTO_INDEX,
    DORA_RELATORIOS_INDEX,
    DORA_RISCOS_INDEX,
    DORA_WORKFLOWS_INDEX,
    ENTITIES_INDEX,
    EPT_DECLARACOES_INDEX,
    EPT_RECOLHAS_INDEX,
    EPT_TITULARES_INDEX,
    EPT_TITULARIDADES_INDEX,
    ERC_ENTIDADES_INDEX,
    ERC_OCS_INDEX,
    ERC_PESSOAS_INDEX,
    ERC_RECOLHAS_INDEX,
    ESG_EMPRESAS_INDEX,
    ESG_INDICADORES_INDEX,
    ESG_RECOLHAS_INDEX,
    EU_TAXONOMY_INDEX,
    EVENTS_INDEX,
    FIRMAS_INDEX,
    GLEIF_LEI_INDEX,
    GLOBAL_PADROES_INDEX,
    GRANDES_LITIGANTES_INDEX,
    GRANDES_LITIGANTES_RECOLHAS_INDEX,
    EMPRESAS_LOCAIS_INDEX,
    FREGUESIAS_CONTACTOS_INDEX,
    INDEX_SETTINGS,
    INVESTIGATIONS_INDEX,
    LORENZ_RUNS_INDEX,
    MERCADO_RUNS_INDEX,
    MUNICIPIOS_CONTACTOS_INDEX,
    MUNICIPIOS_DESPESAS_INDEX,
    MUNICIPIO_PESSOAS_INDEX,
    NETWORK_STATE_INDEX,
    NODE_SUMMARIES_INDEX,
    OSINT_INDEX,
    PARTIDOS_INDEX,
    PARTIDOS_RECOLHAS_INDEX,
    PARTIDOS_REGISTO_INDEX,
    PEOPLE_INDEX,
    PLATFORM_MAIL_ACCOUNTS_INDEX,
    PLATFORM_MAIL_MESSAGES_INDEX,
    PROVIDER_KEYS_INDEX,
    REMUNERACOES_AP_INDEX,
    REMUNERACOES_INDEX,
    REMUNERACOES_PESSOAS_INDEX,
    REMUNERACOES_TERRITORIOS_INDEX,
    RIGORBIZ_INDEX,
    SCRAPED_INDEX,
    SEC_FACTS_INDEX,
    SEC_FILINGS_INDEX,
    SEC_RECOLHAS_INDEX,
    SETTINGS_INDEX,
    SIMULATIONS_INDEX,
    SOCIAL_INDEX,
    SOCIETARIO_INDEX,
    SUBVENCOES_INDEX,
    SUBVENCOES_LOTES_INDEX,
    SUPPORT_EVENTS_INDEX,
    SUPPORT_FORM_RESPONSES_INDEX,
    SUPPORT_MESSAGES_INDEX,
    SUPPORT_OPERATORS_INDEX,
    SUPPORT_SESSIONS_INDEX,
    SUPPORT_TICKETS_INDEX,
    SUPPORT_VISITORS_INDEX,
    TICKER_TRANSLATIONS_INDEX,
    TRADEMARKS_INDEX,
    TRANSPARENCIA_GRAFO_ARESTAS_INDEX,
    TRANSPARENCIA_GRAFO_NOS_INDEX,
    TRANSPARENCIA_GRAFO_RECOLHAS_INDEX,
    USER_STATE_INDEX,
    VEREADORES_INDEX,
    VORTAL_PECAS_INDEX,
    WORLD_EVENTS_INDEX,
    WORLD_HISTORY_INDEX,
    WORLD_RELATIONS_INDEX,
    WORLD_STATE_INDEX,
)

# --- mappings (2 nomes, em api/es/mappings.py)
from api.es.mappings import (  # noqa: F401
    _missing_mapping_fields,
    ensure_indices,
)

# --- mercados (23 nomes, em api/es/mercados.py)
from api.es.mercados import (  # noqa: F401
    NEWS_SEARCH_FIELDS,
    _news_doc_id,
    _news_id,
    _news_terms,
    _news_theme_clause,
    _topic_key,
    autocomplete_suggestions,
    delete_ticker_data,
    fetch_news_for_analysis,
    get_news_item,
    index_analyzed_news_items,
    index_news_items,
    index_price_points,
    list_elastic_indices,
    list_indexed_tickers,
    load_news_graph,
    news_stats,
    save_news_graph,
    save_news_translation,
    search_all_news,
    search_all_tickers,
    search_news,
    search_prices,
)

# --- municipios (11 nomes, em api/es/municipios.py)
from api.es.municipios import (  # noqa: F401
    MUNICIPIOS_ORDENACOES,
    contratos_do_municipio,
    fornecedores_do_municipio,
    get_municipio_despesas,
    index_municipios_despesas_bulk,
    index_vereadores_bulk,
    municipios_despesas_mapa,
    municipios_despesas_status,
    search_municipios_despesas,
    search_vereadores,
    vereadores_status,
)

# --- pessoas (31 nomes, em api/es/pessoas.py)
from api.es.pessoas import (  # noqa: F401
    PEOPLE_GRAPH_MAX_COMPANIES,
    PEOPLE_GRAPH_MAX_PEOPLE,
    _CIRE_PEOPLE_FIELDS,
    _PEOPLE_ROLE_KEYS,
    _company_names_from_roles,
    _fetch_people_docs,
    _iter_cire_publications,
    _merge_person_docs,
    _people_facet_agg,
    _people_facet_values,
    _people_filter_clause,
    _person_from_publications,
    _person_role_key,
    _person_sources,
    _prune_people_company_roles,
    _publicacoes_for_people,
    cire_person_processes,
    companies_with_people,
    company_people_from_index,
    get_person_by_nif,
    index_people,
    index_people_from_cire,
    index_people_from_societario,
    people_autocomplete,
    people_filters,
    people_graph_for_company,
    people_graph_for_person,
    people_index_presence,
    people_status,
    search_people,
    search_people_faceted,
)

# --- remuneracoes (9 nomes, em api/es/remuneracoes.py)
from api.es.remuneracoes import (  # noqa: F401
    index_remuneracoes_ap_bulk,
    index_remuneracoes_bulk,
    index_remuneracoes_pessoas_bulk,
    index_remuneracoes_territorios_bulk,
    remuneracoes_status,
    search_remuneracoes,
    search_remuneracoes_ap,
    search_remuneracoes_pessoas,
    search_remuneracoes_territorios,
)

# --- resumos (9 nomes, em api/es/resumos.py)
from api.es.resumos import (  # noqa: F401
    _analise_doc_id,
    _node_summary_id,
    delete_analise_empresa,
    get_analise_empresa,
    get_node_summary,
    index_node_summary,
    list_analises_empresa,
    node_summaries_status,
    save_analise_empresa,
)

# --- scraping (21 nomes, em api/es/scraping.py)
from api.es.scraping import (  # noqa: F401
    DIRECTORY_KEYWORD_FIELDS,
    DIRECTORY_NUMERIC_FIELDS,
    DIRECTORY_TEXT_FIELDS,
    NON_NEWS_SOURCE_IDS,
    NON_NEWS_SOURCE_PREFIXES,
    _ACCENT_VARIANTS,
    _accent_fold_terms,
    _directory_field,
    _news_source_exclusions,
    _scraped_query,
    _sentiment_summary,
    delete_scraped_source,
    directory_index_mapping,
    ensure_directory_index,
    index_directory_items,
    index_scraped_items,
    scraped_status,
    search_directory,
    search_iberinform,
    search_scraped,
    update_scraped_sentiment,
)

# --- sentimento (6 nomes, em api/es/sentimento.py)
from api.es.sentimento import (  # noqa: F401
    SENTIMENT_DAILY_INDEX,
    delete_sentiment_daily,
    index_sentiment_daily,
    list_news_tickers,
    list_sentiment_daily_tickers,
    search_sentiment_daily,
)

# --- social (6 nomes, em api/es/social.py)
from api.es.social import (  # noqa: F401
    SOCIAL_METRIC_FIELDS,
    _social_query,
    delete_social_channel,
    index_social_items,
    search_social,
    social_status,
)

# --- societario (12 nomes, em api/es/societario.py)
from api.es.societario import (  # noqa: F401
    _CONTRACT_PARTY_PATHS,
    _delete_stale_docs,
    _single_nif,
    companies_with_contracts_in_years,
    company_publicacoes,
    contract_years,
    index_societario_items,
    search_societario,
    societario_counts_by_nif,
    societario_status,
    societario_targets,
    societario_targets_filtered,
)

# --- taxonomia (2 nomes, em api/es/taxonomia.py)
from api.es.taxonomia import (  # noqa: F401
    index_eu_taxonomy,
    search_eu_taxonomy,
)

# --- utilizador (18 nomes, em api/es/utilizador.py)
from api.es.utilizador import (  # noqa: F401
    FAVORITE_KINDS,
    _owner_clause,
    _search_slug,
    _user_state_index,
    _with_owner,
    clear_favorites,
    delete_favorite,
    delete_folder,
    delete_search,
    get_workspace,
    list_favorites,
    list_saved_searches,
    load_ticker_translation,
    save_favorite,
    save_folder,
    save_history,
    save_search,
    save_ticker_translation,
)

# --- vendas (8 nomes, em api/es/vendas.py)
from api.es.vendas import (  # noqa: F401
    delete_vendas_penhorados_run,
    get_venda_penhorada,
    index_vendas_penhorados_items,
    search_vendas_penhorados,
    vendas_penhorados_existing_ids,
    vendas_penhorados_runs_summary,
    vendas_penhorados_status,
)

_MODULOS = {
    "benchmarks": benchmarks,
    "cire": cire,
    "citacoes": citacoes,
    "contratos": contratos,
    "contratos_es": contratos_es,
    "contratos_fr": contratos_fr,
    "contratos_geo": contratos_geo,
    "core": core,
    "entidades": entidades,
    "erc": erc,
    "geo": geo,
    "grafos": grafos,
    "indices": indices,
    "mappings": mappings,
    "mercados": mercados,
    "municipios": municipios,
    "pessoas": pessoas,
    "remuneracoes": remuneracoes,
    "resumos": resumos,
    "scraping": scraping,
    "sentimento": sentimento,
    "social": social,
    "societario": societario,
    "taxonomia": taxonomia,
    "utilizador": utilizador,
    "vendas": vendas,
}

# Os módulos em si não fazem parte da API pública desta fachada.
for _nome in list(_MODULOS):
    globals().pop(_nome, None)
globals().pop("_nome", None)


class _ModuloFachada(types.ModuleType):
    """Fachada mutável: atribuir aqui também atualiza os módulos de ``api.es``.

    Os serviços e os testes fazem ``esc.get_es_client = fake`` (por vezes com
    ``monkeypatch``); como as funções passaram a viver em módulos próprios, a
    atribuição (e a remoção) têm de chegar aos módulos que já tinham esse nome
    ligado — é o que mantém o comportamento de antes da divisão.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for modulo in _MODULOS.values():
            if name in modulo.__dict__:
                setattr(modulo, name, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        for modulo in _MODULOS.values():
            if name in modulo.__dict__:
                delattr(modulo, name)


sys.modules[__name__].__class__ = _ModuloFachada
