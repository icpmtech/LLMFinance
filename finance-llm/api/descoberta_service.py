"""Descoberta — painel de controlo de uma empresa.

Recebe um **NIF** e recolhe tudo o que a plataforma sabe sobre essa empresa:
cadastro, contratos públicos, rede de relações, pessoas e cargos, atos
societários, insolvências (CIRE), risco, marcas (INPI), firmas (RNPC),
subvenções, devedores, contribuintes, mercado, registos LEI e notícias.

Sobre essa recolha assentam os dois paradigmas da descoberta:

- **grafo de informação** — um nó por empresa, ligado por camadas à evidência
  que existe sobre ela (adjudicantes, CPV, pessoas, processos, marcas, firmas,
  subvenções, devedores e notícias), na mesma forma que o estúdio de grafos
  desenha (`nodes`/`edges`/`meta`), pronto para o `GraphCanvas`;
- **ontologia** — a mesma malha projetada sobre a ontologia do IQ OS (`object_types`
  e `link_types` declarados em `api.ontology_registry`): que tipos de objeto
  foram instanciados, que tipos de ligação foram materializados e qual a
  cobertura efetiva.

Por cima, o **Hermes** (`api.hermes_service`) escreve a análise citada, seguindo
a **skill** que a biblioteca da plataforma escolher para o pedido (ou a que o
painel impuser) — a mesma biblioteca partilhada pelo Hermes, pelo Chat IA e pelo
RAG, visível em `api/skills_service`.

Rotas em `api/descoberta_routes.py` (`/descoberta/*`).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PAIS_DEFAULT = "PT"

# Orçamento de cada fonte. Uma fonte lenta não pode segurar o painel: devolve o
# que tiver e o painel diz que ficou incompleta.
FONTE_TIMEOUT = 60.0
# Fontes corridas em paralelo (o Elasticsearch aguenta bem esta concorrência).
MAX_PARALELO = 6

# Limites de desenho do grafo. Um grafo de descoberta é uma vista de leitura: os
# totais exatos vivem nas secções, não no desenho.
MAX_ADJUDICANTES = 10
MAX_CPV = 8
MAX_PESSOAS = 12
MAX_PROCESSOS = 8
MAX_MARCAS = 8
MAX_FIRMAS = 5
MAX_SUBVENCOES = 6
MAX_NOTICIAS = 5
MAX_TICKERS = 2

MAX_RESOLVER_CANDIDATOS = 8


# ---------------------------------------------------------------------------
# Catálogo de fontes
# ---------------------------------------------------------------------------
# `tipo` é o tipo de nó do grafo (mesma taxonomia de `TYPE_COLORS` no frontend);
# `ontologia` é o tipo de objeto da ontologia do IQ OS que a fonte instancia.
FONTES: List[Dict[str, Any]] = [
    {
        "id": "cadastro",
        "label": "Cadastro",
        "grupo": "entidade",
        "descricao": "Identificação, CAE, contactos e valores totais no portal base.",
        "ontologia": "empresa",
        "tipo": "entidade",
    },
    {
        "id": "contratos",
        "label": "Contratos públicos",
        "grupo": "contratacao",
        "descricao": "Contratos em que a empresa é parte, com valores, CPV e procedimento.",
        "ontologia": "contrato",
        "tipo": "contrato",
    },
    {
        "id": "rede",
        "label": "Rede de relações",
        "grupo": "contratacao",
        "descricao": "Adjudicantes, órgãos sociais, processos e co-intervenientes.",
        "ontologia": "entidade_publica",
        "tipo": "entidade",
    },
    {
        "id": "pessoas",
        "label": "Pessoas e cargos",
        "grupo": "pessoas",
        "descricao": "Quem tem cargos registados na empresa (registo societário e CIRE).",
        "ontologia": "pessoa",
        "tipo": "pessoa",
    },
    {
        "id": "societario",
        "label": "Atos societários",
        "grupo": "registos",
        "descricao": "Publicações de atos de registo comercial da empresa.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "cire",
        "label": "Insolvências (CIRE)",
        "grupo": "risco",
        "descricao": "Insolvências, PER, PEAP e PEVE publicados no CITIUS.",
        "ontologia": None,
        "tipo": "processo",
    },
    {
        "id": "risco",
        "label": "Risco da empresa",
        "grupo": "risco",
        "descricao": "Nível de risco, componentes e anomalia face ao mercado.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "marcas",
        "label": "Marcas (INPI)",
        "grupo": "registos",
        "descricao": "Marcas registadas da empresa no INPI.",
        "ontologia": "marca",
        "tipo": "outra",
    },
    {
        "id": "firmas",
        "label": "Firmas (RNPC)",
        "grupo": "registos",
        "descricao": "Firmas e nomes comerciais da empresa no RNPC.",
        "ontologia": "firma",
        "tipo": "outra",
    },
    {
        "id": "subvencoes",
        "label": "Subvenções",
        "grupo": "financiamento",
        "descricao": "Subvenções públicas atribuídas à empresa.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "devedores",
        "label": "Devedores",
        "grupo": "financiamento",
        "descricao": "Presença nas listas de devedores das Finanças e da Segurança Social.",
        "ontologia": None,
        "tipo": "processo",
    },
    {
        "id": "contribuintes",
        "label": "Contribuintes",
        "grupo": "registos",
        "descricao": "NIF/NIPC no sistema, papéis e valores por fonte.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "mercado",
        "label": "Mercado",
        "grupo": "mercados",
        "descricao": "Posicionamento, dependências e atividade (CAE) da empresa.",
        "ontologia": "ticker",
        "tipo": "outra",
    },
    {
        "id": "lei",
        "label": "Registos LEI (GLEIF)",
        "grupo": "registos",
        "descricao": "Identificador global de entidade jurídica e dados do registo.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "racius",
        "label": "Racius",
        "grupo": "registos",
        "descricao": "Ficha comercial: CAE, capital, contactos e administradores.",
        "ontologia": None,
        "tipo": "outra",
    },
    {
        "id": "noticias",
        "label": "Notícias",
        "grupo": "media",
        "descricao": "Menções da empresa na imprensa indexada.",
        "ontologia": "noticia",
        "tipo": "outra",
    },
]
FONTE_BY_ID = {fonte["id"]: fonte for fonte in FONTES}
FONTE_IDS = [fonte["id"] for fonte in FONTES]

# Índice de que cada fonte se alimenta. Serve para confrontar a descoberta com a
# ontologia: um tipo de objeto só está "alinhado" quando a fonte que o
# instanciou é uma das fontes declaradas no `binding` desse tipo.
SECAO_INDICE: Dict[str, str] = {
    "cadastro": "finance_entities",
    "contratos": "contratos",
    "rede": "contratos",
    "pessoas": "finance_people",
    "societario": "finance_societario",
    "cire": "finance_cire",
    "risco": "contratos",
    "marcas": "finance_trademarks",
    "firmas": "finance_firmas",
    "subvencoes": "finance_subvencoes",
    "devedores": "finance_devedores",
    "contribuintes": "finance_contribuintes",
    "mercado": "finance_prices",
    "lei": "finance_gleif",
    "racius": "finance_racius",
    "noticias": "finance_news",
}

# Tipo de objeto da ontologia → índice que o instancia na descoberta.
TIPO_INDICE: Dict[str, str] = {
    str(fonte["ontologia"]): SECAO_INDICE[str(fonte["id"])]
    for fonte in FONTES
    if fonte.get("ontologia") and fonte["id"] in SECAO_INDICE
}

# Quando a ontologia declara várias ligações entre os mesmos dois tipos, esta é
# a que descreve a evidência que a descoberta recolhe.
LIGACAO_PREFERIDA: Dict[Tuple[str, str], str] = {
    ("empresa", "contrato"): "empresa_contratada",
    ("entidade_publica", "contrato"): "entidade_publica_adjudica",
    ("contrato", "cpv"): "contrato_cpv",
    ("empresa", "marca"): "empresa_marcas",
    ("empresa", "firma"): "empresa_firmas",
}


def meta() -> Dict[str, Any]:
    """Catálogo de fontes e limites do painel de descoberta."""
    from api import search360_sources as fontes_plataforma  # noqa: PLC0415
    from api import skills_service as biblioteca  # noqa: PLC0415

    plataforma = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "hint": item.get("hint"),
        }
        for item in getattr(fontes_plataforma, "CATALOG", []) or []
    ]
    try:
        estado_skills = biblioteca.status()
    except Exception as exc:  # pragma: no cover - a biblioteca é tolerante a falhas
        logger.warning("Descoberta: biblioteca de skills indisponível: %s", exc)
        estado_skills = {}
    return {
        "fontes": FONTES,
        "grupos": sorted({fonte["grupo"] for fonte in FONTES}),
        "plataforma": plataforma,
        "skills": {
            "total": estado_skills.get("total") or 0,
            "ativas": estado_skills.get("enabled") or 0,
            "usos": estado_skills.get("uses") or 0,
        },
        "limites": {
            "fontes": len(FONTES),
            "paralelo": MAX_PARALELO,
            "timeout_fonte": FONTE_TIMEOUT,
            "nos_grafo": MAX_ADJUDICANTES + MAX_CPV + MAX_PESSOAS + MAX_PROCESSOS + MAX_MARCAS
            + MAX_FIRMAS + MAX_SUBVENCOES + MAX_NOTICIAS + MAX_TICKERS + 1,
        },
    }


# ---------------------------------------------------------------------------
# Identificação da empresa (NIF)
# ---------------------------------------------------------------------------
def normalizar_nif(value: Any) -> str:
    """Devolve só os dígitos de um NIF/NIPC (aceita espaços e pontuação)."""
    texto = str(value or "").strip()
    digitos = "".join(ch for ch in texto if ch.isdigit())
    return digitos if len(digitos) >= 8 else texto


def resolver(texto: str, *, size: int = MAX_RESOLVER_CANDIDATOS) -> Dict[str, Any]:
    """Resolve um nome ou NIF na empresa certa, com candidatos alternativos."""
    from api import elasticsearch_client as es_client  # noqa: PLC0415
    from api import padroes_service as padroes  # noqa: PLC0415

    consulta = str(texto or "").strip()
    if len(consulta) < 2:
        return {"query": consulta, "items": [], "candidatos": [], "detail": "Indique um nome ou NIF."}

    nif = normalizar_nif(consulta)
    if len(nif) == 9 and nif.isdigit() and consulta.replace(" ", "") == nif:
        try:
            cadastro = es_client.get_company_by_nif(nif) or {}
        except Exception as exc:  # pragma: no cover - depende do Elasticsearch
            logger.warning("Descoberta: cadastro de %s falhou: %s", nif, exc)
            cadastro = {}
        nome = cadastro.get("name") or cadastro.get("nome") or ""
        if nome:
            item = {
                "nif": nif,
                "nome": nome,
                "contratos": cadastro.get("contracts_count") or cadastro.get("total_contracts"),
                "valor": cadastro.get("total_value"),
                "paises": cadastro.get("country") or cadastro.get("country_code"),
                "principal": True,
                "fonte": "cadastro",
            }
            return {"query": consulta, "items": [item], "candidatos": [], "nif_detetado": True}

    try:
        resolvido = padroes.resolver_empresa(consulta, pais=PAIS_DEFAULT)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("Descoberta: resolução de %r falhou: %s", consulta, exc)
        return {"query": consulta, "items": [], "candidatos": [], "detail": str(exc)}

    if resolvido.get("error"):
        return {"query": consulta, "items": [], "candidatos": [], "detail": resolvido["error"]}

    principal = {
        "nif": resolvido.get("nif"),
        "nome": resolvido.get("nome"),
        "alias": resolvido.get("alias") or [],
        "contratos": resolvido.get("contratos"),
        "valor": resolvido.get("valor"),
        "papeis": resolvido.get("papeis") or [],
        "concelho": resolvido.get("concelho"),
        "fonte": resolvido.get("fonte"),
        "principal": True,
    }
    candidatos = [{**item, "principal": False} for item in resolvido.get("candidatos") or []]
    itens = ([principal] if principal.get("nif") else []) + candidatos
    return {
        "query": consulta,
        "nif_detetado": bool(resolvido.get("nif_detetado")),
        "items": itens[: max(1, int(size or MAX_RESOLVER_CANDIDATOS))],
        "candidatos": candidatos,
        "pais": resolvido.get("pais") or PAIS_DEFAULT,
    }


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------
def _adjudicantes(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Agrega os contratos por adjudicante (quem compra) — é onde está o valor."""
    agregado: Dict[str, Dict[str, Any]] = {}
    for contrato in contratos:
        nome = str(contrato.get("adjudicante") or "").strip()
        nif = str(contrato.get("adjudicante_nif") or "").strip()
        chave = nif or nome
        if not chave:
            continue
        entrada = agregado.setdefault(chave, {"nif": nif, "nome": nome or nif, "contratos": 0, "valor": 0.0})
        entrada["contratos"] += 1
        entrada["valor"] = round(entrada["valor"] + float(contrato.get("valor") or 0.0), 2)
        if nome and entrada["nome"] == chave:
            entrada["nome"] = nome
    return agregado


