"""Cliente Elasticsearch para ingestão e pesquisa de dados financeiros.

Índices utilizados:
- finance_prices: histórico de preços de ações (OHLCV) por ticker.
- finance_news: notícias/sociais de ações por ticker.

Ambos suportam pesquisa por ticker, data e texto.
"""
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

# Índice único para contratos públicos normalizados
CONTRACTS_INDEX = "contratos"

# Contratos públicos de Espanha (PLACSP). Índice próprio (`contratos_es`) para não
# se misturar com os contratos portugueses: os identificadores e o vocabulário
# (expediente, CODICE/UBL) são diferentes, mas os dois partilham o mesmo tipo de
# pesquisa por facetas. Alimentado por `collectors/contratos_es.py`.
CONTRATOS_ES_INDEX = "contratos_es"

# Fontes do PLACSP indexadas na plataforma.
CONTRATOS_ES_FONTES = ("licitaciones", "menores")

# Grupo usado para contratos sem valor no campo (ex.: sem NUTs): mantém estes
# contratos visíveis nos grafos em vez de os descartar silenciosamente.
UNSPECIFIED_LABEL = "Não especificado"
_UNSPECIFIED_KEYS = {"nao especificado", "não especificado", "unspecified", "n/a", "na"}


def is_unspecified(value: Optional[str]) -> bool:
    """Indica se um valor representa o grupo "sem informação" (aceita acentos/maiúsculas)."""
    if not value:
        return False
    normalized = value.strip().lower()
    normalized = normalized.replace("ã", "a").replace("á", "a")
    return normalized in _UNSPECIFIED_KEYS

# Índice para marcas do INPI indexadas por entidade
TRADEMARKS_INDEX = "finance_trademarks"

# Índice para firmas/nomes comerciais do RNPC (Pesquisa de Nomes Existentes)
FIRMAS_INDEX = "finance_firmas"

# Índice para o cadastro de entidades do portal base (data/entidades-gov-portal-base/entidades.json)
ENTITIES_INDEX = "finance_entities"

# Índice para preferências do utilizador (favoritos, pastas do dossier e histórico do EmpresasIQ).
# Evita depender do localStorage do browser, que se perde ao mudar de origem/porta ou ao limpar dados.
USER_STATE_INDEX = "finance_user_state"

# Índice de contas de utilizador (autenticação). O `_id` do documento é o email
# normalizado, o que garante unicidade sem necessitar de transações.
AUTH_USERS_INDEX = "finance_users"

# Índice de sessões (uma por início de sessão). Guarda a validade e a revogação,
# para que o "terminar sessão" seja imediato e auditável.
AUTH_SESSIONS_INDEX = "finance_sessions"

# Registo de eventos do sistema (autenticação, pedidos à API, tarefas, erros) —
# alimenta o visualizador de eventos da área de administração.
EVENTS_INDEX = "finance_events"

# Chaves de API dos fornecedores de IA (uma linha por utilizador; `_id` = user id).
PROVIDER_KEYS_INDEX = "finance_provider_keys"

# Definições da plataforma geridas pela administração (documento único com
# `kind` próprio): por agora, o acesso aos módulos da barra lateral por perfil.
SETTINGS_INDEX = "finance_settings"

# Módulo de CRM: contas, contactos, oportunidades e atividades num único índice.
# O campo `kind` distingue o tipo de registo e `owner_id` o utilizador dono
# (os administradores veem todos os registos).
CRM_INDEX = "finance_crm"

# Arquitetura de CRM: índice próprio para os utilizadores do CRM (atribuições de
# perfil/área/departamento/equipa), equipas, perfis personalizados e o registo de
# auditoria imutável. Fica separado de `finance_crm` para que os registos de
# negócio nunca sejam contaminados por metadados de administração.
CRM_RBAC_INDEX = "finance_crm_rbac"

# Módulo de recolha (scraping): itens extraídos de sites pelas "fontes"
# (definições) do `scraper_service`. Os campos de cada fonte variam, por isso o
# conteúdo extraído vive em `data` (tipo `flattened`), pesquisável e agregável
# sem precisar de um mapping diferente por site.
SCRAPED_INDEX = "finance_scraped"

# Módulo de pesquisa social: publicações recolhidas de redes sociais (LinkedIn,
# TikTok, Reddit e Facebook) pelos "canais" (definições) do `social_service`.
# Cada documento é uma publicação normalizada, com as métricas de interação em
# campos próprios (pesquisáveis e agregáveis) e o resto em `data` (`flattened`).
SOCIAL_INDEX = "finance_social"

# Configurações de agentes dinâmicos do IQ OS (LangGraph + ferramentas).
# Guarda grafos de agentes, nós, ferramentas, prompts e chaves por utilizador.
AGENT_CONFIGS_INDEX = "iq_os_agent_configs"

# Publicações de atos societários do Ministério da Justiça (publicacoes.mj.pt).
# A pesquisa do portal exige reCAPTCHA (ver `collectors/publicacoes_mj.py`), pelo que
# a recolha é assistida e o resultado fica guardado aqui para consulta e pesquisa.
SOCIETARIO_INDEX = "finance_publicacoes_mj"

# Publicações do CIRE (CITIUS / Ministério da Justiça): publicidade do PER, do
# PEAP, do PEVE e dos processos de insolvência — tribunal, processo, espécie,
# datas e intervenientes (com NIF/NIPC). Recolhido de `consultascire.aspx`.
CIRE_INDEX = "finance_cire"

# Citações e notificações editais (CITIUS / Ministério da Justiça): os éditos
# publicados quando o citando/notificado não é encontrado — tribunal, ato,
# processo, espécie, data e intervenientes (exequente, executado, réu, …).
# Recolhido de `consultascitedital.aspx`.
CITACOES_INDEX = "finance_citacoes_edital"

# Pessoas e cargos extraídos das publicações societárias (MJ). Um documento por
# NIF de pessoa (individual ou coletiva), com roles aninhados por empresa/acto.
PEOPLE_INDEX = "finance_people"

# Contribuintes: um documento por **NIF/NIPC**, agregando todas as entidades e
# pessoas que aparecem nos restantes índices da plataforma (contratos PT/ES,
# cadastro de entidades, publicações societárias, CIRE, PessoasIQ, firmas,
# marcas e CRM). É um índice **derivado**: `api/contribuintes_service.py`
# reconstrói-o periodicamente (cron) a partir das fontes, para haver um ponto
# único de pesquisa de contribuintes em todo o sistema.
CONTRIBUINTES_INDEX = "finance_contribuintes"

# Resumos de nós dos grafos (pessoas, empresas, sites): texto redigido por IA a
# partir dos factos do IQ OS e de pesquisa na web, guardado para consulta
# posterior (um documento por nó, substituído a cada novo resumo).
NODE_SUMMARIES_INDEX = "finance_node_summaries"

# GLEIF — «Golden Copy» dos registos LEI (Legal Entity Identifier). Um documento
# por LEI, com o nível 1 (quem é quem: nome legal, endereço, jurisdição, forma
# jurídica, estado, datas) e os identificadores associados (BIC, MIC, OCID, QCC,
# S&P Global). O índice é alimentado por `collectors/gleif.py` — quer a partir da
# API oficial do GLEIF, quer a partir do ficheiro *Golden Copy* (LEI-CDF) — e é
# pesquisável no módulo «GLEIF / LEI» (`/gleif/*`).
GLEIF_LEI_INDEX = "finance_gleif_lei"

# ---------------------------------------------------------------------------
# «World Model» — o estado do mundo da contratação pública, materializado.
#
# A camada de *public data* (contratos PT/ES, cadastro de entidades, CIRE,
# pessoas, contribuintes) é lida por `api/world_sources.py`; `api/world_model.py`
# transforma-a em **estado** (entidades e contratos), **eventos** (registo
# temporal) e **relações** (grafo), gravando em três índices próprios. É este
# estado — e não os dados em bruto — que alimenta a rede neuronal dinâmica
# (`api/world_neural.py`), o motor de grafo/tempo (`api/world_graph.py`), o
# simulador de futuro (`api/world_simulator.py`) e o agente de investigação
# (`api/world_investigation.py`).
# ---------------------------------------------------------------------------

# Estado materializado: um documento por entidade (empresa, entidade pública,
# pessoa) ou por contrato-agregado. `_id` = `<entity_ref>`.
WORLD_STATE_INDEX = "finance_world_state"

# Registo de eventos (append-only, um documento por acontecimento): adjudicações,
# alterações de valor, cessação, insolvências, criação/desaparecimento de
# relações. Alimenta a linha temporal e a causalidade.
WORLD_EVENTS_INDEX = "finance_world_events"

# Relações do grafo (uma aresta por par entidade↔entidade e tipo).
WORLD_RELATIONS_INDEX = "finance_world_relations"

# **Estado temporal** do mundo: um documento por entidade **e por período**
# (mês/trimestre/ano), com os contadores acumulados e os do período, o risco
# recalculado no fim do período e o número de contrapartes/administradores.
# É esta série que alimenta o modelo de transição latente e a deteção de
# anomalias (a rede neuronal vê a evolução, não só o retrato atual).
WORLD_HISTORY_INDEX = "finance_world_history"

# Estado da rede neuronal dinâmica (uma versão por treino/growth): nós, arestas,
# memória, métricas e previsões. `_id` = `version:<n>`.
NETWORK_STATE_INDEX = "finance_network_state"

# Execuções do simulador de futuro (t0→t1→t2→t3) com os cenários e as
# distribuições produzidas.
SIMULATIONS_INDEX = "finance_world_simulations"

# Execuções do agente de investigação (Observe→Hypothesize→Search→Validate→
# Simulate→Evidence Report), com a auditoria completa e o relatório.
INVESTIGATIONS_INDEX = "finance_world_investigations"

