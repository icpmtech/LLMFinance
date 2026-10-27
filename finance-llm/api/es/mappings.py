"""`ensure_indices`: cria/atualiza o mapping de todos os índices.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, Optional

from elasticsearch import Elasticsearch
from api.es.core import get_es_client
from api.es.indices import AGENT_CONFIGS_INDEX, ANALISES_EMPRESA_INDEX, ARQUIVO_PT_INDEX, AUTH_SESSIONS_INDEX, AUTH_USERS_INDEX, CIRE_INDEX, CITACOES_INDEX, CONTRACTS_INDEX, CONTRATOS_ES_INDEX, CONTRATOS_FR_INDEX, CONTRIBUINTES_INDEX, CRM_INDEX, CRM_RBAC_INDEX, DEVEDORES_INDEX, DEVEDORES_RECOLHAS_INDEX, DORA_CONTEUDO_INDEX, DORA_INCIDENTES_INDEX, DORA_RECOLHAS_INDEX, DORA_REGISTO_INDEX, DORA_RELATORIOS_INDEX, DORA_RISCOS_INDEX, DORA_WORKFLOWS_INDEX, EMPRESAS_LOCAIS_INDEX, ENTITIES_INDEX, EPT_DECLARACOES_INDEX, EPT_RECOLHAS_INDEX, EPT_TITULARES_INDEX, EPT_TITULARIDADES_INDEX, ERC_ENTIDADES_INDEX, ERC_OCS_INDEX, ERC_PESSOAS_INDEX, ERC_RECOLHAS_INDEX, ESG_EMPRESAS_INDEX, ESG_INDICADORES_INDEX, ESG_RECOLHAS_INDEX, EU_TAXONOMY_INDEX, EVENTS_INDEX, FIRMAS_INDEX, FREGUESIAS_CONTACTOS_INDEX, GLEIF_LEI_INDEX, GLOBAL_PADROES_INDEX, GRANDES_LITIGANTES_INDEX, GRANDES_LITIGANTES_RECOLHAS_INDEX, INDEX_SETTINGS, INVESTIGATIONS_INDEX, LORENZ_RUNS_INDEX, MASSA_INSOLVENTE_INDEX, MERCADO_RUNS_INDEX, MUNICIPIOS_CONTACTOS_INDEX, MUNICIPIOS_DESPESAS_INDEX, MUNICIPIO_PESSOAS_INDEX, NETWORK_STATE_INDEX, NODE_SUMMARIES_INDEX, OSINT_INDEX, PARTIDOS_INDEX, PARTIDOS_RECOLHAS_INDEX, PARTIDOS_REGISTO_INDEX, PEOPLE_INDEX, PROVIDER_KEYS_INDEX, REMUNERACOES_INDEX, REMUNERACOES_PESSOAS_INDEX, REMUNERACOES_TERRITORIOS_INDEX, RIGORBIZ_INDEX, SCRAPED_INDEX, SEC_FACTS_INDEX, SEC_FILINGS_INDEX, SEC_RECOLHAS_INDEX, SETTINGS_INDEX, SIMULATIONS_INDEX, SOCIAL_INDEX, SOCIETARIO_INDEX, SUBVENCOES_INDEX, SUBVENCOES_LOTES_INDEX, TICKER_TRANSLATIONS_INDEX, TRADEMARKS_INDEX, TRANSPARENCIA_GRAFO_ARESTAS_INDEX, TRANSPARENCIA_GRAFO_NOS_INDEX, TRANSPARENCIA_GRAFO_RECOLHAS_INDEX, USER_STATE_INDEX, VENDAS_PENHORADOS_INDEX, VEREADORES_INDEX, VORTAL_PECAS_INDEX, WORLD_EVENTS_INDEX, WORLD_HISTORY_INDEX, WORLD_RELATIONS_INDEX, WORLD_STATE_INDEX

logger = logging.getLogger(__name__)




def ensure_indices(es: Optional[Elasticsearch] = None) -> bool:
    """Cria/atualiza os índices necessários, caso ainda não existam."""
    client = es or get_es_client()
    if not client:
        return False

    prices_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "open": {"type": "float"},
            "high": {"type": "float"},
            "low": {"type": "float"},
            "close": {"type": "float"},
            "volume": {"type": "long"},
            "period": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    news_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "topic": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "publisher": {"type": "keyword"},
            "published": {"type": "date"},
            "url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "analyzed_at": {"type": "date"},
            "sentiment": {"type": "keyword"},
            "language": {"type": "keyword"},
            "translated_title": {"type": "text"},
            "translated_summary": {"type": "text"},
            "summary_pt": {"type": "text"},
            "topics": {"type": "keyword"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "keyword"},
                    "type": {"type": "keyword"},
                },
            },
        }
    }

    sentiment_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "news_count": {"type": "integer"},
            "sentiment_mean": {"type": "float"},
            "sentiment_std": {"type": "float"},
            "positive_count": {"type": "integer"},
            "negative_count": {"type": "integer"},
            "positive_ratio": {"type": "float"},
            "negative_ratio": {"type": "float"},
            "updated_at": {"type": "date"},
            # Leitura ponderada (só documentos com termos de sentimento) e a
            # cobertura: sem isto, um dia cheio de títulos sem léxico aparecia
            # «neutro» por diluição, não por ausência de tom.
            "sentiment_signal": {"type": "float"},
            "coverage": {"type": "float"},
            "documents_with_signal": {"type": "integer"},
            # Histórias distintas no dia e quantas notícias eram repetições
            # (a mesma notícia em vários sítios não vale por várias).
            "unique_articles": {"type": "integer"},
            "duplicates": {"type": "integer"},
            "label": {"type": "keyword"},
            "engine": {"type": "keyword"},
            "topics": {"type": "keyword"},
            "sources": {"type": "keyword"},
            "articles": {"type": "integer"},
            # Destaques do dia (títulos nas pontas): guardados para o drill-down,
            # não indexados (não se pesquisam).
            "highlights": {"type": "object", "enabled": False},
            "generated_at": {"type": "date"},
        }
    }

    macro_mappings = {
        "properties": {
            "name": {"type": "keyword"},
            "date": {"type": "date"},
            "value": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    earnings_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "eps_estimate": {"type": "float"},
            "reported_eps": {"type": "float"},
            "surprise_pct": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    contracts_mappings = {
        "properties": {
            "idcontrato": {"type": "keyword"},
            "nAnuncio": {"type": "keyword"},
            "TipoAnuncio": {"type": "keyword"},
            "idINCM": {"type": "keyword"},
            "tipoContrato": {"type": "keyword"},
            "idprocedimento": {"type": "keyword"},
            "tipoprocedimento": {"type": "text"},
            "objectoContrato": {"type": "text"},
            "descContrato": {"type": "text"},
            "adjudicantes": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {
                                "type": "text",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 512}
                                }
                            },
                        },
                    },
                },
            },
            "adjudicatarios": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {
                                "type": "text",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 512}
                                }
                            },
                        },
                    },
                },
            },
            "dataPublicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataCelebracaoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataDecisaoAdjudicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataFechoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "precoContratual": {"type": "float"},
            "cpv": {
                "type": "nested",
                "properties": {
                    "code": {"type": "keyword"},
                    "description": {"type": "text"},
                },
            },
            "prazoExecucao": {"type": "float"},
            "localExecucao": {"type": "keyword"},
            "fundamentacao": {"type": "text"},
            "ProcedimentoCentralizado": {"type": "keyword"},
            "numAcordoQuadro": {"type": "keyword"},
            "DescrAcordoQuadro": {"type": "text"},
            "precoBaseProcedimento": {"type": "float"},
            "PrecoTotalEfetivo": {"type": "float"},
            "regime": {"type": "text"},
            "justifNReducEscrContrato": {"type": "text"},
            "tipoFimContrato": {"type": "keyword"},
            "CritMateriais": {"type": "keyword"},
            "concorrentes": {"type": "text"},
            "linkPecasProc": {"type": "keyword"},
            "Observacoes": {"type": "text"},
            "ContratEcologico": {"type": "keyword"},
            "Ano": {"type": "integer"},
            "fundamentAjusteDireto": {"type": "text"},
            "adjudicatarioPMEs": {"type": "keyword"},
            "NUTs": {"type": "keyword"},
            "Lotes": {"type": "text"},
            "TipoCriterioAdjudicacao": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "search_text": {"type": "text"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "text"},
                    "type": {"type": "keyword"},
                    "nif": {"type": "keyword"},
                    "code": {"type": "keyword"},
                },
            },
        }
    }

    # Contratos de Espanha (PLACSP). Um documento por expediente (o `_id` é
    # `fonte|DIR3|expediente`), com rótulos oficiais CODICE ao lado dos códigos em
    # bruto. Os campos foram desenhados para facetas diretas (keyword) e valores.
    contratos_es_mappings = {
        "properties": {
            "fonte": {"type": "keyword"},
            "pais": {"type": "keyword"},
            "ano": {"type": "integer"},
            "ano_fonte": {"type": "integer"},
            "id_expediente": {"type": "keyword"},
            "estado": {"type": "keyword"},
            "estado_label": {"type": "keyword"},
            "enlace": {"type": "keyword", "index": False},
            "organo_id": {"type": "keyword"},
            "organo_nombre": {
                "type": "text",
                "analyzer": "es_folding",
                "search_analyzer": "es_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "organo_ciudad": {"type": "keyword"},
            "organo_cp": {"type": "keyword"},
            "organo_web": {"type": "keyword", "index": False},
            "organo_email": {"type": "keyword", "index": False},
            "organo_tipo": {"type": "keyword"},
            "tipo_contrato": {"type": "keyword"},
            "tipo_contrato_label": {"type": "keyword"},
            "subtipo_contrato": {"type": "keyword"},
            "objeto": {
                "type": "text",
                "analyzer": "es_folding",
                "search_analyzer": "es_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "descripcion": {"type": "text", "analyzer": "es_folding", "search_analyzer": "es_folding"},
            "cpv": {
                "type": "nested",
                "properties": {
                    "code": {"type": "keyword"},
                    "nombre": {"type": "text", "analyzer": "es_folding", "search_analyzer": "es_folding"},
                },
            },
            "valor_estimado": {"type": "float"},
            "valor_presupuesto": {"type": "float"},
            "valor_base": {"type": "float"},
            "valor_adjudicado": {"type": "float"},
            "valor_adjudicado_con_iva": {"type": "float"},
            "moneda": {"type": "keyword"},
            "fecha_adjudicacion": {"type": "date"},
            "fecha_publicacion": {"type": "date"},
            "fecha_actualizacion": {"type": "date"},
            "fecha_limite": {"type": "date"},
            "hora_limite": {"type": "keyword"},
            "resultado": {"type": "keyword"},
            "resultado_label": {"type": "keyword"},
            "num_ofertas": {"type": "integer"},
            "adjudicatario_nombre": {
                "type": "text",
                "analyzer": "es_folding",
                "search_analyzer": "es_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "adjudicatario_nif": {"type": "keyword"},
            "adjudicatario_nuts": {"type": "keyword"},
            "adjudicatario_nacionalidad": {"type": "keyword"},
            "procedimiento": {"type": "keyword"},
            "procedimiento_label": {"type": "keyword"},
            "urgencia": {"type": "keyword"},
            "sistema_contratacion": {"type": "keyword"},
            "idioma": {"type": "keyword"},
            "localidad": {"type": "keyword"},
            "nuts": {"type": "keyword"},
            "duracion_valor": {"type": "float"},
            "duracion_unidad": {"type": "keyword"},
            "num_lotes": {"type": "integer"},
            "documentos": {"type": "keyword", "index": False},
            "es_menor": {"type": "boolean"},
            "search_text": {"type": "text", "analyzer": "es_folding", "search_analyzer": "es_folding"},
            "ingested_at": {"type": "date"},
        }
    }

    # Contratos de França (DECP / data.gouv.fr). Documento plano por registo,
    # alinhado com Espanha para facilitar facetas e queries diretas.
    contratos_fr_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "pais": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "filename": {"type": "keyword"},
            "id": {"type": "keyword"},
            "nature": {"type": "keyword"},
            "objet": {
                "type": "text",
                "analyzer": "fr_folding",
                "search_analyzer": "fr_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "code_cpv": {"type": "keyword"},
            "cpv": {
                "type": "nested",
                "properties": {
                    "code": {"type": "keyword"},
                    "nom": {"type": "text", "analyzer": "fr_folding", "search_analyzer": "fr_folding"},
                },
            },
            "procedure": {"type": "keyword"},
            "ccag": {"type": "keyword"},
            "offres_recues": {"type": "integer"},
            "type_groupement": {"type": "keyword"},
            "lieu_execution_code": {"type": "keyword"},
            "lieu_execution_type": {"type": "keyword"},
            "lieu_execution_nom": {"type": "keyword"},
            "duree_mois": {"type": "integer"},
            "date_notification": {"type": "date"},
            "date_notification_raw": {"type": "keyword"},
            "date_publication": {"type": "date"},
            "date_publication_raw": {"type": "keyword"},
            "montant": {"type": "float"},
            "montant_estime": {"type": "float"},
            "valor": {"type": "float"},
            "forme_prix": {"type": "keyword"},
            "acheteur_id": {"type": "keyword"},
            "acheteur_nom": {
                "type": "text",
                "analyzer": "fr_folding",
                "search_analyzer": "fr_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "adjudicatario_id": {"type": "keyword"},
            "adjudicatario_type_identifiant": {"type": "keyword"},
            "adjudicatario_nom": {
                "type": "text",
                "analyzer": "fr_folding",
                "search_analyzer": "fr_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "titulaires": {
                "type": "nested",
                "properties": {
                    "type_identifiant": {"type": "keyword"},
                    "id": {"type": "keyword"},
                    "nom": {"type": "text", "analyzer": "fr_folding", "search_analyzer": "fr_folding"},
                },
            },
            "considerations_sociales": {"type": "keyword"},
            "considerations_environnementales": {"type": "keyword"},
            "modalites_execution": {"type": "keyword"},
            "techniques": {"type": "keyword"},
            "types_prix": {"type": "keyword"},
            "source": {"type": "keyword"},
            "taux_avance": {"type": "float"},
            "origine_ue": {"type": "float"},
            "origine_france": {"type": "float"},
            "marche_innovant": {"type": "boolean"},
            "attribution_avance": {"type": "boolean"},
            "sous_traitance_declaree": {"type": "boolean"},
            "ano": {"type": "integer"},
            "search_text": {"type": "text", "analyzer": "fr_folding", "search_analyzer": "fr_folding"},
            "ingested_at": {"type": "date"},
        }
    }

    trademarks_mappings = {
        "properties": {
            "nord": {"type": "long"},
            "process_number": {"type": "keyword"},
            "mark_name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "mark_type": {"type": "keyword"},
            "modality": {"type": "keyword"},
            "holder_name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "holder_nif": {"type": "keyword"},
            "company_nif": {"type": "keyword"},
            "application_date": {"type": "date", "format": "yyyy-MM-dd"},
            "current_phase": {"type": "keyword"},
            "phase_start_date": {"type": "date", "format": "yyyy-MM-dd"},
            "phase_end_date": {"type": "date", "format": "yyyy-MM-dd"},
            "nice_classes": {"type": "keyword"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "text"},
                    "nif": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "phases": {
                "type": "nested",
                "properties": {
                    "phase": {"type": "text"},
                    "start_date": {"type": "date", "format": "yyyy-MM-dd"},
                    "end_date": {"type": "date", "format": "yyyy-MM-dd"},
                },
            },
            "documents": {
                "type": "nested",
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "type": {"type": "text"},
                    "description": {"type": "text"},
                    "url": {"type": "keyword"},
                },
            },
            "ingested_at": {"type": "date"},
            "source_query": {"type": "keyword"},
            "holder_similarity": {"type": "float"},
        }
    }

    firmas_mappings = {
        "properties": {
            "nome": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nipc": {"type": "keyword"},
            "company_nif": {"type": "keyword"},
            "numero_certificado": {"type": "keyword"},
            "certificado_admissibilidade": {"type": "keyword"},
            "concelho": {"type": "keyword"},
            "concelho_sede": {"type": "keyword"},
            "situacao": {"type": "keyword"},
            "situacao_detalhe": {"type": "keyword"},
            "cae_principal": {"type": "keyword"},
            "score": {"type": "float"},
            "search_query": {"type": "keyword"},
            "source": {"type": "keyword"},
            "name_similarity": {"type": "float"},
            "ingested_at": {"type": "date"},
        }
    }

    societario_mappings = {
        "properties": {
            "pub_id": {"type": "keyword"},
            "data_publicacao": {"type": "date"},
            "nif": {"type": "keyword"},
            "entidade": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "firma": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "concelho": {"type": "keyword"},
            "distrito": {"type": "keyword"},
            "freguesia": {"type": "keyword"},
            "codigo_postal": {"type": "keyword"},
            "acto": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "tipo": {"type": "keyword"},
            "tipo_label": {"type": "keyword"},
            "natureza_juridica": {"type": "keyword"},
            "sede": {"type": "text"},
            "conservatoria": {"type": "keyword"},
            "matricula_nipc": {"type": "keyword"},
            "pedido": {"type": "keyword"},
            "requerente": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "ano_contas": {"type": "keyword"},
            "texto": {"type": "text"},
            "has_documento": {"type": "boolean"},
            "documento_url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "search_nif": {"type": "keyword"},
            "search_term": {"type": "keyword"},
            "detail_fetched": {"type": "boolean"},
            "ingested_at": {"type": "date"},
        }
    }

    cire_mappings = {
        "properties": {
            "pub_id": {"type": "keyword"},
            "referencia": {"type": "keyword"},
            "data_publicacao": {"type": "date"},
            "data_propositura": {"type": "date"},
            "tribunal": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tribunal_comarca": {"type": "keyword"},
            "tribunal_sede": {"type": "keyword"},
            "ato": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "processo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "processo_numero": {"type": "keyword"},
            "juizo": {"type": "keyword", "ignore_above": 512},
            "especie": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tipo": {"type": "keyword"},
            "insolvente": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            # Intervenientes do processo (insolvente, administrador, credores, …).
            "intervenientes": {
                "type": "nested",
                "properties": {
                    "papel": {"type": "keyword"},
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "nif": {"type": "keyword"},
                },
            },
            # Todos os NIF/NIPC do processo (pesquisa por entidade sem passar por `nested`).
            "nifs": {"type": "keyword"},
            "has_documento": {"type": "boolean"},
            "documento_url": {"type": "keyword", "index": False},
            "texto": {"type": "text"},
            "extra": {"type": "flattened"},
            "run_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    citacoes_mappings = {
        "properties": {
            "pub_id": {"type": "keyword"},
            "referencia": {"type": "keyword"},
            "data_publicacao": {"type": "date"},
            "tribunal": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tribunal_comarca": {"type": "keyword"},
            "tribunal_sede": {"type": "keyword", "ignore_above": 512},
            "comarca_judicial": {"type": "keyword", "ignore_above": 512},
            "ato": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tipo": {"type": "keyword"},
            "processo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "processo_numero": {"type": "keyword"},
            "juizo": {"type": "keyword", "ignore_above": 512},
            "especie": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "citado": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "papeis": {"type": "keyword"},
            # Intervenientes do édito (exequente, executado, réu, credor, …).
            "intervenientes": {
                "type": "nested",
                "properties": {
                    "papel": {"type": "keyword"},
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "nif": {"type": "keyword"},
                },
            },
            "has_documento": {"type": "boolean"},
            "documento_url": {"type": "keyword", "index": False},
            "texto": {"type": "text"},
            # Documento (PDF) analisado: texto extraído, modelo, valor da execução,
            # prazo e NIF dos intervenientes (que a lista do portal não publica).
            "has_texto": {"type": "boolean"},
            "documento_paginas": {"type": "integer"},
            "documento_caracteres": {"type": "integer"},
            "documento_bytes": {"type": "integer"},
            "documento_truncado": {"type": "boolean"},
            "documento_modelo": {"type": "keyword"},
            "documento_codigo": {"type": "keyword"},
            "documento_referencia_interna": {"type": "keyword", "ignore_above": 256},
            "documento_titulo": {"type": "keyword", "ignore_above": 512},
            "documento_assunto": {"type": "keyword", "ignore_above": 512},
            "documento_valor": {"type": "double"},
            "documento_prazo": {"type": "keyword"},
            "documento_nifs": {"type": "keyword"},
            "documento_partes": {
                "type": "nested",
                "properties": {
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "nif": {"type": "keyword"},
                },
            },
            "documento_erro": {"type": "text", "index": False},
            "documento_extraido_em": {"type": "date"},
            "extra": {"type": "flattened"},
            "run_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    massa_insolvente_mappings = {
        "properties": {
            "pub_id": {"type": "keyword"},
            "titulo": {"type": "keyword"},
            "processo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "processo_numero": {"type": "keyword"},
            "especie": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tipo": {"type": "keyword"},
            "tribunal": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tribunal_comarca": {"type": "keyword"},
            "juizo": {"type": "keyword", "ignore_above": 512},
            "insolventes": {"type": "keyword", "ignore_above": 512},
            "insolventes": {"type": "keyword", "ignore_above": 512},
            "insolvente": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "area_negocio": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "valor_avaliacao": {"type": "double"},
            "valor_texto": {"type": "keyword", "index": False},
            "data_atualizacao": {"type": "date"},
            "descricao": {"type": "text"},
            # Ativos da composição (tipo, descrição, quantidade, localização).
            "ativos": {
                "type": "nested",
                "properties": {
                    "tipo": {"type": "keyword"},
                    "descricao": {"type": "text"},
                    "quantidade": {"type": "keyword"},
                    "localizacao": {"type": "keyword", "ignore_above": 256},
                },
            },
            "ativo_tipos": {"type": "keyword"},
            "localizacoes": {"type": "keyword"},
            "texto": {"type": "text"},
            "run_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    # Venda de bens penhorados em processos executivos (CITIUS + e-leiloes.pt).
    vendas_penhorados_mappings = {
        "properties": {
            "venda_id": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "referencia": {"type": "keyword"},
            "tribunal": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tribunal_sede": {"type": "keyword", "ignore_above": 512},
            "comarca_judicial": {"type": "keyword", "ignore_above": 512},
            "processo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "processo_numero": {"type": "keyword"},
            "juizo": {"type": "keyword", "ignore_above": 512},
            "especie": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "tipo_bem": {"type": "keyword"},
            "subtipo_bem": {"type": "keyword"},
            "modalidade": {"type": "keyword"},
            "estado": {"type": "keyword"},
            "titulo": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "descricao": {"type": "text"},
            "valor_base": {"type": "double"},
            "valor_minimo": {"type": "double"},
            "valor_abertura": {"type": "double"},
            "lance_atual": {"type": "double"},
            "data_venda": {"type": "date"},
            "data_inicio": {"type": "date"},
            "data_fim": {"type": "date"},
            "distrito": {"type": "keyword", "ignore_above": 256},
            "concelho": {"type": "keyword", "ignore_above": 256},
            "freguesia": {"type": "keyword", "ignore_above": 256},
            "morada": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "codigo_postal": {"type": "keyword"},
            "lat": {"type": "float"},
            "lon": {"type": "float"},
            "intervenientes": {
                "type": "nested",
                "properties": {
                    "papel": {"type": "keyword"},
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "nif": {"type": "keyword"},
                    "morada": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "telefone": {"type": "keyword"},
                },
            },
            "executados": {
                "type": "nested",
                "properties": {
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "nif": {"type": "keyword"},
                    "requerido": {"type": "keyword"},
                },
            },
            "gestor": {"type": "object"},
            "fotos": {"type": "keyword", "index": False},
            "onus": {"type": "flattened"},
            "detalhe_url": {"type": "keyword", "index": False},
            "url": {"type": "keyword", "index": False},
            "data_atualizacao": {"type": "date"},
            "extra": {"type": "flattened"},
            "run_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    people_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 512},
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "entity_index_analyzer",
                        "search_analyzer": "entity_search_analyzer",
                    },
                },
            },
            "name_keyword": {"type": "keyword", "ignore_above": 512},
            "is_company": {"type": "boolean"},
            "roles": {
                "type": "nested",
                "properties": {
                    "role": {"type": "keyword"},
                    "role_org": {"type": "keyword"},
                    "company_nif": {"type": "keyword"},
                    "company_name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
                    },
                    "date": {"type": "date"},
                    "publication_date": {"type": "date"},
                    "acto": {"type": "keyword"},
                    "event": {"type": "keyword"},
                    "quota": {"type": "float"},
                    "causa": {"type": "keyword"},
                    "residencia": {"type": "keyword"},
                    "publication_id": {"type": "keyword"},
                    "nacionalidade": {"type": "keyword"},
                    # Comarca do tribunal (cargos vindos dos processos do CIRE).
                    "tribunal": {"type": "keyword", "ignore_above": 512},
                },
            },
            "companies": {
                "type": "nested",
                "properties": {
                    "nif": {"type": "keyword"},
                    "name": {"type": "keyword", "ignore_above": 512},
                },
            },
            "companies_count": {"type": "integer"},
            "roles_count": {"type": "integer"},
            "latest_roles": {"type": "object", "enabled": False},
            "first_seen": {"type": "date"},
            "last_seen": {"type": "date"},
            "source": {"type": "keyword"},
            # Fontes que contribuíram para a ficha (`publicacoes_mj`, `cire`, ...).
            "sources": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "photo_path": {"type": "keyword", "ignore_above": 512},
            "photo_url": {"type": "keyword", "ignore_above": 1024},
            "biography": {"type": "text"},
            "tags": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": False},
        }
    }

    # Resumos de nós: um documento por nó de grafo (`person:123`, `company:456`,
    # `source:host`), com o texto do resumo, a evidência usada e os factos.
    node_summaries_mappings = {
        "properties": {
            "node_id": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "kind": {"type": "keyword"},
            "summary": {"type": "text"},
            "mode": {"type": "keyword"},
            "provider": {"type": "keyword"},
            "model": {"type": "keyword"},
            "queries": {"type": "keyword", "ignore_above": 512},
            # Evidência (web) e factos ficam guardados mas não indexados: servem
            # para reabrir o resumo sem repetir as pesquisas.
            "evidence": {"type": "object", "enabled": False},
            "facts": {"type": "object", "enabled": False},
            "evidence_count": {"type": "integer"},
            "pages_read": {"type": "integer"},
            "generations": {"type": "integer"},
            "generated_at": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    # Contribuintes: índice derivado, com um documento por NIF/NIPC, que agrega os
    # identificadores fiscais de **todos** os índices da plataforma. Os campos
    # `src_*` guardam o contributo de cada fonte (não indexados: são a matéria-prima
    # dos campos derivados e da ficha do contribuinte).
    contribuintes_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 512},
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "entity_index_analyzer",
                        "search_analyzer": "entity_search_analyzer",
                    },
                },
            },
            # Todas as designações conhecidas (a primeira é a preferida em `name`).
            "names": {"type": "keyword", "ignore_above": 512},
            "name_norm": {"type": "keyword", "ignore_above": 512},
            # `type`: empresa | empresario | pessoa | entidade_publica | estrangeiro | desconhecido
            "type": {"type": "keyword"},
            "is_company": {"type": "boolean"},
            # Validade do dígito de controlo (só para NIF portugueses).
            "nif_valid": {"type": "boolean"},
            "country": {"type": "keyword"},
            # Índices de origem onde o contribuinte foi encontrado (ver o catálogo de fontes).
            "sources": {"type": "keyword"},
            "source_labels": {"type": "keyword", "ignore_above": 256},
            "roles": {"type": "keyword"},
            "contracts_count": {"type": "integer"},
            "contracts_as_adjudicante": {"type": "integer"},
            "contracts_as_adjudicatario": {"type": "integer"},
            "contracts_value": {"type": "float"},
            "contracts_first_date": {"type": "date"},
            "contracts_last_date": {"type": "date"},
            "contratos_es_count": {"type": "integer"},
            "contratos_es_value": {"type": "float"},
            "contratos_es_last_date": {"type": "date"},
            # Totais que o cadastro de entidades já traz calculados.
            "entities_contracts_count": {"type": "integer"},
            "entities_value": {"type": "float"},
            "societario_count": {"type": "integer"},
            "societario_last_date": {"type": "date"},
            "cire_count": {"type": "integer"},
            "cire_last_date": {"type": "date"},
            "cire_roles": {"type": "keyword"},
            "trademarks_count": {"type": "integer"},
            "firmas_count": {"type": "integer"},
            "people_roles_count": {"type": "integer"},
            "people_companies_count": {"type": "integer"},
            "crm_account": {"type": "boolean"},
            # --- devedores (listas das Finanças e da Segurança Social) ---
            # Marcado quando o NIF consta de alguma lista; o escalão é o da lista
            # (o valor exato da dívida não é publicado por devedor).
            "devedor": {"type": "boolean"},
            "devedores_count": {"type": "integer"},
            "devedores_escalao": {"type": "keyword"},
            "devedores_valor_min": {"type": "double"},
            "devedores_entidade": {"type": "keyword"},
            "devedores_tipo": {"type": "keyword"},
            "devedores_ficheiro": {"type": "keyword"},
            "devedores_base": {"type": "keyword"},
            "devedores_lista": {"type": "date"},
            "devedores_recolha": {"type": "date"},
            # Soma das ocorrências em todas as fontes (ordenação por relevância/atividade).
            "records_total": {"type": "integer"},
            "first_seen": {"type": "date"},
            "last_seen": {"type": "date"},
            "location": {
                "properties": {
                    "pais": {"type": "keyword"},
                    "distrito": {"type": "keyword"},
                    "concelho": {"type": "keyword"},
                    "freguesia": {"type": "keyword"},
                    "codigo_postal": {"type": "keyword"},
                }
            },
            # Evidência por fonte (o que cada índice mostrou sobre este NIF) em `src_*`;
            # ver o catálogo de fontes em `api/contribuintes_service.py`.
            "search_text": {
                "type": "text",
                "analyzer": "contribuinte_folding",
                "search_analyzer": "contribuinte_folding",
            },
            "run_id": {"type": "keyword"},
            "synced_at": {"type": "date"},
            "src_contratos": {"type": "object", "enabled": False},
            "src_contratos_es": {"type": "object", "enabled": False},
            "src_entidades": {"type": "object", "enabled": False},
            "src_societario": {"type": "object", "enabled": False},
            "src_cire": {"type": "object", "enabled": False},
            "src_pessoas": {"type": "object", "enabled": False},
            "src_devedores": {"type": "object", "enabled": False},
            "src_firmas": {"type": "object", "enabled": False},
            "src_marcas": {"type": "object", "enabled": False},
            "src_crm": {"type": "object", "enabled": False},
        }
    }

    entities_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 512},
                    "autocomplete": {
                        "type": "text",
                        "analyzer": "entity_index_analyzer",
                        "search_analyzer": "entity_search_analyzer",
                    },
                },
            },
            "country": {"type": "keyword"},
            "country_code": {"type": "keyword"},
            "has_nif": {"type": "boolean"},
            "contracts_count": {"type": "integer"},
            "as_adjudicante_count": {"type": "integer"},
            "as_adjudicatario_count": {"type": "integer"},
            "total_value": {"type": "float"},
            "as_adjudicante_value": {"type": "float"},
            "cae_principal": {"type": "keyword"},
            "caes_secundarios": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "societario_timeline": {
                "type": "object",
                "enabled": False,
                "properties": {
                    "markdown": {"type": "text", "index": False},
                    "total": {"type": "integer", "index": False},
                    "backend_used": {"type": "keyword", "index": False},
                    "generated_at": {"type": "date", "index": False},
                },
            },
        }
    }

    user_state_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "entry_kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "folder_id": {"type": "keyword"},
            # Dono do registo (email da sessão). Documentos antigos não têm este
            # campo e continuam a ser mostrados a toda a gente.
            "owner_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "sublabel": {"type": "keyword"},
            "value": {"type": "float"},
            "url": {"type": "keyword", "ignore_above": 1024},
            # Pesquisa guardada no portfólio: consulta + âmbito + filtros.
            "query": {"type": "keyword", "ignore_above": 512},
            "scope": {"type": "keyword"},
            "description": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "results_total": {"type": "long"},
            "filters": {"type": "object", "enabled": False},
            "open": {"type": "object", "enabled": False},
            "parties": {
                "type": "nested",
                "properties": {
                    "nif": {"type": "keyword"},
                    "label": {"type": "text"},
                    "role": {"type": "keyword"},
                },
            },
            "items": {"type": "object", "enabled": False},
            "added_at": {"type": "date"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_run_at": {"type": "date"},
        }
    }

    auth_users_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "email": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "initials": {"type": "keyword"},
            "title": {"type": "keyword"},
            "organization": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "role": {"type": "keyword"},
            "status": {"type": "keyword"},
            "locale": {"type": "keyword"},
            "timezone": {"type": "keyword"},
            # O hash nunca é pesquisado: fica como objeto opaco.
            "password": {"type": "object", "enabled": False},
            "preferences": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_login_at": {"type": "date"},
            "login_count": {"type": "integer"},
        }
    }

    auth_sessions_mappings = {
        "properties": {
            "session_id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "email": {"type": "keyword"},
            "created_at": {"type": "date"},
            "last_seen_at": {"type": "date"},
            "expires_at": {"type": "date"},
            "revoked": {"type": "boolean"},
            "revoked_at": {"type": "date"},
            "user_agent": {"type": "keyword", "ignore_above": 512},
            "ip": {"type": "keyword"},
        }
    }

    events_mappings = {
        "properties": {
            "timestamp": {"type": "date"},
            "level": {"type": "keyword"},
            "source": {"type": "keyword"},
            "message": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "data": {"type": "object", "enabled": False},
            "user_id": {"type": "keyword"},
            "user_email": {"type": "keyword"},
            "method": {"type": "keyword"},
            "path": {"type": "keyword"},
            "status": {"type": "integer"},
            "duration_ms": {"type": "float"},
            "ip": {"type": "keyword"},
            "user_agent": {"type": "keyword", "ignore_above": 512},
            "host": {"type": "keyword"},
            "pid": {"type": "integer"},
        }
    }

    provider_keys_mappings = {
        "properties": {
            "user_id": {"type": "keyword"},
            "keys": {"type": "object", "enabled": False},
            "defaults": {
                "properties": {
                    "provider": {"type": "keyword"},
                    "model": {"type": "keyword"},
                }
            },
            "updated_at": {"type": "date"},
        }
    }

    # Definições da plataforma: um documento por definição (`id` fixo). O valor
    # (`rules`, `payload`…) fica em `object` desligado — é lido e gravado tal como
    # está, sem obrigar a um mapping por cada definição nova.
    settings_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "rules": {"type": "object", "enabled": False},
            "payload": {"type": "object", "enabled": False},
            "updated_at": {"type": "date"},
            "updated_by": {"type": "keyword"},
        }
    }

    # CRM: um único índice para os quatro tipos de registo (`kind`), porque as
    # suas propriedades não colidem e assim as pesquisas cruzadas (timeline de
    # uma conta) fazem-se sem consultas a vários índices.
    crm_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "owner_email": {"type": "keyword"},
            # --- conta (empresa) ---
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "nif": {"type": "keyword"},
            "sector": {"type": "keyword"},
            "status": {"type": "keyword"},
            "website": {"type": "keyword", "ignore_above": 512},
            "email": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "mobile": {"type": "keyword"},
            "address": {"type": "text"},
            "city": {"type": "keyword"},
            "country": {"type": "keyword"},
            "postal_code": {"type": "keyword"},
            "employees": {"type": "integer"},
            "annual_revenue": {"type": "float"},
            # --- contacto ---
            "account_id": {"type": "keyword"},
            "contact_id": {"type": "keyword"},
            "deal_id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "role": {"type": "keyword"},
            "linkedin": {"type": "keyword", "ignore_above": 512},
            "is_primary": {"type": "boolean"},
            # --- oportunidade ---
            "amount": {"type": "float"},
            "weighted_amount": {"type": "float"},
            "currency": {"type": "keyword"},
            "stage": {"type": "keyword"},
            "probability": {"type": "integer"},
            "expected_close_date": {"type": "date"},
            "closed_at": {"type": "date"},
            "loss_reason": {"type": "keyword"},
            "source": {"type": "keyword"},
            # --- atividade ---
            "type": {"type": "keyword"},
            "subject": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "notes": {"type": "text"},
            "due_at": {"type": "date"},
            "done": {"type": "boolean"},
            "done_at": {"type": "date"},
            "priority": {"type": "keyword"},
            # --- comuns ---
            "tags": {"type": "keyword"},
            # Dados externos (ex.: snapshot do EmpresasIQ na conta) ficam opacos.
            "entity": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # Campos dos restantes módulos do CRM (leads, casos, encomendas, contratos,
    # produtos, propostas, previsões, campanhas, marketing, eventos, documentos,
    # conhecimento e IA). O registo declarativo em `api/crm_registry.py` é a
    # fonte única: os mapeamentos são gerados a partir dele, ignorando os campos
    # já existentes (o Elasticsearch não permite alterar tipos já definidos).
    try:
        from api import crm_registry as _crm_registry

        crm_mappings["properties"].update(
            _crm_registry.es_extra_properties(crm_mappings["properties"])
        )
    except Exception as _crm_exc:  # pragma: no cover - defensivo
        logger.warning("Mapeamentos do CRM não foram ampliados: %s", _crm_exc)

    # CRM — administração: utilizadores do CRM, equipas, perfis e auditoria.
    crm_rbac_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "user_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "email": {"type": "keyword"},
            "key": {"type": "keyword"},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "role": {"type": "keyword"},
            "area": {"type": "keyword"},
            "department": {"type": "keyword"},
            "scope": {"type": "keyword"},
            "modules": {"type": "keyword"},
            "actions": {"type": "keyword"},
            "rank": {"type": "integer"},
            "team_id": {"type": "keyword"},
            "team": {"type": "keyword"},
            "job_title": {"type": "keyword"},
            "phone": {"type": "keyword"},
            "quota": {"type": "float"},
            "manager_email": {"type": "keyword"},
            "members": {"type": "keyword"},
            "members_total": {"type": "integer"},
            "region": {"type": "keyword"},
            "target": {"type": "float"},
            "currency": {"type": "keyword"},
            "parent_team_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "description": {"type": "text"},
            "last_login_at": {"type": "date"},
            "suspended": {"type": "boolean"},
            # --- auditoria ---
            "at": {"type": "date"},
            "actor_id": {"type": "keyword"},
            "actor_email": {"type": "keyword"},
            "action": {"type": "keyword"},
            "module": {"type": "keyword"},
            "record_id": {"type": "keyword"},
            "record_label": {"type": "keyword", "ignore_above": 512},
            "summary": {"type": "text"},
            "changes": {"type": "keyword"},
            "ip": {"type": "keyword"},
            "user_agent": {"type": "keyword"},
            "before": {"type": "object", "enabled": False},
            "after": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # EU Taxonomy Navigator: atividades, objetivos e setores oficiais do Compass
    # da Comissão Europeia. Texto original em inglês e tradução em português,
    # com pesquisa em ambos os idiomas por `world_folding`.
    eu_taxonomy_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "activity_id": {"type": "integer"},
            "objective_id": {"type": "integer"},
            "sector_id": {"type": "integer"},
            "name_en": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "name_pt": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "sector_en": {"type": "keyword"},
            "sector_pt": {"type": "keyword"},
            "description_en": {"type": "text", "analyzer": "world_folding"},
            "description_pt": {"type": "text", "analyzer": "world_folding"},
            "nace_codes": {"type": "keyword"},
            "objectives": {
                "type": "nested",
                "properties": {
                    "objective_id": {"type": "integer"},
                    "objective_name_en": {"type": "keyword"},
                    "objective_name_pt": {"type": "keyword"},
                    "objective_short_en": {"type": "keyword"},
                    "objective_short_pt": {"type": "keyword"},
                    "contribution_type_en": {"type": "keyword"},
                    "contribution_type_pt": {"type": "keyword"},
                },
            },
            "url": {"type": "keyword", "ignore_above": 1024},
            "synced_at": {"type": "date"},
        }
    }

    # Recolha (scraping): cada documento é um item extraído por uma "fonte".
    # Os campos variam de site para site e ficam em `data` (`flattened`), o que
    # permite pesquisar e agregar por qualquer campo declarado na definição da
    # fonte sem alterar o mapping índice a índice.
    scraped_mappings = {
        "properties": {
            "source_id": {"type": "keyword"},
            "source_name": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "url": {"type": "keyword", "ignore_above": 1024},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "summary": {"type": "text"},
            "text": {"type": "text"},
            "tags": {"type": "keyword"},
            # Conteúdo específico da fonte (todos os campos extraídos).
            "data": {"type": "flattened"},
            # Sentimento por item (modelo de IA ou léxico local).
            "sentiment": {"type": "keyword"},
            "sentiment_score": {"type": "float"},
            "sentiment_engine": {"type": "keyword"},
            "scraped_at": {"type": "date"},
            "trigger": {"type": "keyword"},
        }
    }

    # RigorBiz: diretório de empresas portuguesas recolhido do site.
    # Campos de topo para pesquisa e filtros simples.
    rigorbiz_mappings = {
        "properties": {
            "name": {
                "type": "text",
                "analyzer": "pt_folding",
                "search_analyzer": "pt_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nif": {"type": "keyword"},
            "cae_code": {"type": "keyword"},
            "cae_description": {
                "type": "text",
                "analyzer": "pt_folding",
                "search_analyzer": "pt_folding",
            },
            "location": {
                "type": "text",
                "analyzer": "pt_folding",
                "search_analyzer": "pt_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "path": {"type": "keyword"},
            "source": {"type": "keyword"},
            "source_url": {"type": "keyword", "ignore_above": 1024},
            "collected_at": {"type": "date"},
        }
    }

    # Pesquisa social: uma publicação de rede social por documento. As métricas
    # de interação têm campos próprios (para filtrar/ordenar/agregar) e os dados
    # específicos de cada plataforma vivem em `data` (`flattened`).
    social_mappings = {
        "properties": {
            "platform": {"type": "keyword"},
            "channel_id": {"type": "keyword"},
            "channel_name": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "post_id": {"type": "keyword"},
            "url": {"type": "keyword", "ignore_above": 1024},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "text": {"type": "text"},
            "author": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "community": {"type": "keyword", "ignore_above": 256},
            "lang": {"type": "keyword"},
            "image": {"type": "keyword", "ignore_above": 1024},
            "video": {"type": "keyword", "ignore_above": 1024},
            # Galeria: todas as imagens/vídeos encontrados (a primeira é a `image`/`video`).
            "images": {"type": "keyword", "ignore_above": 1024},
            "videos": {"type": "keyword", "ignore_above": 1024},
            "tags": {"type": "keyword"},
            "metrics": {"type": "long"},
            "likes": {"type": "long"},
            "comments": {"type": "long"},
            "shares": {"type": "long"},
            "views": {"type": "long"},
            "published_at": {"type": "date"},
            "collected_at": {"type": "date"},
            "sentiment": {"type": "keyword"},
            "sentiment_score": {"type": "float"},
            "sentiment_engine": {"type": "keyword"},
            "trigger": {"type": "keyword"},
            # Pessoa do PessoasIQ a que a publicação foi associada (recolha por pessoa).
            "person_nif": {"type": "keyword"},
            "person_name": {"type": "keyword", "ignore_above": 512},
            "data": {"type": "flattened"},
        }
    }

    # Agentes dinâmicos do IQ OS: configuração de grafos/nós/ferramentas/prompts.
    agent_configs_mappings = {
        "properties": {
            "agent_id": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "description": {"type": "text"},
            "icon": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "backend": {"type": "keyword"},
            "model": {"type": "keyword"},
            "temperature": {"type": "float"},
            "max_tokens": {"type": "integer"},
            "system_prompt": {"type": "text"},
            # Grafo: nós (steps) e ligações opcionais. Um grafo simples pode ter só nós em sequência.
            "graph": {
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "nested",
                        "properties": {
                            "id": {"type": "keyword"},
                            "label": {"type": "text"},
                            "kind": {"type": "keyword"},
                            "prompt": {"type": "text"},
                            "tools": {"type": "keyword"},
                            "output_key": {"type": "keyword"},
                            "next": {"type": "keyword"},
                            "condition": {"type": "object", "enabled": False},
                        },
                    },
                    "edges": {
                        "type": "nested",
                        "properties": {
                            "source": {"type": "keyword"},
                            "target": {"type": "keyword"},
                            "condition": {"type": "object", "enabled": False},
                        },
                    },
                },
            },
            # Ferramentas declaradas (tool_refs) e parâmetros fixos/injetáveis.
            "tools": {
                "type": "nested",
                "properties": {
                    "tool_id": {"type": "keyword"},
                    "provider": {"type": "keyword"},
                    "name": {"type": "keyword"},
                    "description": {"type": "text"},
                    "params": {"type": "object", "enabled": False},
                    "enabled": {"type": "boolean"},
                },
            },
            "rag_index": {"type": "keyword"},
            "rag_mode": {"type": "keyword"},
            "enabled": {"type": "boolean"},
            "is_public": {"type": "boolean"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # GLEIF: um documento por LEI. Campos de texto com analisador de n-gramas
    # (`gleif_index_analyzer`) para pesquisa incremental e subcampo `.keyword`
    # para ordenação/agregação exata.
    gleif_lei_mappings = {
        "properties": {
            "lei": {"type": "keyword"},
            "legal_name": {
                "type": "text",
                "analyzer": "gleif_index_analyzer",
                "search_analyzer": "gleif_search_analyzer",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "legal_name_folded": {"type": "keyword", "ignore_above": 512},
            "other_names": {"type": "text", "analyzer": "gleif_folding"},
            "transliterated_names": {"type": "text", "analyzer": "gleif_folding"},
            "country": {"type": "keyword"},
            "region": {"type": "keyword"},
            "region_name": {"type": "keyword", "ignore_above": 256},
            "city": {"type": "keyword", "ignore_above": 256},
            "postal_code": {"type": "keyword", "ignore_above": 32},
            "address_lines": {"type": "text", "analyzer": "gleif_folding"},
            "hq_country": {"type": "keyword"},
            "hq_region": {"type": "keyword"},
            "hq_city": {"type": "keyword", "ignore_above": 256},
            "jurisdiction": {"type": "keyword"},
            "category": {"type": "keyword"},
            "sub_category": {"type": "keyword"},
            "legal_form": {"type": "keyword"},
            "legal_form_other": {"type": "keyword", "ignore_above": 256},
            "status": {"type": "keyword"},
            "registration_status": {"type": "keyword"},
            "corroboration_level": {"type": "keyword"},
            "conformity_flag": {"type": "keyword"},
            "managing_lou": {"type": "keyword"},
            "registered_as": {"type": "keyword", "ignore_above": 128},
            "registered_at": {"type": "keyword"},
            "validated_as": {"type": "keyword", "ignore_above": 128},
            "bic": {"type": "keyword"},
            "mic": {"type": "keyword"},
            "ocid": {"type": "keyword", "ignore_above": 128},
            "qcc": {"type": "keyword"},
            "gem": {"type": "keyword", "ignore_above": 128},
            "spglobal": {"type": "keyword", "ignore_above": 128},
            "creation_date": {"type": "date"},
            "initial_registration_date": {"type": "date"},
            "last_update_date": {"type": "date"},
            "next_renewal_date": {"type": "date"},
            "ingested_at": {"type": "date"},
            "source": {"type": "keyword"},
            # Geolocalização da **sede legal**, resolvida na ingestão a partir do
            # código postal/cidade (ver `api/gleif_geo.py`). `location` é o
            # `geo_point` usado pela agregação `geohash_grid` do mapa;
            # `geo_precision` diz de onde veio o ponto (postal/city).
            "location": {"type": "geo_point"},
            "lat": {"type": "float"},
            "lon": {"type": "float"},
            "geo_precision": {"type": "keyword"},
        }
    }

    # ------------------------------------------------------------------
    # «World Model»: estado, eventos, relações, rede neuronal dinâmica,
    # simulações de futuro e investigações. Os objetos grandes (lista de nós e
    # arestas, memória da rede, evidências, relatório) ficam guardados mas
    # **não indexados** (`enabled: false`); tudo o que é pesquisável/agregável
    # vive em campos próprios e explícitos.
    # ------------------------------------------------------------------
    world_state_mappings = {
        "properties": {
            "entity_ref": {"type": "keyword"},
            "entity_type": {"type": "keyword"},
            "entity_id": {"type": "keyword"},
            "name": {
                "type": "text",
                "analyzer": "world_index_analyzer",
                "search_analyzer": "world_search_analyzer",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "name_folded": {"type": "keyword", "ignore_above": 512},
            "country": {"type": "keyword"},
            "roles": {"type": "keyword"},
            "state": {"type": "object", "dynamic": True},
            "metrics": {"type": "object", "dynamic": True},
            "contracts_count": {"type": "long"},
            "contracts_value": {"type": "double"},
            "relations_count": {"type": "integer"},
            "events_count": {"type": "integer"},
            "counterparties_count": {"type": "integer"},
            "cpv_codes": {"type": "keyword"},
            "top_cpv": {"type": "keyword"},
            "risk": {"type": "float"},
            "risk_label": {"type": "keyword"},
            "activity": {"type": "float"},
            "activity_trend": {"type": "keyword"},
            "first_seen": {"type": "date"},
            "last_event_at": {"type": "date"},
            "insolvent": {"type": "boolean"},
            "sources": {"type": "keyword"},
            "source_docs": {"type": "integer"},
            "world_version": {"type": "long"},
            "updated_at": {"type": "date"},
        }
    }

    world_events_mappings = {
        "properties": {
            "event_id": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "kind_label": {"type": "keyword", "index": False},
            "entity_ref": {"type": "keyword"},
            "entity_type": {"type": "keyword"},
            "entity_id": {"type": "keyword"},
            "entity_name": {"type": "text", "analyzer": "world_folding"},
            "counterparty_ref": {"type": "keyword"},
            "counterparty_name": {"type": "text", "analyzer": "world_folding"},
            "ts": {"type": "date"},
            "year": {"type": "integer"},
            "month": {"type": "keyword"},
            "value": {"type": "double"},
            "delta": {"type": "double"},
            "severity": {"type": "float"},
            "severity_label": {"type": "keyword"},
            "country": {"type": "keyword"},
            "source_index": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "payload": {"type": "object", "enabled": False},
            "world_version": {"type": "long"},
            "detected_at": {"type": "date"},
        }
    }

    world_relations_mappings = {
        "properties": {
            "relation_id": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "kind_label": {"type": "keyword", "index": False},
            "source_type": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "source_ref": {"type": "keyword"},
            "source_name": {"type": "text", "analyzer": "world_folding"},
            "target_type": {"type": "keyword"},
            "target_id": {"type": "keyword"},
            "target_ref": {"type": "keyword"},
            "target_name": {"type": "text", "analyzer": "world_folding"},
            "weight": {"type": "float"},
            "contracts_count": {"type": "long"},
            "value_sum": {"type": "double"},
            "first_ts": {"type": "date"},
            "last_ts": {"type": "date"},
            "status": {"type": "keyword"},
            "country": {"type": "keyword"},
            "evidence": {"type": "keyword"},
            "world_version": {"type": "long"},
            "updated_at": {"type": "date"},
        }
    }

    world_history_mappings = {
        "properties": {
            "entity_ref": {"type": "keyword"},
            "entity_id": {"type": "keyword"},
            "entity_type": {"type": "keyword"},
            "name": {"type": "text", "analyzer": "world_folding"},
            "grain": {"type": "keyword"},
            "period": {"type": "keyword"},
            "period_start": {"type": "date"},
            "period_end": {"type": "date"},
            # Contadores do período (o que mudou nesse intervalo).
            "contracts": {"type": "long"},
            "value": {"type": "double"},
            "events": {"type": "long"},
            "kinds": {"type": "object", "dynamic": True},
            "new_counterparties": {"type": "long"},
            "first_contract": {"type": "date"},
            # Contadores acumulados até ao fim do período (o estado nessa data).
            "cum_contracts": {"type": "long"},
            "cum_value": {"type": "double"},
            "cum_counterparties": {"type": "long"},
            "cum_directors": {"type": "long"},
            "insolvent": {"type": "boolean"},
            "risk": {"type": "float"},
            "risk_label": {"type": "keyword"},
            "delta_value": {"type": "double"},
            "delta_contracts": {"type": "long"},
            "status": {"type": "keyword"},
            "country": {"type": "keyword"},
            "world_version": {"type": "long"},
            "updated_at": {"type": "date"},
        }
    }

    network_state_mappings = {
        "properties": {
            "version": {"type": "long"},
            "created_at": {"type": "date"},
            "input_version": {"type": "long"},
            "seed": {"type": "long"},
            "nodes": {"type": "object", "enabled": False},
            "edges": {"type": "object", "enabled": False},
            "memory": {"type": "object", "enabled": False},
            "growth": {"type": "object", "enabled": False},
            "pruned": {"type": "object", "enabled": False},
            "predictions": {"type": "object", "enabled": False},
            "anomalies": {"type": "object", "enabled": False},
            "transition": {"type": "object", "enabled": False},
            "top_anomalies": {
                "type": "nested",
                "properties": {
                    "entity_ref": {"type": "keyword"},
                    "entity_name": {"type": "keyword", "ignore_above": 512},
                    "entity_type": {"type": "keyword"},
                    "score": {"type": "float"},
                    "label": {"type": "keyword"},
                    "signals": {"type": "keyword"},
                },
            },
            "top_predictions": {
                "type": "nested",
                "properties": {
                    "entity_ref": {"type": "keyword"},
                    "entity_name": {"type": "keyword", "ignore_above": 512},
                    "entity_type": {"type": "keyword"},
                    "score": {"type": "float"},
                    "expected_contracts": {"type": "float"},
                    "expected_value": {"type": "float"},
                    "risk_after": {"type": "float"},
                },
            },
            "metrics": {"type": "object", "dynamic": True},
            "params": {"type": "object", "enabled": False},
        }
    }

    simulations_mappings = {
        "properties": {
            "run_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "kind": {"type": "keyword"},
            "subject_ref": {"type": "keyword"},
            "subject_name": {"type": "keyword", "ignore_above": 512},
            "subject_type": {"type": "keyword"},
            "horizon": {"type": "integer"},
            "steps_per_year": {"type": "integer"},
            "samples": {"type": "integer"},
            "seed": {"type": "long"},
            "input_version": {"type": "long"},
            "network_version": {"type": "long"},
            "steps": {"type": "object", "enabled": False},
            "scenarios": {"type": "object", "enabled": False},
            "parameters": {"type": "object", "enabled": False},
            "summary": {"type": "object", "dynamic": True},
            "status": {"type": "keyword"},
            "elapsed_s": {"type": "float"},
        }
    }

    investigations_mappings = {
        "properties": {
            "run_id": {"type": "keyword"},
            "question": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}},
            },
            "created_at": {"type": "date"},
            "status": {"type": "keyword"},
            "elapsed_s": {"type": "float"},
            "subject_ref": {"type": "keyword"},
            "subject_name": {"type": "keyword", "ignore_above": 512},
            "subject_type": {"type": "keyword"},
            "steps": {"type": "object", "enabled": False},
            "hypotheses": {"type": "object", "enabled": False},
            "evidence": {"type": "object", "enabled": False},
            "claims": {"type": "object", "enabled": False},
            "simulation": {"type": "object", "enabled": False},
            "counters": {"type": "object", "dynamic": True},
            "sources": {"type": "keyword"},
            "world_version": {"type": "long"},
            "report": {"type": "text", "analyzer": "world_folding"},
            "engine": {"type": "keyword"},
        }
    }

    # Listas de devedores: um documento por devedor e por lista (Finanças ou
    # Segurança Social), com o escalão da dívida em campos próprios (o PDF publica
    # o escalão no cabeçalho, não o valor de cada devedor).
    lorenz_runs_mappings = {
        "properties": {
            "run_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "titulo": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "area": {"type": "keyword"},
            "cpv_prefixos": {"type": "keyword"},
            "ano_de": {"type": "integer"},
            "ano_ate": {"type": "integer"},
            "regiao": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "autor": {"type": "keyword", "ignore_above": 320},
            "regime": {"type": "keyword"},
            "lambda_empirico": {"type": "float"},
            "kpis": {"type": "object", "dynamic": True},
            # Fotografia completa (lida por id, não pesquisada campo a campo).
            "resultado": {"type": "object", "enabled": False},
        }
    }

    mercado_runs_mappings = {
        "properties": {
            "run_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "titulo": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "area": {"type": "keyword"},
            "cpv_prefixos": {"type": "keyword"},
            "ano_de": {"type": "integer"},
            "ano_ate": {"type": "integer"},
            "regiao": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "autor": {"type": "keyword", "ignore_above": 320},
            "empresas": {"type": "integer"},
            "mercado": {"type": "object", "enabled": False},
            # Fotografia completa (lida por id, não pesquisada campo a campo).
            "resultado": {"type": "object", "enabled": False},
        }
    }

    vortal_pecas_mappings = {
        "properties": {
            "uid": {"type": "keyword"},
            "token": {"type": "keyword", "ignore_above": 1024},
            "url_aviso": {"type": "keyword", "ignore_above": 1024},
            "publicado": {"type": "boolean"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "ficheiro": {"type": "keyword", "ignore_above": 512},
            "descricao": {"type": "text", "analyzer": "world_folding", "search_analyzer": "world_folding"},
            "extensao": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "tipo_label": {"type": "keyword"},
            "doc_id": {"type": "long"},
            "file_id": {"type": "keyword", "ignore_above": 256},
            "url": {"type": "keyword", "index": False, "ignore_above": 2048},
            "bytes": {"type": "long"},
            "sha256": {"type": "keyword", "ignore_above": 64},
            "pasta": {"type": "keyword", "index": False, "ignore_above": 1024},
            "recolhido_em": {"type": "date"},
            "descarregado_em": {"type": "date"},
            "indexado_em": {"type": "date"},
            "texto_chars": {"type": "integer"},
            "texto_metodo": {"type": "keyword"},
            "paginas": {"type": "integer"},
            "precisa_ocr": {"type": "boolean"},
            "texto_partes": {"type": "object", "enabled": False},
            "erro": {"type": "text", "index": False},
            # Texto da peça (caderno de encargos, programa do concurso, …):
            # é isto que dá a pesquisa por dentro dos documentos.
            "texto": {"type": "text", "analyzer": "world_folding", "search_analyzer": "world_folding"},
        }
    }

    devedores_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            # `financas` (AT) ou `seguranca_social`.
            "entidade": {"type": "keyword"},
            # `singulares` ou `coletivos`.
            "tipo": {"type": "keyword"},
            "tipo_label": {"type": "keyword"},
            "escalao": {"type": "keyword"},
            "valor_min": {"type": "double"},
            "valor_max": {"type": "double"},
            "ficheiro": {"type": "keyword"},
            "base": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "source_url": {"type": "keyword", "index": False},
            "pdf": {"type": "keyword", "ignore_above": 512},
            # Data de publicação da lista (a que o próprio ficheiro indica).
            "lista_atualizada_em": {"type": "date"},
            # Data em que a lista foi recolhida por nós (pedida pelo utilizador).
            "collected_at": {"type": "date"},
            "pagina": {"type": "integer"},
            "run_id": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    devedores_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            "ficheiro": {"type": "keyword"},
            "entidade": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "tipo_label": {"type": "keyword"},
            "escalao": {"type": "keyword"},
            "valor_min": {"type": "double"},
            "valor_max": {"type": "double"},
            "lista_atualizada_em": {"type": "date"},
            "collected_at": {"type": "date"},
            "registos": {"type": "long"},
            "paginas": {"type": "integer"},
            "pdf_bytes": {"type": "long"},
            "pdf_sha256": {"type": "keyword"},
            "pdf_path": {"type": "keyword", "ignore_above": 512},
            "json_path": {"type": "keyword", "ignore_above": 512},
            "source_url": {"type": "keyword", "index": False},
            "last_modified": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    # Lista de sociedades com mais de 200 ações (Portaria 200/2011): uma linha por
    # sociedade e por ano civil. O portal publica apenas a faixa (entre 201 e 500,
    # ou 501 e superior) — nunca o número exato de ações de cada sociedade.
    grandes_litigantes_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nipc": {"type": "keyword"},
            "nipc_digitos": {"type": "keyword"},
            "denominacao": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "denominacao_fold": {"type": "keyword", "ignore_above": 512},
            "ano": {"type": "integer"},
            "acoes_texto": {"type": "keyword"},
            "acoes_min": {"type": "integer"},
            "faixa": {"type": "keyword"},
            "faixa_label": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "fonte_label": {"type": "keyword"},
            "source_url": {"type": "keyword", "index": False},
            "collected_at": {"type": "date"},
            "recolha_id": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    grandes_litigantes_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "source_url": {"type": "keyword", "index": False},
            "anos": {"type": "integer"},
            "ano_principal": {"type": "integer"},
            "total_portal": {"type": "integer"},
            "registos": {"type": "long"},
            "paginas": {"type": "integer"},
            "duracao_ms": {"type": "long"},
            "collected_at": {"type": "date"},
            "json_path": {"type": "keyword", "ignore_above": 512},
            "run_id": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    # Subvenções públicas: uma linha do ficheiro da IGF por documento. O valor
    # transferido é o único número publicado por linha; o `fundamento_legal`
    # combina o tipo de ato com o número e a data (o `.ods` traz-nos em três
    # colunas, sob um único cabeçalho «FUNDAMENTO LEGAL»).
    subvencoes_mappings = {
        "properties": {
            # `<ano>:<nº da linha no ficheiro>` — reindexar o mesmo ficheiro
            # sobrepõe-se em vez de duplicar.
            "doc_id": {"type": "keyword"},
            # Ano da **listagem** (o ficheiro), não o da decisão: o mesmo apoio
            # aparece em várias listagens anuais (o ficheiro de 2025 repete
            # decisões de 2022), e interessa poder ver as duas versões.
            "ano": {"type": "integer"},
            "linha": {"type": "integer"},
            "ficheiro": {"type": "keyword", "ignore_above": 512},
            "folha": {"type": "keyword"},
            "nif_entidade": {"type": "keyword"},
            "entidade": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nif_beneficiario": {"type": "keyword"},
            "beneficiario": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            # Deduzido do prefixo do NIF (`1`/`2`/`3` pessoa singular, `5`/`7`
            # pessoa coletiva, `6` entidade pública, `8` empresário em nome
            # individual, `9` outros).
            "beneficiario_tipo": {"type": "keyword"},
            # Verdadeiro quando o NIF(B) traz a letra «E» (beneficiário
            # estrangeiro, ver nota b) do cabeçalho do ficheiro).
            "beneficiario_estrangeiro": {"type": "boolean"},
            "montante": {"type": "double"},
            "data_decisao": {"type": "date"},
            "ano_decisao": {"type": "integer"},
            "finalidade": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
            },
            "tipo_ato": {"type": "keyword"},
            "numero_ato": {"type": "keyword"},
            "data_ato": {"type": "date"},
            "fundamento_legal": {"type": "keyword", "ignore_above": 512},
            "lido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    subvencoes_lotes_mappings = {
        "properties": {
            "lote_id": {"type": "keyword"},
            "ano": {"type": "integer"},
            "ficheiro": {"type": "keyword", "ignore_above": 512},
            "rel_path": {"type": "keyword", "ignore_above": 512},
            "folha": {"type": "keyword"},
            "bytes": {"type": "long"},
            "sha256": {"type": "keyword"},
            "modificado_em": {"type": "date"},
            "linhas": {"type": "long"},
            "registos": {"type": "long"},
            "ignoradas": {"type": "long"},
            "montante_total": {"type": "double"},
            "primeira_decisao": {"type": "date"},
            "ultima_decisao": {"type": "date"},
            "jsonl_path": {"type": "keyword", "index": False},
            "lido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    partidos_mappings = {
        "properties": {
            # `<ano>:<secção>:<partido>` — reindexar o mesmo ano sobrepõe-se.
            "doc_id": {"type": "keyword"},
            # Ano da **página do TC** (o exercício a que as contas respeitam).
            "ano": {"type": "integer"},
            # `contas_anuais` | `lista_acoes` | `relatorios_ecfp` | `acordaos` |
            # `decisoes_ecfp` (derivado do anchor da secção na página anual).
            "secao": {"type": "keyword"},
            "secao_titulo": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "ancora": {"type": "keyword"},
            "ordem": {"type": "integer"},
            "partido_nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "partido_sigla": {"type": "keyword"},
            "partido_chave": {"type": "keyword"},
            # Falso quando a página diz que o partido não entregou/não comunicou.
            "entregou": {"type": "boolean"},
            # Texto entre parênteses a seguir ao nome («Não entregou»,
            # «Balanço rectificado em 17 de junho de 2011»).
            "observacao": {"type": "text", "analyzer": "world_folding"},
            # Entradas que são notas da secção e não um partido.
            "nota": {"type": "boolean"},
            "documento": {"type": "boolean"},
            "ficheiro": {"type": "keyword", "ignore_above": 512},
            "ficheiro_kb": {"type": "long"},
            "pdf_url": {"type": "keyword", "ignore_above": 512},
            "pdf_titulo": {"type": "keyword", "ignore_above": 256},
            "pdf_sha256": {"type": "keyword"},
            "paginas": {"type": "integer"},
            # Verdadeiro quando o PDF é uma digitalização sem camada de texto
            # (várias contas anuais e listas de ações do TC são-no).
            "pdf_digitalizado": {"type": "boolean"},
            # Digitalização: não há texto a indexar sem OCR (que não se faz).
            "precisa_ocr": {"type": "boolean"},
            # Texto indexado: `texto` é o **Markdown** do MarkItDown (com as
            # tabelas das contas/listas de ações) ou, em recurso, o texto simples
            # do PyMuPDF. `texto_metodo` diz qual dos dois o produziu.
            "texto": {"type": "text", "analyzer": "world_folding", "search_analyzer": "world_folding"},
            "texto_metodo": {"type": "keyword"},
            "texto_chars": {"type": "integer"},
            "texto_extraido": {"type": "boolean"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    partidos_registo_mappings = {
        "properties": {
            "chave": {"type": "keyword"},
            "denominacao": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "sigla": {"type": "keyword"},
            # Siglas alternativas (as que a CNE publica e as que o TC usa nas
            # páginas anuais) — a ligação entre as duas fontes faz-se por aqui.
            "siglas": {"type": "keyword"},
            "situacao": {"type": "keyword"},
            "data_inscricao": {"type": "date"},
            "site": {"type": "keyword", "ignore_above": 512},
            "logotipo_url": {"type": "keyword", "ignore_above": 512},
            "descricao": {"type": "text", "analyzer": "world_folding"},
            "url": {"type": "keyword", "ignore_above": 512},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    partidos_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            # `tc` (páginas anuais do Tribunal Constitucional) ou `cne`.
            "fonte": {"type": "keyword"},
            "ano": {"type": "integer"},
            "url": {"type": "keyword", "ignore_above": 512},
            "sha256": {"type": "keyword"},
            "bytes": {"type": "long"},
            "itens": {"type": "long"},
            "documentos": {"type": "long"},
            "pdfs": {"type": "long"},
            "com_texto": {"type": "long"},
            "erro": {"type": "text", "analyzer": "world_folding"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    ept_titulares_mappings = {
        "properties": {
            "titular_id": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            # Chave de comparação com `finance_people` (sem acentos/pontuação).
            "nome_normalizado": {"type": "keyword"},
            "declaracoes_total": {"type": "integer"},
            "anos": {"type": "integer"},
            "naturezas": {"type": "keyword"},
            "entidades": {"type": "keyword", "ignore_above": 512},
            "cargos": {"type": "keyword", "ignore_above": 256},
            "orgaos": {"type": "keyword", "ignore_above": 256},
            "ultima_declaracao": {"type": "date"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
            "fonte": {"type": "keyword"},
        }
    }

    ept_titularidades_mappings = {
        "properties": {
            "titularidade_id": {"type": "keyword"},
            "titular_id": {"type": "keyword"},
            "titular": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "entidade_id": {"type": "keyword"},
            "entidade": {"type": "keyword", "ignore_above": 512},
            "cargo_id": {"type": "keyword"},
            "cargo": {"type": "keyword", "ignore_above": 256},
            "inicio": {"type": "date"},
            "fim": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    ept_declaracoes_mappings = {
        "properties": {
            "declaracao_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "titular_id": {"type": "keyword"},
            "titular": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "titular_normalizado": {"type": "keyword"},
            "ano": {"type": "integer"},
            "natureza_codigo": {"type": "integer"},
            "natureza": {"type": "keyword"},
            "estado_codigo": {"type": "integer"},
            "estado": {"type": "keyword"},
            "entidade_id": {"type": "keyword"},
            "entidade": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "orgao_id": {"type": "keyword"},
            "orgao": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "cargo_id": {"type": "keyword"},
            "cargo": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "nif_entidade": {"type": "keyword"},
            "inicio": {"type": "date"},
            "fim": {"type": "date"},
            "entrega": {"type": "date"},
            "relacionada_id": {"type": "keyword"},
            "secoes_inacessiveis": {"type": "keyword"},
            "tem_registo_interesses": {"type": "boolean"},
            # Árvore normalizada (secções, campos e tabelas) e registo de
            # interesses já rotulado: lidos por id, não pesquisados campo a campo.
            "secoes": {"type": "object", "enabled": False},
            "interesses": {"type": "object", "enabled": False},
            # Texto achatado de todas as secções (pesquisa livre).
            "texto": {"type": "text", "analyzer": "world_folding", "search_analyzer": "world_folding"},
            "fonte": {"type": "keyword"},
            "fonte_url": {"type": "keyword", "ignore_above": 512},
            "url_publica": {"type": "keyword", "ignore_above": 512},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    ept_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "totais": {"type": "object", "enabled": False},
            "catalogo": {"type": "object", "enabled": False},
            "atualizado_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    transparencia_grafo_nos_mappings = {
        "properties": {
            "no_id": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "subtipo": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nome_normalizado": {"type": "keyword"},
            # Identificador de origem (id do titular/entidade/cargo na EPT ou NIF).
            "ref_id": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "nif_entidade": {"type": "keyword"},
            "url": {"type": "keyword", "ignore_above": 1024},
            "entidade_ids": {"type": "keyword"},
            "cargos": {"type": "keyword", "ignore_above": 512},
            "anos": {"type": "integer"},
            "declaracoes": {"type": "integer"},
            "grau": {"type": "integer"},
            "peso": {"type": "integer"},
            "local_sede": {"type": "keyword", "ignore_above": 512},
            "concelho": {"type": "keyword", "ignore_above": 256},
            "precisao_geo": {"type": "keyword"},
            "lat": {"type": "double"},
            "lon": {"type": "double"},
            "location": {"type": "geo_point"},
            "detalhes": {"type": "object", "enabled": False},
        }
    }

    transparencia_grafo_arestas_mappings = {
        "properties": {
            "aresta_id": {"type": "keyword"},
            "origem": {"type": "keyword"},
            "destino": {"type": "keyword"},
            "origem_tipo": {"type": "keyword"},
            "destino_tipo": {"type": "keyword"},
            "relacao": {"type": "keyword"},
            "peso": {"type": "integer"},
            "anos": {"type": "integer"},
            "detalhe": {"type": "object", "enabled": False},
        }
    }

    transparencia_grafo_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            "fonte": {"type": "keyword"},
            "totais": {"type": "object", "enabled": False},
            "relacoes": {"type": "object", "enabled": False},
            "atualizado_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    municipios_despesas_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "nome_keyword": {"type": "keyword", "ignore_above": 256},
            # Código geográfico do INE (7 caracteres) — a chave estável do município.
            "geocod": {"type": "keyword"},
            "codigo": {"type": "keyword"},
            "distrito": {"type": "keyword", "ignore_above": 128},
            "nuts": {"type": "keyword", "ignore_above": 32},
            "nuts_nome": {"type": "keyword", "ignore_above": 128},
            "populacao_2021": {"type": "long"},
            # Ano mais recente com despesa publicada (o INE publica um ano por vez).
            "ano_despesas": {"type": "integer"},
            # Anos com despesa publicada (lista), para o filtro por ano não
            # obrigar a percorrer o objeto `despesas_por_ano`, que é opaco.
            "anos": {"type": "keyword"},
            # Classificador económico: valores do município, em euros, do ano mais
            # recente. Ficam a topo para se poder pesquisar e ordenar por eles.
            "despesas_total": {"type": "double"},
            "despesas_correntes": {"type": "double"},
            "despesas_capital": {"type": "double"},
            "despesas_pessoal": {"type": "double"},
            "despesas_bens_servicos": {"type": "double"},
            "despesas_bens_capital": {"type": "double"},
            "despesas_juros": {"type": "double"},
            "despesas_transferencias_freguesias": {"type": "double"},
            "despesas_transferencias_capital": {"type": "double"},
            "despesas_transferencias_capital_freguesias": {"type": "double"},
            "despesas_outras_transferencias_capital": {"type": "double"},
            "despesas_outras_correntes": {"type": "double"},
            "despesas_outras_capital": {"type": "double"},
            "despesas_ativos_financeiros": {"type": "double"},
            "despesas_passivos_financeiros": {"type": "double"},
            # Série completa (ano → classificador → euros) e a legenda dos códigos:
            # lidas por id, não pesquisadas campo a campo.
            "despesas_por_ano": {"type": "object", "enabled": False},
            "classificadores": {"type": "object", "enabled": False},
            # Contratação pública em que o município é adjudicante.
            "contratos_total": {"type": "long"},
            "contratos_valor": {"type": "double"},
            "contratos_por_ano": {"type": "object", "enabled": False},
            "contratos_primeiro_ano": {"type": "integer"},
            "contratos_ultimo_ano": {"type": "integer"},
            "adjudicantes": {"type": "keyword", "ignore_above": 512},
            "fonte_despesas": {"type": "keyword", "ignore_above": 256},
            "fonte_contratos": {"type": "keyword", "ignore_above": 128},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    vereadores_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "name": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "name_keyword": {"type": "keyword", "ignore_above": 512},
            "concelho": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "concelho_keyword": {"type": "keyword", "ignore_above": 128},
            "district": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "district_keyword": {"type": "keyword", "ignore_above": 128},
            "party": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "party_keyword": {"type": "keyword", "ignore_above": 128},
            "role": {"type": "keyword", "ignore_above": 128},
            "role_keyword": {"type": "keyword", "ignore_above": 128},
            "election": {"type": "keyword", "ignore_above": 128},
            "year": {"type": "integer"},
            "source": {"type": "keyword", "ignore_above": 64},
            "source_url": {"type": "keyword", "ignore_above": 512, "index": False},
            "nif": {"type": "keyword", "ignore_above": 32},
            "notes": {"type": "text", "analyzer": "world_folding"},
            "remuneration": {"type": "object", "enabled": False},
            "raw_data": {"type": "object", "enabled": False},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    municipio_pessoas_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "name": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "name_keyword": {"type": "keyword", "ignore_above": 512},
            "concelho": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "concelho_keyword": {"type": "keyword", "ignore_above": 128},
            "district": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "district_keyword": {"type": "keyword", "ignore_above": 128},
            "party": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "party_keyword": {"type": "keyword", "ignore_above": 128},
            "role": {"type": "keyword", "ignore_above": 128},
            "role_keyword": {"type": "keyword", "ignore_above": 128},
            "pelouros": {"type": "keyword", "ignore_above": 256},
            "concelho_id": {"type": "long"},
            "codigo_ine": {"type": "keyword", "ignore_above": 16},
            "election": {"type": "keyword", "ignore_above": 64},
            "mandato": {"type": "keyword", "ignore_above": 16},
            "source": {"type": "keyword", "ignore_above": 64},
            "source_url": {"type": "keyword", "ignore_above": 512, "index": False},
            "profile_url": {"type": "keyword", "ignore_above": 512, "index": False},
            "photo_url": {"type": "keyword", "ignore_above": 1024, "index": False},
            "email": {"type": "keyword", "ignore_above": 256},
            "curriculo_url": {"type": "keyword", "ignore_above": 512, "index": False},
            "raw_role": {"type": "text", "analyzer": "world_folding"},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    municipios_contactos_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "distrito": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito_keyword": {"type": "keyword", "ignore_above": 128},
            "municipio": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "municipio_keyword": {"type": "keyword", "ignore_above": 128},
            # Versões **sem acentos** (ver `CAMPOS_NORMALIZADOS` no serviço): a
            # pesquisa por fragmento usa-as para «alcac» encontrar «ALCÁCER».
            "municipio_fold": {"type": "keyword", "ignore_above": 128},
            "codigo_ine": {"type": "keyword", "ignore_above": 16},
            "nif": {"type": "keyword", "ignore_above": 32},
            "nome_presidente": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "nome_presidente_keyword": {"type": "keyword", "ignore_above": 256},
            "nome_presidente_fold": {"type": "keyword", "ignore_above": 256},
            "morada": {"type": "text", "analyzer": "world_folding"},
            "morada_fold": {"type": "keyword", "ignore_above": 512},
            "codigo_postal": {"type": "keyword", "ignore_above": 16},
            "localidade": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "localidade_fold": {"type": "keyword", "ignore_above": 128},
            "distrito_fold": {"type": "keyword", "ignore_above": 128},
            "email": {"type": "keyword", "ignore_above": 256},
            "email_fold": {"type": "keyword", "ignore_above": 256},
            "telefone": {"type": "keyword", "ignore_above": 32},
            "site": {"type": "keyword", "ignore_above": 512, "index": False},
            "site_domain": {"type": "keyword", "ignore_above": 128},
            "slug": {"type": "keyword", "ignore_above": 128},
            "fonte": {"type": "keyword", "ignore_above": 256},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    freguesias_contactos_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "municipio": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "municipio_keyword": {"type": "keyword", "ignore_above": 128},
            "municipio_fold": {"type": "keyword", "ignore_above": 128},
            "freguesia": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "freguesia_keyword": {"type": "keyword", "ignore_above": 256},
            "freguesia_fold": {"type": "keyword", "ignore_above": 256},
            "codigo_ine": {"type": "keyword", "ignore_above": 16},
            "nif": {"type": "keyword", "ignore_above": 32},
            "nome_presidente": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "nome_presidente_keyword": {"type": "keyword", "ignore_above": 256},
            "nome_presidente_fold": {"type": "keyword", "ignore_above": 256},
            "morada": {"type": "text", "analyzer": "world_folding"},
            "morada_fold": {"type": "keyword", "ignore_above": 512},
            "codigo_postal": {"type": "keyword", "ignore_above": 16},
            "localidade": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "localidade_keyword": {"type": "keyword", "ignore_above": 128},
            "localidade_fold": {"type": "keyword", "ignore_above": 128},
            "descricao_postal": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "descricao_postal_keyword": {"type": "keyword", "ignore_above": 128},
            "descricao_postal_fold": {"type": "keyword", "ignore_above": 128},
            "email": {"type": "keyword", "ignore_above": 256},
            "email_fold": {"type": "keyword", "ignore_above": 256},
            "telefone": {"type": "keyword", "ignore_above": 32},
            "slug": {"type": "keyword", "ignore_above": 256},
            "fonte": {"type": "keyword", "ignore_above": 256},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    empresas_locais_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "designacao": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "designacao_keyword": {"type": "keyword", "ignore_above": 512},
            "designacao_fold": {"type": "keyword", "ignore_above": 512},
            "entidade_local": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "entidade_local_keyword": {"type": "keyword", "ignore_above": 256},
            "entidade_local_fold": {"type": "keyword", "ignore_above": 256},
            "entidade_dominante": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "entidade_dominante_keyword": {"type": "keyword", "ignore_above": 256},
            "entidade_dominante_fold": {"type": "keyword", "ignore_above": 256},
            "participacao_pct": {"type": "float"},
            "setor": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 64}},
            },
            "setor_keyword": {"type": "keyword", "ignore_above": 64},
            "setor_fold": {"type": "keyword", "ignore_above": 64},
            "data_constituicao": {"type": "date"},
            "observacoes": {"type": "text", "analyzer": "world_folding"},
            "observacoes_keyword": {"type": "keyword", "ignore_above": 1024},
            "observacoes_fold": {"type": "keyword", "ignore_above": 1024},
            "slug": {"type": "keyword", "ignore_above": 512},
            "fonte": {"type": "keyword", "ignore_above": 256},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # Abonos dos eleitos locais: uma linha da tabela oficial por documento.
    remuneracoes_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "ano": {"type": "integer"},
            "nivel": {"type": "keyword"},
            "tabela_titulo": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "regime": {"type": "keyword", "ignore_above": 64},
            "grupo": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "cargo": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "modalidade": {"type": "keyword", "ignore_above": 128},
            "natureza": {"type": "keyword", "ignore_above": 64},
            "base_legal": {"type": "keyword", "ignore_above": 512, "index": False},
            "fonte": {"type": "keyword", "ignore_above": 512, "index": False},
            # Valores por escalão de eleitores, com os limites e a percentagem da
            # remuneração do Presidente da República que lhes dá origem.
            "valores": {
                "type": "nested",
                "properties": {
                    "escalao_id": {"type": "keyword"},
                    "escalao": {"type": "keyword", "ignore_above": 512},
                    "min_eleitores": {"type": "long"},
                    "max_eleitores": {"type": "long"},
                    "percentagem_pr": {"type": "double"},
                    "valor": {"type": "double"},
                    "percentagem": {"type": "double"},
                },
            },
            "valor_minimo": {"type": "double"},
            "valor_maximo": {"type": "double"},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # Os abonos aplicados ao território (concelho e freguesia).
    remuneracoes_pessoas_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "cargo": {"type": "keyword", "ignore_above": 128},
            "tipo": {"type": "keyword"},
            "sigla": {"type": "keyword", "ignore_above": 128},
            "concelho_id": {"type": "integer"},
            "concelho": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
            },
            "distrito": {"type": "keyword", "ignore_above": 128},
            "eleitores": {"type": "long"},
            "escalao": {"type": "keyword", "ignore_above": 512},
            "remuneracao_mensal": {"type": "double"},
            "despesas_representacao": {"type": "double"},
            "senhas": {"type": "double"},
            "fonte": {"type": "keyword", "ignore_above": 512},
            "eleicao": {"type": "keyword", "ignore_above": 128},
            "mandato": {"type": "keyword", "ignore_above": 64},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    remuneracoes_territorios_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "territory_id": {"type": "integer"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nome_keyword": {"type": "keyword", "ignore_above": 512},
            "nivel": {"type": "keyword"},
            "tipo_territorio": {"type": "integer"},
            "distrito": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "distrito_keyword": {"type": "keyword", "ignore_above": 512},
            "concelho": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "concelho_keyword": {"type": "keyword", "ignore_above": 512},
            "concelho_id": {"type": "integer"},
            "eleitores": {"type": "long"},
            "votantes": {"type": "long"},
            "abstencao_percentagem": {"type": "double"},
            "mandatos": {"type": "integer"},
            # Eleitos nas autárquicas de 2025: o presidente de câmara tem nome e
            # lista; a câmara traz os mandatos e os vereadores de cada partido.
            "presidente": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "partido": {"type": "keyword", "ignore_above": 128},
            "partido_descricao": {"type": "keyword", "ignore_above": 256},
            "vereadores": {"type": "integer"},
            "executivo": {
                "type": "object",
                "properties": {
                    "nome": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                    "cargo": {"type": "keyword", "ignore_above": 64},
                    "partido": {"type": "keyword", "ignore_above": 128},
                    "atribuicoes": {"type": "text"},
                },
            },
            "executivo_nomes": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "executivo_fonte": {"type": "keyword", "ignore_above": 512},
            # A câmara municipal (o edifício): fotografia com autor e licença,
            # coordenadas e classificação patrimonial. Vem do Wikidata/Commons.
            "camara_municipal": {
                "type": "object",
                "properties": {
                    "designacao": {"type": "text"},
                    "imagem": {"type": "keyword", "ignore_above": 512},
                    "foto_url": {"type": "keyword", "ignore_above": 2048, "index": False},
                    "credito_autor": {"type": "text"},
                    "credito_licenca": {"type": "keyword", "ignore_above": 256},
                    "patrimonio": {"type": "keyword", "ignore_above": 512},
                    "wikidata": {"type": "keyword", "ignore_above": 64},
                    "artigo": {"type": "keyword", "ignore_above": 2048, "index": False},
                },
            },
            "tem_foto_camara": {"type": "boolean"},
            # O brasão do município e a data de criação do concelho (Wikipédia e
            # Commons, com o Wikidata a completar os brasões que a tabela não traz).
            "brasao": {"type": "keyword", "ignore_above": 2048, "index": False},
            "brasao_ficheiro": {"type": "keyword", "ignore_above": 512},
            "brasao_autor": {"type": "text"},
            "brasao_licenca": {"type": "keyword", "ignore_above": 256},
            "tem_brasao": {"type": "boolean"},
            "criacao": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "criacao_ano": {"type": "integer"},
            "codigo_tres_letras": {"type": "keyword", "ignore_above": 8},
            "populacao_2021": {"type": "integer"},
            "camara": {
                "type": "object",
                "properties": {
                    "sigla": {"type": "keyword", "ignore_above": 128},
                    "votos": {"type": "long"},
                    "percentagem": {"type": "double"},
                    "mandatos": {"type": "integer"},
                    "presidentes": {"type": "integer"},
                    "vereadores": {"type": "integer"},
                    "nomes": {"type": "text"},
                },
            },
            "escalao_id": {"type": "keyword"},
            "escalao": {"type": "keyword", "ignore_above": 512},
            # Remuneração mensal do presidente (exclusividade, tempo inteiro) e as
            # restantes verbas do escalão, com o nome da rubrica que as origina.
            "remuneracao_mensal": {"type": "double"},
            "verbas": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "grupo": {"type": "keyword", "ignore_above": 512},
                    "cargo": {"type": "keyword", "ignore_above": 512},
                    "modalidade": {"type": "keyword", "ignore_above": 128},
                    "natureza": {"type": "keyword", "ignore_above": 64},
                    "valor": {"type": "double"},
                },
            },
            # Polígono desenhável no mapa, no sistema de coordenadas SVG da
            # própria fonte (pontos «x,y» já normalizados para 0-1000).
            "poligono": {"type": "keyword", "index": False, "doc_values": False},
            "poligono_pontos": {"type": "integer"},
            "centroide": {
                "type": "object",
                "properties": {"x": {"type": "double"}, "y": {"type": "double"}},
            },
            # Coordenadas geográficas (Wikidata/OSM) — permitem pintar o
            # território num mapa real e fazer consultas por caixa/raio.
            "lat": {"type": "double"},
            "lon": {"type": "double"},
            "localizacao": {"type": "geo_point"},
            "fonte": {"type": "keyword", "ignore_above": 128},
            "fonte_url": {"type": "keyword", "ignore_above": 512, "index": False},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    # Portal da Transparência da ERC. As sub-listas (pessoas dos órgãos sociais,
    # OCS detidos e participações) são `nested` para poderem ser agregadas sem
    # misturar valores de documentos diferentes.
    _erc_participacao = {
        "type": "nested",
        "properties": {
            "id": {"type": "keyword"},
            "nome": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "e_empresa": {"type": "boolean"},
            "e_pessoa": {"type": "boolean"},
            # `detentor` (a contraparte detém o sujeito) ou `detida` (é detida por ele).
            "tipo_relacao": {"type": "keyword"},
            "tipo_detencao": {"type": "keyword", "ignore_above": 128},
            "percentagem": {"type": "keyword", "ignore_above": 32},
            "percentagem_valor": {"type": "double"},
            "direitos_voto": {"type": "keyword", "ignore_above": 32},
            "direitos_voto_valor": {"type": "double"},
        },
    }

    erc_entidades_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nome_keyword": {"type": "keyword", "ignore_above": 512},
            "slug": {"type": "keyword", "ignore_above": 512},
            "url": {"type": "keyword", "ignore_above": 512, "index": False},
            "tipo_sociedade": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "actividade_principal": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito_keyword": {"type": "keyword", "ignore_above": 128},
            "contabilidade_organizada": {"type": "boolean"},
            "detem_ocs": {"type": "boolean"},
            "capital_social": {"type": "keyword", "ignore_above": 64},
            "capital_social_eur": {"type": "double"},
            "nr_registo": {"type": "keyword"},
            "n_ocs": {"type": "integer"},
            "n_pessoas": {"type": "integer"},
            "n_detentores": {"type": "integer"},
            "n_detidas": {"type": "integer"},
            "pessoas": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "nome": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "tipo_orgao": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 128}}},
                    "funcao": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 128}}},
                },
            },
            "pessoas_nomes": {"type": "keyword", "ignore_above": 512},
            "ocs": {
                "type": "nested",
                "properties": {
                    "designacao": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "tipo": {"type": "keyword", "ignore_above": 128},
                    "entidade_proprietaria": {"type": "keyword", "ignore_above": 512},
                    "distrito": {"type": "keyword", "ignore_above": 128},
                },
            },
            "ocs_designacoes": {"type": "keyword", "ignore_above": 512},
            "detentores": _erc_participacao,
            "detidas": _erc_participacao,
            # Série financeira (secção `dafin`), um objecto por exercício. `nested`
            # porque os rácios e os valores só fazem sentido dentro do mesmo ano.
            "financeiro": {
                "type": "nested",
                "properties": {
                    "ano": {"type": "integer"},
                    "ano_comparacao": {"type": "integer"},
                    "ativo_total": {"type": "double"},
                    "passivo_total": {"type": "double"},
                    "passivos_totais": {"type": "double"},
                    "capital_proprio": {"type": "double"},
                    "rendimentos_totais": {"type": "double"},
                    "resultados_antes_custos": {"type": "double"},
                    "resultados_operacionais_depreciacoes": {"type": "double"},
                    "resultados_liquidos": {"type": "double"},
                    "responsabilidades_nao_inscritas": {"type": "double"},
                    "autonomia_financeira": {"type": "double"},
                    "endividamento": {"type": "double"},
                    "margem_liquida": {"type": "double"},
                    "crescimento_rendimentos": {"type": "double"},
                    "confidencialidade": {"type": "boolean"},
                    "nota": {"type": "text", "index": False},
                },
            },
            # Indicadores de topo do último exercício: existem como campos próprios
            # para ordenar e agregar sem passar por `nested`.
            "n_anos_financeiro": {"type": "integer"},
            "primeiro_ano_financeiro": {"type": "integer"},
            "ultimo_ano_financeiro": {"type": "integer"},
            "ultimo_ativo": {"type": "double"},
            "ultimo_passivo": {"type": "double"},
            "ultimo_capital_proprio": {"type": "double"},
            "ultimo_rendimentos": {"type": "double"},
            "ultimo_resultados": {"type": "double"},
            "ultimo_autonomia": {"type": "double"},
            "ultimo_endividamento": {"type": "double"},
            "ultimo_crescimento_rendimentos": {"type": "double"},
            "anos_resultados_positivos": {"type": "integer"},
            "anos_resultados_negativos": {"type": "integer"},
            "confidencialidade": {"type": "boolean"},
            "financeiro_atualizado_em": {"type": "date"},
            # Análise de risco: os scores são campos próprios (para filtrar e
            # ordenar) e os indicadores que os justificam ficam por indexar, já
            # que o `valor` tanto é número como texto ou booleano.
            "analise": {
                "type": "object",
                "properties": {
                    "transparencia": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "nivel": {"type": "keyword"},
                            "indicadores": {"type": "object", "enabled": False},
                        },
                    },
                    "credito": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "nivel": {"type": "keyword"},
                            "disponivel": {"type": "boolean"},
                            "indicadores": {"type": "object", "enabled": False},
                        },
                    },
                    "risco": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "banda": {"type": "keyword"},
                            "componentes": {"type": "object", "enabled": False},
                        },
                    },
                    "alertas": {"type": "keyword", "ignore_above": 512},
                    "cobertura": {
                        "type": "object",
                        "properties": {
                            "anos_financeiros": {"type": "integer"},
                            "primeiro_ano": {"type": "integer"},
                            "ultimo_ano": {"type": "integer"},
                            "confidencialidade": {"type": "boolean"},
                        },
                    },
                    "limitacoes": {"type": "text", "index": False},
                    "fonte": {"type": "keyword"},
                    "atualizado_em": {"type": "date"},
                },
            },
            "fonte": {"type": "keyword"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    erc_pessoas_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nome": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "nome_keyword": {"type": "keyword", "ignore_above": 512},
            "slug": {"type": "keyword", "ignore_above": 512},
            "url": {"type": "keyword", "ignore_above": 512, "index": False},
            "actividade_principal": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito_keyword": {"type": "keyword", "ignore_above": 128},
            "detem_ocs": {"type": "boolean"},
            "n_empresas": {"type": "integer"},
            "n_participacoes": {"type": "integer"},
            "orgaos": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "nome": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                    "tipo_orgao": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 128}}},
                    "funcao": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 128}}},
                },
            },
            "empresas": {"type": "keyword", "ignore_above": 512},
            "participacoes": _erc_participacao,
            "participacoes_nomes": {"type": "keyword", "ignore_above": 512},
            "financeiro": {"type": "object", "enabled": False},
            "fonte": {"type": "keyword"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    erc_ocs_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "designacao": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "designacao_keyword": {"type": "keyword", "ignore_above": 512},
            "tipo": {"type": "keyword", "ignore_above": 128},
            "entidade_proprietaria": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "entidade_proprietaria_id": {"type": "keyword"},
            "distrito": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 128}},
            },
            "distrito_keyword": {"type": "keyword", "ignore_above": 128},
            "fonte": {"type": "keyword"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    erc_recolhas_mappings = {
        "properties": {
            "recolha_id": {"type": "keyword"},
            # `listagem` (todas as entidades) | `entidade` | `pessoa`.
            "tipo": {"type": "keyword"},
            "entidade_id": {"type": "keyword"},
            "nome": {"type": "keyword", "ignore_above": 512},
            "url": {"type": "keyword", "ignore_above": 512},
            "sha256": {"type": "keyword"},
            "bytes": {"type": "long"},
            "itens": {"type": "long"},
            "erro": {"type": "text", "analyzer": "world_folding"},
            "recolhido_em": {"type": "date"},
            "ingested_at": {"type": "date"},
        }
    }

    analises_empresa_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "nif": {"type": "keyword"},
            "nome": {"type": "keyword", "ignore_above": 512},
            "pais": {"type": "keyword"},
            "titulo": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "notas": {"type": "text", "analyzer": "world_folding"},
            "criado_em": {"type": "date"},
            "atualizado_em": {"type": "date"},
            "autor": {"type": "keyword"},
            "autor_email": {"type": "keyword"},
            "anos": {"type": "integer"},
            "contratos_total": {"type": "long"},
            "contratos_analisados": {"type": "long"},
            "valor_total": {"type": "float"},
            "severidade": {"type": "keyword"},
            "sinais": {"type": "keyword"},
            "regras": {"type": "keyword"},
            "insolvente": {"type": "boolean"},
            "ia": {"type": "boolean"},
            "ia_modelo": {"type": "keyword"},
            "ia_provider": {"type": "keyword"},
            "resumo": {"type": "text", "analyzer": "world_folding"},
            "ficha_ia": {"type": "text", "analyzer": "world_folding"},
            # Fotografia completa da análise (a análise é grande e só é lida por id).
            "analise": {"type": "object", "enabled": False},
            "browser": {"type": "object", "enabled": False},
            "fontes": {"type": "keyword"},
        }
    }

    global_padroes_mappings = {
        "properties": {
            "kind": {"type": "keyword"},
            "pais": {"type": "keyword"},
            "pais_label": {"type": "keyword", "ignore_above": 128},
            "indice": {"type": "keyword"},
            "ano": {"type": "integer"},
            "anos": {"type": "integer"},
            "contratos": {"type": "long"},
            "documentos": {"type": "long"},
            "valor": {"type": "float"},
            "valor_medio": {"type": "float"},
            "valor_mediano": {"type": "float"},
            "valor_maximo": {"type": "float"},
            "valor_base": {"type": "float"},
            "contratos_com_base": {"type": "long"},
            "aditivos": {"type": "long"},
            "valor_aditivos": {"type": "float"},
            "taxa_aditivo": {"type": "float"},
            "sem_concorrentes": {"type": "long"},
            "ofertas_media": {"type": "float"},
            "ofertas_mediana": {"type": "float"},
            "gerado_em": {"type": "date"},
            "duracao_s": {"type": "float"},
            "versao": {"type": "integer"},
            "ajuste_direto": {"type": "object", "enabled": False},
            # Agregados e topos (lidos por id, não pesquisados campo a campo).
            "meses": {"type": "object", "enabled": False},
            "procedimentos": {"type": "object", "enabled": False},
            "cpvs": {"type": "object", "enabled": False},
            "cpvs_somados": {"type": "object", "enabled": False},
            "adjudicatarias": {"type": "object", "enabled": False},
            "adjudicantes": {"type": "object", "enabled": False},
        }
    }

    ticker_translations_mappings = {
        "properties": {
            "ticker": {"type": "keyword", "ignore_above": 32},
            "original_text": {"type": "text", "index": False},
            "translated_text": {"type": "text", "index": False},
            "target_language": {"type": "keyword", "ignore_above": 16},
            "backend": {"type": "keyword", "ignore_above": 120},
            "model": {"type": "keyword", "ignore_above": 120},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }

    osint_mappings = {
        "properties": {
            "target": {"type": "keyword", "ignore_above": 120},
            "kind": {"type": "keyword"},
            "category": {"type": "keyword", "ignore_above": 64},
            "found": {"type": "integer"},
            "total": {"type": "integer"},
            "not_found": {"type": "integer"},
            "errors": {"type": "integer"},
            "duration_s": {"type": "float"},
            "hits": {"type": "object", "enabled": False},
            "graph": {"type": "object", "enabled": False},
            "pivots": {"type": "object", "enabled": False},
            "stats": {"type": "object", "enabled": False},
            # Facetas pesquisáveis (o resto dos detalhes fica em `hits`, opaco).
            "names": {"type": "keyword", "ignore_above": 120},
            "emails": {"type": "keyword", "ignore_above": 160},
            "sites": {"type": "keyword", "ignore_above": 64},
            "pivot_sites": {"type": "keyword", "ignore_above": 64},
            "aliases": {"type": "keyword", "ignore_above": 160},
            # Palavras normalizadas de nomes/aliases (permite procurar «johnson»
            # sem escrever o nome completo).
            "tokens": {"type": "keyword", "ignore_above": 64},
            "scanned_at": {"type": "date"},
            "user_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    # Arquivo.pt — capturas da web preservadas pela FCT.
    arquivo_pt_mappings = {
        "properties": {
            "title": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "url": {
                "type": "keyword",
                "ignore_above": 1024,
                "fields": {"text": {"type": "text", "analyzer": "world_folding"}},
            },
            "domain": {
                "type": "keyword",
                "ignore_above": 256,
                "fields": {"text": {"type": "text", "analyzer": "world_folding"}},
            },
            "tstamp": {"type": "keyword", "ignore_above": 16},
            "capture_date": {"type": "date"},
            "digest": {"type": "keyword", "ignore_above": 64},
            "mime_type": {"type": "keyword", "ignore_above": 64},
            "status": {"type": "keyword"},
            "length": {"type": "long"},
            "collection": {"type": "keyword"},
            "query": {"type": "keyword", "ignore_above": 256},
            "site": {"type": "keyword", "ignore_above": 256},
            "type": {"type": "keyword", "ignore_above": 32},
            "snippet": {"type": "text", "analyzer": "world_folding"},
            "text": {"type": "text", "analyzer": "world_folding"},
            "link_to_archive": {"type": "keyword", "ignore_above": 1024},
            "link_to_no_frame": {"type": "keyword", "ignore_above": 1024},
            "link_to_screenshot": {"type": "keyword", "ignore_above": 1024},
            "link_to_extracted_text": {"type": "keyword", "ignore_above": 1024},
            "link_to_metadata": {"type": "keyword", "ignore_above": 1024},
            "link_to_original_file": {"type": "keyword", "ignore_above": 1024},
            "filename": {"type": "keyword", "ignore_above": 512},
            "host_key": {"type": "keyword", "ignore_above": 256},
            "kind": {"type": "keyword"},  # "search" | "cdx"
            "collected_at": {"type": "date"},
            "raw": {"type": "object", "enabled": False},
        }
    }

    # ESG — fotografia por empresa. Os campos que a UI consulta (score, pilares,
    # cobertura, setor, dimensão) são indexados; os blocos grandes (componentes,
    # histórico, benchmark, evidências e carteira de fornecedores) ficam
    # `enabled: false` porque só são lidos por id.
    esg_empresas_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "name": {
                "type": "text",
                "analyzer": "world_folding",
                "search_analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "name_keyword": {"type": "keyword", "ignore_above": 512},
            "names": {"type": "keyword", "ignore_above": 512},
            "pais": {"type": "keyword"},
            "cae_principal": {"type": "keyword"},
            "cae_label": {"type": "keyword", "ignore_above": 256},
            "setor": {"type": "keyword"},
            "setor_label": {"type": "keyword", "ignore_above": 256},
            "setor_fonte": {"type": "keyword"},
            "dimensao": {"type": "keyword"},
            "dimensao_label": {"type": "keyword", "ignore_above": 128},
            "score": {"type": "float"},
            "nivel": {"type": "keyword"},
            "nivel_label": {"type": "keyword", "ignore_above": 64},
            "cor": {"type": "keyword", "ignore_above": 16},
            "cobertura": {"type": "float"},
            "confianca": {"type": "keyword"},
            "pilares": {
                "properties": {
                    "e": {"type": "float"},
                    "s": {"type": "float"},
                    "g": {"type": "float"},
                    "economico": {"type": "float"},
                }
            },
            "contratos": {"type": "integer"},
            "valor": {"type": "float"},
            "adjudicantes": {"type": "integer"},
            "fornecedores_count": {"type": "integer"},
            "taxonomia_elegivel": {"type": "boolean"},
            "taxonomia_alinhamento": {"type": "keyword"},
            "taxonomia_nace": {"type": "keyword", "ignore_above": 32},
            "taxonomia_objetivos": {"type": "integer"},
            "taxonomia_atividades": {"type": "integer"},
            "taxonomia_cobertura_verificacao": {"type": "float"},
            "ods": {"type": "integer"},
            "ano": {"type": "integer"},
            "anos": {"type": "integer"},
            "modelo_versao": {"type": "keyword", "ignore_above": 32},
            "gerado_em": {"type": "date"},
            "atualizado_em": {"type": "date"},
            "fontes": {"type": "keyword", "ignore_above": 128},
            "avisos": {"type": "keyword", "ignore_above": 512},
            "location": {
                "properties": {
                    "pais": {"type": "keyword"},
                    "distrito": {"type": "keyword"},
                    "concelho": {"type": "keyword"},
                    "freguesia": {"type": "keyword"},
                }
            },
            "search_text": {"type": "text", "analyzer": "world_folding"},
            # Blocos lidos apenas por id.
            "empresa": {"type": "object", "enabled": False},
            "score_detalhe": {"type": "object", "enabled": False},
            "pilares_detalhe": {"type": "object", "enabled": False},
            "componentes": {"type": "object", "enabled": False},
            "historico": {"type": "object", "enabled": False},
            "benchmark": {"type": "object", "enabled": False},
            "indicadores": {"type": "object", "enabled": False},
            "evidencias": {"type": "object", "enabled": False},
            "fornecedores": {"type": "object", "enabled": False},
            "taxonomia": {"type": "object", "enabled": False},
            "cartao_modelo": {"type": "object", "enabled": False},
        }
    }

    # ESG — indicadores declarados nos relatórios de sustentabilidade. O `nested`
    # permite filtrar por código/pilar e somar valores sem misturar indicadores
    # do mesmo documento.
    esg_indicadores_mappings = {
        "properties": {
            "nif": {"type": "keyword"},
            "pais": {"type": "keyword"},
            "empresa_nome": {
                "type": "text",
                "analyzer": "world_folding",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
            },
            "ano": {"type": "integer"},
            "fonte": {"type": "keyword"},
            "fonte_label": {"type": "keyword", "ignore_above": 256},
            "url": {"type": "keyword", "ignore_above": 1024, "index": False},
            "verificacao": {"type": "keyword"},
            "origem": {"type": "keyword"},
            "pilares": {"type": "keyword"},
            "codigos": {"type": "keyword"},
            "n_indicadores": {"type": "integer"},
            "atualizado_em": {"type": "date"},
            "indicadores": {
                "type": "nested",
                "properties": {
                    "codigo": {"type": "keyword"},
                    "label": {"type": "keyword", "ignore_above": 256},
                    "pilar": {"type": "keyword"},
                    "valor": {"type": "float"},
                    "unidade": {"type": "keyword", "ignore_above": 64},
                    "direcao": {"type": "keyword"},
                },
            },
        }
    }

    esg_recolhas_mappings = {
        "properties": {
            "run_id": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "estado": {"type": "keyword"},
            "pais": {"type": "keyword"},
            "iniciado_em": {"type": "date"},
            "concluido_em": {"type": "date"},
            "duracao_s": {"type": "float"},
            "total": {"type": "integer"},
            "processados": {"type": "integer"},
            "erros": {"type": "integer"},
            "mensagem": {"type": "text", "analyzer": "world_folding"},
            "user_id": {"type": "keyword", "ignore_above": 64},
            "user_email": {"type": "keyword", "ignore_above": 256},
            "parametros": {"type": "object", "enabled": False},
            "detalhes": {"type": "object", "enabled": False},
        }
    }

    # DORA: Register of Information, incidentes, riscos, workflows, relatórios,
    # conteúdo recolhido da EIOPA e registo das recolhas.
    dora_registo_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "nome": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "descricao": {"type": "text", "analyzer": "world_folding"},
            "entidade_id": {"type": "keyword"},
            "entidade_nome": {"type": "text", "analyzer": "world_folding"},
            "fornecedor_ids": {"type": "keyword"},
            "sistema_ids": {"type": "keyword"},
            "funcao_ids": {"type": "keyword"},
            "contrato_ids": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "dados": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_incidentes_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "titulo": {"type": "text", "analyzer": "world_folding"},
            "descricao": {"type": "text", "analyzer": "world_folding"},
            "referencia": {"type": "keyword"},
            "severidade": {"type": "keyword"},
            "estado": {"type": "keyword"},
            "entidade_id": {"type": "keyword"},
            "entidade_nome": {"type": "text", "analyzer": "world_folding"},
            "sistema": {"type": "keyword"},
            "data_inicio": {"type": "date"},
            "data_fim": {"type": "date"},
            "impacto_financeiro": {"type": "float"},
            "dados": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_riscos_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "nome": {"type": "text", "analyzer": "world_folding"},
            "descricao": {"type": "text", "analyzer": "world_folding"},
            "categoria": {"type": "keyword"},
            "impacto": {"type": "keyword"},
            "probabilidade": {"type": "keyword"},
            "ativo": {"type": "keyword"},
            "entidade_id": {"type": "keyword"},
            "entidade_nome": {"type": "text", "analyzer": "world_folding"},
            "mitigacao": {"type": "text", "analyzer": "world_folding"},
            "dados": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_workflows_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "nome": {"type": "text", "analyzer": "world_folding"},
            "descricao": {"type": "text", "analyzer": "world_folding"},
            "ativo": {"type": "boolean"},
            "trigger": {"type": "keyword"},
            "acao": {"type": "keyword"},
            "passos": {"type": "object", "enabled": False},
            "entidade_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_relatorios_mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "nome": {"type": "text", "analyzer": "world_folding"},
            "entidade_id": {"type": "keyword"},
            "resumo": {"type": "object", "enabled": False},
            "dados": {"type": "object", "enabled": False},
            "formato": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_conteudo_mappings = {
        "properties": {
            "fonte": {"type": "keyword"},
            "url": {"type": "keyword"},
            "data_extracao": {"type": "date"},
            "idioma": {"type": "keyword"},
            "tipo": {"type": "keyword"},
            "pilar_id": {"type": "keyword"},
            "nivel": {"type": "keyword"},
            "titulo": {"type": "text", "analyzer": "world_folding"},
            "texto": {"type": "text", "analyzer": "world_folding"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    dora_recolhas_mappings = {
        "properties": {
            "fonte": {"type": "keyword"},
            "url": {"type": "keyword"},
            "data": {"type": "date"},
            "total_docs": {"type": "integer"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    # SEC EDGAR: filings de empresas cotadas (metadados + texto), factos
    # extraídos e registo das recolhas.
    sec_filings_mappings = {
        "properties": {
            "cik": {"type": "keyword"},
            "ticker": {"type": "keyword"},
            "company_name": {"type": "text", "analyzer": "world_folding", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "accession_number": {"type": "keyword"},
            "form": {"type": "keyword"},
            "date": {"type": "date"},
            "description": {"type": "text", "analyzer": "world_folding"},
            "primary_document": {"type": "keyword"},
            "url": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "world_folding"},
            "facts_count": {"type": "integer"},
            "indexed_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    sec_facts_mappings = {
        "properties": {
            "cik": {"type": "keyword"},
            "ticker": {"type": "keyword"},
            "company_name": {"type": "text", "analyzer": "world_folding"},
            "accession_number": {"type": "keyword"},
            "form": {"type": "keyword"},
            "date": {"type": "date"},
            "filing_id": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "world_folding"},
            "category": {"type": "keyword"},
            # XBRL structured facts.
            "concept": {"type": "keyword"},
            "label": {"type": "text", "analyzer": "world_folding"},
            "description": {"type": "text", "analyzer": "world_folding"},
            "unit": {"type": "keyword"},
            "value": {"type": "double"},
            "end": {"type": "date"},
            "start": {"type": "date"},
            "fy": {"type": "integer"},
            "fp": {"type": "keyword"},
            "indexed_at": {"type": "date"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
        }
    }

    sec_recolhas_mappings = {
        "properties": {
            "fonte": {"type": "keyword"},
            "url": {"type": "keyword"},
            "data": {"type": "date"},
            "total_docs": {"type": "integer"},
            "autor_id": {"type": "keyword", "ignore_above": 64},
            "parametros": {"type": "object", "enabled": False},
            "detalhes": {"type": "object", "enabled": False},
        }
    }

    for name, mappings in [
        ("finance_prices", prices_mappings),
        ("finance_news", news_mappings),
        ("finance_sentiment_daily", sentiment_mappings),
        ("finance_macro", macro_mappings),
        ("finance_earnings", earnings_mappings),
        (GLEIF_LEI_INDEX, gleif_lei_mappings),
        (CONTRACTS_INDEX, contracts_mappings),
        (CONTRATOS_ES_INDEX, contratos_es_mappings),
        (CONTRATOS_FR_INDEX, contratos_fr_mappings),
        (TRADEMARKS_INDEX, trademarks_mappings),
        (FIRMAS_INDEX, firmas_mappings),
        (SOCIETARIO_INDEX, societario_mappings),
        (CIRE_INDEX, cire_mappings),
        (CITACOES_INDEX, citacoes_mappings),
        (MASSA_INSOLVENTE_INDEX, massa_insolvente_mappings),
        (VENDAS_PENHORADOS_INDEX, vendas_penhorados_mappings),
        (PEOPLE_INDEX, people_mappings),
        (CONTRIBUINTES_INDEX, contribuintes_mappings),
        (NODE_SUMMARIES_INDEX, node_summaries_mappings),
        (ENTITIES_INDEX, entities_mappings),
        (USER_STATE_INDEX, user_state_mappings),
        (AUTH_USERS_INDEX, auth_users_mappings),
        (AUTH_SESSIONS_INDEX, auth_sessions_mappings),
        (EVENTS_INDEX, events_mappings),
        (PROVIDER_KEYS_INDEX, provider_keys_mappings),
        (SETTINGS_INDEX, settings_mappings),
        (CRM_INDEX, crm_mappings),
        (CRM_RBAC_INDEX, crm_rbac_mappings),
        (SCRAPED_INDEX, scraped_mappings),
        (SOCIAL_INDEX, social_mappings),
        (RIGORBIZ_INDEX, rigorbiz_mappings),
        (AGENT_CONFIGS_INDEX, agent_configs_mappings),
        # World Model (estado, eventos, relações), rede neuronal dinâmica,
        # simulações de futuro e investigações.
        (WORLD_STATE_INDEX, world_state_mappings),
        (WORLD_EVENTS_INDEX, world_events_mappings),
        (WORLD_RELATIONS_INDEX, world_relations_mappings),
        (WORLD_HISTORY_INDEX, world_history_mappings),
        (NETWORK_STATE_INDEX, network_state_mappings),
        (SIMULATIONS_INDEX, simulations_mappings),
        (INVESTIGATIONS_INDEX, investigations_mappings),
        (LORENZ_RUNS_INDEX, lorenz_runs_mappings),
        (MERCADO_RUNS_INDEX, mercado_runs_mappings),
        (VORTAL_PECAS_INDEX, vortal_pecas_mappings),
        (ANALISES_EMPRESA_INDEX, analises_empresa_mappings),
        (GLOBAL_PADROES_INDEX, global_padroes_mappings),
        (DEVEDORES_INDEX, devedores_mappings),
        (DEVEDORES_RECOLHAS_INDEX, devedores_recolhas_mappings),
        (GRANDES_LITIGANTES_INDEX, grandes_litigantes_mappings),
        (GRANDES_LITIGANTES_RECOLHAS_INDEX, grandes_litigantes_recolhas_mappings),
        (SUBVENCOES_INDEX, subvencoes_mappings),
        (SUBVENCOES_LOTES_INDEX, subvencoes_lotes_mappings),
        # Financiamento partidário: documentos das contas por partido e ano, o
        # registo oficial da CNE e o histórico das recolhas.
        (PARTIDOS_INDEX, partidos_mappings),
        (PARTIDOS_REGISTO_INDEX, partidos_registo_mappings),
        (PARTIDOS_RECOLHAS_INDEX, partidos_recolhas_mappings),
        (VEREADORES_INDEX, vereadores_mappings),
        (MUNICIPIOS_DESPESAS_INDEX, municipios_despesas_mappings),
        (MUNICIPIO_PESSOAS_INDEX, municipio_pessoas_mappings),
        (MUNICIPIOS_CONTACTOS_INDEX, municipios_contactos_mappings),
        (FREGUESIAS_CONTACTOS_INDEX, freguesias_contactos_mappings),
        (EMPRESAS_LOCAIS_INDEX, empresas_locais_mappings),
        # Abonos dos eleitos locais: a tabela oficial e o mesmo direito aplicado
        # a cada concelho e freguesia (eleitores, escalão e polígono do mapa).
        (REMUNERACOES_INDEX, remuneracoes_mappings),
        (REMUNERACOES_TERRITORIOS_INDEX, remuneracoes_territorios_mappings),
        (REMUNERACOES_PESSOAS_INDEX, remuneracoes_pessoas_mappings),
        # Portal da Transparência da ERC: entidades proprietárias de OCS, pessoas
        # dos órgãos sociais, OCS detidos e o histórico das recolhas.
        (ERC_ENTIDADES_INDEX, erc_entidades_mappings),
        (ERC_PESSOAS_INDEX, erc_pessoas_mappings),
        (ERC_OCS_INDEX, erc_ocs_mappings),
        (ERC_RECOLHAS_INDEX, erc_recolhas_mappings),
        # Entidade para a Transparência: titulares, titularidades, declarações
        # únicas e o manifesto da recolha.
        (EPT_TITULARES_INDEX, ept_titulares_mappings),
        (EPT_TITULARIDADES_INDEX, ept_titularidades_mappings),
        (EPT_DECLARACOES_INDEX, ept_declaracoes_mappings),
        (EPT_RECOLHAS_INDEX, ept_recolhas_mappings),
        # Grafo da Transparência: nós (pessoas, cargos, entidades e empresas),
        # arestas entre eles e o manifesto da construção.
        (TRANSPARENCIA_GRAFO_NOS_INDEX, transparencia_grafo_nos_mappings),
        (TRANSPARENCIA_GRAFO_ARESTAS_INDEX, transparencia_grafo_arestas_mappings),
        (TRANSPARENCIA_GRAFO_RECOLHAS_INDEX, transparencia_grafo_recolhas_mappings),
        (OSINT_INDEX, osint_mappings),
        (TICKER_TRANSLATIONS_INDEX, ticker_translations_mappings),
        (ARQUIVO_PT_INDEX, arquivo_pt_mappings),
        # ESG: fotografia por empresa, indicadores dos relatórios e registo das
        # execuções de cálculo/ingestão.
        (ESG_EMPRESAS_INDEX, esg_empresas_mappings),
        (ESG_INDICADORES_INDEX, esg_indicadores_mappings),
        (ESG_RECOLHAS_INDEX, esg_recolhas_mappings),
        # DORA: Register of Information, incidentes, riscos, workflows,
        # relatórios ITS/RTS, conteúdo da EIOPA e recolhas.
        (DORA_REGISTO_INDEX, dora_registo_mappings),
        (DORA_INCIDENTES_INDEX, dora_incidentes_mappings),
        (DORA_RISCOS_INDEX, dora_riscos_mappings),
        (DORA_WORKFLOWS_INDEX, dora_workflows_mappings),
        (DORA_RELATORIOS_INDEX, dora_relatorios_mappings),
        (DORA_CONTEUDO_INDEX, dora_conteudo_mappings),
        (DORA_RECOLHAS_INDEX, dora_recolhas_mappings),
        # SEC EDGAR: filings, factos e recolhas.
        (SEC_FILINGS_INDEX, sec_filings_mappings),
        (SEC_FACTS_INDEX, sec_facts_mappings),
        (SEC_RECOLHAS_INDEX, sec_recolhas_mappings),
        (EU_TAXONOMY_INDEX, eu_taxonomy_mappings),
    ]:
        if not client.indices.exists(index=name):
            settings: Dict[str, Any] = {"number_of_shards": 1, "number_of_replicas": 0}
            settings.update(INDEX_SETTINGS.get(name, {}))
            try:
                client.indices.create(index=name, body={"mappings": mappings, "settings": settings})
            except Exception as exc:
                # Um índice com uma definição em falta (ex.: analisador por
                # configurar) não pode impedir a verificação dos restantes.
                logger.warning("Não foi possível criar o índice %s: %s", name, exc)
        else:
            # Elasticsearch permite acrescentar campos novos a um índice existente
            # (não permite alterar/remover os já definidos). Enviamos apenas os campos
            # em falta, para manter índices antigos compatíveis com o código atual.
            try:
                existing = client.indices.get_mapping(index=name)[name]["mappings"].get("properties", {})
                missing = _missing_mapping_fields(existing, mappings.get("properties") or {})
                if missing:
                    try:
                        client.indices.put_mapping(index=name, body={"properties": missing})
                    except Exception as exc:
                        # Um campo em conflito (tipo diferente do já indexado, ex.: criado
                        # por mapeamento dinâmico) não deve impedir a criação dos restantes.
                        accepted = 0
                        for field, spec in missing.items():
                            try:
                                client.indices.put_mapping(index=name, body={"properties": {field: spec}})
                                accepted += 1
                            except Exception as inner:
                                logger.debug("put_mapping de %s.%s ignorado: %s", name, field, inner)
                        logger.debug(
                            "put_mapping parcial em %s (%d/%d campos): %s",
                            name,
                            accepted,
                            len(missing),
                            exc,
                        )
            except Exception as exc:
                logger.debug("put_mapping ignorado para %s: %s", name, exc)
    return True




def _missing_mapping_fields(
    existing: Dict[str, Any],
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """Campos de `spec` que ainda não existem em `existing`.

    Desce dentro de `properties` (objectos e `nested`), para que campos novos em
    estruturas já mapeadas — como `roles.tribunal` — também sejam acrescentados a
    índices que já existiam. Ao descer preserva `type` (o Elasticsearch recusa
    juntar um mapeamento `nested` sem o respetivo `type`) e `dynamic`.
    """
    missing: Dict[str, Any] = {}
    for field, definition in (spec or {}).items():
        if not isinstance(definition, dict):
            continue
        current = (existing or {}).get(field)
        if current is None:
            missing[field] = definition
            continue
        children = definition.get("properties")
        if isinstance(children, dict):
            child_missing = _missing_mapping_fields((current or {}).get("properties") or {}, children)
            if child_missing:
                nested_spec: Dict[str, Any] = {}
                for key in ("type", "dynamic"):
                    if key in definition:
                        nested_spec[key] = definition[key]
                nested_spec["properties"] = child_missing
                missing[field] = nested_spec
    return missing