def _por_cpv(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Agrega os contratos por classificação CPV (topo da árvore)."""
    agregado: Dict[str, Dict[str, Any]] = {}
    for contrato in contratos:
        codigo = str(contrato.get("cpv") or "").strip()
        if not codigo:
            continue
        entrada = agregado.setdefault(
            codigo,
            {"cpv": codigo, "descricao": contrato.get("cpv_desc") or "", "contratos": 0, "valor": 0.0},
        )
        entrada["contratos"] += 1
        entrada["valor"] = round(entrada["valor"] + float(contrato.get("valor") or 0.0), 2)
        if not entrada["descricao"] and contrato.get("cpv_desc"):
            entrada["descricao"] = contrato["cpv_desc"]
    return agregado


def _kpis(recolha: Dict[str, Any]) -> Dict[str, Any]:
    """Indicadores de topo do painel, calculados a partir da recolha."""
    secoes = recolha.get("secoes") or {}
    contratos = (secoes.get("contratos") or {}).get("contratos") or []
    resumo = (secoes.get("contratos") or {}).get("resumo") or {}
    adjudicantes = _adjudicantes(contratos)
    maior = max(adjudicantes.values(), key=lambda item: item["valor"], default=None)
    valor_total = float(resumo.get("valor_total") or 0.0)
    concentracao = round((maior["valor"] / valor_total) * 100, 1) if maior and valor_total else None

    risco = (secoes.get("risco") or {}).get("risco") or {}
    pessoas = (secoes.get("pessoas") or {}).get("total") or 0
    marcas = (secoes.get("marcas") or {}).get("total") or 0
    firmas = (secoes.get("firmas") or {}).get("total") or 0
    cire = (secoes.get("cire") or {}).get("total") or 0
    subvencoes = float((secoes.get("subvencoes") or {}).get("valor_total") or 0.0)
    noticias = (secoes.get("noticias") or {}).get("total") or 0

    return {
        "contratos": (secoes.get("contratos") or {}).get("contratos_total") or len(contratos),
        "valor_total": round(valor_total, 2),
        "adjudicantes": len(adjudicantes),
        "valor_mediano": resumo.get("valor_mediano"),
        "taxa_ajuste_direto": resumo.get("taxa_ajuste_direto"),
        "maior_adjudicante": maior,
        "concentracao_maior": concentracao,
        "risco": risco.get("nivel"),
        "risco_pontos": risco.get("pontos") or risco.get("score"),
        "insolvencias": cire,
        "pessoas": pessoas,
        "marcas": marcas,
        "firmas": firmas,
        "subvencoes_valor": round(subvencoes, 2),
        "noticias": noticias,
        "sinais": (secoes.get("contratos") or {}).get("sinais") or [],
    }


def _fonte_cadastro(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import empresas_perfil as perfil  # noqa: PLC0415
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    dados: Dict[str, Any] = {}
    try:
        dados["cadastro"] = es_client.get_company_by_nif(nif) or {}
    except Exception as exc:
        dados["cadastro_erro"] = str(exc)
    try:
        dados["perfil"] = perfil.obter(nif)
    except Exception as exc:
        dados["perfil_erro"] = str(exc)
    return {"total": 1 if dados.get("cadastro") else 0, "dados": dados}


def _fonte_contratos(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import padroes_service as padroes  # noqa: PLC0415

    dossier = padroes.entity_dossier(nif, pais=pais)
    if dossier.get("error"):
        return {"erro": dossier["error"], "total": 0, "dados": {}}
    return {
        "total": dossier.get("contratos_total") or len(dossier.get("contratos") or []),
        "dados": {
            "contratos": dossier.get("contratos") or [],
            "resumo": dossier.get("resumo") or {},
            "sinais": dossier.get("sinais") or [],
            "contratos_total": dossier.get("contratos_total"),
            "nome": dossier.get("nome") or nome,
        },
    }


def _fonte_rede(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import padroes_service as padroes  # noqa: PLC0415

    dossier = padroes.entity_dossier(nif, pais=pais)
    if dossier.get("error"):
        return {"erro": dossier["error"], "total": 0, "dados": {}}
    return {
        "total": len((dossier.get("grafo") or {}).get("nodes") or []),
        "dados": {
            "grafo": dossier.get("grafo") or {},
            "lacos": dossier.get("lacos") or [],
            "intervenientes_processos": dossier.get("intervenientes_processos") or [],
            "cargos_sociais": dossier.get("cargos_sociais") or [],
        },
    }


def _fonte_pessoas(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import elasticsearch_client as es_client  # noqa: PLC0415
    from api import societario_service as societario  # noqa: PLC0415

    dados: Dict[str, Any] = {}
    try:
        ficha = es_client.company_people_from_index(nif, size=120)
        dados["pessoas"] = ficha.get("people") or []
        dados["total"] = ficha.get("total") or 0
        dados["empresa"] = ficha.get("company_name") or ficha.get("name")
    except Exception as exc:
        dados["erro"] = str(exc)
        dados["total"] = 0
    try:
        societario_people = societario.company_people(nif)
        dados["societario"] = societario_people.get("items") if isinstance(societario_people, dict) else None
    except Exception as exc:
        dados["societario_erro"] = str(exc)
    return {"total": dados.get("total") or 0, "dados": dados}


def _fonte_societario(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import societario_service as societario  # noqa: PLC0415

    resultado = societario.company_publicacoes(nif, size=60)
    itens = resultado.get("items") if isinstance(resultado, dict) else None
    return {
        "total": (resultado or {}).get("total") or len(itens or []),
        "dados": {"items": itens or [], "total": (resultado or {}).get("total")},
        "erro": (resultado or {}).get("error") if isinstance(resultado, dict) else None,
    }


def _fonte_cire(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import cire_service as cire  # noqa: PLC0415
    from api import padroes_service as padroes  # noqa: PLC0415

    dossier = padroes.entity_dossier(nif, pais=pais)
    insolvencias = dossier.get("insolvencias") or []
    dados: Dict[str, Any] = {
        "insolvencias": insolvencias,
        "total": dossier.get("insolvencias_total") or len(insolvencias),
        "intervenientes": dossier.get("intervenientes_processos") or [],
    }
    try:
        mencoes = cire.interveniente(nif, size=60)
        dados["mencoes"] = mencoes.get("items") if isinstance(mencoes, dict) else None
        dados["mencoes_total"] = (mencoes or {}).get("total") if isinstance(mencoes, dict) else None
    except Exception as exc:
        dados["mencoes_erro"] = str(exc)
    return {"total": dados.get("total") or 0, "dados": dados, "erro": dossier.get("error")}


def _fonte_risco(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import risco_service as risco  # noqa: PLC0415

    resultado = risco.risco_empresa(nif=nif, pais=pais)
    if resultado.get("error"):
        return {"erro": resultado["error"], "total": 0, "dados": {}}
    return {"total": 1, "dados": resultado}


def _fonte_marcas(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    resultado = es_client.get_company_trademarks(company_nif=nif, company_name=nome, size=MAX_MARCAS)
    return {"total": resultado.get("total") or 0, "dados": resultado, "erro": resultado.get("error")}


def _fonte_firmas(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    resultado = es_client.get_company_firmas(company_nif=nif, company_name=nome, size=MAX_FIRMAS)
    return {"total": resultado.get("total") or 0, "dados": resultado, "erro": resultado.get("error")}


def _fonte_subvencoes(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import subvencoes_service as subvencoes  # noqa: PLC0415

    dados: Dict[str, Any] = {}
    try:
        beneficiario = subvencoes.por_beneficiario(nif, size=50)
        dados.update(beneficiario if isinstance(beneficiario, dict) else {})
    except Exception as exc:
        dados["erro"] = str(exc)
    entidade: Any = None
    try:
        entidade = subvencoes.por_entidade(nif, size=50)
        if isinstance(entidade, dict):
            dados["como_entidade"] = entidade.get("items") or []
    except Exception as exc:
        dados["entidade_erro"] = str(exc)
    itens = dados.get("items") or []
    valor = dados.get("valor_total") or dados.get("total_valor")
    if valor is None:
        valor = sum(float(item.get("valor") or 0.0) for item in itens if isinstance(item, dict))
    return {
        "total": dados.get("total") or len(itens),
        "valor_total": round(float(valor or 0.0), 2),
        "dados": dados,
    }


def _fonte_devedores(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import devedores_service as devedores  # noqa: PLC0415

    resultado = devedores.por_nif(nif)
    itens = resultado.get("items") or resultado.get("registos") or []
    return {
        "total": resultado.get("total") or len(itens),
        "dados": resultado,
        "erro": resultado.get("error"),
    }


def _fonte_contribuintes(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import contribuintes_service as contribuintes  # noqa: PLC0415

    resultado = contribuintes.detail(nif)
    return {"total": 1 if resultado else 0, "dados": resultado, "erro": resultado.get("error")}


def _fonte_mercado(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import mercado_service as mercado  # noqa: PLC0415

    resultado = mercado.empresa(nif)
    return {"total": 1 if resultado else 0, "dados": resultado, "erro": resultado.get("error")}


def _fonte_lei(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import gleif_service as gleif  # noqa: PLC0415

    termo = nome or nif
    if not termo:
        return {"total": 0, "dados": {}}
    resultado = gleif.search(termo, size=MAX_FIRMAS)
    itens = resultado.get("items") or resultado.get("results") or []
    return {"total": resultado.get("total") or len(itens), "dados": resultado, "erro": resultado.get("error")}


def _fonte_racius(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import racius_service as racius  # noqa: PLC0415

    if not racius.available():
        return {"total": 0, "dados": {}, "erro": "Racius indisponível (sem sessão/credenciais)."}
    resultado = racius.detail(nif)
    return {"total": 1 if resultado else 0, "dados": resultado, "erro": resultado.get("error")}


def _fonte_noticias(nif: str, nome: str, pais: str) -> Dict[str, Any]:
    from api import padroes_service as padroes  # noqa: PLC0415

    if not nome:
        return {"total": 0, "dados": {"items": []}}
    itens = padroes.news_mentions([(nome, nome)], per_name=MAX_NOTICIAS)
    return {"total": len(itens or []), "dados": {"items": itens or []}}


CARREGADORES: Dict[str, Callable[[str, str, str], Dict[str, Any]]] = {
    "cadastro": _fonte_cadastro,
    "contratos": _fonte_contratos,
    "rede": _fonte_rede,
    "pessoas": _fonte_pessoas,
    "societario": _fonte_societario,
    "cire": _fonte_cire,
    "risco": _fonte_risco,
    "marcas": _fonte_marcas,
    "firmas": _fonte_firmas,
    "subvencoes": _fonte_subvencoes,
    "devedores": _fonte_devedores,
    "contribuintes": _fonte_contribuintes,
    "mercado": _fonte_mercado,
    "lei": _fonte_lei,
    "racius": _fonte_racius,
    "noticias": _fonte_noticias,
}


def _nome_da_empresa(nif: str, nome: Optional[str] = None) -> str:
    """Nome da empresa a partir do cadastro (a recolha precisa dele para as notícias)."""
    if nome:
        return str(nome)
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    try:
        cadastro = es_client.get_company_by_nif(nif) or {}
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("Descoberta: nome de %s não resolvido: %s", nif, exc)
        return ""
    return str(cadastro.get("name") or cadastro.get("nome") or "")


def _registar_fonte(
    estado: List[Dict[str, Any]],
    secoes: Dict[str, Any],
    fonte_id: str,
    futuro: Any,
    iniciado_em: float,
    alvo: str,
) -> None:
    """Recolhe o resultado de uma fonte e registra-o no estado e nas secções."""
    spec = FONTE_BY_ID[fonte_id]
    linha = {
        "id": fonte_id,
        "label": spec["label"],
        "grupo": spec["grupo"],
        "ontologia": spec.get("ontologia"),
        "tipo": spec.get("tipo"),
        "ms": int((time.perf_counter() - iniciado_em) * 1000),
    }
    try:
        resultado = futuro.result() or {}
    except Exception as exc:
        logger.warning("Descoberta: fonte %s de %s falhou: %s", fonte_id, alvo, exc)
        estado.append({**linha, "estado": "erro", "erro": str(exc), "total": 0})
        return

    erro = resultado.get("erro")
    total = int(resultado.get("total") or 0)
    dados = resultado.get("dados") or {}
    if isinstance(dados, dict) and resultado.get("valor_total") is not None:
        dados["valor_total"] = resultado["valor_total"]
    secoes[fonte_id] = dados
    if erro:
        situacao = "erro"
    elif total:
        situacao = "ok"
    else:
        situacao = "vazio"
    estado.append({**linha, "estado": situacao, "total": total, "erro": erro})


def recolher(
    nif: str,
    *,
    pais: str = PAIS_DEFAULT,
    nome: Optional[str] = None,
    apenas: Optional[Iterable[str]] = None,
    timeout: float = FONTE_TIMEOUT,
) -> Dict[str, Any]:
    """Recolhe todas as fontes para um NIF, em paralelo e com degradação graciosa.

    Cada fonte devolve o seu estado: `ok`, `vazio`, `erro` ou `tempo`. Uma fonte
    que falhe não impede as outras — o painel mostra o que existe e diz o que
    ficou em falta.
    """
    alvo = normalizar_nif(nif)
    if not alvo:
        return {"error": "NIF em falta.", "nif": "", "secoes": {}, "fontes": []}

    nome_empresa = _nome_da_empresa(alvo, nome)
    pretendidas = [fonte_id for fonte_id in (apenas or FONTE_IDS) if fonte_id in FONTE_BY_ID]
    iniciado = time.perf_counter()

    secoes: Dict[str, Any] = {}
    estado: List[Dict[str, Any]] = []

    pool = ThreadPoolExecutor(max_workers=min(MAX_PARALELO, max(1, len(pretendidas))))
    iniciado_em: Dict[Any, float] = {}
    futuros: Dict[Any, str] = {}
    pendentes: set = set()
    try:
        for fonte_id in pretendidas:
            futuro = pool.submit(CARREGADORES[fonte_id], alvo, nome_empresa, pais)
            futuros[futuro] = fonte_id
            iniciado_em[futuro] = time.perf_counter()
            pendentes.add(futuro)

        for futuro in as_completed(futuros, timeout=timeout):
            pendentes.discard(futuro)
            _registar_fonte(estado, secoes, futuros[futuro], futuro, iniciado_em[futuro], alvo)
    except FutureTimeoutError:
        # As que não terminaram a tempo ficam marcadas como tal; o painel mostra
        # o que existe e diz o que faltou, em vez de esperar indefinidamente.
        for futuro in pendentes:
            fonte_id = futuros[futuro]
            spec = FONTE_BY_ID[fonte_id]
            logger.warning("Descoberta: fonte %s de %s excedeu %.0fs", fonte_id, alvo, timeout)
            estado.append({
                "id": fonte_id,
                "label": spec["label"],
                "grupo": spec["grupo"],
                "ontologia": spec.get("ontologia"),
                "tipo": spec.get("tipo"),
                "estado": "tempo",
                "ms": int(timeout * 1000),
                "total": 0,
            })
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    estado.sort(key=lambda item: FONTE_IDS.index(item["id"]) if item["id"] in FONTE_IDS else 99)
    recolha = {
        "nif": alvo,
        "nome": nome_empresa or alvo,
        "pais": str(pais or PAIS_DEFAULT).upper(),
        "secoes": secoes,
        "fontes": estado,
        "recolhidas": sum(1 for item in estado if item["estado"] == "ok"),
        "em_falta": [item["id"] for item in estado if item["estado"] != "ok"],
        "ms": int((time.perf_counter() - iniciado) * 1000),
    }
    recolha["kpis"] = _kpis(recolha)
    return recolha


# ---------------------------------------------------------------------------
# Grafo de informação
# ---------------------------------------------------------------------------
def _no(node_id: str, *, key: str, label: str, dimension: str, tipo: str, role: str = "", count: int = 0,
        total_value: float = 0.0) -> Dict[str, Any]:
    return {
        "id": node_id,
        "key": key,
        "label": label or key,
        "dimension": dimension,
        "type": tipo,
        "role": role,
        "count": int(count),
        "total_value": round(float(total_value or 0.0), 2),
    }


def _aresta(source: str, target: str, *, count: int = 1, value: float = 0.0, relation: str = "") -> Dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "count": int(count),
        "value": round(float(value or 0.0), 2),
        "relation": relation or f"{source}->{target}",
    }


def grafo(recolha: Dict[str, Any]) -> Dict[str, Any]:
    """Constrói o grafo de informação da empresa a partir da recolha.

    Segue a forma do estúdio de grafos (`nodes`/`edges`/`meta`), para o
    `GraphCanvas` desenhar sem conversões. O centro é sempre a empresa; cada
    camada é uma família de evidência (quem compra, o que se classifica, quem
    gere, processos, marcas, firmas, subvenções, devedores e imprensa).
    """
    nif = str(recolha.get("nif") or "")
    nome = str(recolha.get("nome") or nif)
    secoes = recolha.get("secoes") or {}

    centro = f"empresa:{nif}"
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    vistos = {centro}

    contratos_secao = secoes.get("contratos") or {}
    contratos = contratos_secao.get("contratos") or []
    valor_empresa = float((contratos_secao.get("resumo") or {}).get("valor_total") or 0.0)

    nodes.append(
        _no(
            centro,
            key=nif,
            label=nome,
            dimension="empresa",
            tipo="entidade",
            role=f"empresa analisada · {len(contratos)} contratos lidos",
            count=len(contratos),
            total_value=valor_empresa,
        )
    )

    # --- Adjudicantes (quem compra): é onde está o valor ---------------------
    adjudicantes = _adjudicantes(contratos)
    for chave, dados in sorted(adjudicantes.items(), key=lambda item: -item[1]["valor"])[:MAX_ADJUDICANTES]:
        node_id = f"adjudicante:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=dados["nome"],
                dimension="adjudicante",
                tipo="entidade",
                role=f"adjudicante · {dados['contratos']} contratos",
                count=dados["contratos"],
                total_value=dados["valor"],
            )
        )
        edges.append(_aresta(centro, node_id, count=dados["contratos"], value=dados["valor"], relation="é adjudicatária de"))

    # --- Classificação CPV: onde a empresa atua -----------------------------
    for codigo, dados in sorted(_por_cpv(contratos).items(), key=lambda item: -item[1]["valor"])[:MAX_CPV]:
        node_id = f"cpv:{codigo}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=codigo,
                label=(dados["descricao"] or codigo)[:48],
                dimension="cpv",
                tipo="cpv",
                role=f"CPV {codigo} · {dados['contratos']} contratos",
                count=dados["contratos"],
                total_value=dados["valor"],
            )
        )
        edges.append(_aresta(centro, node_id, count=dados["contratos"], value=dados["valor"], relation="atua em"))

    # --- Pessoas com cargos --------------------------------------------------
    rede = secoes.get("rede") or {}
    pessoas = (secoes.get("pessoas") or {}).get("pessoas") or []
    cargos_sociais = rede.get("cargos_sociais") or []
    vistos_pessoas = set()
    for pessoa in (cargos_sociais or pessoas)[:MAX_PESSOAS]:
        chave = str(pessoa.get("nif") or pessoa.get("nome") or "")
        if not chave or chave in vistos_pessoas:
            continue
        vistos_pessoas.add(chave)
        node_id = f"pessoa:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        cargos = pessoa.get("cargos") or []
        detalhe = ", ".join(
            sorted({str((cargo or {}).get("role_org") or (cargo or {}).get("role") or "") for cargo in cargos} - {""})
        )
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(pessoa.get("nome") or chave),
                dimension="pessoa",
                tipo="pessoa",
                role=(detalhe or "cargo registado")[:80],
                count=len(cargos) or 1,
            )
        )
        edges.append(_aresta(node_id, centro, count=len(cargos) or 1, relation="gere"))

    # --- Processos CIRE ------------------------------------------------------
    insolvencias = (secoes.get("cire") or {}).get("insolvencias") or []
    for indice, item in enumerate(insolvencias[:MAX_PROCESSOS]):
        chave = str(item.get("processo") or item.get("especie") or f"processo-{indice}")
        node_id = f"cire:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(item.get("especie") or "processo CIRE")[:60],
                dimension="cire",
                tipo="processo",
                role=f"{item.get('tribunal') or 'tribunal'} · {str(item.get('data') or '')[:10]}",
                count=1,
            )
        )
        edges.append(_aresta(centro, node_id, relation="tem processo"))

    # --- Marcas (INPI) -------------------------------------------------------
    for indice, marca in enumerate(((secoes.get("marcas") or {}).get("items") or [])[:MAX_MARCAS]):
        chave = str(marca.get("nord") or marca.get("id") or marca.get("nome") or f"marca-{indice}")
        node_id = f"marca:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(marca.get("nome") or marca.get("marca") or chave)[:48],
                dimension="marca",
                tipo="outra",
                role=str(marca.get("estado") or marca.get("classe") or "marca registada")[:60],
                count=1,
            )
        )
        edges.append(_aresta(centro, node_id, relation="tem marca"))

    # --- Firmas (RNPC) -------------------------------------------------------
    for indice, firma in enumerate(((secoes.get("firmas") or {}).get("items") or [])[:MAX_FIRMAS]):
        chave = str(firma.get("nipc") or firma.get("nome") or f"firma-{indice}")
        node_id = f"firma:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(firma.get("nome") or firma.get("firma") or chave)[:48],
                dimension="firma",
                tipo="outra",
                role=str(firma.get("situacao") or firma.get("cae") or "firma registada")[:60],
                count=1,
            )
        )
        edges.append(_aresta(centro, node_id, relation="tem firma"))

    # --- Subvenções ----------------------------------------------------------
    itens_subvencao = ((secoes.get("subvencoes") or {}).get("items") or [])[:MAX_SUBVENCOES]
    for indice, subvencao in enumerate(itens_subvencao):
        chave = str(subvencao.get("id") or subvencao.get("numero_ato") or f"subvencao-{indice}")
        node_id = f"subvencao:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        valor = float(subvencao.get("valor") or 0.0)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(subvencao.get("entidade") or subvencao.get("programa") or "subvenção")[:48],
                dimension="subvencao",
                tipo="outra",
                role=f"{subvencao.get('ano') or ''} · {subvencao.get('tipo') or 'subvenção'}".strip(" ·"),
                count=1,
                total_value=valor,
            )
        )
        edges.append(_aresta(centro, node_id, value=valor, relation="beneficiou"))

    # --- Devedores -----------------------------------------------------------
    devedores = secoes.get("devedores") or {}
    itens_devedor = devedores.get("items") or devedores.get("registos") or []
    if itens_devedor:
        valor_devedor = sum(float(item.get("valor") or 0.0) for item in itens_devedor if isinstance(item, dict))
        node_id = "devedor:listas"
        nodes.append(
            _no(
                node_id,
                key=nif,
                label="Listas de devedores",
                dimension="devedor",
                tipo="processo",
                role=f"{len(itens_devedor)} registo(s)",
                count=len(itens_devedor),
                total_value=valor_devedor,
            )
        )
        edges.append(_aresta(centro, node_id, count=len(itens_devedor), value=valor_devedor, relation="consta como devedor"))

    # --- Notícias ------------------------------------------------------------
    noticias = ((secoes.get("noticias") or {}).get("items") or [])[:MAX_NOTICIAS]
    for indice, noticia in enumerate(noticias):
        chave = str(noticia.get("id") or noticia.get("url") or f"noticia-{indice}")
        node_id = f"noticia:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=str(noticia.get("titulo") or noticia.get("title") or "notícia")[:60],
                dimension="noticia",
                tipo="outra",
                role=str(noticia.get("fonte") or noticia.get("source") or "")[:50] or "imprensa",
                count=1,
            )
        )
        edges.append(_aresta(centro, node_id, relation="é mencionada em"))

    # --- Mercado -------------------------------------------------------------
    mercado = secoes.get("mercado") or {}
    tickers = mercado.get("tickers") or mercado.get("instrumentos") or []
    for indice, ticker in enumerate(list(tickers)[:MAX_TICKERS]):
        chave = str(ticker.get("ticker") or ticker.get("symbol") or f"ticker-{indice}")
        node_id = f"ticker:{chave}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            _no(
                node_id,
                key=chave,
                label=chave.upper(),
                dimension="mercado",
                tipo="outra",
                role=str(ticker.get("nome") or ticker.get("name") or "instrumento")[:50],
                count=1,
            )
        )
        edges.append(_aresta(centro, node_id, relation="está cotada como"))

    nodes_por_tipo: Dict[str, int] = {}
    for node in nodes:
        nodes_por_tipo[node["type"]] = nodes_por_tipo.get(node["type"], 0) + 1

    valor_nos = sum(node["total_value"] for node in nodes[1:])
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "empresa",
            "dimension_b": None,
            "metric": "valor",
            "mode": "descoberta",
            "complete": True,
            "scan_capped": False,
            "sample_order": "camadas por relevância",
            "sample_limit": None,
            "documents_scanned": len(contratos),
            "documents_matching": len(contratos),
            "scanned_value": round(valor_empresa, 2),
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(nodes),
            "kept_edges": len(edges),
            "omitted_edges": 0,
            "coverage_value_share": None,
            "coverage_count_share": None,
            "directed": True,
            "limits": {
                "adjudicantes": MAX_ADJUDICANTES,
                "cpv": MAX_CPV,
                "pessoas": MAX_PESSOAS,
                "processos": MAX_PROCESSOS,
                "marcas": MAX_MARCAS,
                "firmas": MAX_FIRMAS,
                "subvencoes": MAX_SUBVENCOES,
                "noticias": MAX_NOTICIAS,
            },
            "notes": [
                "Grafo de descoberta: a empresa no centro e uma camada por família de evidência.",
                "Os totais exatos estão nas secções da recolha, não no desenho.",
            ],
            "filters": {"nif": nif},
            "camadas": nodes_por_tipo,
            "valor_das_camadas": round(valor_nos, 2),
        },
    }


# ---------------------------------------------------------------------------
# Ontologia
# ---------------------------------------------------------------------------
def _ontologia_documento() -> Dict[str, Any]:
    from api import ontology_registry as registry  # noqa: PLC0415

    try:
        return registry.load_ontology()
    except Exception as exc:  # pragma: no cover - depende do ficheiro da ontologia
        logger.warning("Descoberta: ontologia indisponível: %s", exc)
        return {}


def _instancia(identificador: str, titulo: str, *, valor: Any = None, detalhe: str = "") -> Dict[str, Any]:
    return {"id": identificador, "label": titulo, "valor": valor, "detalhe": detalhe}


def _relacoes_evidencia(recolha: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Relações que a recolha **prova** para esta empresa, nos tipos da ontologia.

    Cada relação é expressa com os identificadores de tipo de objeto da
    ontologia (`empresa`, `contrato`, `cpv`, `marca`…), para poder ser confrontada
    com os tipos de ligação declarados. As relações que a ontologia ainda não
    fala aparecem na mesma — é assim que a lacuna fica visível.
    """
    secoes = recolha.get("secoes") or {}
    contratos = (secoes.get("contratos") or {}).get("contratos") or []
    adjudicantes = _adjudicantes(contratos)
    cpvs = _por_cpv(contratos)
    relacoes: List[Dict[str, Any]] = []

    def juntar(origem: str, destino: str, quantidade: int, detalhe: str) -> None:
        if quantidade > 0:
            relacoes.append(
                {"from": origem, "to": destino, "quantidade": int(quantidade), "evidencia": detalhe}
            )

    juntar("empresa", "contrato", len(contratos), "contratos recolhidos em que a empresa é parte")
    juntar("entidade_publica", "contrato", len(contratos), f"{len(adjudicantes)} adjudicantes distintos")
    juntar("contrato", "cpv", len(cpvs), "classificações CPV presentes nos contratos")
    juntar("empresa", "marca", int((secoes.get("marcas") or {}).get("total") or 0), "marcas INPI da empresa")
    juntar("empresa", "firma", int((secoes.get("firmas") or {}).get("total") or 0), "firmas RNPC da empresa")
    juntar("empresa", "noticia", int((secoes.get("noticias") or {}).get("total") or 0), "menções da empresa na imprensa")
    pessoas = (secoes.get("pessoas") or {}).get("pessoas") or []
    cargos = (secoes.get("rede") or {}).get("cargos_sociais") or []
    juntar(
        "pessoa",
        "empresa",
        int((secoes.get("pessoas") or {}).get("total") or len(pessoas) or len(cargos)),
        "pessoas com cargo registado na empresa",
    )
    juntar(
        "empresa",
        "processo_cire",
        int((secoes.get("cire") or {}).get("total") or len((secoes.get("cire") or {}).get("insolvencias") or [])),
        "processos do CIRE",
    )
    juntar("empresa", "subvencao", int((secoes.get("subvencoes") or {}).get("total") or 0), "subvenções atribuídas")
    juntar("empresa", "devedor", int((secoes.get("devedores") or {}).get("total") or 0), "listas de devedores")
    juntar("empresa", "ticker", int((secoes.get("mercado") or {}).get("total") or 0), "presença no mercado")
    return relacoes


def ontologia(recolha: Dict[str, Any], malha: Dict[str, Any]) -> Dict[str, Any]:
    """Projeta a recolha sobre a ontologia do IQ OS.

    Devolve três leituras:

    - **tipos** — por tipo de objeto, as instâncias encontradas nesta empresa,
      se o tipo é declarado na ontologia e se a fonte que o instanciou é uma das
      fontes declaradas no respetivo `binding`;
    - **ligações** — as relações que a recolha prova, casadas com os tipos de
      ligação declarados (`empresa_contratada`, `contrato_cpv`, `empresa_marcas`…);
    - **cobertura e lacunas** — quanto da descoberta a ontologia já fala e o que
      ainda não fala (tipos e ligações a acrescentar).
    """
    documento = _ontologia_documento()
    tipos_declarados: Dict[str, Dict[str, Any]] = {
        str(item.get("id")): item for item in documento.get("object_types") or [] if item.get("id")
    }
    ligacoes_declaradas: List[Dict[str, Any]] = [
        item for item in documento.get("link_types") or [] if item.get("id")
    ]
    por_assinatura: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ligacao in ligacoes_declaradas:
        if ligacao.get("from") and ligacao.get("to"):
            por_assinatura.setdefault((str(ligacao["from"]), str(ligacao["to"])), ligacao)
    # A ontologia declara mais do que uma ligação entre os mesmos dois tipos
    # (`empresa_adjudica` e `empresa_contratada`, por exemplo). A descoberta diz
    # qual é a que descreve a evidência: a empresa é **adjudicatária**.
    for assinatura, preferida in LIGACAO_PREFERIDA.items():
        escolhida = next((item for item in ligacoes_declaradas if str(item.get("id")) == preferida), None)
        if escolhida is not None:
            por_assinatura[assinatura] = escolhida

    secoes = recolha.get("secoes") or {}
    contratos = (secoes.get("contratos") or {}).get("contratos") or []
    adjudicantes = _adjudicantes(contratos)
    pessoas = ((secoes.get("pessoas") or {}).get("pessoas") or []) + ((secoes.get("rede") or {}).get("cargos_sociais") or [])
    nif = str(recolha.get("nif") or "")
    nome = str(recolha.get("nome") or nif)
    resumo = (secoes.get("contratos") or {}).get("resumo") or {}

    instancias: Dict[str, List[Dict[str, Any]]] = {
        "empresa": [_instancia(nif, nome, valor=resumo.get("valor_total"), detalhe="empresa analisada")],
        "entidade_publica": [
            _instancia(chave, dados["nome"], valor=dados["valor"], detalhe=f"{dados['contratos']} contratos")
            for chave, dados in sorted(adjudicantes.items(), key=lambda item: -item[1]["valor"])[:MAX_ADJUDICANTES]
        ],
        "contrato": [
            _instancia(
                str(contrato.get("id") or f"contrato-{indice}"),
                str(contrato.get("objeto") or "")[:90],
                valor=contrato.get("valor"),
                detalhe=f"{contrato.get('adjudicante') or ''} · {contrato.get('ano') or ''}".strip(" ·"),
            )
            for indice, contrato in enumerate(contratos[:12])
        ],
        "cpv": [
            _instancia(codigo, (dados["descricao"] or codigo)[:60], valor=dados["valor"], detalhe=f"{dados['contratos']} contratos")
            for codigo, dados in sorted(_por_cpv(contratos).items(), key=lambda item: -item[1]["valor"])[:MAX_CPV]
        ],
        "pessoa": [
            _instancia(str(pessoa.get("nif") or pessoa.get("nome") or ""), str(pessoa.get("nome") or ""), detalhe="cargo registado")
            for pessoa in pessoas[:MAX_PESSOAS]
            if pessoa.get("nif") or pessoa.get("nome")
        ],
        "marca": [
            _instancia(str(marca.get("nord") or indice), str(marca.get("nome") or marca.get("marca") or ""))
            for indice, marca in enumerate(((secoes.get("marcas") or {}).get("items") or [])[:MAX_MARCAS])
        ],
        "firma": [
            _instancia(str(firma.get("nipc") or indice), str(firma.get("nome") or firma.get("firma") or ""))
            for indice, firma in enumerate(((secoes.get("firmas") or {}).get("items") or [])[:MAX_FIRMAS])
        ],
        "noticia": [
            _instancia(str(noticia.get("id") or indice), str(noticia.get("titulo") or noticia.get("title") or "")[:90])
            for indice, noticia in enumerate(((secoes.get("noticias") or {}).get("items") or [])[:MAX_NOTICIAS])
        ],
    }

    linhas_tipo: List[Dict[str, Any]] = []
    tipos_usados: List[str] = []
    tipos_declarados_usados: List[str] = []
    for tipo_id, lista in instancias.items():
        if not lista:
            continue
        declarado = tipos_declarados.get(tipo_id)
        fontes_declaradas = [
            str(origem) for origem in ((declarado or {}).get("binding") or {}).get("sources") or [] if origem
        ]
        indice_usado = TIPO_INDICE.get(tipo_id)
        tipos_usados.append(tipo_id)
        if declarado is not None:
            tipos_declarados_usados.append(tipo_id)
        linhas_tipo.append(
            {
                "id": tipo_id,
                "label": (declarado or {}).get("label") or tipo_id,
                "grupo": (declarado or {}).get("domain"),
                "declarado": declarado is not None,
                "indice_usado": indice_usado,
                "fontes_declaradas": fontes_declaradas,
                "origem_declarada": bool(indice_usado) and indice_usado in fontes_declaradas,
                "instancias": len(lista),
                "exemplos": lista[:5],
            }
        )
    linhas_tipo.sort(key=lambda item: (-item["instancias"], item["id"]))

    linhas_ligacao: List[Dict[str, Any]] = []
    materializadas: List[str] = []
    for relacao in _relacoes_evidencia(recolha):
        declarada = por_assinatura.get((relacao["from"], relacao["to"]))
        if declarada is not None:
            materializadas.append(str(declarada["id"]))
        linhas_ligacao.append(
            {
                "id": str(declarada["id"]) if declarada else f"{relacao['from']}->{relacao['to']}",
                "label": (declarada or {}).get("label") or f"{relacao['from']} → {relacao['to']}",
                "from": relacao["from"],
                "to": relacao["to"],
                "declarado": declarada is not None,
                "quantidade": relacao["quantidade"],
                "evidencia": relacao["evidencia"],
            }
        )
    linhas_ligacao.sort(key=lambda item: (-item["quantidade"], item["id"]))

    tipos_ontologia = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "grupo": item.get("domain"),
            "fontes": [
                str(origem) for origem in ((item.get("binding") or {}).get("sources") or []) if origem
            ],
            "materializado": item.get("id") in tipos_usados,
        }
        for item in documento.get("object_types") or []
    ]
    ligacoes_catalogo = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "from": item.get("from"),
            "to": item.get("to"),
            "materializado": str(item.get("id")) in materializadas,
        }
        for item in ligacoes_declaradas
    ]

    percent_tipos = round(len(tipos_declarados_usados) / len(tipos_usados) * 100, 1) if tipos_usados else None
    percent_ligacoes = (
        round(len(set(materializadas)) / len(ligacoes_declaradas) * 100, 1) if ligacoes_declaradas else None
    )

    return {
        "ontologia": (documento.get("ontology") or {}).get("name") or "IQ OS",
        "ontologia_id": (documento.get("ontology") or {}).get("id"),
        "tipos": linhas_tipo,
        "ligacoes": linhas_ligacao,
        "catalogo": {"tipos": tipos_ontologia, "ligacoes": ligacoes_catalogo},
        "cobertura": {
            "tipos_instanciados": len(tipos_usados),
            "tipos_declarados_usados": len(tipos_declarados_usados),
            "percent_tipos": percent_tipos,
            "ligacoes_materializadas": len(set(materializadas)),
            "ligacoes_declaradas": len(ligacoes_declaradas),
            "percent_ligacoes": percent_ligacoes,
        },
        "lacunas": {
            "tipos": [item["id"] for item in linhas_tipo if not item["declarado"]],
            "ligacoes": [item["id"] for item in linhas_ligacao if not item["declarado"]],
        },
        "camadas": (malha.get("meta") or {}).get("camadas") or {},
    }