# Definições (settings) específicas de determinados índices — nomeadamente
# analisadores usados em subcampos de pesquisa por prefixo.
INDEX_SETTINGS: Dict[str, Dict[str, Any]] = {
    AGENT_CONFIGS_INDEX: {
        "analysis": {
            "analyzer": {
                "agent_name_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    CONTRATOS_ES_INDEX: {
        # Os textos de origem vêm em espanhol (acentos e «ñ»). `asciifolding` deixa
        # que uma pesquisa sem acentos («adjudicacion») encontre «adjudicación».
        "analysis": {
            "analyzer": {
                "es_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    ENTITIES_INDEX: {
        "analysis": {
            "tokenizer": {
                # Permite pesquisa incremental: "SONAE" encontra "SONAECOM".
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    PEOPLE_INDEX: {
        "analysis": {
            "tokenizer": {
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    GLEIF_LEI_INDEX: {
        "analysis": {
            "tokenizer": {
                # Pesquisa incremental no nome da entidade («SIE» → «SIEMENS»).
                "gleif_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 18,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "gleif_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "gleif_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "gleif_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                # Os textos vêm em várias línguas; `asciifolding` deixa que uma
                # pesquisa sem acentos encontre «Câmara»/«Gesellschaft für …».
                "gleif_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    CONTRIBUINTES_INDEX: {
        "analysis": {
            "tokenizer": {
                "entity_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "entity_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "entity_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "entity_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                "contribuinte_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    WORLD_STATE_INDEX: {
        "analysis": {
            "tokenizer": {
                # Pesquisa incremental na designação da entidade («SON» → «SONAE»).
                "world_edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"],
                }
            },
            "analyzer": {
                "world_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "world_edge_ngram",
                    "filter": ["lowercase", "asciifolding"],
                },
                "world_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                # Os nomes vêm em português e espanhol; sem acentos encontram-se
                # «Camara»/«Adjudicacion».
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        }
    },
    WORLD_HISTORY_INDEX: {
        "analysis": {
            "analyzer": {
                # Igual aos outros índices do mundo: sem acentos encontra «Camara».
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    WORLD_EVENTS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    WORLD_RELATIONS_INDEX: {
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
    INVESTIGATIONS_INDEX: {
        # O relatório e a pergunta são indexados com `world_folding` (sem esta
        # definição, a criação do índice falha com «analyzer has not been configured»).
        "analysis": {
            "analyzer": {
                "world_folding": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        }
    },
}


def _get_es_url() -> str:
    return os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")


def get_es_client(request_timeout: int = 30) -> Optional[Elasticsearch]:
    """Devolve cliente Elasticsearch ou None se não estiver disponível."""
    try:
        es = Elasticsearch([_get_es_url()], request_timeout=request_timeout)
        if not es.ping():
            return None
        return es
    except Exception:
        return None


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
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "sublabel": {"type": "keyword"},
            "value": {"type": "float"},
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

    for name, mappings in [
        ("finance_prices", prices_mappings),
        ("finance_news", news_mappings),
        ("finance_sentiment_daily", sentiment_mappings),
        ("finance_macro", macro_mappings),
        ("finance_earnings", earnings_mappings),
        (GLEIF_LEI_INDEX, gleif_lei_mappings),
        (CONTRACTS_INDEX, contracts_mappings),
        (CONTRATOS_ES_INDEX, contratos_es_mappings),
        (TRADEMARKS_INDEX, trademarks_mappings),
        (FIRMAS_INDEX, firmas_mappings),
        (SOCIETARIO_INDEX, societario_mappings),
        (CIRE_INDEX, cire_mappings),
        (CITACOES_INDEX, citacoes_mappings),
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


def _today() -> str:
    return datetime.utcnow().isoformat()


def index_price_points(ticker: str, points: List[Dict[str, Any]], period: str = "1y", es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa pontos de preço no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        points: lista de dicts com date, open, high, low, close, volume.
        period: período de onde os dados vieram.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_points.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for p in points:
        doc = {
            "_op_type": "index",
            "_index": "finance_prices",
            "_id": f"{ticker}-{p.get('date')}",
            "ticker": ticker,
            "date": p.get("date"),
            "open": _as_float(p.get("open")),
            "high": _as_float(p.get("high")),
            "low": _as_float(p.get("low")),
            "close": _as_float(p.get("close")),
            "volume": _as_int(p.get("volume")),
            "period": period,
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_points": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_points": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_points": len(actions)}


def index_news_items(ticker: str, items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa notícias no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        items: lista de notícias com title, summary, publisher, published, url.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_items.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for i, item in enumerate(items):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def _news_id(item: Dict[str, Any], index: int) -> str:
    """Gera ID estável para uma notícia baseada no URL ou no conteúdo."""
    import hashlib
    url = item.get("url") or item.get("link") or ""
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:20]
    content = (item.get("title") or "") + (item.get("summary") or "") + str(index)
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:20]


def search_prices(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 1000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa preços de um ticker por intervalo de datas."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "points": []}

    query: Dict[str, Any] = {"bool": {"must": [{"term": {"ticker": ticker.upper()}}]}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"date": range_filter}}]

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "query": query,
                "sort": [{"date": {"order": "asc"}}],
                "size": size,
            },
        )
        points = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "points": points,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "points": []}


def search_news(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias por ticker e texto opcional."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "items": []}

    must: List[Dict[str, Any]] = [{"term": {"ticker": ticker.upper()}}]
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["title^2", "summary", "publisher"],
                "type": "best_fields",
            }
        })

    query: Dict[str, Any] = {"bool": {"must": must}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"published": range_filter}}]

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "size": size,
            },
        )
        items = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "items": items,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "items": []}


def index_analyzed_news_items(
    ticker: str,
    items: List[Dict[str, Any]],
    analyses: List[Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa notícias enriquecidas com análise NLP no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    now = _today()
    for i, (item, analysis) in enumerate(zip(items, analyses)):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": now,
            "analyzed_at": now,
            "sentiment": analysis.sentiment,
            "language": analysis.language,
            "translated_title": analysis.translated_title,
            "translated_summary": analysis.translated_summary,
            "summary_pt": analysis.summary_pt,
            "topics": analysis.topics,
            "entities": analysis.entities,
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def fetch_news_for_analysis(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 100,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Recupera notícias indexadas para serem (re)analisadas."""
    result = search_news(ticker, q, start_date, end_date, size, es)
    return result.get("items", [])


def save_news_graph(
    ticker: str,
    graph: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Persiste grafo de notícias/entidades num índice dedicado."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    graph_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "graph_type": {"type": "keyword"},
            "nodes": {"type": "object"},
            "edges": {"type": "object"},
            "created_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_graphs"):
        client.indices.create(
            index="finance_graphs",
            body={"mappings": graph_mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )

    try:
        client.index(
            index="finance_graphs",
            id=f"{ticker.upper()}-news",
            body={
                "ticker": ticker.upper(),
                "graph_type": "news_entities",
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
                "created_at": _today(),
            },
        )
        return {"ticker": ticker.upper(), "saved": True, "node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", []))}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def load_news_graph(ticker: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Carrega grafo de notícias/entidades persistido."""
    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.get(index="finance_graphs", id=f"{ticker.upper()}-news")
        return resp.get("_source")
    except Exception:
        return None


def search_all_tickers(
    q: str,
    from_: int = 0,
    size: int = 50,
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
    topic: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias de todos os tickers por texto, com filtros e paginação."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    must = {
        "multi_match": {
            "query": q,
            "fields": ["ticker^3", "title^2", "summary", "publisher"],
            "type": "best_fields",
        }
    }
    filters = []
    if source:
        filters.append({"wildcard": {"publisher": f"*{source.lower()}*"}})
    if sentiment:
        filters.append({"term": {"sentiment": sentiment.lower()}})
    if topic:
        filters.append({"wildcard": {"topics": f"*{topic.lower()}*"}})

    query: Dict[str, Any] = {"bool": {"must": [must], "filter": filters}}

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            items.append(source)
        return {"total": resp["hits"]["total"]["value"], "items": items}
    except Exception as e:
        return {"error": str(e), "items": []}


def autocomplete_suggestions(q: str, size: int = 12, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Gera sugestões de autocomplete a partir de tickers, títulos, publishers e tópicos indexados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()
    upper_q = q.upper()

    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"wildcard": {"ticker": f"{upper_q}*"}},
                            {"match_phrase_prefix": {"title": q}},
                            {"wildcard": {"publisher": f"*{lower_q}*"}},
                            {"wildcard": {"topics": f"*{lower_q}*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "tickers": {
                        "terms": {
                            "field": "ticker",
                            "size": 5,
                            "include": f"{upper_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "publishers": {
                        "terms": {
                            "field": "publisher",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "topics": {
                        "terms": {
                            "field": "topics",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "title_hits": {
                        "terms": {
                            "field": "title.keyword",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()

        for bucket in resp["aggregations"]["tickers"]["buckets"]:
            text = bucket["key"]
            if text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "ticker", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["publishers"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "publisher", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["topics"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "topic", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["title_hits"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "title", "count": bucket["doc_count"]})

        suggestions = suggestions[:size]
        return {"suggestions": suggestions}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def delete_ticker_data(ticker: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Apaga todos os dados de preços e notícias de um ticker."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    ticker = ticker.upper()
    try:
        prices_resp = client.delete_by_query(
            index="finance_prices",
            body={"query": {"term": {"ticker": ticker}}},
        )
        news_resp = client.delete_by_query(
            index="finance_news",
            body={"query": {"term": {"ticker": ticker}}},
        )
        return {
            "ticker": ticker,
            "prices_deleted": prices_resp.get("deleted", 0),
            "news_deleted": news_resp.get("deleted", 0),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def list_indexed_tickers(es: Optional[Elasticsearch] = None) -> List[str]:
    """Devolve a lista de tickers que já têm dados indexados."""
    client = es or get_es_client()
    if not client:
        return []

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "size": 0,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 1000}}},
            },
        )
        return [bucket["key"] for bucket in resp["aggregations"]["tickers"]["buckets"]]
    except Exception:
        return []


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def list_elastic_indices(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Lista todos os índices da plataforma com contagem de documentos e estado.

    Filtra apenas índices internos (prefixo finance_* e os índices de contratos).
    """
    client = es or get_es_client()
    if not client:
        return []

    try:
        indices = client.cat.indices(format="json", bytes="b")
    except Exception:
        return []

    def is_platform_index(name: str) -> bool:
        if name.startswith("finance_"):
            return True
        if name.startswith("."):
            return False
        return name in {"contratos", "contratos_es"}

    result: List[Dict[str, Any]] = []
    for idx in indices:
        name = idx.get("index", "")
        if not is_platform_index(name):
            continue
        result.append({
            "index": name,
            "label": name,
            "docs": _as_int(idx.get("docs.count")),
            "size": idx.get("store.size"),
            "health": idx.get("health"),
            "status": idx.get("status"),
        })
    return sorted(result, key=lambda x: x["index"])


# --- Contratos públicos ---

def index_contracts(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos no índice finance_contracts."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("idcontrato") or doc.get("idprocedimento"))
        actions.append({
            "_op_type": "index",
            "_index": CONTRACTS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"error": str(e), "indexed_count": 0, "total": len(actions)}


def bulk_index_contracts_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 1000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um ficheiro JSONL de contratos em chunks."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = 0
    success_total = 0
    error_total = 0
    chunk: List[Dict[str, Any]] = []

    try:
        resolved_path = Path(jsonl_path) if not isinstance(jsonl_path, Path) else jsonl_path
        print(f"[bulk_index_contracts] path={resolved_path} exists={resolved_path.exists()} chunk_size={chunk_size} max_records={max_records}")
        with open(resolved_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    print(f"[bulk_index_contracts] max_records reached {total}")
                    break
                try:
                    doc = json.loads(line)
                except Exception:
                    continue
                chunk.append(doc)
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contracts(chunk, client)
                    print(f"[bulk_index_contracts] chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
                    chunk = []
        if chunk:
            res = index_contracts(chunk, client)
            print(f"[bulk_index_contracts] final chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
        print(f"[bulk_index_contracts] done total={total} success={success_total} errors={error_total}")
        return {"indexed_count": success_total, "total": total, "errors": error_total}
    except Exception as e:
        print(f"[bulk_index_contracts] exception {e}")
        return {"error": str(e), "indexed_count": success_total, "total": total}


def find_contract_ids_by_idcontrato(
    idcontratos: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> List[str]:
    """Devolve os _id de documentos existentes no índice finance_contracts cujo idcontrato corresponde aos valores fornecidos."""
    client = es or get_es_client()
    if not client or not idcontratos:
        return []

    ids = [str(v).strip() for v in idcontratos if v is not None and str(v).strip()]
    if not ids:
        return []

    existing: set = set()
    batch_size = 1000
    try:
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            resp = client.search(
                index=CONTRACTS_INDEX,
                body={
                    "query": {"terms": {"idcontrato": batch}},
                    "_source": False,
                    "size": len(batch),
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                existing.add(hit.get("_id"))
    except Exception as e:
        print(f"[find_contract_ids_by_idcontrato] error: {e}")
        return []
    return sorted(existing)


def delete_contracts_by_ids(
    doc_ids: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Apaga documentos do índice finance_contracts pelos respetivos _id."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "deleted_count": 0}

    ids = [str(v).strip() for v in doc_ids if v is not None and str(v).strip()]
    if not ids:
        return {"deleted_count": 0, "total": 0}

    try:
        resp = client.delete_by_query(
            index=CONTRACTS_INDEX,
            body={"query": {"terms": {"_id": ids}}},
            refresh=True,
        )
        return {"deleted_count": resp.get("deleted", 0), "total": len(ids)}
    except Exception as e:
        return {"error": str(e), "deleted_count": 0, "total": len(ids)}


def _contract_to_flat_dict(source: Dict[str, Any]) -> Dict[str, Any]:
    """Converte documento de contrato num dicionário plano para exportação."""
    def party_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        names = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                names.extend([x.get("nome", "") for x in parsed if x.get("nome")])
            raw = p.get("raw") if isinstance(p, dict) else None
            if isinstance(raw, list):
                names.extend([str(r) for r in raw])
            elif isinstance(raw, str):
                names.append(raw)
        return "; ".join(names)

    def nif_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        nifs = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                nifs.extend([x.get("nif", "") for x in parsed if x.get("nif")])
        return "; ".join(nifs)

    def cpv_str(cpv: Any) -> str:
        if not cpv:
            return ""
        if isinstance(cpv, dict):
            cpv = [cpv]
        return "; ".join([f"{x.get('code','')} {x.get('description','')}".strip() for x in cpv])

    return {
        "idcontrato": source.get("idcontrato"),
        "nAnuncio": source.get("nAnuncio"),
        "tipoContrato": source.get("tipoContrato"),
        "tipoprocedimento": source.get("tipoprocedimento"),
        "objectoContrato": source.get("objectoContrato"),
        "descContrato": source.get("descContrato"),
        "adjudicante": party_str(source.get("adjudicantes")),
        "nif_adjudicante": nif_str(source.get("adjudicantes")),
        "adjudicatario": party_str(source.get("adjudicatarios")),
        "nif_adjudicatario": nif_str(source.get("adjudicatarios")),
        "dataPublicacao": source.get("dataPublicacao"),
        "dataCelebracaoContrato": source.get("dataCelebracaoContrato"),
        "precoContratual": source.get("precoContratual"),
        "PrecoTotalEfetivo": source.get("PrecoTotalEfetivo"),
        "precoBaseProcedimento": source.get("precoBaseProcedimento"),
        "cpv": cpv_str(source.get("cpv")),
        "localExecucao": source.get("localExecucao"),
        "Ano": source.get("Ano"),
        "NUTs": source.get("NUTs"),
        "regime": source.get("regime"),
    }


def export_contracts_to_excel(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 10000,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para Excel (bytes)."""
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise RuntimeError("openpyxl não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    # Argumentos por nome: a ordem de `_build_contract_query` inclui `counterparty_nif`
    # e `region` antes do CPV, e a chamada posicional antiga deslocava os filtros
    # (o CPV era aplicado como região, o preço mínimo como CPV…).
    query = _build_contract_query(
        q=q,
        year=year,
        entity=entity,
        nif=nif,
        cpv_code=cpv_code,
        min_price=min_price,
        max_price=max_price,
        start_date=start_date,
        end_date=end_date,
    )
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 10000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contratos"
    headers = list(rows[0].keys()) if rows else [
        "idcontrato", "nAnuncio", "tipoContrato", "tipoprocedimento", "objectoContrato",
        "descContrato", "adjudicante", "nif_adjudicante", "adjudicatario", "nif_adjudicatario",
        "dataPublicacao", "dataCelebracaoContrato", "precoContratual", "PrecoTotalEfetivo",
        "precoBaseProcedimento", "cpv", "localExecucao", "Ano", "NUTs", "regime",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    def value_to_excel(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return v

    for row in rows:
        ws.append([value_to_excel(row.get(h)) for h in headers])
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                val_len = len(str(cell.value))
                if val_len > max_length:
                    max_length = val_length
            except Exception:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 60)

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def export_contracts_to_pdf(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 500,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para PDF (bytes)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError as e:
        raise RuntimeError("reportlab não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    # Argumentos por nome: ver a nota em `export_contracts_to_excel` (a chamada
    # posicional antiga deslocava CPV/valores/datas para os filtros errados).
    query = _build_contract_query(
        q=q,
        year=year,
        entity=entity,
        nif=nif,
        cpv_code=cpv_code,
        min_price=min_price,
        max_price=max_price,
        start_date=start_date,
        end_date=end_date,
    )
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 1000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    headers = ["ID", "Ano", "Tipo", "Objecto", "Adjudicante", "Adjudicatário", "Valor", "Publicação"]
    data = [headers]
    for r in rows:
        data.append([
            str(r.get("idcontrato") or ""),
            str(r.get("Ano") or ""),
            str(r.get("tipoContrato") or ""),
            str(r.get("objectoContrato") or "")[:80],
            str(r.get("adjudicante") or "")[:50],
            str(r.get("adjudicatario") or "")[:50],
            f"{r.get('precoContratual') or 0:.2f} €",
            str(r.get("dataPublicacao") or ""),
        ])

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Relatório de Contratos Públicos", styles["Title"]))
    elements.append(Paragraph(f"Total exportado: {len(rows)} contratos", styles["Normal"]))
    elements.append(Spacer(1, 12))
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10a37f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("WORDWRAP", (0, 0), (-1, -1), True),
    ]))
    elements.append(table)
    doc.build(elements)
    buf.seek(0)
    return buf.read()


def search_contracts(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos por texto, entidades, datas e valores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contract_query(q, year, entity, nif, counterparty_nif, region, cpv_code, min_price, max_price, start_date, end_date)
    sort = _build_contract_sort(sort_by, sort_order)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "query": query,
                "sort": sort,
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "items": []}


def _build_contract_sort(
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    field = sort_by or "dataPublicacao"
    if field == "relevance":
        return ["_score"]
    if field == "adjudicantes":
        return [{"adjudicantes.parsed.nome.keyword": {"order": order, "nested": {"path": "adjudicantes.parsed"}}}, "_score"]
    if field == "adjudicatarios":
        return [{"adjudicatarios.parsed.nome.keyword": {"order": order, "nested": {"path": "adjudicatarios.parsed"}}}, "_score"]
    if field == "tipoContrato":
        return [{"tipoContrato.keyword": {"order": order}}, "_score"]
    if field == "objectoContrato":
        return [{"objectoContrato.keyword": {"order": order}}, "_score"]
    if field in ("dataPublicacao", "dataCelebracaoContrato"):
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if field == "precoContratual":
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    return [{"dataPublicacao": {"order": "desc"}}, "_score"]


def contracts_autocomplete(
    q: str,
    size: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de autocomplete para entidades e CPV."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"objectoContrato": q}},
                            {"match_phrase_prefix": {"descContrato": q}},
                            {
                                "bool": {
                                    "should": [
                                        {
                                            "nested": {
                                                "path": "adjudicantes.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicantes.parsed.nome": q}},
                                            }
                                        },
                                        {
                                            "nested": {
                                                "path": "adjudicatarios.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicatarios.parsed.nome": q}},
                                            }
                                        },
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": 5,
                                    "include": f"{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()
        for agg_key in ("adjudicantes", "adjudicatarios"):
            for bucket in resp["aggregations"][agg_key]["names"]["buckets"]:
                text = bucket["key"]
                if text and text not in seen:
                    seen.add(text)
                    suggestions.append({"text": text, "type": "entity", "count": bucket["doc_count"]})
        for bucket in resp["aggregations"]["cpv_codes"]["codes"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "cpv", "count": bucket["doc_count"]})

        return {"suggestions": suggestions[:size]}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def contracts_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve contagem total de contratos indexados e anos conhecidos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": []}

    ensure_indices(client)
    try:
        total = client.count(index=CONTRACTS_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {"years": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}}},
            },
        )
        years = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        return {"total": total, "years": years}
    except Exception as e:
        return {"error": str(e), "total": 0, "years": []}


def contract_years_available() -> List[int]:
    """Anos de contratos com JSONL normalizado disponível."""
    years = []
    if not (ROOT / "data" / "processed" / "contratos").exists():
        return years
    for path in sorted((ROOT / "data" / "processed" / "contratos").glob("contratos_*.jsonl")):
        m = re.search(r"(\d{4})", path.stem)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _build_contract_query(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "objectoContrato^3",
                    "descContrato^2",
                    "search_text",
                    "adjudicantes.parsed.nome",
                    "adjudicatarios.parsed.nome",
                    "cpv.description",
                    "localExecucao",
                ],
                "type": "best_fields",
            }
        })

    if year:
        filters.append({"term": {"Ano": year}})
    if entity:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"match": {"adjudicantes.parsed.nome": entity}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"match": {"adjudicatarios.parsed.nome": entity}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    if nif and not counterparty_nif:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    elif nif and counterparty_nif:
        filters.append({
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        })
    if region:
        filters.append(_region_filter(region))
    if cpv_code:
        filters.append({
            "nested": {
                "path": "cpv",
                "query": {"wildcard": {"cpv.code": f"{cpv_code}*"}},
            }
        })

    price_range = {}
    if min_price is not None:
        price_range["gte"] = min_price
    if max_price is not None:
        price_range["lte"] = max_price
    if price_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"precoContratual": price_range}},
                    {"range": {"PrecoTotalEfetivo": price_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    date_range = {}
    if start_date:
        date_range["gte"] = start_date
    if end_date:
        date_range["lte"] = end_date
    if date_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"dataPublicacao": date_range}},
                    {"range": {"dataCelebracaoContrato": date_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    if not must and not filters:
        return {"match_all": {}}

    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    return query


_AGG_FIELD_CACHE: Dict[str, Dict[str, Any]] = {}


def _resolve_agg_target(client: Elasticsearch, field: str) -> Dict[str, Any]:
    """Descobre como agregar um campo textual: campo direto, subcampo `.keyword` ou campo de execução.

    O mapeamento real do índice manda: alguns campos declarados como `text` acabam
    indexados como `keyword` (e vice-versa), pelo que agregar `campo.keyword` às cegas
    produzia agregações vazias ("N/A" em todos os contratos).
    """
    cached = _AGG_FIELD_CACHE.get(field)
    if cached:
        return cached

    spec: Dict[str, Any] = {}
    try:
        mapping = client.indices.get_mapping(index=CONTRACTS_INDEX)
        props = list(mapping.values())[0].get("mappings", {}).get("properties", {})
        spec = props.get(field) or {}
    except Exception:
        spec = {}

    if spec.get("type") == "keyword":
        resolved = {"field": field, "runtime": None}
    elif (spec.get("fields") or {}).get("keyword"):
        resolved = {"field": f"{field}.keyword", "runtime": None}
    else:
        runtime_name = f"{field}_kw"
        resolved = {
            "field": runtime_name,
            "runtime": {
                runtime_name: {
                    "type": "keyword",
                    "script": {
                        "source": (
                            "def v = params._source == null ? null : params._source.get('"
                            + field
                            + "'); if (v == null) { return; }"
                            " if (v instanceof List) { for (def item : v) { if (item != null) { emit(item); } } }"
                            " else { emit(v); }"
                        )
                    },
                }
            },
        }

    _AGG_FIELD_CACHE[field] = resolved
    return resolved


def get_contract_analytics(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    region: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_entities: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    base_query = _build_contract_query(
        q, year, entity, nif, region=region, cpv_code=cpv_code,
        min_price=min_price, max_price=max_price, start_date=start_date, end_date=end_date,
    )

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    analytics_body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "value_distribution": {
                        "histogram": {
                            "field": "precoContratual",
                            "interval": 50000,
                            "min_doc_count": 1,
                        }
                    },
                    "top_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    # `*.parsed.nome` é `keyword` e não pode ser agregado;
                                    # os `top_hits` trazem o nome legível de cada NIF.
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": top_cpv,
                                    "order": {"_count": "desc"},
                                },
                                "aggs": {
                                    # `cpv.description` é `text` (sem `.keyword`): os `top_hits`
                                    # devolvem a descrição legível de cada documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": procedure_agg["field"], "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": contract_agg["field"], "size": 20, "missing": "N/A"}
                    },
        },
    }
    if runtime_mappings:
        analytics_body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=analytics_body)

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        entity_rows: List[Dict[str, Any]] = []
        seen_entities: set = set()
        for agg_key in ("top_adjudicantes", "top_adjudicatarios"):
            for b in aggs.get(agg_key, {}).get("names", {}).get("buckets", []):
                key = b["key"]
                if not key or key in seen_entities:
                    continue
                seen_entities.add(key)
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                entity_rows.append({
                    "key": key,
                    "count": b["doc_count"],
                    "total_value": fmt_money(value),
                    "description": _top_hit_name(b.get("name")),
                })
        entity_rows.sort(key=lambda x: (x.get("total_value") or 0, x.get("count") or 0), reverse=True)
        entity_rows = entity_rows[:top_entities]

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            total_value_obj = b.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(value),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(b.get("total_value", {}).get("value"))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            # `precoContratual` tem valores negativos (correções/notas de crédito) que
            # caíam nos primeiros escalões do histograma; ignoram-se aqui.
            "value_distribution": [
                {"key": f"{int(b['key'])} - {int(b['key']) + 50000}", "count": b["doc_count"]}
                for b in aggs["value_distribution"]["buckets"]
                if b.get("key") is not None and b["key"] >= 0
            ][:value_buckets],
            "top_entities": entity_rows,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


# --- Diretório de empresas (entidades) ---

def _entity_lookup_by_nif_query(nif: str) -> Dict[str, Any]:
    """Devolve uma query nested que procura uma entidade por NIF em ambos os papéis."""
    return {
        "bool": {
            "should": [
                {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
            ],
            "minimum_should_match": 1,
        }
    }


def get_company_by_nif(
    nif: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve resumo de uma entidade específica pelo NIF.

    Faz uma pesquisa nested com agregações por papel, devolvendo a estrutura
    CompanySummary (nif, name, total_value, adjudicante/adjudicatario, etc.).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": _entity_lookup_by_nif_query(nif),
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicantes.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicatarios.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def build_role_summary(agg_key: str) -> Optional[Dict[str, Any]]:
            bucket = aggs.get(agg_key, {}).get("filtered", {})
            doc_count = bucket.get("doc_count", 0)
            if not doc_count:
                return None
            name_hits = bucket.get("name", {}).get("hits", {}).get("hits", [])
            name_from_hit: Optional[str] = None
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    name_from_hit = src.get("nome")
            total_value_obj = bucket.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            years_stats = bucket.get("years", {}).get("stats", {})
            first_year = years_stats.get("min")
            last_year = years_stats.get("max")
            return {
                "contracts_count": doc_count,
                "total_value": fmt_money(value) or 0.0,
                "avg_value": fmt_money(value / doc_count) if value and doc_count else None,
                "first_year": int(first_year) if first_year is not None else None,
                "last_year": int(last_year) if last_year is not None else None,
                "name": name_from_hit,
            }

        adjudicante = build_role_summary("adjudicantes")
        adjudicatario = build_role_summary("adjudicatarios")
        contracts_total = (adjudicante["contracts_count"] if adjudicante else 0) + (adjudicatario["contracts_count"] if adjudicatario else 0)
        total_value = (adjudicante["total_value"] if adjudicante else 0.0) + (adjudicatario["total_value"] if adjudicatario else 0.0)

        # Escolhe o nome mais comum entre os papéis
        names: List[str] = []
        for key in ("adjudicantes", "adjudicatarios"):
            role_summary = adjudicante if key == "adjudicantes" else adjudicatario
            if role_summary and role_summary.get("name"):
                names.append(role_summary["name"])
        name = names[0] if names else nif

        return {
            "nif": nif,
            "name": name,
            "normalized_name": name,
            "contracts_total": contracts_total,
            "total_value": fmt_money(total_value) or 0.0,
            "adjudicante": adjudicante,
            "adjudicatario": adjudicatario,
        }
    except Exception as e:
        return {"error": str(e)}


def _company_role_filter(role: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Devolve filtro de caminho nested conforme o papel pretendido."""
    if role == "adjudicante":
        return [{"nested": {"path": "adjudicantes.parsed", "query": {"exists": {"field": "adjudicantes.parsed.nif"}}}}]
    if role == "adjudicatario":
        return [{"nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}}]
    return None


def _company_name_query(q: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query de texto para nome ou NIF de empresa em qualquer um dos papéis.

    O nome em `*.parsed.nome` é um campo `keyword` (só corresponde a nomes
    exatos), pelo que a pesquisa por nome parcial usa o campo de texto
    `*.raw` (ex.: ``"503933813 - Infraestruturas de Portugal"``), insensível a
    maiúsculas e a palavras parciais.
    """
    if not q:
        return None
    q_clean = q.strip()
    if not q_clean:
        return None
    should_clauses: List[Dict[str, Any]] = []
    for role_path in ("adjudicantes", "adjudicatarios"):
        should_clauses.append(
            {"match": {f"{role_path}.raw": {"query": q_clean, "operator": "and"}}}
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"match": {f"{role_path}.parsed.nome": {"query": q_clean, "operator": "and"}}},
                }
            }
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"term": {f"{role_path}.parsed.nif": q_clean}},
                }
            }
        )
    return {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }


def search_companies(
    q: Optional[str] = None,
    role: Optional[str] = "all",
    region: Optional[str] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    year: Optional[int] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa entidades únicas derivadas dos contratos indexados.

    Utiliza duas agregações nested por NIF (adjudicantes/adjudicatarios) e depois
    combina os resultados em memória para devolver uma lista paginada de empresas.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    ensure_indices(client)

    base_filters: List[Dict[str, Any]] = []
    if year:
        base_filters.append({"term": {"Ano": year}})
    if region:
        base_filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        base_filters.extend(role_filter)

    name_query = _company_name_query(q)

    base_query: Dict[str, Any] = {"bool": {}}
    if base_filters:
        base_query["bool"]["filter"] = base_filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": base_query,
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    # Contagens reais de NIF distintos (a lista acima é limitada aos
                    # 2000 maiores por papel, pelo que `total` é sempre um limite
                    # inferior do universo de entidades).
                    "unique_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicantes.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                    "unique_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                },
            },
        )

        companies: Dict[str, Dict[str, Any]] = {}

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        for agg_key in ("adjudicantes", "adjudicatarios"):
            role_name = "adjudicante" if agg_key == "adjudicantes" else "adjudicatario"
            for b in resp["aggregations"][agg_key]["by_nif"]["buckets"]:
                nif = b["key"]
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                name = nif or "Nome desconhecido"
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                total_value = value or 0.0
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")
                count = b["doc_count"]

                if count < min_contracts:
                    continue
                if min_value is not None and total_value < min_value:
                    continue
                if max_value is not None and total_value > max_value:
                    continue

                if nif and nif not in companies:
                    companies[nif] = {
                        "nif": nif,
                        "name": name,
                        "normalized_name": name,
                        "contracts_total": 0,
                        "total_value": 0.0,
                        "adjudicante": None,
                        "adjudicatario": None,
                    }
                if not nif:
                    key = f"__no_nif__{name.lower().strip()}"
                    if key not in companies:
                        companies[key] = {
                            "nif": None,
                            "name": name,
                            "normalized_name": name,
                            "contracts_total": 0,
                            "total_value": 0.0,
                            "adjudicante": None,
                            "adjudicatario": None,
                        }

                entry = companies[nif if nif else key]
                role_summary = {
                    "contracts_count": count,
                    "total_value": fmt_money(total_value) or 0.0,
                    "avg_value": fmt_money(total_value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry[role_name] = role_summary
                entry["contracts_total"] = (entry["contracts_total"] or 0) + count
                entry["total_value"] = (entry["total_value"] or 0.0) + total_value

        items = sorted(companies.values(), key=lambda x: (x.get("total_value") or 0, x.get("contracts_total") or 0), reverse=True)
        total = len(items)
        page = items[from_: from_ + size]
        for it in page:
            it["total_value"] = fmt_money(it["total_value"]) or 0.0

        unique_adjudicantes = resp["aggregations"].get("unique_adjudicantes", {}).get("nifs", {}).get("value", 0)
        unique_adjudicatarios = resp["aggregations"].get("unique_adjudicatarios", {}).get("nifs", {}).get("value", 0)

        return {
            "query": q,
            "total": total,
            "items": page,
            "from": from_,
            "size": size,
            "unique_adjudicantes": int(unique_adjudicantes or 0),
            "unique_adjudicatarios": int(unique_adjudicatarios or 0),
        }
    except Exception as e:
        return {"query": q, "total": 0, "items": [], "error": str(e)}


def get_entity_role_summary(
    role: Optional[str] = "all",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    min_contracts: int = 1,
    top_n: int = 25,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Resumo agregado do universo de entidades por papel (adjudicante/adjudicatário).

    Numa única pesquisa devolve tudo o que um dashboard de entidades precisa:
    volume e valor contratual, médias, entidades distintas, distribuição por
    ano/NUTS/CPV/procedimento/tipo de contrato, contrapartes mais frequentes,
    ranking das maiores entidades e a concentração do mercado.

    O parâmetro `role` aceita ``"adjudicante"``, ``"adjudicatario"`` ou
    ``"all"`` (empresas nos dois papéis, com a decomposição por papel).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "role": role, "top_entities": []}

    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})
    if region:
        filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        filters.extend(role_filter)
    if min_value is not None:
        filters.append({"range": {"precoContratual": {"gte": min_value}}})
    if max_value is not None:
        filters.append({"range": {"precoContratual": {"lte": max_value}}})

    name_query = _company_name_query(q)

    base_query: Dict[str, Any] = {"bool": {}}
    if filters:
        base_query["bool"]["filter"] = filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    def _role_agg(path: str) -> Dict[str, Any]:
        """Agg nested com o ranking de NIF daquele papel e a contagem distinta."""
        return {
            "nested": {"path": f"{path}.parsed"},
            "aggs": {
                "by_nif": {
                    "terms": {
                        "field": f"{path}.parsed.nif",
                        "size": max(top_n, 10),
                        "order": {"total_value": "desc"},
                    },
                    "aggs": {
                        "name": {"top_hits": {"size": 1, "_source": [f"{path}.parsed.nome"]}},
                        "total_value": {
                            "reverse_nested": {},
                            "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                        },
                        "years": {
                            "reverse_nested": {},
                            "aggs": {"stats": {"stats": {"field": "Ano"}}},
                        },
                    },
                },
                "nifs": {
                    "cardinality": {
                        "field": f"{path}.parsed.nif",
                        "precision_threshold": 40000,
                    }
                },
            },
        }

    # Contrapartes: quem contrata com as entidades do papel pedido.
    counterpart_path = "adjudicatarios" if role == "adjudicante" else "adjudicantes"

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
            "total_value": {"sum": {"field": "precoContratual"}},
            "avg_value": {"avg": {"field": "precoContratual"}},
            "max_value": {"max": {"field": "precoContratual"}},
            "by_year": {
                "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_region": {
                "terms": {"field": "NUTs", "size": 20, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": 15, "order": {"total_value": "desc"}},
                        "aggs": {
                            "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            },
            "by_procedure_type": {
                "terms": {"field": procedure_agg["field"], "size": 15, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_contract_type": {
                "terms": {"field": contract_agg["field"], "size": 15, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_value_range": {
                "histogram": {"field": "precoContratual", "interval": 100000, "min_doc_count": 1}
            },
            "counterparties": {
                "nested": {"path": f"{counterpart_path}.parsed"},
                "aggs": {
                    "by_nif": {
                        "terms": {
                            "field": f"{counterpart_path}.parsed.nif",
                            "size": 20,
                            "order": {"total_value": "desc"},
                        },
                        "aggs": {
                            "name": {"top_hits": {"size": 1, "_source": [f"{counterpart_path}.parsed.nome"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            },
            "adjudicantes": _role_agg("adjudicantes"),
            "adjudicatarios": _role_agg("adjudicatarios"),
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    def _fmt_money(value: Any) -> Optional[float]:
        return round(value, 2) if isinstance(value, (int, float)) else None

    def _agg_value(bucket: Dict[str, Any]) -> float:
        """Lê o valor de um sub-aggregation `total_value` (sum ou reverse_nested/sum)."""
        raw = bucket.get("total_value", {})
        if isinstance(raw.get("value"), dict):
            return float(raw["value"].get("value") or 0.0)
        return float(raw.get("value") or 0.0)

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
        aggs = resp.get("aggregations", {})

        total_contracts = (
            resp.get("hits", {}).get("total", {}).get("value", 0)
            if isinstance(resp.get("hits", {}).get("total"), dict)
            else resp.get("hits", {}).get("total", 0)
        ) or 0
        total_value = float(aggs.get("total_value", {}).get("value") or 0.0)
        avg_value = float(aggs.get("avg_value", {}).get("value") or 0.0)
        max_value = float(aggs.get("max_value", {}).get("value") or 0.0)

        def _rows(agg_name: str) -> List[Dict[str, Any]]:
            return [
                {
                    "key": str(b["key"]),
                    "count": b["doc_count"],
                    "total_value": _fmt_money(_agg_value(b)) or 0.0,
                }
                for b in aggs.get(agg_name, {}).get("buckets", [])
            ]

        by_year = _rows("by_year")
        by_region = _rows("by_region")
        by_procedure_type = _rows("by_procedure_type")
        by_contract_type = _rows("by_contract_type")

        # O histograma devolve chaves numéricas: publica-se o limite inferior
        # (em euros) e uma etiqueta legível para o intervalo. Os escalões
        # negativos (valores anómalos nos dados de origem) são ignorados.
        by_value_range: List[Dict[str, Any]] = []
        for b in aggs.get("by_value_range", {}).get("buckets", []):
            start = int(b["key"])
            if start < 0:
                continue
            if len(by_value_range) >= 12:
                break
            by_value_range.append({
                "key": str(start),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": f"{start:,} – {start + 100000:,} €".replace(",", " "),
            })

        by_cpv: List[Dict[str, Any]] = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            by_cpv.append({
                "key": str(b["key"]),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        counterparties: List[Dict[str, Any]] = []
        for b in aggs.get("counterparties", {}).get("by_nif", {}).get("buckets", []):
            name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            label = b["key"]
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    label = src.get("nome") or label
            counterparties.append({
                "key": str(b["key"]),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": label,
            })
        # --- Ranking de entidades (união dos dois papéis quando role == "all") ---
        entities: Dict[str, Dict[str, Any]] = {}
        role_paths = (
            ("adjudicantes", "adjudicante"),
            ("adjudicatarios", "adjudicatario"),
        ) if role in (None, "all") else (
            (("adjudicantes", "adjudicante"),) if role == "adjudicante" else (("adjudicatarios", "adjudicatario"),)
        )

        for agg_key, role_name in role_paths:
            for b in aggs.get(agg_key, {}).get("by_nif", {}).get("buckets", []):
                nif = b.get("key")
                if not nif:
                    continue
                name = nif
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                count = b["doc_count"]
                value = _agg_value(b)
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")

                entry = entities.setdefault(nif, {
                    "nif": nif,
                    "name": name,
                    "normalized_name": name,
                    "contracts_total": 0,
                    "total_value": 0.0,
                    "adjudicante": None,
                    "adjudicatario": None,
                })
                entry[role_name] = {
                    "contracts_count": count,
                    "total_value": _fmt_money(value) or 0.0,
                    "avg_value": _fmt_money(value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry["contracts_total"] += count
                entry["total_value"] += value

        ranked = [e for e in entities.values() if e["contracts_total"] >= max(min_contracts, 1)]
        ranked.sort(key=lambda x: (x.get("total_value") or 0.0, x.get("contracts_total") or 0), reverse=True)
        top_entities = ranked[:top_n]
        for entry in top_entities:
            entry["total_value"] = _fmt_money(entry["total_value"]) or 0.0

        # Concentração: peso das maiores entidades no valor total (só é
        # significativa quando o ranking cobre todo o universo — sem filtros de
        # texto — pelo que é devolvida como indicador aproximado).
        def _share(n: int) -> Optional[float]:
            if total_value <= 0 or not ranked:
                return None
            top = sum(e.get("total_value") or 0.0 for e in ranked[:n])
            return round(min(1.0, top / total_value), 4)

        unique_adjudicantes = int(aggs.get("adjudicantes", {}).get("nifs", {}).get("value") or 0)
        unique_adjudicatarios = int(aggs.get("adjudicatarios", {}).get("nifs", {}).get("value") or 0)
        if role == "adjudicante":
            unique_entities: Optional[int] = unique_adjudicantes
        elif role == "adjudicatario":
            unique_entities = unique_adjudicatarios
        else:
            # A união exata dos dois papéis exigiria interseção de conjuntos; o
            # maior dos dois é um limite inferior do número de empresas únicas.
            unique_entities = max(unique_adjudicantes, unique_adjudicatarios)

        avg_per_entity = (
            round(total_value / unique_entities, 2) if unique_entities and total_value else None
        )

        return {
            "role": role or "all",
            "query": q,
            "year": year,
            "region": region,
            "total_contracts": int(total_contracts),
            "total_value": _fmt_money(total_value) or 0.0,
            "avg_value": _fmt_money(avg_value),
            "max_value": _fmt_money(max_value),
            "unique_entities": unique_entities,
            "unique_adjudicantes": unique_adjudicantes,
            "unique_adjudicatarios": unique_adjudicatarios,
            "avg_value_per_entity": avg_per_entity,
            "top_entities": top_entities,
            "counterparties": counterparties,
            "by_year": by_year,
            "by_region": by_region,
            "by_cpv": by_cpv,
            "by_procedure_type": by_procedure_type,
            "by_contract_type": by_contract_type,
            "by_value_range": by_value_range,
            "concentration": {
                "top1": _share(1),
                "top5": _share(5),
                "top10": _share(10),
                "top25": _share(25),
                "covered_entities": len(ranked),
            },
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - dependente do cluster
        return {"error": str(exc), "role": role, "top_entities": []}


def get_company_contracts(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve contratos onde a entidade aparece como adjudicante/adjudicatário."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome", "total": 0, "items": []}

    query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": size,
                "from": from_,
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            src["doc_id"] = hit["_id"]
            src["score"] = hit.get("_score")
            items.append(src)

        return {
            "nif": nif,
            "name": name,
            "role": role,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "total": 0, "items": []}


def _top_hit_name(agg: Optional[Dict[str, Any]]) -> str:
    """Nome legível de um bucket a partir de uma agregação `top_hits`.

    `*.parsed.nome` é `keyword` (não agregável), pelo que o nome vem dos
    documentos; o `_source` pode trazer só o campo pedido ou o objeto completo.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        name = source.get("nome")
        if isinstance(name, str) and name.strip():
            return name.strip()
        parsed = source.get("parsed")
        if isinstance(parsed, dict):
            nested_name = parsed.get("nome")
            if isinstance(nested_name, str) and nested_name.strip():
                return nested_name.strip()
    return ""


def _cpv_description_from_hits(agg: Optional[Dict[str, Any]], code: Any) -> str:
    """Lê a descrição legível de um CPV a partir de uma agregação `top_hits`.

    `cpv.description` está mapeado como `text` (sem `.keyword`), pelo que não
    pode ser agregado. Os `top_hits` trazem `_source.cpv` — que pode vir como a
    lista completa do documento ou já como o próprio objeto do CPV visitado —
    e aqui escolhe-se a entrada cujo `code` corresponde ao do bucket.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    fallback = ""
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        entries = source.get("cpv")
        if entries is None:
            entries = source
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description")
            if not description:
                continue
            if code is None or entry.get("code") == code:
                return description
            if not fallback:
                fallback = description
    return fallback


def get_company_analytics(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    year: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve analytics para uma empresa específica."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome"}

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})

    query = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        query["bool"]["filter"] = filters

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": query,
                "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "by_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {"field": "cpv.code", "size": 10, "order": {"total_value": "desc"}},
                                "aggs": {
                                    # `cpv.description` é `text` sem subcampo `.keyword`, pelo que
                                    # uma agregação `terms` devolvia sempre vazio; os `top_hits`
                                    # trazem a descrição real do documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_partners": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {"field": "adjudicatarios.parsed.nif", "size": 8, "order": {"total_value": "desc"}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": "tipoprocedimento.keyword", "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": "tipoContrato.keyword", "size": 20, "missing": "N/A"}
                    },
                    "by_value_range": {
                        "histogram": {"field": "precoContratual", "interval": 25000, "min_doc_count": 1}
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def extract_value(total_value_obj):
            if isinstance(total_value_obj.get("value"), dict):
                return total_value_obj["value"].get("value")
            return total_value_obj.get("value")

        cpv_rows = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        partner_rows = []
        for b in aggs.get("top_partners", {}).get("by_nif", {}).get("buckets", []):
            if b["key"] == nif:
                continue
            partner_name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            partner_name = ""
            if partner_name_hits:
                partner_src = partner_name_hits[0].get("_source", {})
                if isinstance(partner_src, dict):
                    partner_name = partner_src.get("nome", "")
            partner_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": partner_name,
            })

        company_summary = None
        if nif:
            company_summary = get_company_by_nif(nif, es=client)
            if "error" in company_summary:
                company_summary = None

        return {
            "company": company_summary,
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(b.get("total_value", {}).get("value"))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "by_cpv": cpv_rows,
            "top_partners": partner_rows,
            "by_procedure_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "by_contract_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "by_value_range": [{"key": f"{int(b['key'])} - {int(b['key']) + 25000}", "count": b["doc_count"]} for b in aggs["by_value_range"]["buckets"][:10]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


def list_contract_years(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve anos disponíveis e total indexado por ano."""
    client = es or get_es_client()
    available = contract_years_available()
    if not client:
        return {"available": available, "indexed": []}
    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                    }
                },
            },
        )
        indexed = [{"year": int(bucket["key"]), "count": bucket["doc_count"]} for bucket in resp["aggregations"]["by_year"]["buckets"]]
        return {"available": available, "indexed": indexed}
    except Exception as e:
        return {"available": available, "indexed": [], "error": str(e)}


def get_contract_by_id(idcontrato: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato pelo identificador publicado no portal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={"size": 1, "query": {"term": {"idcontrato": idcontrato}}},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return {"error": "Contrato não encontrado", "status_code": 404}
        source = dict(hits[0].get("_source", {}))
        source["doc_id"] = hits[0].get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}


def get_contract_regional_analytics(year: Optional[int] = None, size: int = 30, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Agrega volume e valor contratual por NUTS."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}
    query: Dict[str, Any] = {"match_all": {}}
    if year:
        query = {"term": {"Ano": year}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "track_total_hits": True,
                "size": 0,
                "query": query,
                "aggs": {
                    "regions": {
                        "terms": {"field": "NUTs", "size": size, "missing": "Não especificado"},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "total_value": {"sum": {"field": "precoContratual"}},
                },
            },
        )
        aggs = response.get("aggregations", {})
        return {
            "total_contracts": response.get("hits", {}).get("total", {}).get("value", 0),
            "total_value": aggs.get("total_value", {}).get("value"),
            "regions": [
                {"key": bucket["key"], "count": bucket["doc_count"], "total_value": bucket.get("total_value", {}).get("value")}
                for bucket in aggs.get("regions", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "regions": []}


# Distritos e regiões autónomas de Portugal, escritos como aparecem no segundo
# segmento de `localExecucao` («Portugal, <Distrito>[, <Município>]»).
#
# Esta é a geografia com cobertura real nos contratos portugueses: o campo `NUTs`
# só existe em ~14% dos documentos (309 mil de 2,25 M), enquanto `localExecucao`
# traz distrito em ~91% (2,05 M). O `_region_filter` aceita por isso tanto um
# código/string NUTS como o nome de um distrito.
PT_DISTRICTS: tuple = (
    "Aveiro",
    "Beja",
    "Braga",
    "Bragança",
    "Castelo Branco",
    "Coimbra",
    "Évora",
    "Faro",
    "Guarda",
    "Leiria",
    "Lisboa",
    "Portalegre",
    "Porto",
    "Santarém",
    "Setúbal",
    "Viana do Castelo",
    "Vila Real",
    "Viseu",
    "Região Autónoma da Madeira",
    "Região Autónoma dos Açores",
)


def _fold_text(value: Optional[str]) -> str:
    """Minúsculas sem acentos (comparação tolerante de nomes de distrito)."""
    text = (value or "").strip().lower()
    for source, target in (("ã", "a"), ("á", "a"), ("â", "a"), ("à", "a"), ("é", "e"), ("ê", "e"),
                           ("í", "i"), ("ó", "o"), ("ô", "o"), ("õ", "o"), ("ú", "u"), ("ç", "c")):
        text = text.replace(source, target)
    return text


def _strip_accents(value: str) -> str:
    """Remove acentos mantendo a caixa («Bragança» → «Braganca»).

    O portal base escreve o mesmo distrito das duas formas («Bragança» nos ZIPs
    antigos, «Braganca» em Ficheiros mais recentes), por isso o filtro tem de
    aceitar ambas.
    """
    return "".join(
        char for char in unicodedata.normalize("NFD", value or "") if unicodedata.category(char) != "Mn"
    )


# Nome canónico a partir da chave comparável («setubal» → «Setúbal»), para que o
# filtro use a grafia que existe nos dados mesmo que o pedido venha sem acentos.
_PT_DISTRICT_BY_KEY = {_fold_text(name): name for name in PT_DISTRICTS}



def _pt_district_from_local(local: Any) -> Optional[str]:
    """Extrai o distrito de `localExecucao` («Portugal, Lisboa, Cascais» → «Lisboa»)."""
    text = str(local or "").strip()
    if not text.startswith("Portugal"):
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 2:
        return None
    return parts[1] or None

def _district_filter(distrito: str, unspecified: bool = False) -> Dict[str, Any]:
    """Filtro por distrito de execução (Portugal).

    O distrito aparece como segundo segmento de `localExecucao`, com ou sem
    município («Portugal, Braga» e «Portugal, Braga, Guimarães»). O termo exato
    + prefixo com vírgula evita colisões de nomes (Braga vs. Bragança).

    Aceita as duas grafias usadas nos dados («Bragança» e «Braganca»), senão o
    mapa agrega contratos que a pesquisa depois não encontra.
    """
    if unspecified:
        return {
            "bool": {
                "must_not": {"wildcard": {"localExecucao": {"value": "Portugal, *"}}},
            }
        }
    variants: List[str] = []
    for name in (distrito, _strip_accents(distrito)):
        if name and name not in variants:
            variants.append(name)
    should: List[Dict[str, Any]] = []
    for name in variants:
        should.append({"term": {"localExecucao": f"Portugal, {name}"}})
        should.append({"prefix": {"localExecucao": f"Portugal, {name}, "}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _region_filter(region: Optional[str] = None) -> Dict[str, Any]:
    """Filtro de região. Aceita NUTS (código ou string completa) ou distrito PT.

    ES armazena NUTs como strings completas (ex: "PT11A - Área Metropolitana do Porto"),
    por isso usamos wildcard/prefixo quando a região fornecida não contém o separador.
    O grupo "Não especificado" corresponde aos contratos sem NUTs (campo ausente ou vazio).
    """
    if not region:
        return None
    if is_unspecified(region):
        return {
            "bool": {
                "should": [
                    {"bool": {"must_not": {"exists": {"field": "NUTs"}}}},
                    {"term": {"NUTs": ""}},
                ],
                "minimum_should_match": 1,
            }
        }
    if " - " in region:
        return {"term": {"NUTs": region}}
    distrito = _PT_DISTRICT_BY_KEY.get(_fold_text(region))
    if distrito:
        # Nome de distrito português: a geografia fiável é `localExecucao`, não a NUTS.
        return _district_filter(distrito)
    return {"wildcard": {"NUTs": f"{region}*"}}


# ---------------------------------------------------------------------------
# Mapa ibérico de contratos públicos (Portugal + Espanha)
# ---------------------------------------------------------------------------
#
# Os contratos não têm coordenadas: a geografia disponível é administrativa
# (distrito português, província/NUTS espanhola). Este agregado devolve volume e
# valor por região para cada país; a conversão em pontos no mapa (centroide da
# capital) é feita no frontend, onde também se marca o que é aproximado.


def _sum_agg_value(agg: Optional[Dict[str, Any]]) -> float:
    """Valor de uma agregação `sum` (0.0 quando ausente/nula)."""
    value = (agg or {}).get("value")
    return float(value) if value is not None else 0.0


# Campos de texto para a pesquisa do mapa. Os nomes das partes entram por
# `adjudicantes.raw`/`adjudicatarios.raw` (texto) e não por `parsed.nome`, que é
# `keyword`: nesse campo só casaria o nome completo exato («METROPOLITANO DE
# LISBOA, S.A.»), nunca «Metropolitano de Lisboa».
_IBERIA_TEXT_FIELDS_PT = [
    "objectoContrato^3",
    "descContrato^2",
    "search_text",
    "adjudicantes.raw",
    "adjudicatarios.raw",
    "cpv.description",
]
_IBERIA_TEXT_FIELDS_ES = [
    "objeto^3",
    "adjudicatario_nombre^2",
    "organo_nombre^2",
    "descripcion",
    "search_text",
]


def _iberia_text_query(text: str, fields: List[str]) -> Dict[str, Any]:
    """`multi_match` que exige **todos** os termos (`operator: and`).

    A pesquisa livre dos contratos (páginas de pesquisa) usa `best_fields` sem
    mínimo de termos: «Hospital de Cascais» devolve 2,1 M contratos (basta o
    «de»). Num mapa isso acenderia o país inteiro, por isso a pesquisa do mapa
    exige todos os termos.
    """
    return {
        "multi_match": {
            "query": text,
            "fields": fields,
            "type": "best_fields",
            "operator": "and",
        }
    }


def _with_required(query: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Acrescenta uma condição obrigatória a uma query já construída."""
    if not extra:
        return query
    if query == {"match_all": {}}:
        return extra
    combined = dict(query)
    bool_query = dict(combined.get("bool", {}))
    bool_query["must"] = list(bool_query.get("must", [])) + [extra]
    combined["bool"] = bool_query
    return combined


def _es_code_level(code: str) -> str:
    """Nível NUTS de um código espanhol: `ES300` (3), `ES30` (2), `ES3` (1) ou país."""
    body = code[2:]
    if body.isdigit():
        return {1: "nuts1", 2: "nuts2", 3: "nuts3"}.get(len(body), "pais")
    return "pais"


def _iberia_map_portugal(
    client: Elasticsearch,
    ano: Optional[int],
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
) -> Dict[str, Any]:
    """Contratos portugueses por distrito de execução (`localExecucao`).

    Os filtros de país (`cpv`, `ano`) vêm da pesquisa de contratos; o texto
    (objeto, entidades) usa uma pesquisa que exige todos os termos, para o mapa
    não mostrar o país inteiro com uma pesquisa de duas palavras.
    """
    texto = " ".join(part.strip() for part in (q, entidade) if part and part.strip())
    query = _build_contract_query(year=ano, cpv_code=cpv)
    if texto:
        query = _with_required(query, _iberia_text_query(texto, _IBERIA_TEXT_FIELDS_PT))
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": query,
            "aggs": {
                "total_value": {"sum": {"field": "precoContratual"}},
                "locais": {
                    "terms": {"field": "localExecucao", "size": 2000},
                    "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                },
                "com_distrito": {
                    "filter": {"wildcard": {"localExecucao": {"value": "Portugal, *"}}},
                    "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                },
            },
        },
    )
    aggs = resp.get("aggregations", {}) or {}
    districts: Dict[str, Dict[str, float]] = {}
    for bucket in aggs.get("locais", {}).get("buckets", []):
        raw = _pt_district_from_local(bucket.get("key"))
        if not raw:
            continue
        # O portal escreve o mesmo distrito com variantes (ex.: «Braganca» sem
        # cedilha): normalizamos para o nome canónico para não partir a região.
        # Valores que não são distritos («Portugal Continental», «Distrito não
        # determinado») ficam como região própria e o frontend lista-os à parte.
        distrito = _PT_DISTRICT_BY_KEY.get(_fold_text(raw), raw)
        entry = districts.setdefault(distrito, {"count": 0.0, "total_value": 0.0})
        entry["count"] += bucket.get("doc_count", 0)
        entry["total_value"] += _sum_agg_value(bucket.get("total_value"))

    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = _sum_agg_value(aggs.get("total_value"))
    with_district = (aggs.get("com_distrito", {}) or {}).get("doc_count", 0)
    with_district_value = _sum_agg_value((aggs.get("com_distrito", {}) or {}).get("total_value"))

    regions = [
        {
            "pais": "PT",
            "code": name,
            "label": name,
            "level": "distrito",
            "count": int(values["count"]),
            "total_value": round(values["total_value"], 2),
        }
        for name, values in sorted(districts.items(), key=lambda item: item[1]["total_value"], reverse=True)
    ]
    return {
        "total_contracts": int(total),
        "total_value": round(total_value, 2),
        "regions": regions,
        "unspecified": {
            "count": max(int(total) - int(with_district), 0),
            "total_value": round(max(total_value - with_district_value, 0.0), 2),
        },
        "other_locations": {"count": 0, "total_value": 0.0},
    }


def _iberia_map_espanha(
    client: Elasticsearch,
    ano: Optional[int],
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
) -> Dict[str, Any]:
    """Contratos de Espanha por província/NUTS (`nuts`).

    A `entidade` entra no texto livre: no PLACSP o nome do órgão e da
    adjudicatária são campos pesquisáveis do mesmo `multi_match`.
    """
    value_source = _contratos_es_value_source("valor_adjudicado")
    texto = " ".join(part.strip() for part in (q, entidade) if part and part.strip())
    query = _build_contratos_es_query(ano=ano, cpv_code=cpv)
    if texto:
        query = _with_required(query, _iberia_text_query(texto, _IBERIA_TEXT_FIELDS_ES))
    resp = client.search(
        index=CONTRATOS_ES_INDEX,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": query,
            "aggs": {
                "total_value": {"sum": value_source},
                "codigos": {
                    "terms": {"field": "nuts", "size": 600},
                    "aggs": {"total_value": {"sum": value_source}},
                },
                "com_nuts": {
                    "filter": {"prefix": {"nuts": "ES"}},
                    "aggs": {"total_value": {"sum": value_source}},
                },
            },
        },
    )
    aggs = resp.get("aggregations", {}) or {}
    regions: List[Dict[str, Any]] = []
    other_count = 0
    other_value = 0.0
    for bucket in aggs.get("codigos", {}).get("buckets", []):
        code = str(bucket.get("key") or "").strip()
        if not code:
            continue
        value = _sum_agg_value(bucket.get("total_value"))
        if not code.startswith("ES"):
            # Local de execução fora de Espanha (o adjudicatário pode ser estrangeiro).
            other_count += bucket.get("doc_count", 0)
            other_value += value
            continue
        regions.append({
            "pais": "ES",
            "code": code,
            "label": code,
            "level": _es_code_level(code),
            "count": int(bucket.get("doc_count", 0)),
            "total_value": round(value, 2),
        })

    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = _sum_agg_value(aggs.get("total_value"))
    with_nuts = (aggs.get("com_nuts", {}) or {}).get("doc_count", 0)
    with_nuts_value = _sum_agg_value((aggs.get("com_nuts", {}) or {}).get("total_value"))

    regions.sort(key=lambda row: row["total_value"], reverse=True)
    return {
        "total_contracts": int(total),
        "total_value": round(total_value, 2),
        "regions": regions,
        "unspecified": {
            "count": max(int(total) - int(with_nuts), 0),
            "total_value": round(max(total_value - with_nuts_value, 0.0), 2),
        },
        "other_locations": {
            "count": int(other_count),
            "total_value": round(other_value, 2),
        },
    }


def get_contracts_iberia_map(
    ano: Optional[int] = None,
    pais: str = "all",
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Volume e valor de contratos por região, para o mapa de Portugal e Espanha.

    Uma só chamada devolve as duas geografias (distrito em Portugal, província em
    Espanha) e o que não é localizável, para o mapa não inventar posições. Aceita
    os mesmos filtros de pesquisa dos dois países (`q`, `entidade`, `cpv`, `ano`).
    """
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}

    ensure_indices(client)

    selecao = (pais or "all").strip().lower()
    if selecao in ("pt", "portugal"):
        selecao = "pt"
    elif selecao in ("es", "espanha", "spain"):
        selecao = "es"
    else:
        selecao = "all"

    result: Dict[str, Any] = {
        "ano": ano,
        "pais": selecao,
        "filters": {"q": q or None, "entidade": entidade or None, "cpv": cpv or None},
        "countries": [],
        "regions": [],
        "unspecified": {},
        "other_locations": {"count": 0, "total_value": 0.0},
    }
    warnings: List[str] = []

    parts = []
    if selecao in ("all", "pt"):
        try:
            parts.append(("PT", _iberia_map_portugal(client, ano, q=q, entidade=entidade, cpv=cpv)))
        except Exception as exc:  # noqa: BLE001 — um país indisponível não deve derrubar o mapa
            warnings.append(f"Portugal: {exc}")
    if selecao in ("all", "es"):
        try:
            parts.append(("ES", _iberia_map_espanha(client, ano, q=q, entidade=entidade, cpv=cpv)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Espanha: {exc}")

    for code, part in parts:
        result["countries"].append({
            "code": code,
            "label": "Portugal" if code == "PT" else "Espanha",
            "total_contracts": part["total_contracts"],
            "total_value": part["total_value"],
        })
        result["regions"].extend(part["regions"])
        result["unspecified"][code] = part["unspecified"]
        result["other_locations"]["count"] += part["other_locations"]["count"]
        result["other_locations"]["total_value"] += part["other_locations"]["total_value"]

    result["other_locations"]["total_value"] = round(result["other_locations"]["total_value"], 2)
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Ficha de uma região (aberta a partir do mapa)
# ---------------------------------------------------------------------------


def _pt_region_detail(
    client: Elasticsearch,
    code: str,
    ano: Optional[int],
    q: Optional[str],
    cpv: Optional[str],
    top_n: int,
    contracts_size: int,
) -> Dict[str, Any]:
    """Ficha de um distrito português: entidades, empresas, analíticas e contratos.

    Uma só pesquisa devolve tudo — incluindo os maiores contratos, em `top_hits` —
    para que as métricas e a lista de contratos venham sempre do mesmo conjunto
    (a pesquisa do mapa exige todos os termos; é a mesma aqui).
    """
    query = _build_contract_query(year=ano, region=code, cpv_code=cpv)
    if q:
        query = _with_required(query, _iberia_text_query(q, _IBERIA_TEXT_FIELDS_PT))

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    def role_agg(path: str) -> Dict[str, Any]:
        """Ranking de NIF de um papel (adjudicantes/adjudicatários) por valor."""
        return {
            "nested": {"path": f"{path}.parsed"},
            "aggs": {
                "by_nif": {
                    "terms": {
                        "field": f"{path}.parsed.nif",
                        "size": top_n,
                        "order": {"total_value": "desc"},
                    },
                    "aggs": {
                        "name": {"top_hits": {"size": 1, "_source": [f"{path}.parsed.nome"]}},
                        "total_value": {
                            "reverse_nested": {},
                            "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                        },
                        "anos": {
                            "reverse_nested": {},
                            "aggs": {"stats": {"stats": {"field": "Ano"}}},
                        },
                    },
                },
                "nifs": {"cardinality": {"field": f"{path}.parsed.nif", "precision_threshold": 40000}},
            },
        }

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "total_value": {"sum": {"field": "precoContratual"}},
            "avg_value": {"avg": {"field": "precoContratual"}},
            "max_value": {"max": {"field": "precoContratual"}},
            "by_year": {
                "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_n, "order": {"total_value": "desc"}},
                        "aggs": {
                            "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            },
            "by_procedure": {
                "terms": {"field": procedure_agg["field"], "size": 10, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_contract_type": {
                "terms": {"field": contract_agg["field"], "size": 10, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_value_range": {
                "histogram": {"field": "precoContratual", "interval": 100000, "min_doc_count": 1}
            },
            "adjudicantes": role_agg("adjudicantes"),
            "adjudicatarios": role_agg("adjudicatarios"),
            "top_contracts": {
                "top_hits": {
                    "size": contracts_size,
                    "sort": [
                        {"precoContratual": {"order": "desc", "missing": "_last", "unmapped_type": "float"}}
                    ],
                    "_source": [
                        "objectoContrato",
                        "precoContratual",
                        "Ano",
                        "adjudicantes.parsed",
                        "adjudicatarios.parsed",
                        "dataCelebracaoContrato",
                        "dataPublicacao",
                        "idcontrato",
                    ],
                }
            },
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    resp = client.search(index=CONTRACTS_INDEX, body=body)
    aggs = resp.get("aggregations", {}) or {}

    def agg_value(bucket: Optional[Dict[str, Any]]) -> float:
        """Valor de um `sum` (incluindo os encaixados em `reverse_nested`)."""
        raw = (bucket or {}).get("total_value", {})
        value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(value, dict):
            value = value.get("value")
        return float(value or 0.0)

    total_contracts = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = float(aggs.get("total_value", {}).get("value") or 0.0)

    def rows(agg_name: str) -> List[Dict[str, Any]]:
        return [
            {"key": str(b["key"]), "count": b["doc_count"], "total_value": round(agg_value(b), 2)}
            for b in (aggs.get(agg_name, {}) or {}).get("buckets", [])
        ]

    value_ranges: List[Dict[str, Any]] = []
    for bucket in (aggs.get("by_value_range", {}) or {}).get("buckets", []):
        start = bucket.get("key")
        if start is None or start < 0 or len(value_ranges) >= 12:
            continue
        value_ranges.append({
            "key": str(int(start)),
            "count": bucket.get("doc_count", 0),
            "total_value": round(agg_value(bucket), 2),
            "description": f"{int(start):,} – {int(start) + 100000:,} €".replace(",", " "),
        })

    cpv_rows: List[Dict[str, Any]] = []
    for bucket in (aggs.get("by_cpv", {}) or {}).get("codes", {}).get("buckets", []):
        cpv_rows.append({
            "key": str(bucket["key"]),
            "count": bucket["doc_count"],
            "total_value": round(agg_value(bucket), 2),
            "description": _cpv_description_from_hits(bucket.get("description"), bucket["key"]),
        })

    def entity_rows(path: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for bucket in (aggs.get(path, {}) or {}).get("by_nif", {}).get("buckets", []):
            nif = bucket.get("key")
            if not nif:
                continue
            name = str(nif)
            hits = ((bucket.get("name") or {}).get("hits") or {}).get("hits") or []
            if hits:
                source = hits[0].get("_source") or {}
                name = str(source.get("nome") or name)
            value = agg_value(bucket)
            count = bucket.get("doc_count", 0)
            stats = ((bucket.get("anos") or {}).get("stats") or {})
            out.append({
                "nif": str(nif),
                "name": _unescape_label(name),
                "count": count,
                "total_value": round(value, 2),
                "avg_value": round(value / count, 2) if count else None,
                "share": round(value / total_value, 4) if total_value > 0 else None,
                "first_year": int(stats["min"]) if stats.get("min") is not None else None,
                "last_year": int(stats["max"]) if stats.get("max") is not None else None,
            })
        return out

    contract_rows: List[Dict[str, Any]] = []
    for hit in ((aggs.get("top_contracts", {}) or {}).get("hits", {}) or {}).get("hits", []):
        source = hit.get("_source") or {}
        contract_rows.append({
            "doc_id": hit.get("_id") or source.get("idcontrato"),
            "title": source.get("objectoContrato") or "",
            "awarder": _party_names(source.get("adjudicantes")),
            "supplier": _party_names(source.get("adjudicatarios")),
            "value": source.get("precoContratual"),
            "ano": source.get("Ano"),
            "date": source.get("dataCelebracaoContrato") or source.get("dataPublicacao"),
        })

    return {
        "pais": "PT",
        "code": code,
        "ano": ano,
        "filters": {"q": q or None, "cpv": cpv or None},
        "totals": {
            "contracts": int(total_contracts),
            "value": round(total_value, 2),
            "avg": round(float(aggs.get("avg_value", {}).get("value") or 0.0), 2) or None,
            "max": round(float(aggs.get("max_value", {}).get("value") or 0.0), 2) or None,
            "awarders": int((aggs.get("adjudicantes", {}) or {}).get("nifs", {}).get("value") or 0),
            "suppliers": int((aggs.get("adjudicatarios", {}) or {}).get("nifs", {}).get("value") or 0),
        },
        "by_year": rows("by_year"),
        "by_cpv": cpv_rows,
        "by_procedure": rows("by_procedure"),
        "by_contract_type": rows("by_contract_type"),
        "by_value_range": value_ranges,
        "awarders": entity_rows("adjudicantes"),
        "suppliers": entity_rows("adjudicatarios"),
        "contracts": contract_rows,
        "error": None,
    }


def _party_names(parties: Any) -> str:
    """Nomes das partes de um contrato português (`adjudicantes`/`adjudicatarios`)."""
    entries = parties if isinstance(parties, list) else [parties] if parties else []
    names: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for parsed in entry.get("parsed") or []:
            if isinstance(parsed, dict) and parsed.get("nome"):
                names.append(_unescape_label(parsed["nome"]))
    return ", ".join(names[:3])


def _unescape_label(value: Any) -> str:
    """Desfaz entidades HTML nos nomes publicados («SANTOS &amp; FILHOS» → «& FILHOS»).

    Os feeds do portal base e do PLACSP trazem o `&` escapado em nomes de
    entidades; sem isto a ficha da região mostrava `&amp;`.
    """
    text = str(value or "")
    for source, target in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(source, target)
    return text


def _es_region_detail(
    client: Elasticsearch,
    code: str,
    ano: Optional[int],
    q: Optional[str],
    cpv: Optional[str],
    top_n: int,
    contracts_size: int,
) -> Dict[str, Any]:
    """Ficha de uma província/NUTS espanhola: órgãos, empresas, analíticas e contratos.

    Uma só pesquisa (incluindo os maiores contratos em `top_hits`) para que a
    pesquisa da janela filtre métricas, entidades e contratos ao mesmo tempo.
    """
    value_source = _contratos_es_value_source("valor_adjudicado")
    query = _build_contratos_es_query(nuts=code, ano=ano, cpv_code=cpv)
    if q:
        query = _with_required(query, _iberia_text_query(q, _IBERIA_TEXT_FIELDS_ES))

    def with_value(agg: Dict[str, Any]) -> Dict[str, Any]:
        return {**agg, "aggs": {"total_value": {"sum": value_source}}}

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "total_value": {"sum": value_source},
            "avg_value": {"avg": value_source},
            "max_value": {"max": value_source},
            "by_year": {
                "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_organos": {
                "terms": {"field": "organo_id", "size": top_n, "order": {"total_value": "desc"}},
                "aggs": {
                    "total_value": {"sum": value_source},
                    "name": {"top_hits": {"size": 1, "_source": ["organo_nombre", "organo_ciudad"]}},
                },
            },
            "top_adjudicatarios": {
                "terms": {
                    "field": "adjudicatario_nif",
                    "size": top_n,
                    "order": {"total_value": "desc"},
                },
                "aggs": {
                    "total_value": {"sum": value_source},
                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatario_nombre"]}},
                },
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_n, "order": {"total_value": "desc"}},
                        "aggs": {
                            "nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}},
                            "total_value": {"reverse_nested": {}, "aggs": {"value": {"sum": value_source}}},
                        },
                    }
                },
            },
            "procedure_types": with_value({
                "terms": {"field": "procedimiento_label", "size": 10, "missing": "N/A"},
            }),
            "contract_types": with_value({
                "terms": {"field": "tipo_contrato_label", "size": 10, "missing": "N/A"},
            }),
            "by_value_range": {
                "histogram": {"script": value_source["script"], "interval": 1000000, "min_doc_count": 1}
            },
            "organos": {"cardinality": {"field": "organo_id", "precision_threshold": 4000}},
            "adjudicatarios": {"cardinality": {"field": "adjudicatario_nif", "precision_threshold": 40000}},
            "top_contracts": {
                "top_hits": {
                    "size": contracts_size,
                    "sort": [
                        {"valor_adjudicado": {"order": "desc", "missing": "_last", "unmapped_type": "float"}}
                    ],
                    "_source": [
                        "objeto",
                        "descripcion",
                        "organo_nombre",
                        "adjudicatario_nombre",
                        "valor_adjudicado",
                        "valor_base",
                        "ano",
                        "fecha_adjudicacion",
                        "fecha_publicacion",
                        "id_expediente",
                    ],
                }
            },
        },
    }

    resp = client.search(index=CONTRATOS_ES_INDEX, body=body)
    aggs = resp.get("aggregations", {}) or {}

    def agg_value(bucket: Dict[str, Any]) -> float:
        raw = (bucket or {}).get("total_value", {})
        value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(value, dict):  # reverse_nested/sum encaixado
            value = value.get("value")
        return round(float(value or 0.0), 2)

    def rows(agg_name: str, label_field: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for bucket in (aggs.get(agg_name, {}) or {}).get("buckets", []):
            row = {"key": str(bucket.get("key")), "count": bucket.get("doc_count", 0), "total_value": agg_value(bucket)}
            if label_field:
                row["description"] = row["key"]
            out.append(row)
        return out

    cpv_rows = []
    for bucket in (aggs.get("top_cpv", {}) or {}).get("codes", {}).get("buckets", []):
        cpv_rows.append({
            "key": str(bucket.get("key")),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": _top_hit_cpv_es_name(bucket.get("nombre"), bucket.get("key")),
        })

    value_ranges = []
    for bucket in (aggs.get("by_value_range", {}) or {}).get("buckets", []):
        start = bucket.get("key")
        if start is None or start < 0 or len(value_ranges) >= 12:
            continue
        value_ranges.append({
            "key": str(int(start)),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": f"{int(start):,} – {int(start) + 1000000:,} €".replace(",", " "),
        })

    top_value = float(aggs.get("total_value", {}).get("value") or 0.0)

    def entity_rows(agg_name: str, name_field: str) -> List[Dict[str, Any]]:
        """Linhas de entidades a partir de um `terms` por identificador (DIR3/NIF).

        A chave do bucket é o identificador da entidade e o nome vem dos
        `top_hits` — é o que permite abrir a ficha (dossiê ou contratos) da linha.
        """
        out = []
        for bucket in (aggs.get(agg_name, {}) or {}).get("buckets", []):
            value = agg_value(bucket)
            count = bucket.get("doc_count", 0)
            identifier = str(bucket.get("key") or "")
            name = identifier
            hits = ((bucket.get("name") or {}).get("hits") or {}).get("hits") or []
            if hits:
                source = hits[0].get("_source") or {}
                name = str(source.get(name_field) or name)
            out.append({
                "nif": identifier or None,
                "name": _unescape_label(name),
                "count": count,
                "total_value": value,
                "avg_value": round(value / count, 2) if count else None,
                "share": round(value / top_value, 4) if top_value > 0 else None,
            })
        return out

    contract_rows = []
    for hit in ((aggs.get("top_contracts", {}) or {}).get("hits", {}) or {}).get("hits", []):
        source = hit.get("_source") or {}
        value = source.get("valor_adjudicado")
        contract_rows.append({
            "doc_id": hit.get("_id") or source.get("id_expediente"),
            "title": source.get("objeto") or source.get("descripcion") or "",
            "awarder": _unescape_label(source.get("organo_nombre")),
            "supplier": _unescape_label(source.get("adjudicatario_nombre")),
            "value": value if value is not None else source.get("valor_base"),
            "ano": source.get("ano"),
            "date": source.get("fecha_adjudicacion") or source.get("fecha_publicacion"),
        })

    return {
        "pais": "ES",
        "code": code,
        "ano": ano,
        "filters": {"q": q or None, "cpv": cpv or None},
        "totals": {
            "contracts": resp.get("hits", {}).get("total", {}).get("value", 0),
            "value": round(top_value, 2),
            "avg": round(float(aggs.get("avg_value", {}).get("value") or 0.0), 2) or None,
            "max": round(float(aggs.get("max_value", {}).get("value") or 0.0), 2) or None,
            "awarders": int((aggs.get("organos", {}) or {}).get("value") or 0),
            "suppliers": int((aggs.get("adjudicatarios", {}) or {}).get("value") or 0),
        },
        "by_year": rows("by_year"),
        "by_cpv": cpv_rows,
        "by_procedure": rows("procedure_types", label_field="key"),
        "by_contract_type": rows("contract_types", label_field="key"),
        "by_value_range": value_ranges,
        "awarders": entity_rows("top_organos", "organo_nombre"),
        "suppliers": entity_rows("top_adjudicatarios", "adjudicatario_nombre"),
        "contracts": contract_rows,
        "error": None,
    }


def get_contract_region_detail(
    pais: str,
    code: str,
    ano: Optional[int] = None,
    q: Optional[str] = None,
    cpv: Optional[str] = None,
    top_n: int = 12,
    contracts_size: int = 20,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Contratos, entidades (adjudicantes e adjudicatárias) e métricas de uma região.

    `pais="PT"` espera o **distrito** de execução («Bragança»); `pais="ES"` espera o
    **código NUTS** («ES300»). Alimenta a janela aberta no menu de contexto do mapa,
    onde `q` (texto) e `cpv` filtram métricas, entidades e contratos ao mesmo tempo.
    """
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        if (pais or "").strip().upper() == "ES":
            return _es_region_detail(client, code, ano, q, cpv, top_n, contracts_size)
        return _pt_region_detail(client, code, ano, q, cpv, top_n, contracts_size)
    except Exception as exc:  # pragma: no cover - dependente do cluster
        return {"error": str(exc)}


def _match_pair_query(nif: Optional[str] = None, counterparty_nif: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns nested must query for adjudicante/adjudicatario pair when both provided."""
    if nif and counterparty_nif:
        return {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        }
    return None


def get_contract_relationships(
    limit: int = 1000,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói relações adjudicante -> adjudicatário a partir dos contratos recentes."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "relations": []}
    filters: List[Dict[str, Any]] = []
    if region:
        filters.append(_region_filter(region))
    pair_query = _match_pair_query(nif, counterparty_nif)
    if pair_query:
        filters.append(pair_query)
    elif nif:
        # Include any contract where this NIF appears (adjudicante or adjudicatario)
        filters.append({
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        })
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": limit,
                "_source": ["adjudicantes.parsed", "adjudicatarios.parsed", "precoContratual", "Ano"],
                "query": query,
                "sort": [{"Ano": {"order": "desc", "unmapped_type": "integer"}}],
            },
        )
        pairs: Dict[str, Dict[str, Any]] = {}
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            buyers = source.get("adjudicantes", {}).get("parsed", [])
            suppliers = source.get("adjudicatarios", {}).get("parsed", [])
            value = source.get("precoContratual") or 0
            for buyer in buyers:
                for supplier in suppliers:
                    buyer_id = buyer.get("nif") or buyer.get("nome")
                    supplier_id = supplier.get("nif") or supplier.get("nome")
                    if not buyer_id or not supplier_id:
                        continue
                    # Apply role filter after the fact when only one NIF provided
                    if nif and not pair_query:
                        if role == "adjudicante" and buyer_id != nif:
                            continue
                        if role == "adjudicatario" and supplier_id != nif:
                            continue
                    key = f"{buyer_id}|{supplier_id}"
                    pair = pairs.setdefault(key, {
                        "source": buyer_id, "source_name": buyer.get("nome") or buyer_id,
                        "target": supplier_id, "target_name": supplier.get("nome") or supplier_id,
                        "count": 0, "total_value": 0.0,
                    })
                    pair["count"] += 1
                    pair["total_value"] += value
        relations = sorted(pairs.values(), key=lambda item: item["total_value"], reverse=True)[:100]
        for relation in relations:
            relation["total_value"] = round(relation["total_value"], 2)
        return {"relations": relations}
    except Exception as exc:
        return {"error": str(exc), "relations": []}


def get_contract_network(
    limit: int = 500,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve nós e ligações para uma visualização de rede de entidades."""
    result = get_contract_relationships(limit=limit, region=region, nif=nif, role=role, es=es)
    if result.get("error"):
        return result
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []
    for relation in result.get("relations", []):
        for node_id, name, node_type in (
            (relation["source"], relation["source_name"], "adjudicante"),
            (relation["target"], relation["target_name"], "adjudicatario"),
        ):
            nodes.setdefault(node_id, {"id": node_id, "label": name, "type": node_type})
        edges.append({"source": relation["source"], "target": relation["target"], "count": relation["count"], "value": relation["total_value"]})
    return {"nodes": list(nodes.values()), "edges": edges}


# --- Marcas INPI (por entidade) e firmas RNPC (Pesquisa de Nomes Existentes) ---

def _enrich_docs_with_company(
    docs: List[Dict[str, Any]],
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Acrescenta company_nif/company_name a cada documento antes de indexar."""
    enriched = []
    for doc in docs:
        item = dict(doc)
        if company_nif:
            item["company_nif"] = str(company_nif)
        if company_name:
            item["company_name"] = company_name
        enriched.append(item)
    return enriched


def _bulk_index_docs(
    index: str,
    docs: List[Dict[str, Any]],
    id_field: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos num índice, usando id_field para o _id (idempotente)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    if not docs:
        return {"index": index, "indexed_count": 0, "total": 0}

    actions = []
    for doc in docs:
        doc_id = doc.get(id_field)
        action: Dict[str, Any] = {"_index": index, "_source": doc}
        if doc_id not in (None, ""):
            action["_id"] = f"{index}:{doc_id}"
        actions.append(action)

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)
        error_count = len(errors) if isinstance(errors, list) else 0
        # Elasticsearch é near-real-time: refrescar garante que os dados ficam
        # imediatamente visíveis na ficha da empresa após o enriquecimento.
        try:
            client.indices.refresh(index=index)
        except Exception:
            pass
        return {
            "index": index,
            "indexed_count": success,
            "errors": error_count,
            "total": len(docs),
            "error_details": [str(e)[:300] for e in errors[:5]] if error_count else [],
        }
    except Exception as exc:
        return {"index": index, "error": str(exc), "indexed_count": 0, "total": len(docs)}


def _delete_stale_company_docs(
    index: str,
    company_nif: str,
    keep_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove documentos de uma empresa que já não constam do resultado atual.

    Evita acumular registos obsoletos quando a ficha é reenriquecida com um
    conjunto de resultados diferente (ex.: marcas entretanto expiradas).
    """
    return _delete_stale_docs(index, "company_nif", company_nif, keep_ids, es=es)


def index_company_trademarks(
    company_nif: Optional[str],
    company_name: str,
    trademarks: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as marcas INPI de uma empresa no índice TRADEMARKS_INDEX."""
    docs = _enrich_docs_with_company(trademarks, company_nif=company_nif, company_name=company_name)
    result = _bulk_index_docs(TRADEMARKS_INDEX, docs, id_field="nord", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{TRADEMARKS_INDEX}:{d.get('nord')}" for d in docs if d.get("nord") is not None]
        result["deleted_stale"] = _delete_stale_company_docs(TRADEMARKS_INDEX, str(company_nif), keep_ids, es=es)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result


def index_company_firmas(
    company_nif: Optional[str],
    company_name: str,
    firmas: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa firmas/nomes comerciais (RNPC/PNS) de uma empresa no índice FIRMAS_INDEX."""
    docs = _enrich_docs_with_company(firmas, company_nif=company_nif, company_name=company_name)
    # Usar NIPC quando existe; caso contrário o nome pesquisado + nome da firma.
    for doc in docs:
        doc.setdefault("_doc_key", doc.get("nipc") or f"{doc.get('search_query', '')}|{doc.get('nome', '')}")
    for doc in docs:
        doc["_source_id"] = doc.pop("_doc_key", None)
    result = _bulk_index_docs(FIRMAS_INDEX, docs, id_field="_source_id", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{FIRMAS_INDEX}:{d.get('_source_id')}" for d in docs if d.get("_source_id")]
        result["deleted_stale"] = _delete_stale_company_docs(FIRMAS_INDEX, str(company_nif), keep_ids, es=es)
    for doc in docs:
        doc.pop("_source_id", None)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result


# --- Construtor genérico de grafos de contratos ---------------------------------
#
# Cada dimensão descreve uma forma de agrupar contratos em nós. O construtor
# agrega uma amostra de contratos (por valor ou por data) em nós/arestas,
# devolvendo sempre `count` e `total_value`/`value` para a UI poder alternar
# entre a métrica de contratos e a métrica de valor sem novo pedido.

GRAPH_DIMENSIONS: Dict[str, Dict[str, str]] = {
    "adjudicante": {"label": "Entidade adjudicante", "type": "entidade"},
    "adjudicatario": {"label": "Entidade adjudicatária", "type": "entidade"},
    "entidade": {"label": "Entidade (qualquer papel)", "type": "entidade"},
    "concorrente": {"label": "Concorrente", "type": "concorrente"},
    "regiao": {"label": "Região (NUTS)", "type": "regiao"},
    "local_execucao": {"label": "Local de execução", "type": "regiao"},
    "cpv_divisao": {"label": "CPV — divisão (2 dígitos)", "type": "cpv"},
    "cpv_classe": {"label": "CPV — classe (4 dígitos)", "type": "cpv"},
    "procedimento": {"label": "Tipo de procedimento", "type": "processo"},
    "tipo_contrato": {"label": "Tipo de contrato", "type": "processo"},
    "pme": {"label": "Adjudicatário PME", "type": "processo"},
    "ano": {"label": "Ano", "type": "tempo"},
}

_GRAPH_SOURCE_FIELDS = [
    "idcontrato",
    "precoContratual",
    "PrecoTotalEfetivo",
    "Ano",
    "NUTs",
    "localExecucao",
    "tipoprocedimento",
    "tipoContrato",
    "adjudicatarioPMEs",
    "concorrentes",
    "cpv",
    "adjudicantes.parsed",
    "adjudicatarios.parsed",
]

# Separa "500233810-NOME, LDA., 502540249-OUTRA, LDA." em pares NIF/nome.
# O NIF pode vir mascarado como "--" em alguns contratos, daí a alternância.
_COMPETITOR_SPLIT_RE = re.compile(r",?\s*(?=(?:\d{9}|--)\s*-)")
_COMPETITOR_RE = re.compile(r"^(\d{9})\s*-\s*(.+)$")

# Máximo de valores considerados por contrato e por lado (evita explosão combinatória).
_GRAPH_MAX_VALUES_PER_DOC = 10

# Tetos de segurança do servidor. O cliente pode pedir "sem limite" (0), ficando
# sujeito a estes valores — devolvidos em `meta` para serem visíveis na UI.
GRAPH_MAX_SCAN = 400_000
GRAPH_MAX_NODES = 10_000
GRAPH_MAX_EDGES = 30_000
GRAPH_MAX_AGG_BUCKETS = 10_000
# Orçamento de buckets por pedido de agregação (o Elasticsearch falha acima de ~65 mil).
GRAPH_AGG_BUCKET_BUDGET = 20_000

# Dimensões agregáveis por termos (as restantes exigem varredura por documento,
# como `concorrente`, cujo campo textual tem vários valores por contrato).
_GRAPH_AGG_FIELDS: Dict[str, Dict[str, Optional[str]]] = {
    "adjudicante": {
        "nested": "adjudicantes.parsed",
        "field": "adjudicantes.parsed.nif",
        "label": "adjudicantes.parsed.nome",
    },
    "adjudicatario": {
        "nested": "adjudicatarios.parsed",
        "field": "adjudicatarios.parsed.nif",
        "label": "adjudicatarios.parsed.nome",
    },
    "regiao": {"nested": None, "field": "NUTs", "label": None, "missing": True},
    "local_execucao": {"nested": None, "field": "localExecucao", "label": None, "missing": True},
    "cpv_classe": {"nested": "cpv", "field": "cpv.code", "label": None},
    "cpv_divisao": {"nested": "cpv", "field": "cpv.code", "label": None},
    "procedimento": {"nested": None, "field": "tipoprocedimento", "label": None, "missing": True},
    "tipo_contrato": {"nested": None, "field": "tipoContrato", "label": None, "missing": True},
    "pme": {"nested": None, "field": "adjudicatarioPMEs", "label": None, "missing": True},
    "ano": {"nested": None, "field": "Ano", "label": None},
}


def _as_list(value: Any) -> List[Any]:
    """Normaliza valores que o Elasticsearch pode devolver como escalar ou lista."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _graph_parties(source: Dict[str, Any], key: str) -> List[Dict[str, str]]:
    """Extrai as entidades de `adjudicantes`/`adjudicatarios` (nested parsed)."""
    block = source.get(key) or {}
    if not isinstance(block, dict):
        return []
    out: List[Dict[str, str]] = []
    for party in _as_list(block.get("parsed")):
        if not isinstance(party, dict):
            continue
        nif = str(party.get("nif") or "").strip()
        nome = str(party.get("nome") or "").strip()
        if not nif and not nome:
            continue
        out.append({"id": nif or nome, "label": nome or nif})
    return out


def _graph_competitors(source: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extrai os concorrentes do campo textual `concorrentes`."""
    raw = source.get("concorrentes")
    if not raw:
        return []
    chunks: List[str] = []
    for part in _as_list(raw):
        chunks.extend(_COMPETITOR_SPLIT_RE.split(str(part)))
    out: List[Dict[str, str]] = []
    seen: set = set()
    for chunk in chunks:
        text = chunk.strip().strip(",").strip()
        if not text:
            continue
        # Alguns contratos mascaram o NIF como "--"; nesses casos só há nome.
        if text.startswith("--"):
            text = text.lstrip("-").strip()
        match = _COMPETITOR_RE.match(text)
        if match:
            nif, nome = match.group(1), match.group(2).strip()
        else:
            nif, nome = "", text
        node_id = nif or nome
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        out.append({"id": node_id, "label": nome or node_id})
    return out


def _dimension_values(source: Dict[str, Any], dimension: str) -> List[Dict[str, Any]]:
    """Devolve os valores de uma dimensão para um contrato: [{id, label, description?}]."""
    if dimension in ("adjudicante", "adjudicatario", "entidade"):
        values: List[Dict[str, Any]] = []
        if dimension in ("adjudicante", "entidade"):
            values.extend(_graph_parties(source, "adjudicantes"))
        if dimension in ("adjudicatario", "entidade"):
            values.extend(_graph_parties(source, "adjudicatarios"))
        return values

    if dimension == "concorrente":
        return _graph_competitors(source)

    if dimension == "regiao":
        out = []
        for nuts in _as_list(source.get("NUTs")):
            text = str(nuts or "").strip()
            if not text:
                continue
            code = text.split(" - ")[0].strip() or text
            out.append({"id": code, "label": text})
        # Contratos sem NUTs entram como "Não especificado" (em vez de desaparecerem).
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "local_execucao":
        out = []
        for local in _as_list(source.get("localExecucao")):
            text = str(local or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension in ("cpv_divisao", "cpv_classe"):
        size = 2 if dimension == "cpv_divisao" else 4
        out = []
        seen_codes: set = set()
        for entry in _as_list(source.get("cpv")):
            if not isinstance(entry, dict):
                continue
            digits = re.sub(r"\D", "", str(entry.get("code") or ""))
            if len(digits) < size:
                continue
            prefix = digits[:size]
            if prefix in seen_codes:
                continue
            seen_codes.add(prefix)
            description = str(entry.get("description") or "").strip()
            if dimension == "cpv_divisao":
                # A descrição ao nível da divisão não é representativa (varia por classe).
                out.append({"id": prefix, "label": f"CPV {prefix}"})
            else:
                out.append({
                    "id": prefix,
                    "label": f"{prefix} — {description}" if description else prefix,
                    "description": description,
                })
        return out

    if dimension == "ano":
        ano = source.get("Ano")
        return [{"id": str(ano), "label": str(ano)}] if ano not in (None, "") else []

    if dimension == "procedimento":
        out = []
        for value in _as_list(source.get("tipoprocedimento")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "tipo_contrato":
        out = []
        for value in _as_list(source.get("tipoContrato")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "pme":
        out = []
        for value in _as_list(source.get("adjudicatarioPMEs")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    return []


def _graph_add_node(
    nodes: Dict[str, Dict[str, Any]],
    descriptions: Dict[str, Dict[str, int]],
    dimension: str,
    item: Dict[str, Any],
    value: float,
) -> str:
    """Acumula um nó (contagem + valor) e devolve o seu id único."""
    node_id = f"{dimension}|{item['id']}"
    node = nodes.get(node_id)
    if node is None:
        node = nodes[node_id] = {
            "id": node_id,
            "key": item["id"],
            "label": item.get("label") or item["id"],
            "dimension": dimension,
            "type": GRAPH_DIMENSIONS[dimension]["type"],
            "role": GRAPH_DIMENSIONS[dimension]["label"],
            "count": 0,
            "total_value": 0.0,
        }
    node["count"] += 1
    node["total_value"] += value
    description = item.get("description")
    if description:
        bucket = descriptions.setdefault(node_id, {})
        bucket[description] = bucket.get(description, 0) + 1
    return node_id


def _graph_add_edge(
    edges: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    value: float,
    directed: bool,
) -> None:
    """Acumula uma aresta; em grafos não dirigidos os extremos são normalizados."""
    if not directed and target < source:
        source, target = target, source
    key = f"{source}->{target}"
    edge = edges.get(key)
    if edge is None:
        edge = edges[key] = {"source": source, "target": target, "count": 0, "value": 0.0}
    edge["count"] += 1
    edge["value"] += value


def _aggregate_dimension_buckets(
    client: Elasticsearch,
    query: Dict[str, Any],
    target: str,
    metric: str,
    size: int,
    with_description: bool,
) -> Optional[Dict[str, Any]]:
    """Agrega uma dimensão em termos (exato sobre todos os contratos filtrados)."""
    spec = _GRAPH_AGG_FIELDS.get(target)
    if not spec:
        return None

    field = spec["field"] or ""
    runtime: Optional[Dict[str, Any]] = None
    if spec["nested"] is None:
        resolved = _resolve_agg_target(client, field)
        field = resolved["field"]
        runtime = resolved.get("runtime")

    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    bucket_aggs: Dict[str, Any] = {}
    if spec["nested"]:
        bucket_aggs["valor"] = {
            "reverse_nested": {},
            "aggs": {"total": {"sum": {"field": "precoContratual"}}},
        }
    else:
        bucket_aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if spec["label"]:
        bucket_aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_description and spec["nested"] == "cpv":
        # `cpv.description` é texto (fielddata desativada): só é recolhido quando há
        # poucos buckets, para não devolver milhares de documentos.
        bucket_aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}

    terms_agg: Dict[str, Any] = {
        "terms": {"field": field, "size": size, "order": order},
        "aggs": bucket_aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo formam o grupo "Não especificado".
        terms_agg["terms"]["missing"] = UNSPECIFIED_LABEL
    agg_body: Dict[str, Any] = (
        {"nested": {"path": spec["nested"]}, "aggs": {"buckets": terms_agg}}
        if spec["nested"]
        else terms_agg
    )

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {"dim": agg_body, "total_value": {"sum": {"field": "precoContratual"}}},
    }
    if runtime:
        body["runtime_mappings"] = runtime

    resp = client.search(index=CONTRACTS_INDEX, body=body)
    node = resp["aggregations"]["dim"]
    if spec["nested"]:
        node = node["buckets"]
    total_block = resp.get("hits", {}).get("total") or {}
    return {
        "buckets": node.get("buckets", []),
        "other_doc_count": node.get("sum_other_doc_count", 0),
        "documents_matching": total_block.get("value", 0) if isinstance(total_block, dict) else 0,
        "documents_value": resp["aggregations"]["total_value"].get("value") or 0.0,
    }


def aggregate_graph_nodes(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension: str,
    metric: str,
    limit: int,
    max_buckets: int = GRAPH_MAX_AGG_BUCKETS,
) -> Optional[Dict[str, Any]]:
    """Grafo de um nível calculado por agregações: exato sobre TODOS os contratos.

    Devolve `None` quando a dimensão não é agregável (ex.: concorrentes), para o
    chamador fazer a varredura por documento.
    """
    targets = ["adjudicante", "adjudicatario"] if dimension == "entidade" else [dimension]
    if not targets or any(target not in _GRAPH_AGG_FIELDS for target in targets):
        return None

    requested = limit if limit else max_buckets
    size = max(10, min(requested * (2 if len(targets) > 1 else 1), max_buckets))
    with_description = size <= 400
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    aggregated: Dict[str, Dict[str, Any]] = {}
    other_doc_count = 0
    documents_matching = 0
    documents_value = 0.0

    for target in targets:
        result = _aggregate_dimension_buckets(client, query, target, metric, size, with_description)
        if result is None:
            return None
        other_doc_count += result["other_doc_count"]
        documents_matching = max(documents_matching, result["documents_matching"])
        documents_value = max(documents_value, result["documents_value"])

        for bucket in result["buckets"]:
            raw_key = str(bucket["key"])
            if not raw_key:
                if not spec.get("missing"):
                    continue
                raw_key = UNSPECIFIED_LABEL
            if raw_key == "N/A":
                continue
            label = raw_key
            description = ""
            rotulo = bucket.get("rotulo", {}).get("buckets") or []
            if rotulo:
                label = str(rotulo[0]["key"])
            if use_prefix:
                digits = re.sub(r"\D", "", raw_key)
                if len(digits) < prefix_size:
                    continue
                key = digits[:prefix_size]
                label = f"CPV {key}"
                samples = (bucket.get("amostra", {}).get("hits", {}).get("hits") or [])
                if samples:
                    for entry in _as_list((samples[0].get("_source") or {}).get("cpv")):
                        if not isinstance(entry, dict):
                            continue
                        code = re.sub(r"\D", "", str(entry.get("code") or ""))
                        if code.startswith(key):
                            description = str(entry.get("description") or "").strip()
                            if description:
                                break
            elif dimension == "regiao":
                key = raw_key.split(" - ")[0].strip() or raw_key
                label = raw_key
            elif dimension == "ano":
                key = raw_key
                label = raw_key
            else:
                key = raw_key

            value = bucket.get("valor")
            value = value.get("total", {}).get("value") if isinstance(value, dict) and "total" in value else value
            value = value.get("value") if isinstance(value, dict) else value
            entry = aggregated.get(key)
            if entry is None:
                entry = aggregated[key] = {
                    "id": f"{dimension}|{key}",
                    "key": key,
                    "label": label,
                    "dimension": dimension,
                    "type": GRAPH_DIMENSIONS[dimension]["type"],
                    "role": GRAPH_DIMENSIONS[dimension]["label"],
                    "count": 0,
                    "total_value": 0.0,
                }
            entry["count"] += int(bucket.get("doc_count") or 0)
            entry["total_value"] += float(value or 0)
            if use_prefix and description and " — " not in entry["label"]:
                entry["label"] = f"{key} — {description}"

    metric_key = "total_value" if metric == "valor" else "count"
    ordered = sorted(aggregated.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept = ordered[:limit] if limit else ordered
    kept_value = sum(node["total_value"] for node in kept)
    kept_count = sum(node["count"] for node in kept)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered) > len(kept):
        notes.append(f"Mostrados {len(kept)} de {len(ordered)} nós agregados.")
    if other_doc_count:
        notes.append("Existem agrupamentos além dos apresentados (limite de buckets do Elasticsearch).")
    if use_prefix and not with_description and len(kept) > 400:
        notes.append("Descrições CPV omitidas acima de 400 nós.")

    return {
        "nodes": kept,
        "edges": [],
        "meta": {
            "dimension_a": dimension,
            "dimension_b": None,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered) <= len(kept) and other_doc_count == 0,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(documents_value, 2),
            "nodes_total": len(ordered),
            "edges_total": 0,
            "kept_nodes": len(kept),
            "kept_edges": 0,
            "omitted_edges": 0,
            "coverage_value_share": round(kept_value / documents_value, 4) if documents_value else None,
            "coverage_count_share": None if not documents_matching else round(kept_count / max(documents_matching, 1), 4),
            "directed": False,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": max_buckets,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }


def _resolve_dimension_spec(client: Elasticsearch, dimension: str) -> Optional[Dict[str, Any]]:
    """Resolve o campo agregável de uma dimensão (campo/subcampo/runtime) ou None."""
    spec = _GRAPH_AGG_FIELDS.get(dimension)
    if not spec:
        return None
    resolved = dict(spec)
    if spec["nested"] is None:
        target = _resolve_agg_target(client, spec["field"] or "")
        resolved["field"] = target["field"]
        resolved["runtime"] = target.get("runtime")
    return resolved


def _terms_block(spec: Dict[str, Any], metric: str, size: int, with_label: bool) -> Dict[str, Any]:
    """Bloco de agregação de termos com contagem de contratos e soma de valor."""
    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    aggs: Dict[str, Any] = {}
    if spec["nested"]:
        aggs["valor"] = {"reverse_nested": {}, "aggs": {"total": {"sum": {"field": "precoContratual"}}}}
    else:
        aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if with_label and spec.get("label"):
        aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_label and spec.get("nested") == "cpv" and size <= 400:
        # `cpv.description` é texto (fielddata desativada): recolhido só com poucos buckets.
        aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}
    block: Dict[str, Any] = {
        "terms": {"field": spec["field"], "size": size, "order": order},
        "aggs": aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo passam a formar o grupo "Não especificado".
        block["terms"]["missing"] = UNSPECIFIED_LABEL
    if spec["nested"]:
        return {"nested": {"path": spec["nested"]}, "aggs": {"buckets": block}}
    return block


def _graph_key_for(dimension: str, raw_key: str) -> Optional[str]:
    """Normaliza a chave de um valor agregado (prefixo CPV, código NUTS) — igual em nós e arestas."""
    if dimension in ("cpv_classe", "cpv_divisao"):
        size = 4 if dimension == "cpv_classe" else 2
        digits = re.sub(r"\D", "", raw_key)
        return digits[:size] if len(digits) >= size else None
    if dimension == "regiao":
        return raw_key.split(" - ")[0].strip() or raw_key
    return raw_key


def _descriptions_from_bucket(bucket: Dict[str, Any], key: str) -> str:
    """Extrai a descrição CPV (top_hits) correspondente ao prefixo do bucket."""
    samples = bucket.get("amostra", {}).get("hits", {}).get("hits") or []
    for sample in samples:
        for entry in _as_list((sample.get("_source") or {}).get("cpv")):
            if not isinstance(entry, dict):
                continue
            code = re.sub(r"\D", "", str(entry.get("code") or ""))
            if code.startswith(key):
                description = str(entry.get("description") or "").strip()
                if description:
                    return description
    return ""


def _extract_buckets(node: Any) -> List[Dict[str, Any]]:
    """Extrai a lista de buckets de um bloco de termos (aceita wrappers de `nested`)."""
    for _hop in range(3):
        if isinstance(node, dict) and isinstance(node.get("buckets"), dict):
            node = node["buckets"]
            continue
        break
    if isinstance(node, dict):
        node = node.get("buckets")
    return node if isinstance(node, list) else []


def _bucket_value(bucket: Dict[str, Any]) -> float:
    value = bucket.get("valor")
    if isinstance(value, dict) and "total" in value and isinstance(value["total"], dict):
        value = value["total"].get("value")
    elif isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _nodes_from_buckets(
    block: Dict[str, Any],
    dimension: str,
    spec: Dict[str, Any],
    total: Dict[str, Dict[str, Any]],
) -> None:
    """Acumula buckets de termos no dicionário de nós (chave, rótulo, contagem, valor)."""
    buckets = block.get("buckets") if spec.get("nested") else block
    buckets = _extract_buckets(buckets)
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    for bucket in buckets:
        raw_key = str(bucket.get("key"))
        if raw_key == "N/A":
            continue
        if not raw_key:
            # Campo presente mas vazio: conta como "Não especificado".
            if not spec.get("missing"):
                continue
            raw_key = UNSPECIFIED_LABEL
        key = _graph_key_for(dimension, raw_key)
        if not key:
            continue
        label = raw_key
        rotulo = (bucket.get("rotulo") or {}).get("buckets") or []
        if rotulo:
            label = str(rotulo[0]["key"])
        if use_prefix:
            label = f"CPV {key}" if dimension == "cpv_divisao" else key
            description = _descriptions_from_bucket(bucket, key)
            if description and dimension == "cpv_classe":
                label = f"{key} — {description}"
        elif dimension == "regiao":
            label = raw_key

        node = total.get(key)
        if node is None:
            node = total[key] = {
                "id": f"{dimension}|{key}",
                "key": key,
                "label": label,
                "dimension": dimension,
                "type": GRAPH_DIMENSIONS[dimension]["type"],
                "role": GRAPH_DIMENSIONS[dimension]["label"],
                "count": 0,
                "total_value": 0.0,
            }
        node["count"] += int(bucket.get("doc_count") or 0)
        node["total_value"] += _bucket_value(bucket)


def aggregate_graph_edges(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension_a: str,
    dimension_b: str,
    metric: str,
    limit: int,
    edge_limit: int,
) -> Optional[Dict[str, Any]]:
    """Grafo de dois níveis exato (todos os contratos) por agregações.

    Corre três agregações no mesmo pedido: nós do lado A, nós do lado B (ambas
    exatas) e os pares A→B. Devolve `None` quando alguma dimensão não é agregável.
    """
    spec_a = _resolve_dimension_spec(client, dimension_a)
    spec_b = _resolve_dimension_spec(client, dimension_b)
    if not spec_a or not spec_b:
        return None

    node_size = min(limit or GRAPH_MAX_AGG_BUCKETS, GRAPH_MAX_AGG_BUCKETS)
    pair_budget = max(5, GRAPH_AGG_BUCKET_BUDGET // max(node_size, 1))
    pair_size = max(5, min(edge_limit or 200, pair_budget))

    edges_agg = _terms_block(spec_a, metric, node_size, with_label=False)
    inner = _terms_block(spec_b, metric, pair_size, with_label=False)
    if spec_a["nested"]:
        # `reverse_nested` volta ao documento pai: é aí que a dimensão B tem de viver.
        edges_agg["aggs"]["buckets"]["aggs"]["valor"]["aggs"]["links"] = inner
    else:
        edges_agg["aggs"]["links"] = inner

    runtime_mappings: Dict[str, Any] = {}
    for spec in (spec_a, spec_b):
        if spec.get("runtime"):
            runtime_mappings.update(spec["runtime"])

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "nodes_a": _terms_block(spec_a, metric, node_size, with_label=True),
            "nodes_b": _terms_block(spec_b, metric, node_size, with_label=True),
            "edges": edges_agg,
            "total_value": {"sum": {"field": "precoContratual"}},
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception:
        # Por exemplo, acima do teto de buckets: o chamador cai para a varredura.
        return None
    aggregations = resp["aggregations"]

    nodes_a: Dict[str, Dict[str, Any]] = {}
    nodes_b: Dict[str, Dict[str, Any]] = {}
    _nodes_from_buckets(aggregations["nodes_a"], dimension_a, spec_a, nodes_a)
    _nodes_from_buckets(aggregations["nodes_b"], dimension_b, spec_b, nodes_b)

    metric_key = "total_value" if metric == "valor" else "count"
    ordered_a = sorted(nodes_a.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    ordered_b = sorted(nodes_b.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept_a = ordered_a[:limit] if limit else ordered_a
    kept_b = ordered_b[:limit] if limit else ordered_b
    kept_ids = {node["id"] for node in kept_a} | {node["id"] for node in kept_b}

    edges: Dict[str, Dict[str, Any]] = {}
    edges_block = aggregations["edges"]
    a_buckets = _extract_buckets(edges_block.get("buckets") if spec_a["nested"] else edges_block)
    for a_bucket in a_buckets:
        a_key = _graph_key_for(dimension_a, str(a_bucket.get("key")))
        if not a_key:
            continue
        a_id = f"{dimension_a}|{a_key}"
        if a_id not in kept_ids:
            continue
        links = a_bucket["valor"].get("links") if spec_a["nested"] else a_bucket.get("links")
        if not links:
            continue
        for b_bucket in _extract_buckets(links):
            b_key = _graph_key_for(dimension_b, str(b_bucket.get("key")))
            if not b_key:
                continue
            b_id = f"{dimension_b}|{b_key}"
            if b_id not in kept_ids:
                continue
            key = f"{a_id}->{b_id}"
            edge = edges.get(key)
            if edge is None:
                edge = edges[key] = {"source": a_id, "target": b_id, "count": 0, "value": 0.0}
            edge["count"] += int(b_bucket.get("doc_count") or 0)
            edge["value"] += _bucket_value(b_bucket)

    edge_metric = "value" if metric == "valor" else "count"
    ordered_edges = sorted(edges.values(), key=lambda edge: edge.get(edge_metric) or 0, reverse=True)
    dropped_edges = max(0, len(ordered_edges) - edge_limit) if edge_limit else 0
    kept_edges = ordered_edges[:edge_limit] if edge_limit else ordered_edges

    total_value = aggregations["total_value"].get("value") or 0.0
    total_block = resp.get("hits", {}).get("total") or {}
    documents_matching = total_block.get("value", 0) if isinstance(total_block, dict) else 0
    kept_value = sum(node["total_value"] for node in kept_a)
    kept_count = sum(node["count"] for node in kept_a)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered_a) > len(kept_a) or len(ordered_b) > len(kept_b):
        notes.append(
            f"Mostrados {len(kept_a)} nós de {len(ordered_a)} no lado A e "
            f"{len(kept_b)} de {len(ordered_b)} no lado B."
        )
    if pair_size < (edge_limit or 200):
        notes.append(
            f"Cada nó mostra até {pair_size} ligações por pedido de agregação "
            "(aumente as arestas ou reduza os nós para ver pares adicionais)."
        )
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite (aumente 'arestas' ou reduza os nós).")

    return {
        "nodes": kept_a + kept_b,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered_a) <= len(kept_a) and len(ordered_b) <= len(kept_b) and not dropped_edges,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(total_value, 2),
            "nodes_total": len(ordered_a) + len(ordered_b),
            "edges_total": len(ordered_edges),
            "kept_nodes": len(kept_a) + len(kept_b),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_value / total_value, 4) if total_value else None,
            "coverage_count_share": round(kept_count / max(documents_matching, 1), 4) if documents_matching else None,
            "directed": True,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": GRAPH_MAX_AGG_BUCKETS,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }


def build_contract_graph(
    dimension_a: str,
    dimension_b: Optional[str] = None,
    metric: str = "valor",
    mode: str = "auto",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    limit: int = 60,
    edge_limit: int = 400,
    sample: int = 3000,
    sample_order: str = "valor",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói um grafo de contratos segundo duas dimensões (nós e arestas).

    - `dimension_b` igual a `dimension_a` → rede de co-ocorrência (ex.: concorrentes
      que participam nos mesmos contratos).
    - `dimension_b` nulo → apenas nós (para treemaps, rankings e mapas).
    - `metric` decide que nós/arestas são mantidos nos limites pedidos; os dois
      valores (contratos e valor) são sempre devolvidos.
    - `mode`:
      - `exato`: sem amostragem. Com uma só dimensão usa agregações do Elasticsearch
        (todos os contratos que correspondem aos filtros); com arestas percorre todos
        os contratos até ao teto do servidor.
      - `amostra`: percorre apenas `sample` contratos (ordem `sample_order`).
      - `auto` (por omissão): `exato` quando não há dimensão B.
    - `limit`, `edge_limit` e `sample` aceitam 0 = "todos" (sujeito aos tetos
      `GRAPH_MAX_NODES`, `GRAPH_MAX_EDGES` e `GRAPH_MAX_SCAN`, devolvidos em `meta`).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    if dimension_a not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_a}", "nodes": [], "edges": []}
    if dimension_b and dimension_b not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_b}", "nodes": [], "edges": []}

    dimension_b = dimension_b or None
    metric = metric if metric in ("valor", "contratos") else "valor"
    mode = mode if mode in ("auto", "exato", "amostra") else "auto"
    same_dimension = dimension_b == dimension_a

    query = _build_contract_query(
        q=q,
        year=year,
        region=region,
        cpv_code=cpv_code,
        min_price=min_value,
        max_price=max_value,
    )

    # Caminho exato (sem amostragem) para grafos de um só nível.
    if mode in ("auto", "exato") and not dimension_b:
        exact = aggregate_graph_nodes(
            client,
            query,
            dimension_a,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
        )
        if exact is not None:
            exact["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact

    # Caminho exato com arestas: agregações de dois níveis (todos os contratos).
    if mode in ("auto", "exato") and dimension_b and not same_dimension:
        exact_edges = aggregate_graph_edges(
            client,
            query,
            dimension_a,
            dimension_b,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
            edge_limit=0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES)),
        )
        if exact_edges is not None:
            exact_edges["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact_edges

    all_documents = int(sample) <= 0
    scan_ceiling = GRAPH_MAX_SCAN
    sample = scan_ceiling if all_documents else max(100, min(int(sample), scan_ceiling))
    limit = 0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES))
    edge_limit = 0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES))
    page_size = 5000 if all_documents else min(1000, sample)

    if sample_order == "recentes":
        sort: List[Any] = [
            {"dataPublicacao": {"order": "desc", "unmapped_type": "date"}},
            {"idcontrato": {"order": "asc"}},
        ]
    else:
        sort = [
            {"precoContratual": {"order": "desc", "unmapped_type": "float"}},
            {"idcontrato": {"order": "asc"}},
        ]

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    descriptions: Dict[str, Dict[str, int]] = {}
    scanned = 0
    scanned_value = 0.0
    total_hits = 0
    scan_capped = False

    try:
        search_after: Optional[List[Any]] = None
        while all_documents or scanned < sample:
            remaining = scan_ceiling - scanned
            if remaining <= 0:
                scan_capped = True
                break
            page = min(page_size, remaining)
            body: Dict[str, Any] = {
                "size": page,
                "query": query,
                "sort": sort,
                "_source": _GRAPH_SOURCE_FIELDS,
                "track_total_hits": True,
            }
            if search_after:
                body["search_after"] = search_after
            resp = client.search(index=CONTRACTS_INDEX, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            total_block = resp.get("hits", {}).get("total") or {}
            total_hits = total_block.get("value", total_hits) if isinstance(total_block, dict) else total_hits
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source") or {}
                scanned += 1
                raw_value = source.get("precoContratual") or source.get("PrecoTotalEfetivo") or 0
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = 0.0
                scanned_value += value

                values_a = _dimension_values(source, dimension_a)
                if not values_a:
                    continue
                ids_a = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_a, item, value)
                        for item in values_a[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                if not dimension_b:
                    continue
                if same_dimension:
                    # Co-ocorrência: liga todos os pares presentes no mesmo contrato.
                    for index, left in enumerate(ids_a):
                        for right in ids_a[index + 1:]:
                            _graph_add_edge(edges, left, right, value, directed=False)
                    continue
                values_b = _dimension_values(source, dimension_b)
                ids_b = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_b, item, value)
                        for item in values_b[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                for left in ids_a:
                    for right in ids_b:
                        _graph_add_edge(edges, left, right, value, directed=True)

            if len(hits) < page:
                break
            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

    # Rótulo descritivo mais frequente (ex.: classe CPV "4521 — Construção de edifícios").
    for node_id, bucket in descriptions.items():
        node = nodes.get(node_id)
        if not node or not bucket:
            continue
        best = max(bucket.items(), key=lambda kv: kv[1])[0]
        if best:
            node["label"] = f"{node['key']} — {best}"

    metric_key = "total_value" if metric == "valor" else "count"
    scored_nodes = sorted(nodes.values(), key=lambda node: (node.get(metric_key) or 0), reverse=True)
    kept_nodes = scored_nodes[:limit] if limit else scored_nodes
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [
        edge for edge in edges.values() if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    edge_metric = "value" if metric == "valor" else "count"
    kept_edges.sort(key=lambda edge: (edge.get(edge_metric) or 0), reverse=True)
    dropped_edges = max(0, len(kept_edges) - edge_limit) if edge_limit else 0
    if edge_limit:
        kept_edges = kept_edges[:edge_limit]

    # Cobertura: independentemente do lado, usa os nós do lado A para reportar
    # quanto do valor/contratos ficou representado.
    side_a = [node for node in nodes.values() if node["dimension"] == dimension_a]
    side_a_total_count = sum(node["count"] for node in side_a) or 0
    side_a_total_value = sum(node["total_value"] for node in side_a) or 0.0
    kept_a = [node for node in kept_nodes if node["dimension"] == dimension_a]
    kept_a_count = sum(node["count"] for node in kept_a)
    kept_a_value = sum(node["total_value"] for node in kept_a)

    sampled = scanned < total_hits or scan_capped
    complete = not sampled and len(kept_nodes) == len(nodes) and not dropped_edges

    notes = []
    if scan_capped:
        notes.append(
            f"Varredura limitada a {scanned} de {total_hits} contratos (teto do servidor: "
            f"{GRAPH_MAX_SCAN}). Aplique filtros (ano, região, valor mínimo) para reduzir o conjunto."
        )
    elif sampled:
        notes.append(
            f"Amostra de {scanned} de {total_hits} contratos "
            f"({'maior valor' if sample_order == 'valor' else 'mais recentes'}). "
            "Use o modo exato ou 'todos os contratos' para valores completos."
        )
    else:
        notes.append(f"Todos os {total_hits} contratos do filtro foram analisados (sem amostragem).")
    if len(nodes) > len(kept_nodes):
        notes.append(f"Mostrados {len(kept_nodes)} de {len(nodes)} nós agregados.")
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite.")
    if same_dimension:
        notes.append("Arestas representam co-ocorrência no mesmo contrato; o valor é o total desses contratos.")

    return {
        "nodes": kept_nodes,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "varredura-total" if all_documents else "amostra",
            "complete": complete,
            "scan_capped": scan_capped,
            "sample_order": sample_order,
            "sample_limit": None if all_documents else sample,
            "documents_scanned": scanned,
            "documents_matching": total_hits,
            "scanned_value": round(scanned_value, 2),
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(kept_nodes),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_a_value / side_a_total_value, 4) if side_a_total_value else None,
            "coverage_count_share": round(kept_a_count / side_a_total_count, 4) if side_a_total_count else None,
            "directed": bool(dimension_b) and not same_dimension,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
            },
            "notes": notes,
            "filters": {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            },
        },
    }


def get_company_trademarks(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    holder_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as marcas indexadas de uma empresa (por NIF, nome de empresa ou titular)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
    if company_name:
        should.append({"match_phrase": {"holder_name": company_name}})
        should.append({"match": {"company_name": company_name}})
    if holder_name:
        should.append({"match_phrase": {"holder_name": holder_name}})
    if q:
        should.append({"match": {"mark_name": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do titular primeiro (docs antigos ficam no fim), depois data.
                "sort": [
                    {"holder_similarity": {"order": "desc", "missing": "_last"}},
                    {"application_date": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def search_trademarks(
    q: Optional[str] = None,
    holder_name: Optional[str] = None,
    nice_class: Optional[str] = None,
    mark_type: Optional[str] = None,
    current_phase: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa global de marcas indexadas no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["mark_name^3", "holder_name^2", "process_number"],
                "operator": "and",
            }
        })
    if holder_name:
        must.append({"match_phrase": {"holder_name": holder_name}})
    if nice_class:
        filters.append({"term": {"nice_classes": nice_class}})
    if mark_type:
        filters.append({"term": {"mark_type": mark_type}})
    if current_phase:
        filters.append({"term": {"current_phase": current_phase}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [
                    {"application_date": {"order": "desc", "missing": "_last"}},
                    "_score",
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"], "relevance": hit.get("_score")} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def get_company_firmas(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as firmas/nomes comerciais indexados de uma empresa (RNPC/PNS)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
        should.append({"term": {"nipc": str(company_nif)}})
    if company_name:
        should.append({"match": {"nome": company_name}})
        should.append({"term": {"search_query": company_name}})
    if q:
        should.append({"match": {"nome": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do nome primeiro, depois o score de confundibilidade do RNPC.
                "sort": [
                    {"name_similarity": {"order": "desc", "missing": "_last"}},
                    {"score": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def search_firmas(
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    cae: Optional[str] = None,
    situacao: Optional[str] = None,
    min_score: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa firmas/nomes comerciais (RNPC) indexados no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({"match": {"nome": {"query": q, "operator": "and"}}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if cae:
        filters.append({"term": {"cae_principal": cae}})
    if situacao:
        filters.append({"term": {"situacao": situacao}})
    if min_score is not None:
        filters.append({"range": {"score": {"gte": min_score}}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [{"score": {"order": "desc", "missing": "_last"}}, "_score"],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


# --- Cadastro de entidades do portal base (finance_entities) ---

def index_entities(
    docs: Iterable[Dict[str, Any]],
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    refresh: bool = False,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa entidades normalizadas no índice ENTITIES_INDEX.

    Aceita qualquer iterável (por exemplo o gerador de ``iter_normalized_entities``),
    pelo que não é necessário carregar o ficheiro todo em memória. O ``_id`` é o NIF
    ou um hash do nome, garantindo reingestões idempotentes.
    """
    from api.entities_service import entity_doc_id

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    ensure_indices(client)

    indexed = 0
    errors = 0
    seen = 0
    buffer: List[Dict[str, Any]] = []

    try:
        for doc in docs:
            if max_records is not None and seen >= max_records:
                break
            seen += 1
            source = {k: v for k, v in doc.items() if not k.startswith("_")}
            source["ingested_at"] = _today()
            buffer.append({"_index": ENTITIES_INDEX, "_id": f"{ENTITIES_INDEX}:{entity_doc_id(doc)}", "_source": source})

            if len(buffer) >= chunk_size:
                success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
                indexed += success
                errors += len(errs) if isinstance(errs, list) else 0
                buffer = []

        if buffer:
            success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
            indexed += success
            errors += len(errs) if isinstance(errs, list) else 0

        if refresh:
            try:
                client.indices.refresh(index=ENTITIES_INDEX)
            except Exception:
                pass

        return {
            "index": ENTITIES_INDEX,
            "indexed_count": indexed,
            "total": seen,
            "errors": errors,
            "message": f"{indexed} entidades indexadas de {seen}",
        }
    except Exception as exc:
        return {"index": ENTITIES_INDEX, "error": str(exc), "indexed_count": indexed, "total": seen}


def search_entities(
    q: Optional[str] = None,
    country: Optional[str] = None,
    only_with_nif: Optional[bool] = None,
    min_contracts: Optional[int] = None,
    max_contracts: Optional[int] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    role: Optional[str] = "all",
    sort_by: Optional[str] = "total_value",
    sort_order: Optional[str] = "desc",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa o cadastro de entidades com filtros e ordenação.

    ``role`` permite restringir a entidades que aparecem como adjudicante
    (``totAdjudicante``), adjudicatário (``totAdjudicatario``) ou ambos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    text_query: Optional[Dict[str, Any]] = None

    if q:
        term = q.strip()
        if term:
            # Combina: NIF exato, nome exato (frase) e correspondência incremental
            # por prefixo (edge-ngram), para que "SONAE" encontre "SONAECOM".
            text_query = {
                "bool": {
                    "should": [
                        {"term": {"nif": term}},
                        {"match_phrase": {"name": {"query": term, "boost": 5}}},
                        {"multi_match": {"query": term, "fields": ["name^3"], "operator": "and", "boost": 3}},
                        {"match": {"name.autocomplete": {"query": term, "boost": 1}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
    if country:
        filters.append({"term": {"country": country}})
    if only_with_nif:
        filters.append({"term": {"has_nif": True}})
    if min_contracts is not None:
        filters.append({"range": {"contracts_count": {"gte": min_contracts}}})
    if max_contracts is not None:
        filters.append({"range": {"contracts_count": {"lte": max_contracts}}})
    if min_value is not None:
        filters.append({"range": {"total_value": {"gte": min_value}}})
    if max_value is not None:
        filters.append({"range": {"total_value": {"lte": max_value}}})
    if role == "adjudicante":
        filters.append({"range": {"as_adjudicante_count": {"gte": 1}}})
    elif role == "adjudicatario":
        filters.append({"range": {"as_adjudicatario_count": {"gte": 1}}})

    query: Dict[str, Any]
    if text_query or filters:
        query = {"bool": {}}
        if text_query:
            query["bool"]["must"] = [text_query]
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    allowed_sort = {
        "name", "contracts_count", "total_value", "as_adjudicante_value",
        "as_adjudicante_count", "as_adjudicatario_count",
    }
    sort_field = sort_by if sort_by in allowed_sort else "total_value"
    order = "asc" if (sort_order or "desc").lower() == "asc" else "desc"
    # Em empates ordena por nome para garantir paginação estável.
    sort_spec: List[Any] = [{sort_field: {"order": order}}, {"name.keyword": {"order": "asc"}}]

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": sort_spec,
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def get_entity_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Estatísticas agregadas do cadastro de entidades (totais, países, com/sem NIF)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "with_nif": {"filter": {"term": {"has_nif": True}}},
                    "without_nif": {"filter": {"term": {"has_nif": False}}},
                    "countries": {
                        "terms": {"field": "country", "size": 15, "order": {"_count": "desc"}},
                        "aggs": {"value": {"sum": {"field": "total_value"}}},
                    },
                    "total_value": {"sum": {"field": "total_value"}},
                    "total_contracts": {"sum": {"field": "contracts_count"}},
                    "as_adjudicante": {"filter": {"range": {"as_adjudicante_count": {"gte": 1}}}},
                    "as_adjudicatario": {"filter": {"range": {"as_adjudicatario_count": {"gte": 1}}}},
                },
            },
        )
        aggs = resp["aggregations"]
        countries = [
            {
                "country": b["key"],
                "count": b["doc_count"],
                "total_value": round(b.get("value", {}).get("value") or 0.0, 2),
            }
            for b in aggs.get("countries", {}).get("buckets", [])
        ]
        return {
            "total": resp["hits"]["total"]["value"],
            "with_nif": aggs.get("with_nif", {}).get("doc_count", 0),
            "without_nif": aggs.get("without_nif", {}).get("doc_count", 0),
            "total_value": round(aggs.get("total_value", {}).get("value") or 0.0, 2),
            "total_contracts": int(aggs.get("total_contracts", {}).get("value") or 0),
            "adjudicante_count": aggs.get("as_adjudicante", {}).get("doc_count", 0),
            "adjudicatario_count": aggs.get("as_adjudicatario", {}).get("doc_count", 0),
            "countries": countries,
        }
    except Exception as exc:
        return {"error": str(exc)}


def get_entity_by_nif(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o registo do cadastro de entidades para um NIF."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"query": {"bool": {"should": [{"term": {"nif": nif}}, {"term": {"_id": f"{ENTITIES_INDEX}:{nif}"}}], "minimum_should_match": 1}}, "size": 1},
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return {"nif": nif, "error": "Entidade não encontrada no cadastro"}
        return {"nif": nif, **hits[0]["_source"], "doc_id": hits[0]["_id"]}
    except Exception as exc:
        return {"error": str(exc)}


def save_entity_societario_timeline(
    nif: str,
    markdown: str,
    total: int,
    backend_used: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Guarda a timeline societária gerada por IA na ficha da entidade (ENTITIES_INDEX)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nif": nif}

    ensure_indices(client)

    doc = {
        "societario_timeline": {
            "markdown": markdown,
            "total": total,
            "backend_used": backend_used,
            "generated_at": _today(),
        }
    }

    try:
        resp = client.update(
            index=ENTITIES_INDEX,
            id=f"{ENTITIES_INDEX}:{nif}",
            body={"doc": doc, "doc_as_upsert": True},
            refresh=True,
        )
        return {"nif": nif, "updated": resp.get("result") in ("updated", "created")}
    except Exception as exc:
        return {"error": str(exc), "nif": nif}


def list_entity_countries(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Lista os países presentes no cadastro de entidades, com contagem."""
    client = es or get_es_client()
    if not client:
        return []

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"size": 0, "aggs": {"countries": {"terms": {"field": "country", "size": 300, "order": {"_key": "asc"}}}}},
        )
        return [
            {"country": b["key"], "count": b["doc_count"]}
            for b in resp["aggregations"]["countries"]["buckets"]
            if b["key"]
        ]
    except Exception:
        return []

# --- Preferências do utilizador (favoritos, pastas e histórico do EmpresasIQ) ---
# Um único índice guarda o estado que antes vivia apenas no browser. Favoritos e pastas
# têm um documento por item (permite marcar/remover de forma isolada); o histórico é
# um documento único com a lista completa.

def _user_state_index() -> str:
    return USER_STATE_INDEX


def list_favorites(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Lista os favoritos guardados no Elasticsearch (mais recentes primeiro)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={
                "query": {"term": {"kind": "favorite"}},
                "size": 1000,
                "sort": [{"added_at": {"order": "desc", "missing": "_last"}}],
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            # No índice `kind` identifica o tipo de documento ("favorite"/"folder"/"history");
            # na resposta o campo `kind` é o tipo de ficha ("entity"/"contract").
            items.append(
                {
                    "kind": src.get("entry_kind"),
                    "id": src.get("id"),
                    "label": src.get("label") or src.get("id"),
                    "sublabel": src.get("sublabel"),
                    "value": src.get("value"),
                    "parties": src.get("parties") or [],
                    "added_at": src.get("added_at"),
                    "doc_id": hit["_id"],
                }
            )
        return {"items": items, "total": len(items)}
    except Exception as exc:
        return {"error": str(exc), "items": []}


def save_favorite(doc: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) um favorito. O id do documento é ``kind:id``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    kind = str(doc.get("kind") or "").strip()
    item_id = str(doc.get("id") or "").strip()
    if kind not in {"entity", "contract"} or not item_id:
        return {"error": "Favorito inválido: precisa de kind ('entity'|'contract') e id"}

    source = {
        "kind": "favorite",
        "entry_kind": kind,
        "id": item_id,
        "label": doc.get("label") or item_id,
        "sublabel": doc.get("sublabel"),
        "value": doc.get("value"),
        "parties": doc.get("parties") or [],
        "added_at": doc.get("added_at") or _today(),
    }
    try:
        client.index(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", document=source, refresh=True)
        return {"ok": True, "id": item_id, "kind": kind}
    except Exception as exc:
        return {"error": str(exc)}


def delete_favorite(kind: str, item_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove um favorito."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def clear_favorites(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove todos os favoritos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=USER_STATE_INDEX,
            body={"query": {"term": {"kind": "favorite"}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}


def get_workspace(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o dossier (pastas) e o histórico guardados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "folders": [], "history": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={"query": {"terms": {"kind": ["folder", "history"]}}, "size": 1000},
        )
        folders = []
        history = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            if src.get("kind") == "folder":
                folders.append(
                    {
                        "id": src.get("folder_id") or hit["_id"],
                        "name": src.get("name") or "Pasta",
                        "createdAt": src.get("created_at"),
                        "items": src.get("items") or [],
                    }
                )
            elif src.get("kind") == "history":
                history = src.get("items") or []
        folders.sort(key=lambda folder: folder.get("createdAt") or "")
        return {"folders": folders, "history": history}
    except Exception as exc:
        return {"error": str(exc), "folders": [], "history": []}


def save_folder(folder: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) uma pasta do dossier com as suas fichas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    folder_id = str(folder.get("id") or "").strip()
    if not folder_id:
        return {"error": "Pasta inválida: falta o id"}

    source = {
        "kind": "folder",
        "folder_id": folder_id,
        "name": folder.get("name") or "Pasta",
        "created_at": folder.get("createdAt") or _today(),
        "items": folder.get("items") or [],
        "updated_at": _today(),
    }
    try:
        client.index(index=USER_STATE_INDEX, id=f"folder:{folder_id}", document=source, refresh=True)
        return {"ok": True, "id": folder_id}
    except Exception as exc:
        return {"error": str(exc)}


def delete_folder(folder_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove uma pasta do dossier."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"folder:{folder_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def save_history(items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda o histórico de fichas consultadas (documento único)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.index(
            index=USER_STATE_INDEX,
            id="history",
            document={"kind": "history", "items": items, "updated_at": _today()},
            refresh=True,
        )
        return {"ok": True, "count": len(items)}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Recolha de sites (scraping) — índice `finance_scraped`
# ---------------------------------------------------------------------------

def _clean_flattened(value: Any) -> Any:
    """Prepara um valor para o campo `flattened` (apenas str/número/bool/listas)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:20000]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple, set)):
        cleaned = [_clean_flattened(v) for v in value]
        return [v for v in cleaned if v is not None]
    if isinstance(value, dict):
        cleaned = {str(k): _clean_flattened(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v is not None}
    return str(value)[:20000]


def index_scraped_items(
    source_id: str,
    source_name: str,
    run_id: str,
    items: List[Dict[str, Any]],
    trigger: str = "manual",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa itens recolhidos em `finance_scraped`.

    O `_id` do documento é o `item_id` calculado pelo `scraper_service`, pelo que
    re-executar uma fonte **atualiza** os itens já conhecidos em vez de os
    duplicar (a identidade do item é definida na definição da fonte).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "error_count": 0}

    ensure_indices(client)
    now = _today()
    actions: List[Dict[str, Any]] = []
    for item in items or []:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        tags = item.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        sentimento = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        doc = {
            "source_id": source_id,
            "source_name": source_name or source_id,
            "run_id": run_id,
            "item_id": item_id,
            "url": str(item.get("url") or "")[:1024],
            "title": str(item.get("title") or "")[:1024],
            "summary": str(item.get("summary") or "")[:20000],
            "text": str(item.get("text") or "")[:100000],
            "tags": [str(t) for t in (tags or []) if t not in (None, "")][:64],
            "data": _clean_flattened(item.get("data") or {}) or {},
            "scraped_at": str(item.get("scraped_at") or now),
            "trigger": trigger or "manual",
        }
        label = str(sentimento.get("label") or "").strip().lower()
        if label:
            doc["sentiment"] = label
            doc["sentiment_engine"] = str(sentimento.get("engine") or "")[:32]
            try:
                doc["sentiment_score"] = float(sentimento.get("polarity") or 0.0)
            except (TypeError, ValueError):
                doc["sentiment_score"] = 0.0
        actions.append({"_index": SCRAPED_INDEX, "_id": item_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("Recolha: %s de %s itens falharam na indexação", len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}


def _scraped_query(
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de itens recolhidos."""
    must: List[Dict[str, Any]] = []
    if q:
        # `data.*` cobre todos os campos extraídos (índice `flattened`).
        must.append(
            {
                "query_string": {
                    "query": q,
                    "fields": ["title^3", "summary^2", "text", "url", "data.*"],
                    "default_operator": "and",
                    "lenient": True,
                    "analyze_wildcard": True,
                }
            }
        )
    filters: List[Dict[str, Any]] = []
    if source_id:
        filters.append({"term": {"source_id": source_id}})
    if tags:
        filters.append({"terms": {"tags": tags}})
    etiquetas = [str(s).strip().lower() for s in (sentiments or []) if str(s).strip()]
    if etiquetas:
        filters.append({"terms": {"sentiment": etiquetas}})
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"scraped_at": rng}})

    bool_query: Dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if filters:
        bool_query["filter"] = filters
    return {"bool": bool_query}


def _sentiment_summary(aggs: Dict[str, Any], total: int) -> Dict[str, Any]:
    """Resumo do sentimento do conjunto de resultados (não só da página).

    É isto que dá «um sentimento à pesquisa»: a distribuição por etiqueta e a
    polaridade média dos itens classificados, com a cobertura (quantos dos
    resultados têm sentimento) para não confundir «neutro» com «sem análise».
    """
    buckets = {b["key"]: b["doc_count"] for b in aggs.get("sentiment", {}).get("buckets", [])}
    media = aggs.get("sentiment_avg", {}).get("value")
    analisados = sum(buckets.values())
    polaridade = round(float(media), 3) if isinstance(media, (int, float)) else 0.0
    label = "sem dados"
    if analisados:
        label = "positivo" if polaridade >= 0.15 else "negativo" if polaridade <= -0.15 else "neutro"
    return {
        "positivo": int(buckets.get("positivo", 0)),
        "neutro": int(buckets.get("neutro", 0)),
        "negativo": int(buckets.get("negativo", 0)),
        "analyzed": int(analisados),
        "total": int(total),
        "polarity": polaridade,
        "label": label,
        "coverage": round(analisados / total, 3) if total else 0.0,
    }


def search_scraped(
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "recent",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa itens recolhidos, com facetas por fonte, etiqueta, dia e sentimento."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}

    ensure_indices(client)

    sort_spec: List[Any]
    if sort == "oldest":
        sort_spec = [{"scraped_at": {"order": "asc"}}]
    elif sort == "relevance" and q:
        sort_spec = [{"_score": {"order": "desc"}}, {"scraped_at": {"order": "desc"}}]
    else:
        sort_spec = [{"scraped_at": {"order": "desc"}}]

    body: Dict[str, Any] = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": _scraped_query(q, source_id, tags, date_from, date_to, sentiments),
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            "sources": {"terms": {"field": "source_id", "size": 50}},
            "tags": {"terms": {"field": "tags", "size": 50}},
            "days": {"date_histogram": {"field": "scraped_at", "calendar_interval": "day", "min_doc_count": 0}},
            # Sentimento do conjunto de resultados (não só da página).
            "sentiment": {"terms": {"field": "sentiment", "size": 10}},
            "sentiment_avg": {"avg": {"field": "sentiment_score"}},
        },
    }

    try:
        resp = client.search(index=SCRAPED_INDEX, body=body)
    except Exception as exc:
        # Alguns campos de texto podem não existir (índice criado por versão
        # anterior): repete a pesquisa apenas sobre os campos garantidos.
        logger.debug("Pesquisa de recolha falhou (%s); a repetir sem `data.*`: %s", q, exc)
        if not q:
            return {"error": str(exc), "total": 0, "items": [], "facets": {}}
        fallback = dict(body)
        fallback["query"] = _scraped_query(None, source_id, tags, date_from, date_to, sentiments)
        fallback["query"] = {
            "bool": {
                "must": [{"multi_match": {"query": q, "fields": ["title", "summary", "text"], "lenient": True}}],
                "filter": fallback["query"]["bool"].get("filter", []),
            }
        }
        try:
            resp = client.search(index=SCRAPED_INDEX, body=fallback)
        except Exception as inner:
            return {"error": str(inner), "total": 0, "items": [], "facets": {}}

    aggs = resp.get("aggregations", {}) or {}
    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            "sources": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sources", {}).get("buckets", [])
            ],
            "tags": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("tags", {}).get("buckets", [])],
            "days": [
                {"key": b.get("key_as_string"), "count": b["doc_count"]}
                for b in aggs.get("days", {}).get("buckets", [])
                if b.get("doc_count")
            ],
            "sentiment": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sentiment", {}).get("buckets", [])
            ],
        },
        "sentiment": _sentiment_summary(aggs, int(total_value or 0)),
    }


# ---------------------------------------------------------------------------
# Sentimento diário de mercado — índice `finance_sentiment_daily`
# ---------------------------------------------------------------------------
SENTIMENT_DAILY_INDEX = "finance_sentiment_daily"


def index_sentiment_daily(rows: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Grava/atualiza o sentimento diário por ticker (idempotente).

    O `_id` do documento é `ticker|data`, pelo que reconstruir o mesmo dia
    **atualiza** o documento em vez de o duplicar: reprocessar é seguro.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    bulk_body: List[Dict[str, Any]] = []
    total = 0
    for row in rows or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        day = str(row.get("date") or "").strip()[:10]
        if not ticker or not day:
            continue
        document = {key: value for key, value in row.items() if key != "_id"}
        document["ticker"] = ticker
        document["date"] = day
        bulk_body.append({"index": {"_index": SENTIMENT_DAILY_INDEX, "_id": f"{ticker}|{day}"}})
        bulk_body.append(document)
        total += 1
    if not bulk_body:
        return {"indexed": 0, "errors": 0, "total": 0}
    try:
        response = client.bulk(body=bulk_body, refresh=True)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        return {"error": str(exc), "indexed": 0, "errors": total, "total": total}
    errors = sum(1 for item in response.get("items", []) if (item.get("index") or {}).get("error"))
    return {"indexed": total - errors, "errors": errors, "total": total}


def search_sentiment_daily(
    ticker: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 3000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê o sentimento diário guardado (por ticker e/ou intervalo de datas)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    must: List[Dict[str, Any]] = []
    if ticker:
        must.append({"term": {"ticker": str(ticker).strip().upper()}})
    window: Dict[str, str] = {}
    if start_date:
        window["gte"] = str(start_date)[:10]
    if end_date:
        window["lte"] = str(end_date)[:10]
    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}]}}
    if window:
        query["bool"]["filter"] = [{"range": {"date": window}}]
    try:
        response = client.search(
            index=SENTIMENT_DAILY_INDEX,
            body={
                "query": query,
                "size": max(1, min(int(size), 10000)),
                "sort": [{"date": {"order": "asc"}}, {"ticker": {"order": "asc"}}],
                "track_total_hits": True,
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in response.get("hits", {}).get("hits", [])],
    }


def list_news_tickers(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Tickers com notícias indexadas em `finance_news` (com contagem)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    try:
        response = client.search(
            index="finance_news",
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 500}}},
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    items = [
        {"ticker": bucket.get("key"), "news": int(bucket.get("doc_count") or 0)}
        for bucket in response.get("aggregations", {}).get("tickers", {}).get("buckets", [])
    ]
    return {"total": int(total_value or 0), "items": items}


def list_sentiment_daily_tickers(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Tickers com sentimento diário guardado (nº de dias, primeira e última data)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    try:
        response = client.search(
            index=SENTIMENT_DAILY_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "tickers": {
                        "terms": {"field": "ticker", "size": 500},
                        "aggs": {
                            "first": {"min": {"field": "date", "format": "yyyy-MM-dd"}},
                            "last": {"max": {"field": "date", "format": "yyyy-MM-dd"}},
                            "news": {"sum": {"field": "news_count"}},
                        },
                    }
                },
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    items = [
        {
            "ticker": bucket.get("key"),
            "days": bucket.get("doc_count", 0),
            "first_date": (bucket.get("first") or {}).get("value_as_string"),
            "last_date": (bucket.get("last") or {}).get("value_as_string"),
            "news": int((bucket.get("news") or {}).get("value") or 0),
        }
        for bucket in response.get("aggregations", {}).get("tickers", {}).get("buckets", [])
    ]
    return {"total": int(total_value or 0), "items": items}


def delete_sentiment_daily(
    ticker: Optional[str] = None,
    dates: Optional[List[str]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Apaga o sentimento diário (de um ticker, de dias concretos ou de todos).

    Com `dates`, apaga apenas esses dias (é o que permite limpar dias obsoletos da
    série sem tocar no resto).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    must: List[Dict[str, Any]] = []
    if ticker:
        must.append({"term": {"ticker": str(ticker).strip().upper()}})
    if dates:
        must.append({"terms": {"date": [str(day)[:10] for day in dates if day]}})
    query: Dict[str, Any] = {"bool": {"must": must}} if must else {"match_all": {}}
    try:
        response = client.delete_by_query(index=SENTIMENT_DAILY_INDEX, body={"query": query}, refresh=True, conflicts="proceed")
        return {"ok": True, "deleted": response.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}


def update_scraped_sentiment(rows: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Actualiza só o sentimento de itens já indexados (análise à posteriori).

    `rows` são `{item_id, sentiment}`; a atualização é parcial para não reescrever
    o texto nem os campos extraídos de cada documento.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "updated": 0}
    actions: List[Dict[str, Any]] = []
    for row in rows or []:
        item_id = str(row.get("item_id") or "").strip()
        sentimento = row.get("sentiment") if isinstance(row.get("sentiment"), dict) else None
        if not item_id or not sentimento or not sentimento.get("label"):
            continue
        try:
            score = float(sentimento.get("polarity") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        actions.append(
            {
                "_op_type": "update",
                "_index": SCRAPED_INDEX,
                "_id": item_id,
                "doc": {
                    "sentiment": str(sentimento["label"]).lower(),
                    "sentiment_score": score,
                    "sentiment_engine": str(sentimento.get("engine") or "")[:32],
                    "sentiment_model": str(sentimento.get("model") or "")[:80],
                    "sentiment_at": str(sentimento.get("analyzed_at") or _today()),
                },
            }
        )
    if not actions:
        return {"updated": 0, "error_count": 0}
    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        return {"updated": int(success), "error_count": len(error_list)}
    except Exception as exc:
        return {"error": str(exc), "updated": 0, "error_count": len(actions)}


def scraped_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de recolha (total e por fonte)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0, "sources": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=SCRAPED_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {"sources": {"terms": {"field": "source_id", "size": 50}}},
            },
        )
        total = resp.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        return {
            "available": True,
            "total": int(total_value or 0),
            "sources": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in resp.get("aggregations", {}).get("sources", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"available": False, "total": 0, "sources": [], "error": str(exc)}


def delete_scraped_source(source_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todos os itens de uma fonte."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=SCRAPED_INDEX,
            body={"query": {"term": {"source_id": source_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Pesquisa social (LinkedIn, TikTok, Reddit, Facebook) — índice `finance_social`
# ---------------------------------------------------------------------------

#: Métricas de interação guardadas como campos próprios (para ordenar/agregar).
SOCIAL_METRIC_FIELDS = ("likes", "comments", "shares", "views")


def index_social_items(
    channel: Dict[str, Any],
    items: List[Dict[str, Any]],
    trigger: str = "manual",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações sociais em `finance_social`.

    O `_id` do documento é o `item_id` calculado pelo `social_service`
    (`sha1(plataforma|tipo|alvo|id-da-publicação)`), pelo que repetir uma recolha
    **atualiza** as publicações já conhecidas (métricas mais recentes) em vez de
    as duplicar.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "error_count": 0}

    ensure_indices(client)
    now = _today()
    channel = channel or {}
    actions: List[Dict[str, Any]] = []
    for item in items or []:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        tags = item.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        sentimento = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        doc: Dict[str, Any] = {
            "platform": str(item.get("platform") or channel.get("platform") or "")[:32],
            "channel_id": str(item.get("channel_id") or channel.get("id") or "")[:128],
            "channel_name": str(item.get("channel_name") or channel.get("name") or "")[:256],
            "kind": str(item.get("kind") or channel.get("kind") or "")[:32],
            "run_id": str(item.get("run_id") or "")[:64],
            "item_id": item_id,
            "post_id": str(item.get("post_id") or "")[:256],
            "url": str(item.get("url") or "")[:1024],
            "title": str(item.get("title") or "")[:1024],
            "text": str(item.get("text") or "")[:100000],
            "author": str(item.get("author") or "")[:256],
            "community": str(item.get("community") or "")[:256],
            "lang": str(item.get("lang") or "")[:16],
            "image": str((item.get("media") or {}).get("image") or item.get("image") or "")[:1024],
            "video": str((item.get("media") or {}).get("video") or item.get("video") or "")[:1024],
            "images": [str(url)[:1024] for url in ((item.get("media") or {}).get("images") or item.get("images") or []) if url][:24],
            "videos": [str(url)[:1024] for url in ((item.get("media") or {}).get("videos") or item.get("videos") or []) if url][:12],
            "person_nif": str(item.get("person_nif") or channel.get("person_nif") or "")[:32],
            "person_name": str(item.get("person_name") or channel.get("person_name") or "")[:512],
            "tags": [str(t) for t in (tags or []) if t not in (None, "")][:64],
            "collected_at": str(item.get("collected_at") or now),
            "trigger": trigger or "manual",
            "data": _clean_flattened(item.get("data") or {}) or {},
        }
        for metric in SOCIAL_METRIC_FIELDS:
            try:
                doc[metric] = int(metrics.get(metric) or 0)
            except (TypeError, ValueError):
                doc[metric] = 0
        published = item.get("published_at")
        if published:
            doc["published_at"] = str(published)
        label = str(sentimento.get("label") or "").strip().lower()
        if label:
            doc["sentiment"] = label
            doc["sentiment_engine"] = str(sentimento.get("engine") or "")[:32]
            try:
                doc["sentiment_score"] = float(sentimento.get("polarity") or 0.0)
            except (TypeError, ValueError):
                doc["sentiment_score"] = 0.0
        actions.append({"_index": SOCIAL_INDEX, "_id": item_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("Pesquisa social: %s de %s itens falharam na indexação", len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}


def _social_query(
    q: Optional[str] = None,
    platform: Optional[str] = None,
    channel_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    person_nif: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de publicações sociais."""
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "query_string": {
                    "query": q,
                    "fields": ["title^3", "text^2", "author^2", "community", "url", "data.*"],
                    "default_operator": "and",
                    "lenient": True,
                    "analyze_wildcard": True,
                }
            }
        )
    filters: List[Dict[str, Any]] = []
    if platform:
        filters.append({"term": {"platform": platform}})
    if channel_id:
        filters.append({"term": {"channel_id": channel_id}})
    if person_nif:
        filters.append({"term": {"person_nif": str(person_nif)}})
    if tags:
        filters.append({"terms": {"tags": tags}})
    etiquetas = [str(s).strip().lower() for s in (sentiments or []) if str(s).strip()]
    if etiquetas:
        filters.append({"terms": {"sentiment": etiquetas}})
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        # Filtra pela data de publicação, mas cai na de recolha quando a
        # publicação não traz data (é o caso dos vídeos do TikTok e de páginas
        # do Facebook sem `created_time`).
        filters.append(
            {
                "bool": {
                    "should": [
                        {"range": {"published_at": rng}},
                        {
                            "bool": {
                                "must_not": {"exists": {"field": "published_at"}},
                                "must": [{"range": {"collected_at": rng}}],
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    bool_query: Dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if filters:
        bool_query["filter"] = filters
    return {"bool": bool_query}


def search_social(
    q: Optional[str] = None,
    platform: Optional[str] = None,
    channel_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    person_nif: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "recent",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações sociais, com facetas por plataforma, canal, etiqueta e dia."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}

    ensure_indices(client)

    sort_spec: List[Any]
    if sort == "oldest":
        sort_spec = [{"collected_at": {"order": "asc"}}]
    elif sort == "engagement":
        sort_spec = [{"likes": {"order": "desc"}}, {"comments": {"order": "desc"}}]
    elif sort == "views":
        sort_spec = [{"views": {"order": "desc"}}, {"likes": {"order": "desc"}}]
    elif sort == "relevance" and q:
        sort_spec = [{"_score": {"order": "desc"}}, {"collected_at": {"order": "desc"}}]
    else:
        sort_spec = [{"collected_at": {"order": "desc"}}]

    body: Dict[str, Any] = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": _social_query(q, platform, channel_id, tags, date_from, date_to, sentiments, person_nif),
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            "platforms": {"terms": {"field": "platform", "size": 20}},
            "channels": {"terms": {"field": "channel_id", "size": 50}},
            "tags": {"terms": {"field": "tags", "size": 50}},
            "days": {"date_histogram": {"field": "collected_at", "calendar_interval": "day", "min_doc_count": 0}},
            "sentiment": {"terms": {"field": "sentiment", "size": 10}},
            "sentiment_avg": {"avg": {"field": "sentiment_score"}},
        },
    }

    try:
        resp = client.search(index=SOCIAL_INDEX, body=body)
    except Exception as exc:
        logger.debug("Pesquisa social falhou (%s); a repetir sem `data.*`: %s", q, exc)
        if not q:
            return {"error": str(exc), "total": 0, "items": [], "facets": {}}
        fallback = dict(body)
        fallback["query"] = {
            "bool": {
                "must": [{"multi_match": {"query": q, "fields": ["title", "text", "author"], "lenient": True}}],
                "filter": _social_query(None, platform, channel_id, tags, date_from, date_to, sentiments, person_nif)["bool"].get("filter", []),
            }
        }
        try:
            resp = client.search(index=SOCIAL_INDEX, body=fallback)
        except Exception as inner:
            return {"error": str(inner), "total": 0, "items": [], "facets": {}}

    aggs = resp.get("aggregations", {}) or {}
    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            "platforms": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("platforms", {}).get("buckets", [])
            ],
            "channels": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("channels", {}).get("buckets", [])
            ],
            "tags": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("tags", {}).get("buckets", [])],
            "days": [
                {"key": b.get("key_as_string"), "count": b["doc_count"]}
                for b in aggs.get("days", {}).get("buckets", [])
                if b.get("doc_count")
            ],
            "sentiment": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sentiment", {}).get("buckets", [])
            ],
        },
        "sentiment": _sentiment_summary(aggs, int(total_value or 0)),
    }


def social_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice social (total e por plataforma)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0, "platforms": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=SOCIAL_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "platforms": {"terms": {"field": "platform", "size": 20}},
                    "channels": {"terms": {"field": "channel_id", "size": 50}},
                },
            },
        )
        total = resp.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        aggs = resp.get("aggregations", {}) or {}
        return {
            "available": True,
            "total": int(total_value or 0),
            "platforms": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("platforms", {}).get("buckets", [])
            ],
            "channels": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("channels", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"available": False, "total": 0, "platforms": [], "error": str(exc)}


def delete_social_channel(channel_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todas as publicações de um canal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=SOCIAL_INDEX,
            body={"query": {"term": {"channel_id": channel_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}


# --- Contratos públicos de Espanha (PLACSP) ---------------------------------
# Documentos produzidos por `collectors/contratos_es.py`. O `_id` do documento é
# `fonte|DIR3 do órgão|n.º de expediente`, pelo que reprocessar um ano atualiza em
# vez de duplicar (a publicação mais recente vence).

CONTRATOS_ES_FACET_FIELDS: Dict[str, str] = {
    "ano": "ano",
    "fonte": "fonte",
    "tipo": "tipo_contrato_label",
    "tipo_codigo": "tipo_contrato",
    "estado": "estado_label",
    "localidad": "localidad",
    "nuts": "nuts",
    "procedimiento": "procedimiento_label",
    "resultado": "resultado_label",
    "organo": "organo_nombre.keyword",
    "adjudicatario": "adjudicatario_nombre.keyword",
}


def index_contratos_es(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos de Espanha no índice `contratos_es`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "")
        if not doc_id:
            continue
        actions.append({"_op_type": "index", "_index": CONTRATOS_ES_INDEX, "_id": doc_id, **doc})

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=False)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}


def bulk_index_contratos_es_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um JSONL de contratos de Espanha em blocos (bulk)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = success_total = error_total = 0
    chunk: List[Dict[str, Any]] = []
    resolved = Path(jsonl_path)
    started = time.time()

    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contratos_es(chunk, client)
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
                    chunk = []
                    if total % (chunk_size * 10) == 0:
                        rate = total / max(time.time() - started, 1e-6)
                        print(f"[contratos_es] {total:,} docs · {rate:,.0f} docs/s", flush=True)
        if chunk:
            res = index_contratos_es(chunk, client)
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
        client.indices.refresh(index=CONTRATOS_ES_INDEX)
        return {
            "indexed_count": success_total,
            "total": total,
            "errors": error_total,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": success_total, "total": total}


def contratos_es_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice `contratos_es` (total, anos e fontes indexadas)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": [], "fontes": []}

    ensure_indices(client)
    try:
        if not client.indices.exists(index=CONTRATOS_ES_INDEX):
            return {"total": 0, "years": [], "fontes": [], "available": False}
        total = client.count(index=CONTRATOS_ES_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "years": {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}},
                    "fontes": {"terms": {"field": "fonte", "size": 10}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        years = [
            {"year": b["key"], "count": b["doc_count"]}
            for b in aggs.get("years", {}).get("buckets", [])
            if isinstance(b["key"], int)
        ]
        fontes = [{"fonte": b["key"], "count": b["doc_count"]} for b in aggs.get("fontes", {}).get("buckets", [])]
        return {
            "available": True,
            "total": total,
            "years": [y["year"] for y in years],
            "years_detail": years,
            "fontes": fontes,
        }
    except Exception as exc:
        return {"error": str(exc), "total": 0, "years": [], "fontes": []}


def contratos_es_years_available() -> List[int]:
    """Anos com JSONL normalizado em `data/processed/contratos-es`."""
    years: set[int] = set()
    for path in (ROOT / "data" / "processed" / "contratos-es").glob("*.jsonl"):
        match = re.search(r"_(\d{4})\.jsonl$", path.name)
        if match:
            years.add(int(match.group(1)))
    return sorted(years)


def _contratos_es_value_range(
    min_value: Optional[float],
    max_value: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Filtro de valor: usa o valor adjudicado e, na sua falta, o valor base."""
    if min_value is None and max_value is None:
        return None
    budget: Dict[str, Any] = {"gte": min_value, "lte": max_value}
    budget = {k: v for k, v in budget.items() if v is not None}
    return {
        "bool": {
            "should": [
                {"range": {"valor_adjudicado": budget}},
                {
                    "bool": {
                        "must": [
                            {"bool": {"must_not": {"exists": {"field": "valor_adjudicado"}}}},
                            {"range": {"valor_base": budget}},
                        ]
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


def _build_contratos_es_query(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de contratos de Espanha."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q and q.strip():
        text = q.strip()
        must.append(
            {
                "bool": {
                    "should": [
                        {"multi_match": {"query": text, "fields": ["objeto^3", "adjudicatario_nombre^2", "organo_nombre^2", "descripcion", "search_text"], "type": "best_fields"}},
                        {"multi_match": {"query": text, "fields": ["objeto^4", "search_text"], "type": "phrase", "boost": 2}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    if ano is not None:
        filters.append({"term": {"ano": ano}})
    if fonte:
        filters.append({"term": {"fonte": fonte}})
    if tipo:
        filters.append({"term": {"tipo_contrato": tipo}} if tipo.isdigit() else {"term": {"tipo_contrato_label": tipo}})
    if estado:
        filters.append({"term": {"estado": estado}} if len(estado) <= 5 and estado.isupper() else {"term": {"estado_label": estado}})
    if procedimiento:
        filters.append({"term": {"procedimiento": procedimiento}} if procedimiento.isdigit() else {"term": {"procedimiento_label": procedimiento}})
    if organismo_id:
        filters.append({"term": {"organo_id": organismo_id}})
    if organo:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"organo_nombre": organo}},
                        {"term": {"organo_nombre.keyword": organo}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if adjudicatario_nif:
        filters.append({"term": {"adjudicatario_nif": adjudicatario_nif}})
    if adjudicatario:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"adjudicatario_nombre": adjudicatario}},
                        {"term": {"adjudicatario_nombre.keyword": adjudicatario}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if localidad:
        filters.append({"term": {"localidad": localidad}})
    if nuts:
        filters.append({"term": {"nuts": nuts}})
    if cpv_code:
        code = cpv_code.strip()
        filters.append(
            {
                "nested": {
                    "path": "cpv",
                    "query": (
                        {"term": {"cpv.code": code}}
                        if re.fullmatch(r"\d{8}(-\d)?", code)
                        else {"prefix": {"cpv.code": code}}
                    ),
                }
            }
        )
    if solo_menores is not None:
        filters.append({"term": {"es_menor": solo_menores}})

    value_range = _contratos_es_value_range(min_value, max_value)
    if value_range:
        filters.append(value_range)

    field = date_field if date_field in ("fecha_publicacion", "fecha_adjudicacion", "fecha_actualizacion") else "fecha_publicacion"
    date_range = {k: v for k, v in (("gte", start_date), ("lte", end_date)) if v}
    if date_range:
        filters.append({"range": {field: date_range}})

    return {"bool": {"must": must, "filter": filters}}


def _contratos_es_sort(sort_by: Optional[str], sort_order: Optional[str]) -> List[Any]:
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    if sort_by in ("valor_adjudicado", "valor_base", "valor_presupuesto"):
        return [{sort_by: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    if sort_by in ("fecha_adjudicacion", "fecha_publicacion", "fecha_actualizacion"):
        return [{sort_by: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if sort_by == "num_ofertas":
        return [{"num_ofertas": {"order": order, "missing": "_last", "unmapped_type": "integer"}}, "_score"]
    if sort_by == "ano":
        return [{"ano": {"order": order, "missing": "_last", "unmapped_type": "integer"}}, "_score"]
    if sort_by == "relevancia":
        return ["_score", {"fecha_publicacion": {"order": "desc"}}]
    return [{"fecha_publicacion": {"order": "desc", "missing": "_last"}}, "_score"]


def _contratos_es_aggs(cpv_size: int = 15, terms_size: int = 15) -> Dict[str, Any]:
    """Facetas usadas pela página de pesquisa (incluem os rótulos em espanhol)."""
    aggs: Dict[str, Any] = {
        name: {"terms": {"field": field, "size": terms_size}} for name, field in CONTRATOS_ES_FACET_FIELDS.items()
    }
    aggs["anos"] = {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}}
    aggs["cpv_codes"] = {
        "nested": {"path": "cpv"},
        "aggs": {
            "codes": {
                "terms": {"field": "cpv.code", "size": cpv_size},
                "aggs": {"nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}}},
            }
        },
    }
    aggs["valor_adjudicado"] = {
        "filter": {"exists": {"field": "valor_adjudicado"}},
        "aggs": {"sum": {"sum": {"field": "valor_adjudicado"}}, "avg": {"avg": {"field": "valor_adjudicado"}}},
    }
    aggs["valor_base"] = {
        "filter": {"exists": {"field": "valor_base"}},
        "aggs": {"sum": {"sum": {"field": "valor_base"}}},
    }
    return aggs


def _cpv_label_from_bucket(bucket: Dict[str, Any], code: str) -> str:
    """Descrição de um código CPV a partir do `top_hits` de um *bucket* aninhado.

    Dependendo da versão do Elasticsearch, o `top_hits` dentro de uma agregação
    `nested` devolve o objeto aninhado (`{"code":..., "nombre":...}`) ou o documento
    pai com a lista `cpv`. Ambos os formatos são aceites.
    """
    hits = bucket.get("nombre", {}).get("hits", {}).get("hits", [])
    if not hits:
        return code
    source = hits[0].get("_source") or {}
    cpvs = source.get("cpv")
    if isinstance(cpvs, list):
        for entry in cpvs:
            if isinstance(entry, dict) and entry.get("code") == code and entry.get("nombre"):
                return entry["nombre"]
    if isinstance(source, dict) and source.get("nombre"):
        return source["nombre"]
    return code


def search_contratos_es(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    with_facets: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos de Espanha com filtros e facetas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contratos_es_query(
        q=q,
        ano=ano,
        fonte=fonte,
        tipo=tipo,
        estado=estado,
        procedimiento=procedimiento,
        organo=organo,
        organismo_id=organismo_id,
        adjudicatario=adjudicatario,
        adjudicatario_nif=adjudicatario_nif,
        localidad=localidad,
        nuts=nuts,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        solo_menores=solo_menores,
    )
    body: Dict[str, Any] = {
        "query": query,
        "sort": _contratos_es_sort(sort_by, sort_order),
        "from": max(from_, 0),
        "size": size,
        "track_total_hits": True,
    }
    if with_facets:
        body["aggs"] = _contratos_es_aggs()

    try:
        resp = client.search(index=CONTRATOS_ES_INDEX, body=body)
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)

        result: Dict[str, Any] = {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
        if with_facets:
            aggs = resp.get("aggregations", {})
            facets: Dict[str, List[Dict[str, Any]]] = {}
            for name in CONTRATOS_ES_FACET_FIELDS:
                buckets = aggs.get(name, {}).get("buckets", [])
                if isinstance(buckets, dict):  # agregações por outra via (ex.: cpv)
                    buckets = buckets.get("codes", {}).get("buckets", [])
                facets[name] = [{"value": b["key"], "count": b["doc_count"]} for b in buckets]
            facets["cpv"] = []
            for bucket in aggs.get("cpv_codes", {}).get("codes", {}).get("buckets", []):
                facets["cpv"].append(
                    {
                        "value": bucket["key"],
                        "count": bucket["doc_count"],
                        "label": _cpv_label_from_bucket(bucket, bucket["key"]),
                    }
                )
            result["facets"] = facets
            result["stats"] = {
                "valor_adjudicado_sum": aggs.get("valor_adjudicado", {}).get("sum", {}).get("value"),
                "valor_adjudicado_avg": aggs.get("valor_adjudicado", {}).get("avg", {}).get("value"),
                "valor_adjudicado_docs": aggs.get("valor_adjudicado", {}).get("doc_count"),
                "valor_base_sum": aggs.get("valor_base", {}).get("sum", {}).get("value"),
                "valor_base_docs": aggs.get("valor_base", {}).get("doc_count"),
            }
        return result
    except Exception as exc:
        return {"error": str(exc), "items": []}


def contratos_es_autocomplete(q: str, size: int = 10, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Sugestões de órgãos, adjudicatários, objetos e CPV para a pesquisa espanhola."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    text = (q or "").strip()
    if len(text) < 2:
        return {"suggestions": []}

    try:
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"organo_nombre": text}},
                            {"match_phrase_prefix": {"adjudicatario_nombre": text}},
                            {"match_phrase_prefix": {"objeto": text}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "organos": {"terms": {"field": "organo_nombre.keyword", "size": size}},
                    "adjudicatarios": {"terms": {"field": "adjudicatario_nombre.keyword", "size": size}},
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": size,
                                    **({"include": f"{text}.*"} if text.isdigit() else {}),
                                }
                            }
                        },
                    },
                },
            },
        )
        aggs = resp.get("aggregations", {})
        suggestions: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for kind, key in (("organo", "organos"), ("adjudicatario", "adjudicatarios")):
            for bucket in aggs.get(key, {}).get("buckets", []):
                if bucket["key"] and bucket["key"] not in seen:
                    seen.add(bucket["key"])
                    suggestions.append({"text": bucket["key"], "type": kind, "count": bucket["doc_count"]})
        for bucket in aggs.get("cpv_codes", {}).get("codes", {}).get("buckets", []):
            if bucket["key"] and bucket["key"] not in seen:
                seen.add(bucket["key"])
                suggestions.append({"text": bucket["key"], "type": "cpv", "count": bucket["doc_count"]})
        return {"suggestions": suggestions[: size * 2]}
    except Exception as exc:
        return {"error": str(exc), "suggestions": []}


# Entidades do PLACSP. Cada documento do índice é **um contrato**, pelo que as
# entidades (órgãos adjudicantes e empresas adjudicatárias) são obtidas por
# agregação sobre o nome — é a forma de «pesquisar entidades» nos dados espanhóis.
CONTRATOS_ES_ENTITY_FIELDS: Dict[str, Dict[str, str]] = {
    "organo": {"field": "organo_nombre.keyword", "label": "Órgão adjudicante"},
    "adjudicatario": {"field": "adjudicatario_nombre.keyword", "label": "Empresa adjudicatária"},
}

CONTRATOS_ES_ENTITY_SAMPLE_FIELDS = [
    "organo_ciudad",
    "organo_id",
    "organo_tipo",
    "nuts",
    "adjudicatario_nif",
    "adjudicatario_nuts",
]


def _contratos_es_entity_filter(field: str, text: str) -> Dict[str, Any]:
    """Filtro de documentos cujo nome de entidade casa com o texto.

    Aceita a frase exata (`match_phrase`) e o prefixo da última palavra
    (`match_phrase_prefix`), para «Renfe» encontrar «Dirección General de Renfe
    Viajeros…» sem exigir o nome completo.
    """
    source = field[: -len(".keyword")] if field.endswith(".keyword") else field
    if not text:
        return {"match_all": {}}
    return {
        "bool": {
            "should": [
                {"match_phrase": {source: text}},
                {"match_phrase_prefix": {source: text}},
            ],
            "minimum_should_match": 1,
        }
    }


def search_contratos_es_entities(
    q: Optional[str] = None,
    *,
    kind: Optional[str] = None,
    ano: Optional[int] = None,
    min_count: int = 1,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades de Espanha (órgãos adjudicantes e adjudicatárias) por nome.

    Agrega os contratos por nome de entidade e devolve, para cada uma, o número
    de contratos, o valor adjudicado somado, a cidade, o NIF/DIR3 quando exista e
    o ano do último contrato. Sem texto devolve o diretório por volume; com texto
    filtra os nomes que casam com o termo.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    text = (q or "").strip()
    kinds = [kind] if kind in CONTRATOS_ES_ENTITY_FIELDS else list(CONTRATOS_ES_ENTITY_FIELDS)
    wanted = max(1, min(int(size), 100))
    offset = max(0, int(from_))
    # Os `terms` não têm paginação: pede-se o topo (offset + página) de cada tipo.
    bucket_size = min(300, offset + wanted)

    filters: List[Dict[str, Any]] = []
    if ano is not None:
        filters.append({"term": {"ano": ano}})

    aggs: Dict[str, Any] = {}
    for name in kinds:
        field = CONTRATOS_ES_ENTITY_FIELDS[name]["field"]
        aggs[name] = {
            "filter": _contratos_es_entity_filter(field, text),
            "aggs": {
                "entities": {
                    "terms": {"field": field, "size": bucket_size, "order": {"_count": "desc"}},
                    "aggs": {
                        # Mesma soma robusta da analítica: `max(valor_adjudicado, valor_base)`.
                        "valor": {"sum": _contratos_es_value_source()},
                        "ultimo_ano": {"max": {"field": "ano"}},
                        "sample": {"top_hits": {"size": 1, "_source": CONTRATOS_ES_ENTITY_SAMPLE_FIELDS}},
                    },
                }
            },
        }

    try:
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "track_total_hits": False,
                "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "aggs": aggs,
            },
        )
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}

    floor = max(1, int(min_count))
    pages: Dict[str, List[Dict[str, Any]]] = {}
    counts: Dict[str, int] = {}
    for name in kinds:
        info = CONTRATOS_ES_ENTITY_FIELDS[name]
        bucket_group = resp.get("aggregations", {}).get(name, {})
        entries: List[Dict[str, Any]] = []
        for bucket in bucket_group.get("entities", {}).get("buckets", []):
            if bucket["doc_count"] < floor:
                continue
            sample = ((bucket.get("sample", {}).get("hits", {}).get("hits") or [{}])[0].get("_source")) or {}
            is_organo = name == "organo"
            entries.append(
                {
                    "kind": name,
                    "kind_label": info["label"],
                    "name": bucket["key"],
                    "count": bucket["doc_count"],
                    # A cidade e o NUTS do documento são os do **órgão**; para a
                    # adjudicatária só o NUTS da empresa faz sentido.
                    "city": (sample.get("organo_ciudad") or "") if is_organo else "",
                    "nuts": ((sample.get("nuts") if is_organo else sample.get("adjudicatario_nuts")) or ""),
                    "nif": (sample.get("adjudicatario_nif") or "") if not is_organo else "",
                    "organo_id": (sample.get("organo_id") or "") if is_organo else "",
                    "organo_tipo": (sample.get("organo_tipo") or "") if is_organo else "",
                    "total_value": bucket.get("valor", {}).get("value"),
                    # O `max` do ano chega como float (`2024.0`): arredonda para o badge.
                    "last_year": (
                        int(bucket["ultimo_ano"]["value"])
                        if isinstance(bucket.get("ultimo_ano", {}).get("value"), (int, float))
                        else None
                    ),
                }
            )
        counts[name] = len(entries)
        pages[name] = entries[offset : offset + wanted]

    # Intercala os dois tipos (1.º órgão, 1.ª adjudicatária, 2.º órgão, …) para
    # que a página mostre sempre entidades contratantes e empresas adjudicatárias.
    items: List[Dict[str, Any]] = []
    depth = max((len(entries) for entries in pages.values()), default=0)
    for index in range(depth):
        for entries in pages.values():
            if index < len(entries):
                items.append(entries[index])

    return {
        "query": q,
        "total": sum(counts.values()),
        "by_kind": counts,
        "items": items[:wanted],
        "from": offset,
        "size": wanted,
    }


def get_contrato_es(doc_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato de Espanha pelo respetivo `_id`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = client.get(index=CONTRATOS_ES_INDEX, id=doc_id)
        source = resp.get("_source", {})
        source["doc_id"] = resp.get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}


def _contratos_es_value_source(field: str = "valor_adjudicado") -> Dict[str, Any]:
    """Devolve um `sum`/`avg`/`max` robusto para o valor adjudicado/base espanhol.

    A maior parte dos documentos tem `valor_adjudicado`, mas alguns (ou algumas
    versões do feed) só trazem `valor_base`. Usamos um `script` simples para
    escolher o primeiro disponível sem criar runtime_mappings no índice.
    """
    return {
        "script": {
            "source": "Math.max(doc.containsKey(params.adj) && !doc[params.adj].empty ? doc[params.adj].value : 0.0, doc.containsKey(params.base) && !doc[params.base].empty ? doc[params.base].value : 0.0)",
            "params": {"adj": field, "base": "valor_base"},
            "lang": "painless",
        }
    }


def _top_hit_cpv_es_name(agg: Optional[Dict[str, Any]], code: Any) -> str:
    """Lê a descrição espanhola de um CPV a partir de `top_hits`."""
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        entries = source.get("cpv")
        if entries is None:
            entries = source
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if code is None or entry.get("code") == code:
                name = entry.get("nombre")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return str(code) if code is not None else ""


def get_contratos_es_analytics(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
    top_organs: int = 8,
    top_adjudicatarios: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos de Espanha."""
    client = es or get_es_client(request_timeout=90)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    base_query = _build_contratos_es_query(
        q=q,
        ano=ano,
        fonte=fonte,
        tipo=tipo,
        estado=estado,
        procedimiento=procedimiento,
        organo=organo,
        organismo_id=organismo_id,
        adjudicatario=adjudicatario,
        adjudicatario_nif=adjudicatario_nif,
        localidad=localidad,
        nuts=nuts,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        solo_menores=solo_menores,
    )

    value_source = _contratos_es_value_source("valor_adjudicado")

    analytics_body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
            "total_value": {"sum": value_source},
            "avg_value": {"avg": value_source},
            "max_value": {"max": value_source},
            "by_year": {
                "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "by_month": {
                "date_histogram": {
                    "field": "fecha_publicacion",
                    "calendar_interval": "month",
                    "format": "yyyy-MM",
                    "min_doc_count": 1,
                    "missing": "2000-01",
                }
            },
            "value_distribution": {
                "histogram": {
                    "script": value_source["script"],
                    "interval": 100000,
                    "min_doc_count": 1,
                }
            },
            "top_organos": {
                "terms": {
                    "field": "organo_nombre.keyword",
                    "size": top_organs,
                    "order": {"total_value": "desc"},
                },
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_adjudicatarios": {
                "terms": {
                    "field": "adjudicatario_nombre.keyword",
                    "size": top_adjudicatarios,
                    "order": {"total_value": "desc"},
                },
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_cpv, "order": {"total_value": "desc"}},
                        "aggs": {
                            "nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": value_source}},
                            },
                        },
                    }
                },
            },
            "procedure_types": {
                "terms": {"field": "procedimiento_label", "size": 20, "missing": "N/A"}
            },
            "contract_types": {
                "terms": {"field": "tipo_contrato_label", "size": 20, "missing": "N/A"}
            },
        },
    }

    try:
        resp = client.search(index=CONTRATOS_ES_INDEX, body=analytics_body)
        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def read_value(bucket_total_value: Dict[str, Any]) -> Optional[float]:
            value = bucket_total_value.get("value", {})
            return value.get("value") if isinstance(value, dict) else value

        organo_rows = []
        for b in aggs.get("top_organos", {}).get("buckets", []):
            organo_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": b["key"],
            })

        adjudicatario_rows = []
        for b in aggs.get("top_adjudicatarios", {}).get("buckets", []):
            adjudicatario_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": b["key"],
            })

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": _top_hit_cpv_es_name(b.get("nombre"), b["key"]),
            })

        # Histograma pode ter valores negativos (correções); ignoramos bins < 0.
        value_distribution = []
        for b in aggs.get("value_distribution", {}).get("buckets", []):
            if b.get("key") is None or b["key"] < 0:
                continue
            value_distribution.append({
                "key": f"{int(b['key'])} - {int(b['key']) + 100000}",
                "count": b["doc_count"],
            })
            if len(value_distribution) >= value_buckets:
                break

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(read_value(b.get("total_value", {})))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "value_distribution": value_distribution,
            "top_entities": organo_rows + adjudicatario_rows,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": ano,
        }
    except Exception as exc:
        return {"error": str(exc)}


# --- Publicações de atos societários (Ministério da Justiça) ---------------
#
# O portal `publicacoes.mj.pt` publica os atos de registo comercial das entidades
# portuguesas. A pesquisa exige reCAPTCHA (ver `collectors/publicacoes_mj.py`),
# pelo que a recolha é assistida: uma pessoa resolve o captcha e o coletor trata
# da paginação, do detalhe e da ingestão. Este índice guarda o resultado.


def _delete_stale_docs(
    index: str,
    field: str,
    value: str,
    keep_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove documentos de um índice cujo campo ``field`` == ``value`` e que já não constam.

    Evita acumular registos obsoletos quando uma entidade é recolhida de novo com
    um conjunto de resultados diferente (ex.: publicações entretanto removidas).
    """
    client = es or get_es_client()
    if not client or not value:
        return 0
    try:
        body: Dict[str, Any] = {
            "query": {"bool": {"filter": [{"term": {field: str(value)}}]}}
        }
        if keep_ids:
            body["query"]["bool"]["must_not"] = [{"ids": {"values": keep_ids}}]
        resp = client.delete_by_query(index=index, body=body, refresh=True, conflicts="proceed")
        return resp.get("deleted", 0)
    except Exception as exc:
        logger.warning("Falha a remover documentos obsoletos de %s=%s em %s: %s", field, value, index, exc)
        return 0


def index_societario_items(
    items: List[Dict[str, Any]],
    replace_for_nif: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações de atos societários no índice SOCIETARIO_INDEX.

    ``replace_for_nif`` (NIF) ativa a limpeza dos registos dessa entidade que já
    não constam da recolha atual, mantendo a ficha coerente após reingestão.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    now = datetime.utcnow().isoformat()
    docs: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "publicacoes_mj"
        doc["ingested_at"] = now
        docs.append(doc)

    result = _bulk_index_docs(SOCIETARIO_INDEX, docs, id_field="pub_id", es=client)
    target_nif = replace_for_nif or (docs[0].get("nif") if docs and _single_nif(docs) else None)
    if target_nif:
        keep_ids = [f"{SOCIETARIO_INDEX}:{d['pub_id']}" for d in docs if d.get("nif") == target_nif]
        result["deleted_stale"] = _delete_stale_docs(
            SOCIETARIO_INDEX, "nif", str(target_nif), keep_ids, es=client
        )
    return result


def _single_nif(docs: List[Dict[str, Any]]) -> bool:
    """Indica se todos os documentos pertencem à mesma entidade."""
    nifs = {str(d.get("nif")) for d in docs if d.get("nif")}
    return len(nifs) == 1


def search_societario(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    entidade: Optional[str] = None,
    acto: Optional[str] = None,
    tipo: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    natureza_juridica: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações de atos societários indexadas.

    ``q`` procura em texto livre (entidade/firma/acto/texto integral); os restantes
    parâmetros são filtros exatos (exceto as datas, que são intervalos inclusivos).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["entidade^3", "firma^3", "acto^2", "texto", "requerente"],
                    "operator": "and",
                }
            }
        )
    if nif:
        filters.append({"term": {"nif": str(nif)}})
    if entidade:
        filters.append({"match_phrase": {"entidade": entidade}})
    if acto:
        filters.append({"match_phrase": {"acto": acto}})
    if tipo:
        filters.append({"term": {"tipo": str(tipo)}})
    if distrito:
        filters.append({"term": {"distrito": distrito}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if natureza_juridica:
        filters.append({"term": {"natureza_juridica": natureza_juridica}})
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_acto": {"terms": {"field": "acto.keyword", "size": 15}},
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_distrito": {"terms": {"field": "distrito", "size": 25}},
            "by_ano": {"date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}},
            "by_natureza": {"terms": {"field": "natureza_juridica", "size": 15}},
        },
    }

    try:
        resp = client.search(index=SOCIETARIO_INDEX, body=body)
        aggs = resp.get("aggregations", {})
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "facets": {
                "acto": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_acto", {}).get("buckets", [])],
                "tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
                "distrito": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_distrito", {}).get("buckets", [])],
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "natureza_juridica": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_natureza", {}).get("buckets", [])
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def company_publicacoes(
    nif: str,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Publicações de atos societários de uma entidade (por NIF)."""
    return search_societario(nif=str(nif), size=size, from_=from_, es=es)


def societario_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de publicações (entidades, intervalo de datas, atos)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=SOCIETARIO_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": SOCIETARIO_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=SOCIETARIO_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "entities": {"cardinality": {"field": "nif"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_acto": {"terms": {"field": "acto.keyword", "size": 10}},
                    "by_ano": {"date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        out["entities"] = aggs.get("entities", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["by_tipo"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])]
        out["top_actos"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_acto", {}).get("buckets", [])]
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}


def societario_targets(
    limit: int = 50,
    from_: int = 0,
    min_contracts: int = 1,
    exclude_collected: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades portuguesas com contratos no Portal BASE, ordenadas por volume.

    Serve para escolher os alvos da recolha assistida: por omissão devolve só as
    entidades que ainda não têm publicações no índice societário.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"country_code": "PT"}},
                            {"term": {"has_nif": True}},
                            {"range": {"contracts_count": {"gte": max(1, min_contracts)}}},
                        ]
                    }
                },
                "from": max(0, from_),
                "size": max(1, min(limit, 200)),
                "track_total_hits": False,
                "_source": ["nif", "name", "contracts_count", "total_value", "country"],
                "sort": [{"contracts_count": {"order": "desc", "missing": "_last"}}],
            },
        )
        rows = [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}

    nifs = [str(r.get("nif")) for r in rows if r.get("nif")]
    counts: Dict[str, int] = {}
    if nifs:
        try:
            agg = client.search(
                index=SOCIETARIO_INDEX,
                body={
                    "size": 0,
                    "query": {"terms": {"nif": nifs}},
                    "aggs": {"by_nif": {"terms": {"field": "nif", "size": len(nifs)}}},
                },
            )
            counts = {
                b["key"]: b["doc_count"]
                for b in agg.get("aggregations", {}).get("by_nif", {}).get("buckets", [])
            }
        except Exception:
            counts = {}

    items = [
        {
            "nif": str(row.get("nif")),
            "name": row.get("name"),
            "contracts_count": row.get("contracts_count"),
            "total_value": row.get("total_value"),
            "publications_count": counts.get(str(row.get("nif")), 0),
        }
        for row in rows
        if row.get("nif")
    ]
    if exclude_collected:
        items = [item for item in items if not item["publications_count"]]
    return {"items": items, "total": len(items), "from": from_, "size": limit}


# --- CIRE: publicidade da insolvência e da revitalização de empresas ---

def cire_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice do CIRE.

    Serve para a importação **não reescrever** documentos que já lá estão: uma
    recolha repetida do mesmo período só acrescenta o que é novo. A consulta é
    feita em blocos (o ``terms`` tem limite prático de 10 000 valores).
    """
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": CIRE_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start: start + chunk_size]
            resp = client.search(
                index=CIRE_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["pub_id"],
                    "query": {"terms": {"pub_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                # O `_id` do documento leva o prefixo do índice (`finance_cire:<pub_id>`),
                # por isso o valor tem de vir do campo `pub_id`.
                valor = (hit.get("_source") or {}).get("pub_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {"error": str(exc), "found": [], "known": 0, "checked": len(unique), "index": CIRE_INDEX}

    return {
        "found": found,
        "known": len(found),
        "checked": len(unique),
        "index": CIRE_INDEX,
    }


def index_cire_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    replace_for_referencias: Optional[List[str]] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações do CIRE no índice ``CIRE_INDEX``.

    O ``_id`` é o ``pub_id`` (sha1 de referência + processo + data + ato). Com
    ``skip_existing`` (por omissão) os documentos **que já existem no índice são
    ignorados** — recolher de novo o mesmo período só acrescenta o que é novo e
    não reescreve nada (o número de ignorados vem em ``skipped_existing``). Use
    ``skip_existing=False`` para forçar a atualização dos existentes.

    Se ``replace_for_referencias`` for dado, os documentos dessas referências que
    já não constem da lista são apagados (a lista considera **todos** os itens
    recebidos, mesmo os ignorados por já existirem).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    referencias_por_pub: Dict[str, str] = {}
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_cire"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)
        if doc.get("referencia") is not None:
            referencias_por_pub[str(doc["pub_id"])] = str(doc["referencia"])

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = cire_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados do CIRE: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(CIRE_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)

    if replace_for_referencias:
        deleted = 0
        for referencia in replace_for_referencias:
            keep_ids = [
                f"{CIRE_INDEX}:{pub_id}"
                for pub_id, ref in referencias_por_pub.items()
                if ref == str(referencia)
            ]
            deleted += _delete_stale_docs(
                CIRE_INDEX, "referencia", str(referencia), keep_ids, es=client
            )
        result["deleted_stale"] = deleted
    return result


def search_cire(
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    nif: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    insolvente: Optional[str] = None,
    papel: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações do CIRE (insolvências e revitalizações).

    ``q`` procura em texto livre (interveniente, tribunal, processo, ato). Os
    restantes parâmetros são filtros exatos, exceto as datas (intervalo
    inclusivo sobre a data de publicação) e ``papel`` (papel do interveniente).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": [
                        "insolvente^3",
                        "intervenientes.nome^3",
                        "referencia^3",
                        "processo^2",
                        "processo_numero^2",
                        "tribunal^2",
                        "ato^2",
                        "especie",
                        "texto",
                    ],
                    "operator": "and",
                }
            }
        )
    if referencia:
        filters.append({"term": {"referencia": str(referencia)}})
    if processo:
        filters.append({"match_phrase": {"processo": processo}})
    if nif:
        filters.append({"term": {"nifs": str(nif)}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if ato:
        filters.append({"match_phrase": {"ato": ato}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if insolvente:
        filters.append({"match_phrase": {"insolvente": insolvente}})
    if papel:
        filters.append(
            {"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.papel": papel}}}}
        )
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "by_ato": {"terms": {"field": "ato.keyword", "size": 20}},
            "by_ano": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"}
            },
            "by_papel": {
                "nested": {"path": "intervenientes"},
                "aggs": {"papel": {"terms": {"field": "intervenientes.papel", "size": 15}}},
            },
        },
    }

    try:
        resp = client.search(index=CIRE_INDEX, body=body)
        aggs = resp.get("aggregations", {})
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "facets": {
                "tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
                "tribunal_comarca": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_comarca", {}).get("buckets", [])
                ],
                "tribunal": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tribunal", {}).get("buckets", [])
                ],
                "especie": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_especie", {}).get("buckets", [])
                ],
                "ato": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_ato", {}).get("buckets", [])],
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "mes": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_mes", {}).get("buckets", [])
                ],
                "papel": [
                    {"key": b["key"], "count": b["doc_count"]}
                    for b in aggs.get("by_papel", {}).get("papel", {}).get("buckets", [])
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def cire_interveniente(nif: str, size: int = 100, from_: int = 0, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Publicações do CIRE em que um NIF/NIPC é interveniente (qualquer papel)."""
    return search_cire(nif=str(nif), size=size, from_=from_, es=es)


def cire_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice do CIRE (documentos, NIFs, datas e distribuições)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=CIRE_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": CIRE_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "nifs": {"cardinality": {"field": "nifs"}},
                    "insolventes": {"cardinality": {"field": "insolvente.keyword"}},
                    "referencias": {"cardinality": {"field": "referencia"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 15}},
                    "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 15}},
                    "by_ato": {"terms": {"field": "ato.keyword", "size": 15}},
                    "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
                    "by_ano": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"
                        }
                    },
                    "by_mes": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"
                        }
                    },
                    "com_documento": {"filter": {"term": {"has_documento": True}}},
                },
            },
        )
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        out["nifs"] = aggs.get("nifs", {}).get("value", 0)
        out["insolventes"] = aggs.get("insolventes", {}).get("value", 0)
        out["referencias"] = aggs.get("referencias", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["with_documento"] = aggs.get("com_documento", {}).get("doc_count", 0)
        out["by_tipo"] = _buckets("by_tipo")
        out["top_comarcas"] = _buckets("by_comarca")
        out["top_tribunais"] = _buckets("by_tribunal")
        out["top_actos"] = _buckets("by_ato")
        out["by_especie"] = _buckets("by_especie")
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        out["by_mes"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_mes", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}


def cire_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id`` (para a lista de recolhas)."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"by_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_run", {}).get("buckets", [])
        }
    except Exception:
        return {}


# --- Citações e notificações editais (CITIUS) -------------------------------

def citacoes_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice das citações editais.

    Serve para a importação **não reescrever** documentos que já lá estão (uma
    recolha repetida do mesmo nome só acrescenta o que é novo). A consulta é
    feita em blocos (o ``terms`` tem limite prático de 10 000 valores).
    """
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": CITACOES_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start: start + chunk_size]
            resp = client.search(
                index=CITACOES_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["pub_id"],
                    "query": {"terms": {"pub_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                valor = (hit.get("_source") or {}).get("pub_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {
            "error": str(exc), "found": [], "known": 0,
            "checked": len(unique), "index": CITACOES_INDEX,
        }

    return {"found": found, "known": len(found), "checked": len(unique), "index": CITACOES_INDEX}


def index_citacoes_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa citações/notificações editais no índice ``CITACOES_INDEX``.

    O ``_id`` é o ``pub_id`` (sha1 de referência + processo + data + ato). Com
    ``skip_existing`` (por omissão) os documentos **que já existem no índice são
    ignorados** — recolher de novo o mesmo nome só acrescenta o que é novo
    (o número de ignorados vem em ``skipped_existing``). Use
    ``skip_existing=False`` para forçar a atualização dos existentes.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_citacoes"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = citacoes_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados das citações editais: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(CITACOES_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)
    return result


def search_citacoes(
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    citado: Optional[str] = None,
    nome: Optional[str] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    modelo: Optional[str] = None,
    titulo: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    has_texto: Optional[bool] = None,
    with_texto: bool = True,
    size: int = 20,
    from_: int = 0,
    search_after: Optional[List[Any]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa citações e notificações editais já indexadas.

    ``q`` procura em texto livre (interveniente, tribunal, processo, ato e o
    **texto extraído do PDF**); ``nome`` restringe ao nome de um interveniente
    (qualquer papel) e ``papel`` ao papel exato desse interveniente.
    ``nif`` procura nos NIF dos intervenientes (da lista e do documento) e
    ``modelo``/``titulo`` no que foi analisado do PDF. ``with_texto=False``
    omite o texto integral da resposta (listas mais leves).

    Com ``search_after`` (cursor devolvido em ``next``) a pesquisa entra em
    **modo de varredura**: sem agregações, ordenada por data+`pub_id`, para
    percorrer o índice inteiro em páginas (usado pelo grafo e pelo mapa).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        # `intervenientes.nome` é `nested`: o `multi_match` sozinho não o alcança
        # (uma pesquisa por nome de uma parte devolvia zero), pelo que a pesquisa
        # livre junta as duas vias — campos planos e intervenientes.
        must.append(
            {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": q,
                                "fields": [
                                    "citado^3",
                                    "referencia^3",
                                    "processo^2",
                                    "processo_numero^2",
                                    "tribunal^2",
                                    "ato^2",
                                    "especie",
                                    "texto",
                                ],
                                "operator": "and",
                            }
                        },
                        {
                            "nested": {
                                "path": "intervenientes",
                                "query": {
                                    "match": {"intervenientes.nome": {"query": q, "operator": "and"}}
                                },
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if nome:
        filters.append(
            {"nested": {"path": "intervenientes", "query": {"match": {"intervenientes.nome": nome}}}}
        )
    if referencia:
        filters.append({"term": {"referencia": str(referencia)}})
    if processo:
        filters.append({"match_phrase": {"processo": processo}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if comarca_judicial:
        filters.append({"term": {"comarca_judicial": comarca_judicial}})
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if ato:
        filters.append({"match_phrase": {"ato": ato}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if citado:
        filters.append({"match_phrase": {"citado": citado}})
    if papel:
        filters.append({"term": {"papeis": papel}})
    if nif:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"documento_nifs": str(nif)}},
                        {
                            "nested": {
                                "path": "intervenientes",
                                "query": {"term": {"intervenientes.nif": str(nif)}},
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if modelo:
        filters.append({"term": {"documento_modelo": modelo}})
    if titulo:
        filters.append({"term": {"documento_titulo": titulo}})
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if has_texto is not None:
        filters.append({"term": {"has_texto": bool(has_texto)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 25}},
            "by_comarca_judicial": {"terms": {"field": "comarca_judicial", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "by_ato": {"terms": {"field": "ato.keyword", "size": 20}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "by_papel": {"terms": {"field": "papeis", "size": 20}},
            "by_modelo": {"terms": {"field": "documento_modelo", "size": 15}},
            "by_assunto": {"terms": {"field": "documento_assunto", "size": 15}},
            "by_ano": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"}
            },
            "valor_total": {"sum": {"field": "documento_valor"}},
            "valor_medio": {"avg": {"field": "documento_valor"}},
            "com_texto": {"filter": {"term": {"has_texto": True}}},
        },
    }

    if search_after is not None:
        # Modo de varredura: ordem estável (data + `pub_id`) e sem agregações.
        body["sort"] = [
            {"data_publicacao": {"order": "desc", "missing": "_last"}},
            {"pub_id": {"order": "asc"}},
        ]
        body["search_after"] = list(search_after)
        body["size"] = max(1, min(size, 1000))
        body.pop("from", None)
        body.pop("aggs", None)

    try:
        resp = client.search(index=CITACOES_INDEX, body=body)
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        items: List[Dict[str, Any]] = []
        for hit in resp["hits"]["hits"]:
            source = dict(hit["_source"])
            source["doc_id"] = hit["_id"]
            # `texto`/`documento_partes` são pesados: saem só quando interessa.
            if not with_texto:
                source.pop("texto", None)
                source.pop("documento_partes", None)
            items.append(source)

        total = aggs.get("com_texto", {}).get("doc_count", 0)
        resposta: Dict[str, Any] = {
            "query": q,
            "total": resp["hits"]["total"]["value"] if isinstance(resp["hits"]["total"], dict) else resp["hits"]["total"],
            "items": items,
            "from": from_,
            "size": size,
            "with_texto": total,
            "valor_total": round(float(aggs.get("valor_total", {}).get("value") or 0.0), 2),
            "valor_medio": (
                round(float(aggs["valor_medio"]["value"]), 2)
                if isinstance(aggs.get("valor_medio", {}).get("value"), (int, float))
                else None
            ),
            "facets": {
                "tipo": _buckets("by_tipo"),
                "tribunal_comarca": _buckets("by_comarca"),
                "comarca_judicial": _buckets("by_comarca_judicial"),
                "tribunal": _buckets("by_tribunal"),
                "ato": _buckets("by_ato"),
                "especie": _buckets("by_especie"),
                "papel": _buckets("by_papel"),
                "modelo": _buckets("by_modelo"),
                "assunto": _buckets("by_assunto"),
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "mes": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_mes", {}).get("buckets", [])
                ],
            },
        }
        # Cursor da página seguinte (modo de varredura) — ver `scan_citacoes`.
        hits = resp["hits"]["hits"]
        if search_after is not None:
            resposta["next"] = hits[-1].get("sort") if hits else None
        return resposta
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def scan_citacoes(
    *,
    max_docs: int = 20_000,
    page_size: int = 500,
    fields: Optional[List[str]] = None,
    **filters: Any,
) -> Dict[str, Any]:
    """Percorre (por `search_after`) os éditos que correspondem aos filtros.

    Serve o grafo e o mapa, que precisam do conjunto inteiro — não de uma página.
    Devolve ``{items, scanned, total, truncated, error}``: ``total`` é o total que
    o Elasticsearch conta para os filtros e ``truncated`` diz se o teto de
    ``max_docs`` cortou a varredura.
    """
    items: List[Dict[str, Any]] = []
    cursor: Optional[List[Any]] = None
    total = 0
    truncated = False
    try:
        while len(items) < max_docs:
            size = max(1, min(page_size, max_docs - len(items)))
            kwargs: Dict[str, Any] = {"with_texto": False, "size": size, "search_after": cursor or []}
            if fields:
                pass  # a projeção de campos é feita depois (os documentos são pequenos)
            res = search_citacoes(**{**filters, **kwargs})
            if res.get("error"):
                return {"items": items, "scanned": len(items), "total": total, "truncated": truncated, "error": res["error"]}
            lote = res.get("items") or []
            total = int(res.get("total") or total)
            items.extend(lote)
            cursor = res.get("next")
            if not lote or not cursor:
                break
        truncated = len(items) >= max_docs and total > len(items)
    except Exception as exc:  # noqa: BLE001
        return {"items": items, "scanned": len(items), "total": total, "truncated": truncated, "error": str(exc)}
    return {"items": items, "scanned": len(items), "total": total, "truncated": truncated}


def citacoes_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice das citações editais (documentos, datas e distribuições)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=CITACOES_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": CITACOES_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=CITACOES_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "referencias": {"cardinality": {"field": "referencia"}},
                    "processos": {"cardinality": {"field": "processo_numero"}},
                    "tribunais": {"cardinality": {"field": "tribunal.keyword"}},
                    "citados": {"cardinality": {"field": "citado.keyword"}},
                    "nifs": {"cardinality": {"field": "documento_nifs"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 15}},
                    "by_comarca_judicial": {"terms": {"field": "comarca_judicial", "size": 15}},
                    "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 15}},
                    "by_ato": {"terms": {"field": "ato.keyword", "size": 15}},
                    "by_papel": {"terms": {"field": "papeis", "size": 15}},
                    "by_modelo": {"terms": {"field": "documento_modelo", "size": 10}},
                    "by_assunto": {"terms": {"field": "documento_assunto", "size": 10}},
                    "by_ano": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"
                        }
                    },
                    "by_mes": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"
                        }
                    },
                    "com_documento": {"filter": {"term": {"has_documento": True}}},
                    "com_texto": {"filter": {"term": {"has_texto": True}}},
                    "com_valor": {
                        "filter": {"exists": {"field": "documento_valor"}},
                        "aggs": {
                            "total": {"sum": {"field": "documento_valor"}},
                            "medio": {"avg": {"field": "documento_valor"}},
                            "maximo": {"max": {"field": "documento_valor"}},
                        },
                    },
                },
            },
        )
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        out["referencias"] = aggs.get("referencias", {}).get("value", 0)
        out["processos"] = aggs.get("processos", {}).get("value", 0)
        out["tribunais"] = aggs.get("tribunais", {}).get("value", 0)
        out["citados"] = aggs.get("citados", {}).get("value", 0)
        out["nifs"] = aggs.get("nifs", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["with_documento"] = aggs.get("com_documento", {}).get("doc_count", 0)
        out["with_texto"] = aggs.get("com_texto", {}).get("doc_count", 0)
        valor = aggs.get("com_valor", {}) or {}
        out["with_valor"] = valor.get("doc_count", 0)
        out["valor_total"] = round(float((valor.get("total") or {}).get("value") or 0.0), 2)
        out["valor_medio"] = (
            round(float((valor.get("medio") or {}).get("value")), 2)
            if isinstance((valor.get("medio") or {}).get("value"), (int, float))
            else None
        )
        out["valor_maximo"] = round(float((valor.get("maximo") or {}).get("value") or 0.0), 2) or None
        out["by_tipo"] = _buckets("by_tipo")
        out["top_comarcas"] = _buckets("by_comarca")
        out["top_comarcas_judiciais"] = _buckets("by_comarca_judicial")
        out["top_tribunais"] = _buckets("by_tribunal")
        out["top_actos"] = _buckets("by_ato")
        out["by_papel"] = _buckets("by_papel")
        out["top_modelos"] = _buckets("by_modelo")
        out["top_assuntos"] = _buckets("by_assunto")
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        out["by_mes"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_mes", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}


def get_citacao(pub_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um édito pelo ``pub_id`` (documento completo, com o texto extraído)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = client.get(index=CITACOES_INDEX, id=f"{CITACOES_INDEX}:{pub_id}")
    except Exception as exc:  # noqa: BLE001
        return {"pub_id": pub_id, "error": str(exc)}
    source = dict(resp.get("_source") or {})
    source["doc_id"] = resp.get("_id")
    return source


def citacoes_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id`` (para a lista de recolhas)."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=CITACOES_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"by_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_run", {}).get("buckets", [])
        }
    except Exception:
        return {}



# --- Pessoas e cargos extraídos do societário ---

# Campos que identificam um cargo, para o deduplicar ao juntar fichas da mesma pessoa.
_PEOPLE_ROLE_KEYS = ("publication_id", "company_nif", "role", "event", "date")


def _person_role_key(role: Dict[str, Any]) -> tuple:
    """Chave de deduplicação de um cargo (publicação + empresa + cargo + evento + data)."""
    return tuple(str(role.get(key) or "") for key in _PEOPLE_ROLE_KEYS)


def _merge_person_docs(
    existing: Optional[Dict[str, Any]],
    incoming: Dict[str, Any],
    drop_company_nif: Optional[str] = None,
    drop_role_org: Optional[str] = None,
) -> Dict[str, Any]:
    """Junta uma ficha guardada com a recém-extraída sem perder cargos de outras empresas.

    A extração é feita **por empresa** (as publicações são pesquisadas por NIF),
    mas o documento `finance_people:{nif}` é único por pessoa: indexar apenas o
    resultado da empresa A substituiria os cargos que a mesma pessoa tem na
    empresa B. Aqui os cargos são acumulados. Quando é uma reingestão
    (``drop_company_nif``) os cargos antigos dessa empresa são descartados; com
    ``drop_role_org`` (ex.: `CIRE`) descartam-se os cargos dessa origem, para não
    deixar registos obsoletos.
    """
    merged: Dict[str, Any] = dict(existing or {})
    merged.update({k: v for k, v in incoming.items() if k not in ("roles", "sources")})

    roles: List[Dict[str, Any]] = list(incoming.get("roles") or [])
    for role in (existing or {}).get("roles") or []:
        if drop_company_nif and str(role.get("company_nif") or "") == str(drop_company_nif):
            continue
        if drop_role_org and str(role.get("role_org") or "") == str(drop_role_org):
            continue
        roles.append(role)

    seen_roles: set = set()
    unique: List[Dict[str, Any]] = []
    for role in roles:
        key = _person_role_key(role)
        if key in seen_roles:
            continue
        seen_roles.add(key)
        unique.append(role)
    unique.sort(key=lambda role: str(role.get("date") or ""), reverse=True)

    companies: List[Dict[str, str]] = []
    seen_companies: set = set()
    latest: Dict[str, Dict[str, Any]] = {}
    for role in unique:
        cnif = role.get("company_nif")
        if cnif and cnif not in seen_companies:
            seen_companies.add(cnif)
            companies.append({"nif": cnif, "name": role.get("company_name") or cnif})
        latest.setdefault(str(cnif or ""), role)

    dates = [str(role["date"]) for role in unique if role.get("date")]
    name = str(merged.get("name") or "")
    if len(str(incoming.get("name") or "")) > len(name):
        name = str(incoming["name"])

    merged.update({
        "name": name,
        "name_keyword": name,
        "roles": unique,
        "companies": companies,
        "companies_count": len(companies),
        "roles_count": len(unique),
        "latest_roles": list(latest.values()),
        "first_seen": min(dates) if dates else merged.get("first_seen"),
        "last_seen": max(dates) if dates else merged.get("last_seen"),
    })
    # Fontes: a ficha pode vir do societário e ser enriquecida pelo CIRE (e vice-versa).
    sources = _person_sources(existing, incoming)
    if sources:
        merged["sources"] = sources
        # `source` fica com a fonte primária (a que criou a ficha).
        merged["source"] = sources[0]
    return merged


def _person_sources(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> List[str]:
    """União ordenada das fontes que alimentaram a ficha (`sources` + `source`)."""
    sources: List[str] = []
    for doc in (existing or {}, incoming or {}):
        for value in (doc.get("sources"), doc.get("source")):
            values = [value] if isinstance(value, str) else list(value or [])
            for item in values:
                item = str(item or "").strip()
                if item and item not in sources:
                    sources.append(item)
    return sources


def _fetch_people_docs(
    nifs: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Dict[str, Any]]:
    """Fichas já indexadas dos NIF indicados (``nif`` -> ``_source``)."""
    client = es or get_es_client()
    wanted = list(dict.fromkeys(str(n).strip() for n in nifs if str(n or "").strip()))
    if not client or not wanted:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(wanted), 500):
        batch = wanted[start : start + 500]
        try:
            resp = client.mget(index=PEOPLE_INDEX, ids=[f"{PEOPLE_INDEX}:{n}" for n in batch])
        except Exception as exc:
            logger.debug("mget de pessoas falhou: %s", exc)
            continue
        for doc in resp.get("docs", []):
            source = doc.get("_source")
            if doc.get("found") and isinstance(source, dict):
                nif = str(source.get("nif") or str(doc.get("_id") or "").split(":")[-1])
                out[nif] = source
    return out


def people_index_presence(nifs: Iterable[str], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indica quais dos NIF indicados já têm ficha no PessoasIQ (`finance_people`)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "indexed": [], "missing": []}
    ensure_indices(client)

    wanted = list(dict.fromkeys(str(n).strip() for n in nifs if str(n or "").strip()))
    if not wanted:
        return {"total": 0, "indexed": [], "missing": []}

    found = set(_fetch_people_docs(wanted, es=client))
    return {
        "total": len(wanted),
        "indexed": [nif for nif in wanted if nif in found],
        "missing": [nif for nif in wanted if nif not in found],
    }


def index_people(
    people: Iterable[Dict[str, Any]],
    merge: bool = True,
    drop_company_nif: Optional[str] = None,
    drop_role_org: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa fichas de pessoas no `finance_people` (um documento por NIF).

    Com ``merge`` (por omissão) os cargos já indexados são preservados, para que
    processar as publicações de uma empresa não apague os cargos da mesma pessoa
    noutras empresas. ``drop_company_nif`` / ``drop_role_org`` descartam os cargos
    obsoletos da empresa / da origem que está a ser reingerida.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    docs: List[Dict[str, Any]] = []
    for person in people:
        nif = str((person or {}).get("nif") or "").strip()
        if not nif:
            continue
        doc = {k: v for k, v in person.items() if v is not None}
        doc["nif"] = nif
        doc.setdefault("sources", [doc.get("source")] if doc.get("source") else [])
        docs.append(doc)
    if not docs:
        return {"indexed_count": 0, "total": 0}

    previous = _fetch_people_docs([d["nif"] for d in docs], es=client) if merge else {}
    now = _today()
    actions = []
    for doc in docs:
        base = previous.get(doc["nif"])
        if base:
            doc = _merge_person_docs(
                base,
                doc,
                drop_company_nif=drop_company_nif,
                drop_role_org=drop_role_org,
            )
        doc["ingested_at"] = now
        actions.append({
            "_op_type": "index",
            "_index": PEOPLE_INDEX,
            "_id": f"{PEOPLE_INDEX}:{doc['nif']}",
            **doc,
        })

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}


def _prune_people_company_roles(
    company_nif: str,
    keep_nifs: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove cargos obsoletos de uma empresa, apagando as fichas que fiquem sem cargos.

    Numa reingestão, as pessoas que já não constam das publicações da empresa
    deixam de ter lá cargos; se não tiverem cargos noutras empresas, a ficha é
    removida (senão ficaria uma pessoa vazia no PessoasIQ).
    """
    client = es or get_es_client()
    if not client or not company_nif:
        return 0
    keep = {str(n) for n in keep_nifs}
    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "query": {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": str(company_nif)}}}},
                "size": 2000,
            },
        )
    except Exception as exc:
        logger.debug("prune de pessoas ignorado: %s", exc)
        return 0

    now = _today()
    actions: List[Dict[str, Any]] = []
    to_delete: List[str] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        nif = str(source.get("nif") or "")
        if nif in keep:
            continue
        doc = _merge_person_docs(source, {"nif": nif, "roles": []}, drop_company_nif=str(company_nif))
        if not doc.get("roles"):
            to_delete.append(hit["_id"])
            continue
        doc["ingested_at"] = now
        actions.append({"_op_type": "index", "_index": PEOPLE_INDEX, "_id": hit["_id"], **doc})

    if actions:
        try:
            bulk(client, actions, raise_on_error=False, refresh=False)
        except Exception as exc:
            logger.debug("prune de pessoas (update) falhou: %s", exc)
    if to_delete:
        try:
            client.delete_by_query(
                index=PEOPLE_INDEX,
                body={"query": {"terms": {"_id": to_delete}}},
                refresh=False,
            )
        except Exception as exc:
            logger.debug("prune de pessoas (delete) falhou: %s", exc)
    try:
        client.indices.refresh(index=PEOPLE_INDEX)
    except Exception:
        pass
    return len(actions) + len(to_delete)


def _publicacoes_for_people(
    nif: Optional[str],
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Publicações societárias a usar na extração de pessoas (de uma entidade ou todas)."""
    client = es or get_es_client()
    if not client:
        return []
    if nif:
        return (company_publicacoes(str(nif), size=1000, es=client) or {}).get("items", [])

    items: List[Dict[str, Any]] = []
    offset = 0
    while offset < 20000:
        page = search_societario(size=200, from_=offset, es=client)
        batch = page.get("items", [])
        items.extend(batch)
        if len(batch) < 200:
            break
        offset += len(batch)
    return items


def index_people_from_societario(
    nif: Optional[str] = None,
    replace_for_nif: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa pessoas/cargos extraídos das publicações societárias.

    Se ``nif`` for dado, processa apenas as publicações dessa entidade (caso
    contrário percorre o índice societário completo). Se ``replace_for_nif`` for
    dado, os cargos dessa empresa que já não constem da recolha são removidos —
    os cargos da mesma pessoa noutras empresas são preservados.
    """
    from collectors.people_extractor import extract_from_publicacoes

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    target_nif = nif or replace_for_nif
    items = _publicacoes_for_people(str(target_nif) if target_nif else None, es=client)
    if not items:
        return {"indexed_count": 0, "total": 0, "nif": target_nif}

    people = extract_from_publicacoes(items)
    result = index_people(
        people,
        drop_company_nif=str(replace_for_nif) if replace_for_nif else None,
        es=client,
    )
    if replace_for_nif:
        result["pruned"] = _prune_people_company_roles(
            str(replace_for_nif), [p.get("nif") for p in people], es=client
        )
    result["nif"] = target_nif
    return result


#: Campos do CIRE necessários para extrair pessoas.
_CIRE_PEOPLE_FIELDS = (
    "pub_id",
    "data_publicacao",
    "processo",
    "processo_numero",
    "especie",
    "ato",
    "tribunal_comarca",
    "tribunal",
    "insolvente",
    "intervenientes",
)


def _iter_cire_publications(
    client: Elasticsearch,
    *,
    limit: Optional[int] = None,
    page_size: int = 2000,
    progress: Optional[Dict[str, Any]] = None,
) -> Any:
    """Percorre as publicações do CIRE (com intervenientes), com `search_after`."""
    body: Dict[str, Any] = {
        "size": page_size,
        # `intervenientes` é `nested`: um `exists` direto não encontra nada.
        "query": {"nested": {"path": "intervenientes", "query": {"match_all": {}}}},
        "_source": list(_CIRE_PEOPLE_FIELDS),
        "sort": [{"pub_id": "asc"}],
    }
    emitted = 0
    search_after: Optional[List[Any]] = None
    while True:
        if search_after:
            body["search_after"] = search_after
        try:
            resp = client.search(index=CIRE_INDEX, body=body)
        except Exception as exc:
            logger.warning("Leitura do CIRE para pessoas falhou: %s", exc)
            break
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            break
        for hit in hits:
            yield hit.get("_source") or {}
            emitted += 1
            if limit and emitted >= limit:
                if progress is not None:
                    progress["publications"] = emitted
                return
        search_after = hits[-1].get("sort")
        if progress is not None:
            progress["publications"] = emitted
        if not search_after or len(hits) < page_size:
            break


def index_people_from_cire(
    *,
    limit: Optional[int] = None,
    include_companies: bool = False,
    papeis: Optional[Iterable[str]] = None,
    write_chunk: int = 1000,
    progress: Optional[Dict[str, Any]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa no PessoasIQ as pessoas que constam dos processos do CIRE.

    Percorre `finance_cire` (publicações com intervenientes), transforma cada
    interveniente pessoa singular num cargo (`role_org = CIRE`) e junta-o à ficha
    da pessoa em `finance_people`. Os cargos do CIRE já indexados são substituídos
    (``drop_role_org``), mas os cargos do societário são preservados.

    ``papeis`` filtra os papéis a considerar (ex.: `["Insolvente", "Administrador
    da insolvência"]`); ``include_companies`` inclui pessoas coletivas (por
    omissão só entram pessoas singulares).
    """
    from collectors.cire_people import (
        CIRE_ROLE_ORG,
        aggregate_cire_people,
        extract_people_from_cire,
    )

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    if progress is not None:
        progress.setdefault("phase", "a ler o CIRE")
    records: List[Dict[str, Any]] = []
    publications = 0
    for pub in _iter_cire_publications(client, limit=limit, progress=progress):
        publications += 1
        records.extend(
            extract_people_from_cire(pub, papeis=papeis, include_companies=include_companies)
        )

    if progress is not None:
        progress["phase"] = "a agregar por pessoa"
        progress["intervenientes"] = len(records)

    people = aggregate_cire_people(records)
    if not people:
        return {
            "indexed_count": 0,
            "total": 0,
            "publications": publications,
            "intervenientes": len(records),
            "message": "Sem pessoas a indexar a partir do CIRE.",
        }

    if progress is not None:
        progress["phase"] = "a indexar"
        progress["people"] = len(people)

    indexed = 0
    errors = 0
    chunk = max(1, int(write_chunk or 1000))
    for start in range(0, len(people), chunk):
        batch = people[start : start + chunk]
        result = index_people(batch, drop_role_org=CIRE_ROLE_ORG, es=client)
        indexed += int(result.get("indexed_count") or 0)
        errors += int(result.get("errors") or 0)
        if progress is not None:
            progress["indexed"] = indexed
            progress["errors"] = errors
        if result.get("error"):
            logger.warning("Indexação de pessoas do CIRE falhou: %s", result["error"])
            return {
                "error": result["error"],
                "indexed_count": indexed,
                "total": len(people),
                "publications": publications,
                "intervenientes": len(records),
                "errors": errors,
            }

    return {
        "indexed_count": indexed,
        "total": len(people),
        "publications": publications,
        "intervenientes": len(records),
        "errors": errors,
        "source": CIRE_ROLE_ORG.lower(),
    }


def _person_from_publications(nif: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Reconstrói a ficha de uma pessoa a partir das publicações que a mencionam.

    Rede de segurança para pessoas que aparecem no societário mas cujas
    publicações ainda não foram processadas para o índice `finance_people`.
    """
    from collectors.people_extractor import extract_from_publicacoes

    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.search(
            index=SOCIETARIO_INDEX,
            body={
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"texto": str(nif)}},
                            {"term": {"nif": str(nif)}},
                            {"match": {"requerente": str(nif)}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "size": 500,
            },
        )
        items = [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])]
    except Exception as exc:
        logger.debug("Ficha de %s a partir das publicações falhou: %s", nif, exc)
        return None

    for person in extract_from_publicacoes(items):
        if str(person.get("nif")) == str(nif):
            return person
    return None


def get_person_by_nif(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve ficha de uma pessoa pelo NIF.

    Se ainda não estiver em `finance_people` (o índice é alimentado pelas
    publicações societárias processadas), a ficha é reconstruída a partir das
    publicações que mencionam o NIF e fica indexada — abrir uma pessoa a partir
    do dossiê de uma empresa não deve falhar por falta de ingestão.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    nif = str(nif).strip()
    try:
        resp = client.get(index=PEOPLE_INDEX, id=f"{PEOPLE_INDEX}:{nif}", _source=True)
        return {**resp.get("_source", {}), "doc_id": resp.get("_id")}
    except NotFoundError:
        pass
    except Exception as exc:
        return {"nif": nif, "error": str(exc)}

    person = _person_from_publications(nif, es=client)
    if not person:
        return {"nif": nif, "error": "Pessoa não encontrada nas publicações societárias indexadas"}

    index_people([person], es=client)
    stored = _fetch_people_docs([nif], es=client).get(nif)
    return {**(stored or person), "doc_id": f"{PEOPLE_INDEX}:{nif}", "derived": True}


def search_people(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    company_nif: Optional[str] = None,
    role: Optional[str] = None,
    is_company: Optional[bool] = None,
    origin: Optional[str] = None,
    min_roles: Optional[int] = None,
    min_companies: Optional[int] = None,
    sort: str = "relevance",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa no índice finance_people (com filtros).

    - ``q``: nome (frase/termos) ou NIF;
    - ``role``: cargo/papel (contém, sem distinguir maiúsculas) — ex.: `Credor`;
    - ``company_nif``: tem de ter um cargo nessa empresa;
    - ``origin``: `cire` (papéis do CIRE) ou `societario` (cargos das publicações do MJ);
    - ``min_roles`` / ``min_companies``: nº mínimo de cargos/empresas na ficha;
    - ``sort``: `relevance` (por omissão, com mais cargos primeiro), `roles`, `recent`.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    nested_filters: List[Dict[str, Any]] = []

    if q:
        # Sem `operator: and` (e sem a frase completa) uma pesquisa por nome
        # completo devolvia quase todo o índice — os nomes partilham termos.
        must.append({
            "bool": {
                "should": [
                    {"term": {"nif": str(q)}},
                    {"match_phrase": {"name": {"query": q, "boost": 6}}},
                    {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
                    {"match": {"name.autocomplete": {"query": q, "operator": "and"}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if nif:
        filters.append({"term": {"nif": str(nif)}})
    if is_company is not None:
        filters.append({"term": {"is_company": bool(is_company)}})
    if min_roles is not None:
        filters.append({"range": {"roles_count": {"gte": int(min_roles)}}})
    if min_companies is not None:
        filters.append({"range": {"companies_count": {"gte": int(min_companies)}}})
    if company_nif:
        nested_filters.append({
            "nested": {
                "path": "roles",
                "query": {"term": {"roles.company_nif": str(company_nif)}},
            }
        })
    if role:
        nested_filters.append({
            "nested": {
                "path": "roles",
                # `wildcard` sem `case_insensitive` não encontra cargos com maiúsculas
                # (o campo é keyword e mantém o texto original).
                "query": {
                    "wildcard": {
                        "roles.role": {"value": f"*{role}*", "case_insensitive": True},
                    }
                },
            }
        })
    if origin:
        wanted = str(origin).strip().lower()
        if wanted in ("cire", "societario", "societário"):
            # CIRE = cargos com `role_org = CIRE`; societário = todos os outros.
            condition = {"term": {"roles.role_org": "CIRE"}}
            nested_filters.append({
                "nested": {
                    "path": "roles",
                    "query": condition if wanted == "cire" else {"bool": {"must_not": [condition]}},
                }
            })

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    if nested_filters:
        bool_query.setdefault("filter", []).extend(nested_filters)

    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    sort_spec: List[Any]
    if sort == "roles":
        sort_spec = [{"roles_count": {"order": "desc"}}, {"last_seen": {"order": "desc"}}, "_score"]
    elif sort == "recent":
        sort_spec = [{"last_seen": {"order": "desc"}}, {"roles_count": {"order": "desc"}}]
    elif sort == "name":
        sort_spec = [{"name.keyword": {"order": "asc"}}]
    else:
        sort_spec = [{"_score": {"order": "desc"}}, {"roles_count": {"order": "desc"}}]

    body = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "sort": sort_spec,
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        return {
            "total": total,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "filters": {
                "q": q or None,
                "role": role or None,
                "company_nif": company_nif or None,
                "origin": origin or None,
                "is_company": is_company,
                "min_roles": min_roles,
                "min_companies": min_companies,
                "sort": sort,
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def people_autocomplete(
    q: str,
    *,
    limit: int = 8,
    is_company: Optional[bool] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de pessoas/entidades para o autocomplete (nome, NIF e cargo).

    Usa o analisador de prefixo (`name.autocomplete`) para sugerir enquanto se
    escreve, com o nome, o NIF, o nº de cargos/empresas e um cargo recente — o
    suficiente para escolher a pessoa certa sem fazer a pesquisa completa.
    """
    client = es or get_es_client()
    term = str(q or "").strip()
    if not client or len(term) < 2:
        return {"q": term, "items": []}
    ensure_indices(client)

    should: List[Dict[str, Any]] = [
        {"term": {"nif": {"value": term, "boost": 8}}},
        {"match_phrase_prefix": {"name": {"query": term, "boost": 5, "max_expansions": 30}}},
        {"match": {"name.autocomplete": {"query": term, "operator": "and", "boost": 2}}},
    ]
    body: Dict[str, Any] = {
        "size": max(1, min(int(limit or 8), 25)),
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
        "_source": ["nif", "name", "name_keyword", "is_company", "roles_count", "companies_count", "latest_roles", "sources", "last_seen"],
        "sort": ["_score", {"roles_count": {"order": "desc"}}],
    }
    if is_company is not None:
        body["query"]["bool"]["filter"] = [{"term": {"is_company": bool(is_company)}}]

    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        return {"q": term, "items": [], "error": str(exc)}

    items: List[Dict[str, Any]] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        latest = (source.get("latest_roles") or [])
        role = latest[0] if latest and isinstance(latest[0], dict) else {}
        items.append({
            "nif": source.get("nif"),
            "name": source.get("name_keyword") or source.get("name") or "",
            "is_company": bool(source.get("is_company")),
            "roles_count": int(source.get("roles_count") or 0),
            "companies_count": int(source.get("companies_count") or 0),
            "role": role.get("role"),
            "company_name": role.get("company_name"),
            "origin": (source.get("sources") or [None])[0] if source.get("sources") else None,
            "last_seen": source.get("last_seen"),
        })
    return {"q": term, "items": items}


def people_filters(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Facetas para os filtros da pesquisa de pessoas (cargos, origens e tipos)."""
    client = es or get_es_client()
    if not client:
        return {"available": False}
    ensure_indices(client)
    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "roles": {"nested": {"path": "roles"}, "aggs": {"top": {"terms": {"field": "roles.role", "size": 40}}}},
                    "origins": {"terms": {"field": "source", "size": 10}},
                    "types": {"terms": {"field": "is_company", "size": 5}},
                    "with_cire": {
                        "nested": {"path": "roles"},
                        "aggs": {"cire": {"filter": {"term": {"roles.role_org": "CIRE"}}}},
                    },
                },
            },
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    aggs = resp.get("aggregations", {})
    return {
        "available": True,
        "roles": [
            {"key": bucket["key"], "count": bucket["doc_count"]}
            for bucket in aggs.get("roles", {}).get("top", {}).get("buckets", [])
        ],
        "origins": [
            {"key": bucket["key"], "count": bucket["doc_count"]}
            for bucket in aggs.get("origins", {}).get("buckets", [])
        ],
        "types": [
            {"key": "company" if bucket["key"] else "person", "count": bucket["doc_count"]}
            for bucket in aggs.get("types", {}).get("buckets", [])
        ],
        "with_cire": aggs.get("with_cire", {}).get("cire", {}).get("doc_count", 0),
    }


def cire_person_processes(
    nif: str,
    *,
    size: int = 200,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Processos do CIRE em que um NIF participa, com papéis e co-intervenientes.

    Serve a análise 360 de uma pessoa: quantos processos tem, em que papéis
    (insolvente, devedor, credor, administrador da insolvência…) e com quem
    contracena. A lista de processos é limitada a ``size`` (os mais recentes),
    pelo que a contagem de co-intervenientes é uma **amostra** — o `total` de
    processos vem do próprio Elasticsearch.
    """
    client = es or get_es_client()
    nif = str(nif or "").strip()
    empty: Dict[str, Any] = {
        "total": 0,
        "sampled": 0,
        "processes": [],
        "by_papel": [],
        "co_intervenientes": [],
        "tribunais": [],
        "years": [],
    }
    if not client or not nif:
        return empty
    ensure_indices(client)

    try:
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": max(1, min(int(size), 1000)),
                "query": {"term": {"nifs": nif}},
                "_source": [
                    "pub_id",
                    "data_publicacao",
                    "processo",
                    "processo_numero",
                    "especie",
                    "tipo",
                    "ato",
                    "tribunal",
                    "tribunal_comarca",
                    "insolvente",
                    "intervenientes",
                    "has_documento",
                    "documento_url",
                ],
                "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
            },
        )
    except Exception as exc:
        return {**empty, "error": str(exc)}

    hits = resp.get("hits", {}).get("hits", []) or []
    total = resp.get("hits", {}).get("total", 0)
    total_value = int((total.get("value", 0) if isinstance(total, dict) else total) or 0)

    from collections import Counter

    papeis: Counter = Counter()
    comarcas: Counter = Counter()
    anos: Counter = Counter()
    co: Dict[str, Dict[str, Any]] = {}
    processes: List[Dict[str, Any]] = []

    for hit in hits:
        source = hit.get("_source") or {}
        intervenientes = [i for i in (source.get("intervenientes") or []) if isinstance(i, dict)]
        meus = []
        seen_papeis: set = set()
        for item in intervenientes:
            if str(item.get("nif") or "").strip() == nif:
                papel = str(item.get("papel") or "").strip() or "Interveniente"
                # Uma publicação conta uma vez por papel (o mesmo NIF pode aparecer
                # repetido na lista de intervenientes).
                if papel not in seen_papeis:
                    seen_papeis.add(papel)
                    papeis[papel] += 1
                if papel not in meus:
                    meus.append(papel)
        data = source.get("data_publicacao") or ""
        if data[:4].isdigit():
            anos[data[:4]] += 1
        comarca = str(source.get("tribunal_comarca") or "").strip()
        if comarca:
            comarcas[comarca] += 1

        outros = []
        for item in intervenientes:
            outro_nif = str(item.get("nif") or "").strip()
            if not outro_nif or outro_nif == nif:
                continue
            entry = co.setdefault(outro_nif, {"nif": outro_nif, "name": "", "papeis": Counter(), "processes": 0})
            nome = str(item.get("nome") or "").strip()
            if nome and (not entry["name"] or len(nome) > len(entry["name"])):
                entry["name"] = nome
            entry["papeis"][str(item.get("papel") or "Interveniente").strip()] += 1
            entry["processes"] += 1
            outros.append({"nif": outro_nif, "name": nome, "papel": str(item.get("papel") or "")})

        processes.append({
            "pub_id": source.get("pub_id") or str(hit.get("_id", "")).split(":")[-1],
            "processo": source.get("processo_numero") or source.get("processo") or "",
            "especie": source.get("especie") or source.get("tipo") or "",
            "tribunal": source.get("tribunal_comarca") or source.get("tribunal") or "",
            "date": data or None,
            "insolvente": source.get("insolvente") or "",
            "papeis": meus,
            "intervenientes": len(intervenientes),
            "co_intervenientes": outros[:12],
            "has_documento": bool(source.get("has_documento")),
        })

    co_intervenientes = [
        {
            "nif": entry["nif"],
            "name": entry["name"] or entry["nif"],
            "processes": entry["processes"],
            "papeis": [{"key": key, "count": value} for key, value in entry["papeis"].most_common(3)],
        }
        for entry in sorted(co.values(), key=lambda item: -item["processes"])
    ]

    return {
        "total": total_value,
        "sampled": len(processes),
        "processes": processes,
        "by_papel": [{"key": key, "count": value} for key, value in papeis.most_common(20)],
        "co_intervenientes": co_intervenientes[:60],
        "tribunais": [{"key": key, "count": value} for key, value in comarcas.most_common(10)],
        "years": [{"key": key, "count": value} for key, value in sorted(anos.items(), reverse=True)[:12]],
    }


def _node_summary_id(node_id: str) -> str:
    return f"{NODE_SUMMARIES_INDEX}:{node_id}"


def index_node_summary(doc: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) o resumo de um nó de grafo.

    Um documento por nó (`node_id` = `person:<nif>`, `company:<nif>`,
    `source:<host>`), com o texto, a evidência e os factos usados. Cada gravação
    conta em `generations` e atualiza `generated_at`/`ingested_at`, para se saber
    quantas vezes o resumo foi refeito e quando.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "saved": False}
    node_id = str((doc or {}).get("node_id") or "").strip()
    if not node_id:
        return {"error": "Resumo sem `node_id`.", "saved": False}
    ensure_indices(client)

    previous = get_node_summary(node_id, es=client) or {}
    generations = int(previous.get("generations") or 0) + 1
    now = _today()
    payload: Dict[str, Any] = {
        "node_id": node_id,
        "nif": str(doc.get("nif") or "")[:32],
        "name": str(doc.get("name") or "")[:512],
        "kind": str(doc.get("kind") or "")[:32],
        "summary": str(doc.get("summary") or ""),
        "mode": str(doc.get("mode") or "factual")[:32],
        "provider": str(doc.get("provider") or "")[:64],
        "model": str(doc.get("model") or "")[:128],
        "queries": [str(q)[:512] for q in (doc.get("queries") or [])][:12],
        "evidence": (doc.get("evidence") or [])[:40],
        "facts": doc.get("facts") or {},
        "evidence_count": len(doc.get("evidence") or []),
        "pages_read": int(doc.get("pages_read") or 0),
        "generations": generations,
        "generated_at": doc.get("generated_at") or now,
        "ingested_at": now,
    }
    try:
        client.index(index=NODE_SUMMARIES_INDEX, id=_node_summary_id(node_id), document=payload, refresh=True)
        return {"saved": True, "node_id": node_id, "generations": generations, "generated_at": payload["generated_at"]}
    except Exception as exc:
        return {"error": str(exc), "saved": False}


def get_node_summary(
    node_id: Optional[str] = None,
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Resumo já guardado de um nó (por `node_id`, ou por NIF/nome como recurso)."""
    client = es or get_es_client()
    if not client:
        return {}
    ensure_indices(client)
    node_id = str(node_id or "").strip()
    try:
        if node_id:
            resp = client.get(index=NODE_SUMMARIES_INDEX, id=_node_summary_id(node_id), _source=True)
            source = resp.get("_source")
            if isinstance(source, dict):
                return source
            return {}
        query: Dict[str, Any] = {"match_all": {}}
        if nif:
            query = {"term": {"nif": str(nif)}}
        elif name:
            query = {"match": {"name": str(name)}}
        resp = client.search(
            index=NODE_SUMMARIES_INDEX,
            body={"size": 1, "query": query, "sort": [{"generated_at": {"order": "desc"}}]},
        )
        hits = resp.get("hits", {}).get("hits", [])
        return (hits[0].get("_source") if hits else {}) or {}
    except Exception as exc:
        logger.debug("Resumo de nó %s não encontrado: %s", node_id or nif or name, exc)
        return {}


def node_summaries_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de resumos (total, por tipo de nó e por modo)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0}
    ensure_indices(client)
    try:
        count = int(client.count(index=NODE_SUMMARIES_INDEX).get("count", 0) or 0)
        out: Dict[str, Any] = {"available": True, "index": NODE_SUMMARIES_INDEX, "total": count}
        if count:
            resp = client.search(
                index=NODE_SUMMARIES_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "kinds": {"terms": {"field": "kind", "size": 10}},
                        "modes": {"terms": {"field": "mode", "size": 10}},
                        "latest": {"max": {"field": "generated_at"}},
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["kinds"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("kinds", {}).get("buckets", [])]
            out["modes"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("modes", {}).get("buckets", [])]
            out["latest"] = aggs.get("latest", {}).get("value_as_string")
        return out
    except Exception as exc:
        return {"available": False, "error": str(exc), "total": 0}


#: Limites dos grafos de pessoas: com centenas de cargos o grafo fica ilegível (e o
#: browser lento), por isso agrega-se **uma aresta por empresa** e mostra-se só o
#: topo por número de cargos/atividade recente.
PEOPLE_GRAPH_MAX_COMPANIES = int(os.getenv("PEOPLE_GRAPH_MAX_COMPANIES", "60"))
PEOPLE_GRAPH_MAX_PEOPLE = int(os.getenv("PEOPLE_GRAPH_MAX_PEOPLE", "60"))


def people_graph_for_person(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Constrói grafo pessoa->empresas a partir dos cargos (agregado por empresa).

    Uma aresta por empresa (com o total de cargos e o cargo mais recente) e apenas
    as `PEOPLE_GRAPH_MAX_COMPANIES` empresas com mais cargos — é o que mantém o
    grafo legível e rápido mesmo para quem tem centenas de processos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    person = get_person_by_nif(str(nif), es=client)
    if person.get("error"):
        return {"error": person["error"], "nodes": [], "edges": []}

    nodes: Dict[str, Dict[str, Any]] = {}
    person_id = f"person:{nif}"
    nodes[person_id] = {
        "id": person_id,
        "type": "person",
        "label": person.get("name", nif),
        "nif": nif,
        "is_company": person.get("is_company", False),
    }

    by_company: Dict[str, Dict[str, Any]] = {}
    for role in person.get("roles", []):
        cnif = str(role.get("company_nif") or "")
        if not cnif:
            continue
        entry = by_company.setdefault(cnif, {
            "name": role.get("company_name") or cnif,
            "count": 0,
            "roles": [],
            "latest": None,
        })
        entry["count"] += 1
        label = str(role.get("role") or "")
        if label and label not in entry["roles"]:
            entry["roles"].append(label)
        if role.get("company_name") and len(str(role["company_name"])) > len(str(entry["name"])):
            entry["name"] = role["company_name"]
        if role.get("date") and (not entry["latest"] or str(role["date"]) > str(entry["latest"].get("date") or "")):
            entry["latest"] = role

    edges: List[Dict[str, Any]] = []
    ranked = sorted(by_company.items(), key=lambda kv: (-kv[1]["count"], str(kv[1]["name"])))[:PEOPLE_GRAPH_MAX_COMPANIES]
    for cnif, entry in ranked:
        company_id = f"company:{cnif}"
        nodes[company_id] = {
            "id": company_id,
            "type": "company",
            "label": entry["name"],
            "nif": cnif,
            "is_company": True,
        }
        latest = entry["latest"] or {}
        edges.append({
            "source": person_id,
            "target": company_id,
            "label": latest.get("role", "") or (entry["roles"][0] if entry["roles"] else ""),
            "type": "role",
            "role": latest.get("role", "") or (entry["roles"][0] if entry["roles"] else ""),
            "role_org": latest.get("role_org", ""),
            "event": latest.get("event", ""),
            "date": latest.get("date"),
            "acto": latest.get("acto", ""),
            "quota": latest.get("quota"),
            # Cargos não são euros: `count` é o nº de cargos nessa empresa e é o
            # que engrossa a aresta. `value` fica a 0 (só contratos têm valor).
            "count": entry["count"],
            "value": 0.0,
        })

    return {
        "person_nif": nif,
        "person_name": person.get("name"),
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "companies_total": len(by_company),
            "companies_shown": len(ranked),
            "grouped": True,
        },
    }


def people_graph_for_company(company_nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Constrói grafo de todas as pessoas ligadas a uma empresa (uma aresta por pessoa)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "query": {
                    "nested": {
                        "path": "roles",
                        "query": {"term": {"roles.company_nif": str(company_nif)}},
                    }
                },
                "size": 500,
            },
        )
        people = [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

    company_id = f"company:{company_nif}"
    nodes: Dict[str, Dict[str, Any]] = {
        company_id: {
            "id": company_id,
            "type": "company",
            "label": company_nif,
            "nif": company_nif,
            "is_company": True,
        }
    }
    edges: List[Dict[str, Any]] = []
    ranked: List[tuple] = []

    for person in people:
        pnif = person.get("nif")
        if not pnif:
            continue
        relevant = [role for role in person.get("roles", []) if role.get("company_nif") == company_nif]
        if not relevant:
            continue
        latest = max(relevant, key=lambda role: str(role.get("date") or ""))
        ranked.append((len(relevant), person, latest))

    ranked.sort(key=lambda item: -item[0])
    for count, person, latest in ranked[:PEOPLE_GRAPH_MAX_PEOPLE]:
        pnif = person.get("nif")
        person_id = f"person:{pnif}"
        company = nodes[company_id]
        if company["label"] in (company_nif, ""):
            company["label"] = latest.get("company_name") or company_nif
        nodes[person_id] = {
            "id": person_id,
            "type": "person",
            "label": person.get("name", pnif),
            "nif": pnif,
            "is_company": person.get("is_company", False),
        }
        edges.append({
            "source": person_id,
            "target": company_id,
            "label": latest.get("role", ""),
            "type": "role",
            "role": latest.get("role", ""),
            "role_org": latest.get("role_org", ""),
            "event": latest.get("event", ""),
            "date": latest.get("date"),
            "acto": latest.get("acto", ""),
            "quota": latest.get("quota"),
            # `count` = nº de cargos (não euros).
            "count": count,
            "value": 0.0,
        })

    return {
        "company_nif": company_nif,
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {"people_total": len(ranked), "people_shown": min(len(ranked), PEOPLE_GRAPH_MAX_PEOPLE), "grouped": True},
    }


def people_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria rápida do índice de pessoas/cargos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=PEOPLE_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": PEOPLE_INDEX, "documents": count}
        if count:
            resp = client.search(
                index=PEOPLE_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "is_company": {"terms": {"field": "is_company", "size": 5}},
                        "companies_stats": {"sum": {"field": "companies_count"}},
                        "by_source": {"terms": {"field": "source", "size": 10}},
                        "top_roles": {
                            "nested": {"path": "roles"},
                            "aggs": {"roles": {"terms": {"field": "roles.role", "size": 15}}},
                        },
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["is_company"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("is_company", {}).get("buckets", [])]
            out["total_company_links"] = int(aggs.get("companies_stats", {}).get("value", 0))
            out["by_source"] = [{"key": str(b["key"]), "count": b["doc_count"]} for b in aggs.get("by_source", {}).get("buckets", [])]
            out["top_roles"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("top_roles", {}).get("roles", {}).get("buckets", [])]
        return out
    except Exception as exc:
        return {"error": str(exc)}


_UNIFIED_GRAPH_MAX_CONTRACTS = 200
_UNIFIED_GRAPH_MAX_PEOPLE = 100


def combined_graph_for_company(
    company_nif: str,
    include_people: bool = True,
    include_contracts: bool = True,
    contract_limit: int = 60,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Grafo unificado: pessoas/cargos, contratos e entidades para um NIF.

    - Nó central: `company:<nif>` (empresa do cadastro).
    - Pessoas: nós `person:<nif>` ligadas por cargos/sócios.
    - Contratos: nós `entity:<nif>` de adjudicantes/adjudicatários ligados por
      arestas `contrato`, agregando valor e contagem.
    - Entidade: metadados do cadastro enriquecem o nó central.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}

    company_nif = str(company_nif)
    company_id = f"company:{company_nif}"

    # Enriquece com cadastro de entidades (melhor nome, contagem de contratos, etc.)
    entity = get_entity_by_nif(company_nif, es=client)
    company_name = entity.get("name") or company_nif
    if entity.get("error"):
        company_name = company_nif

    nodes[company_id] = {
        "id": company_id,
        "type": "company",
        "label": company_name,
        "nif": company_nif,
        "is_company": True,
        "entity": {
            "name": company_name,
            "country": entity.get("country"),
            "contracts_count": entity.get("contracts_count"),
            "as_adjudicante_count": entity.get("as_adjudicante_count"),
            "as_adjudicatario_count": entity.get("as_adjudicatario_count"),
            "total_value": entity.get("total_value"),
            "has_nif": entity.get("has_nif", True),
        },
    }

    total_people_edges = 0
    total_contract_nodes = 0
    total_contract_edges = 0
    contract_value_total = 0.0
    contract_count_total = 0

    if include_people:
        people = people_graph_for_company(company_nif, es=client)
        total_people_edges = people.get("edge_count", 0)
        for node in people.get("nodes", []):
            node_id = node["id"]
            if node_id in nodes:
                continue
            nodes[node_id] = {
                "id": node_id,
                "type": node.get("type", "person"),
                "label": node.get("label", node_id),
                "nif": node.get("nif"),
                "is_company": node.get("is_company", False),
            }
        for edge in people.get("edges", []):
            edge_id = f"{edge['source']}->{edge['target']}|{edge.get('role','')}"
            if edge_id not in edges:
                edges[edge_id] = {
                    "source": edge["source"],
                    "target": edge["target"],
                    "label": edge.get("label", ""),
                    "type": "role",
                    "role": edge.get("role"),
                    "role_org": edge.get("role_org"),
                    "event": edge.get("event"),
                    "date": edge.get("date"),
                    "acto": edge.get("acto"),
                    "quota": edge.get("quota"),
                    "count": 1,
                    "value": 0.0,
                }
            else:
                edges[edge_id]["count"] = edges[edge_id].get("count", 0) + 1

    if include_contracts:
        contract_data = get_company_contracts(
            nif=company_nif,
            role="all",
            size=_UNIFIED_GRAPH_MAX_CONTRACTS,
            es=client,
        )
        for contract in contract_data.get("items", [])[:_UNIFIED_GRAPH_MAX_CONTRACTS]:
            value = float(contract.get("precoContratual") or contract.get("PrecoTotalEfetivo") or 0)
            contract_count_total += 1
            contract_value_total += value
            other_role = None
            other_nif = None
            other_name = None
            # Determina o lado oposto da empresa central
            sides = []
            for party in contract.get("adjudicantes", {}).get("parsed", []):
                if party.get("nif") != company_nif:
                    sides.append(("adjudicante", party.get("nif"), party.get("nome")))
            for party in contract.get("adjudicatarios", {}).get("parsed", []):
                if party.get("nif") != company_nif:
                    sides.append(("adjudicatario", party.get("nif"), party.get("nome")))
            for role_side, onif, oname in sides:
                if not onif:
                    continue
                other_nif = onif
                other_name = oname or onif
                other_role = role_side
                entity_id = f"entity:{onif}"
                if entity_id in nodes:
                    existing = nodes[entity_id]
                    existing["contract_count"] = existing.get("contract_count", 0) + 1
                    existing["total_value"] = existing.get("total_value", 0.0) + value
                else:
                    total_contract_nodes += 1
                    nodes[entity_id] = {
                        "id": entity_id,
                        "type": "entity",
                        "label": other_name,
                        "nif": onif,
                        "is_company": True,
                        "role_side": other_role,
                        "contract_count": 1,
                        "total_value": value,
                    }
                edge_id = f"{company_id}<->{entity_id}"
                if edge_id not in edges:
                    edges[edge_id] = {
                        "source": company_id,
                        "target": entity_id,
                        "label": "contrato",
                        "type": "contract",
                        "count": 1,
                        "value": value,
                    }
                    total_contract_edges += 1
                else:
                    edges[edge_id]["count"] = edges[edge_id].get("count", 0) + 1
                    edges[edge_id]["value"] = edges[edge_id].get("value", 0.0) + value

    return {
        "company_nif": company_nif,
        "company_name": company_name,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "include_people": include_people,
            "include_contracts": include_contracts,
            "people_edge_count": total_people_edges,
            "contract_nodes": total_contract_nodes,
            "contract_edges": total_contract_edges,
            "contract_count_total": contract_count_total,
            "contract_value_total": round(contract_value_total, 2),
            "contract_limit": _UNIFIED_GRAPH_MAX_CONTRACTS,
            "notes": [
                "Grafo combinado: pessoas/cargos, contratos públicos e entidades.",
                f"Contratos analisados: {contract_count_total} (limite {_UNIFIED_GRAPH_MAX_CONTRACTS}).",
            ],
        },
    }