# ---------------------------------------------------------------------------
# Decisão
# ---------------------------------------------------------------------------
def decisao(recolha: Dict[str, Any]) -> Dict[str, Any]:
    """Números e regras que sustentam uma decisão (delega em `api.descoberta_decisao`).

    Nada aqui depende de um modelo: são agregações da recolha (evolução,
    concentração de compradores, mix de CPV e de procedimento, escalões, preços,
    concorrência, prazos), o cartão de risco e as regras de atenção.
    """
    from api import descoberta_decisao as motor  # noqa: PLC0415

    return motor.decisao(recolha)


# ---------------------------------------------------------------------------
# Skills do Hermes
# ---------------------------------------------------------------------------
def skills(pergunta: Optional[str] = None) -> Dict[str, Any]:
    """Biblioteca de skills que o Hermes segue.

    As skills são o método que os assistentes da plataforma escolhem (ou criam)
    antes de responder — o Hermes, o Chat IA e o RAG partilham a mesma
    biblioteca. A descoberta expõe esta biblioteca para se ver e escolher o
    método, e para pré-visualizar qual seria escolhido para uma pergunta.
    """
    from api import skills_service as biblioteca  # noqa: PLC0415

    itens = [
        {
            "id": skill.get("id"),
            "nome": skill.get("name"),
            "quando": skill.get("when"),
            "passos": len(skill.get("steps") or []),
            "verificacoes": len(skill.get("checks") or []),
            "ferramentas": skill.get("tools") or [],
            "usos": int(skill.get("uses") or 0),
            "ativa": bool(skill.get("enabled", True)),
            "origem": skill.get("origin") or skill.get("source"),
        }
        for skill in biblioteca.list_skills()
    ]
    resposta: Dict[str, Any] = {
        "total": len(itens),
        "ativas": len([item for item in itens if item["ativa"]]),
        "skills": itens,
        "status": biblioteca.status(),
    }
    if pergunta:
        encontrada = biblioteca.match(pergunta)
        resposta["pergunta"] = pergunta
        resposta["sugerida"] = biblioteca.public(encontrada) if encontrada else None
        resposta["score"] = biblioteca.score(encontrada, pergunta) if encontrada else 0.0
    return resposta


def _bloco_da_skill(skill_id: str) -> str:
    """Método da skill escolhida, pronto a injetar no pedido ao Hermes."""
    from api import skills_service as biblioteca  # noqa: PLC0415

    skill = biblioteca.get_skill(str(skill_id))
    if skill is None:
        raise ValueError(f"Skill desconhecida: {skill_id}.")
    if not skill.get("enabled", True):
        raise ValueError(f"A skill «{skill.get('name') or skill_id}» está desativada.")
    return biblioteca.prompt_block(skill, label="Skill escolhida no painel de descoberta")


# Limite de caracteres do pedido ao Hermes (`hermes_service.MAX_QUESTION_CHARS`).
MAX_PEDIDO_CHARS = 1800


# ---------------------------------------------------------------------------
# Análise pelo Hermes
# ---------------------------------------------------------------------------
def pergunta_padrao(recolha: Dict[str, Any]) -> str:
    """Compõe a pergunta do Hermes a partir da recolha, ancorada nos números exatos."""
    nome = str(recolha.get("nome") or "")
    nif = str(recolha.get("nif") or "")
    kpis = recolha.get("kpis") or {}
    maior = kpis.get("maior_adjudicante") or {}

    factos = [
        f"contratos lidos: {kpis.get('contratos') or 0}",
        f"valor contratado: {kpis.get('valor_total') or 0} EUR",
        f"adjudicantes distintos: {kpis.get('adjudicantes') or 0}",
    ]
    if maior.get("nome"):
        factos.append(f"maior adjudicante: {maior['nome']} ({maior.get('valor')} EUR)")
    if kpis.get("concentracao_maior") is not None:
        factos.append(f"concentração no maior adjudicante: {kpis['concentracao_maior']}%")
    if kpis.get("risco"):
        factos.append(f"nível de risco: {kpis['risco']}")
    factos.append(f"pessoas com cargos: {kpis.get('pessoas') or 0}")
    factos.append(f"insolvências (CIRE): {kpis.get('insolvencias') or 0}")
    if kpis.get("subvencoes_valor"):
        factos.append(f"subvenções: {kpis['subvencoes_valor']} EUR")

    return (
        f"Presta uma análise da empresa «{nome}» (NIF {nif}): o que faz, com quem contrata, "
        f"que riscos apresenta e o que deve ser verificado a seguir. "
        f"Factos calculados na plataforma: {'; '.join(factos)}."
    )


async def analisar(
    recolha: Dict[str, Any],
    *,
    pergunta: Optional[str] = None,
    profundidade: Optional[str] = None,
    fontes: Optional[Sequence[str]] = None,
    backend: Optional[str] = None,
    skill_id: Optional[str] = None,
    session: Any = None,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pede ao Hermes a análise citada da empresa, com as skills da plataforma.

    Sem `skill_id`, é o Hermes que escolhe (ou cria) a skill do pedido — é o
    comportamento normal dos assistentes da plataforma. Com `skill_id`, o método
    da skill escolhida é injetado no pedido, para o painel poder impor um método.
    """
    from api import hermes_service as hermes  # noqa: PLC0415

    nif = str(recolha.get("nif") or "")
    if not nif:
        raise ValueError("Recolha sem NIF: não há empresa para analisar.")

    texto = (pergunta or "").strip() or pergunta_padrao(recolha)
    metodo = _bloco_da_skill(skill_id) if skill_id else ""
    if metodo:
        # O bloco do método entra primeiro e a pergunta fica inteira: corta-se o
        # bloco, nunca o pedido.
        disponivel = max(0, MAX_PEDIDO_CHARS - len(texto) - 2)
        texto = f"{metodo[:disponivel]}\n\n{texto}" if disponivel > 0 else texto

    resultado = await hermes.ask(
        texto,
        depth=str(profundidade or hermes.DEFAULT_DEPTH),
        sources_ids=list(fontes) if fontes else None,
        backend=backend,
        scope=scope,
        session=session,
        country="PRT",
    )
    return {
        "pergunta": texto,
        "nif": nif,
        "profundidade": profundidade or hermes.DEFAULT_DEPTH,
        "skill_imposta": skill_id or None,
        **resultado,
    }


__all__ = [
    "FONTES",
    "FONTE_IDS",
    "analisar",
    "decisao",
    "grafo",
    "meta",
    "normalizar_nif",
    "ontologia",
    "pergunta_padrao",
    "recolher",
    "resolver",
    "skills",
]
