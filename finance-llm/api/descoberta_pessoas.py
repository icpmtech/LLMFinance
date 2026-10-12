"""Descoberta de **pessoas** a partir das empresas (`/descoberta/pessoas/*`).

O painel de uma empresa responde «o que é isto?». Este módulo faz a pergunta ao
contrário: dão-se uma ou várias empresas (NIF ou nome) e pergunta-se *quem está
por trás delas?* As fontes dizem, todas sobre pessoas:

1. **Cargos societários** — `finance_people`: gerência, conselhos de
   administração e restantes órgãos sociais, com as datas e os atos que os
   registam (publicações de registo comercial).
2. **Capital** — os mesmos registos dizem quem tem quota: os sócios.
3. **Universo da pessoa** — onde mais cada pessoa tem cargos (a rede para fora
   das empresas do pedido), já somada na ficha de cada uma.
4. **Processos do CIRE** — quem é nomeado nos processos em que as empresas são
   parte: administradores de insolvência, credores pessoa e insolventes.
5. **Listas de devedores** — se os titulares encontrados figuram nas listas das
   Finanças ou da Segurança Social (amostra dos titulares mais relevantes).

Com **duas ou mais** empresas, a pergunta que só aí existe é *quem as liga*:
quem se senta nas duas, quem gere várias, quem só aparece numa. É a leitura do
painel de conjunto das empresas, mas do lado das pessoas.

Não indexa nada e não fala com o Elasticsearch diretamente: orquestra os
serviços existentes (`elasticsearch_client`, `cire_service`,
`devedores_service`) e o catálogo de órgãos sociais do módulo de padrões.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api import cire_service
from api import descoberta_service as service
from api import devedores_service
from api import elasticsearch_client as es_client

logger = logging.getLogger(__name__)

PAIS_DEFAULT = service.PAIS_DEFAULT
PAISES_SUPORTADOS = service.PAISES_SUPORTADOS

#: Uma empresa já é uma descoberta («quem manda aqui?»); acima de seis deixa de
#: caber num painel que se lê de uma vez.
MIN_EMPRESAS = 1
MAX_EMPRESAS = 6

#: Pessoas lidas por empresa. Acima disto é truncagem — e o painel di-lo.
MAX_PESSOAS_POR_EMPRESA = 300
#: Pessoas devolvidas no painel (ordenadas por relevância de decisão).
MAX_PESSOAS_PAINEL = 120
#: Pessoas desenhadas no grafo.
MAX_GRAFO_PESSOAS = 40
#: Processos do CIRE lidos por empresa.
MAX_PROCESSOS = 40
#: Titulares verificados nas listas de devedores (uma consulta por titular).
MAX_DEVEDORES = 12
#: Acumulação de cargos no universo que merece aviso.
LIMIAR_EMPRESAS_UNIVERSO = 5
#: Um cargo registado nos últimos meses é uma mudança de gestão, não historial.
LIMIAR_RECENTE_DIAS = 90
#: Barra de cargos do painel.
MAX_BARRAS_CARGO = 10

FONTE_TIMEOUT = 60.0
MAX_PARALELO = 6

SEVERIDADE_ORDEM = {"alerta": 0, "aviso": 1, "info": 2}

#: Papéis processuais do CIRE. São de pessoas, mas não são gestão: quem é credor
#: de várias empresas falidas não está ligado a elas por um laço societário.
PAPEIS_PROCESSUAIS = (
    "Credor",
    "Insolvente",
    "Requerente",
    "Requerido",
    "Devedor",
    "Administrador da insolvência",
    "Administrador judicial",
    "Fiel depositário",
)
#: Títulos que, no `role` do registo, contam como cargo de gestão (o `role_org`
#: vem truncado em algumas publicações, pelo que o nome do cargo desempata).
CARGOS_GESTAO_NOMES = (
    "presidente",
    "vice-presidente",
    "vogal",
    "gerente",
    "gestor",
    "administrador",
    "administrador-delegado",
    "diretor",
    "sócio-gerente",
    "membro",
)
def _orgaos_gestao() -> Tuple[str, ...]:
    """Órgãos sociais que contam como gestão: a lista do módulo de padrões.

    É a mesma fronteira que o grafo de padrões usa — sem ela, ligar pessoas por
    serem credoras umas das outras seria ruído, não laço societário.
    """
    from api import padroes_service as padroes  # noqa: PLC0415

    return padroes.CARGO_GESTAO_ORGS


# ---------------------------------------------------------------------------
# Catálogo de fontes
# ---------------------------------------------------------------------------
# `tipo` é o tipo de nó do grafo (a taxonomia do estúdio, em `TYPE_COLORS`);
# `fonte_plataforma` é o índice de onde a evidência vem, para a descoberta poder
# ser confrontada com a ontologia como no painel das empresas.
FONTES: List[Dict[str, Any]] = [
    {
        "id": "cargos",
        "label": "Cargos societários",
        "grupo": "governo",
        "descricao": "Quem tem cargo de órgão social registado nas empresas (publicações de registo comercial).",
        "indice": "finance_people",
    },
    {
        "id": "quotas",
        "label": "Capital e quotas",
        "grupo": "governo",
        "descricao": "Sócios e titulares de capital com quota registada nos mesmos atos.",
        "indice": "finance_people",
    },
    {
        "id": "universo",
        "label": "Universo da pessoa",
        "grupo": "rede",
        "descricao": "Todas as empresas onde cada pessoa tem cargos — a rede para fora das empresas pedidas.",
        "indice": "finance_people",
    },
    {
        "id": "cire",
        "label": "Processos do CIRE",
        "grupo": "risco",
        "descricao": "Pessoas nomeadas nos processos de insolvência e revitalização em que as empresas são parte.",
        "indice": "finance_cire",
    },
    {
        "id": "devedores",
        "label": "Listas de devedores",
        "grupo": "risco",
        "descricao": "Titulares encontrados nas listas de devedores das Finanças e da Segurança Social.",
        "indice": "finance_devedores",
    },
]
FONTE_BY_ID = {fonte["id"]: fonte for fonte in FONTES}
FONTE_IDS = [fonte["id"] for fonte in FONTES]

#: Classes de cargo, da mais para a menos relevante para decidir quem olhar.
CLASSES = ("gestao", "capital", "processo", "outro")
CLASSE_LABEL = {
    "gestao": "Órgão social",
    "capital": "Capital",
    "processo": "Processo do CIRE",
    "outro": "Outro cargo",
}


def meta() -> Dict[str, Any]:
    """Catálogo de fontes, classes de cargo e limites do módulo."""
    return {
        "fontes": FONTES,
        "grupos": sorted({fonte["grupo"] for fonte in FONTES}),
        "pais": list(PAISES_SUPORTADOS),
        "classes": [{"id": classe, "label": CLASSE_LABEL[classe]} for classe in CLASSES],
        "orgaos_gestao": list(_orgaos_gestao()),
        "limites": {
            "empresas": MAX_EMPRESAS,
            "pessoas_por_empresa": MAX_PESSOAS_POR_EMPRESA,
            "pessoas_painel": MAX_PESSOAS_PAINEL,
            "pessoas_grafo": MAX_GRAFO_PESSOAS,
            "processos": MAX_PROCESSOS,
            "devedores": MAX_DEVEDORES,
            "timeout_fonte": FONTE_TIMEOUT,
            "paralelo": MAX_PARALELO,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fold(valor: Any) -> str:
    """Minúsculas sem acentos (comparação de vocabulário do registo)."""
    from api import padroes_service as padroes  # noqa: PLC0415

    return padroes.fold(valor)


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _data(valor: Any) -> str:
    """Data em ISO, aceitando o `AAAA.MM.DD` que aparece em alguns atos."""
    texto = _texto(valor)
    if not texto:
        return ""
    return texto.replace(".", "-")[:10]


def _classe_cargo(cargo: Dict[str, Any]) -> str:
    """Classifica um cargo: órgão social, capital, processo do CIRE ou outro.

    A ordem importa: «Administrador da insolvência» contém «administrador», mas
    é um papel de processo — e é isso que a leitura do painel tem de dizer.
    """
    papel = _fold(cargo.get("role"))
    if papel and any(_fold(nome) == papel for nome in PAPEIS_PROCESSUAIS):
        return "processo"
    if cargo.get("quota") not in (None, "", 0) or _fold(cargo.get("role")) == "socio":
        return "capital"
    orgao = _fold(cargo.get("role_org"))
    if orgao and any(_fold(nome) in orgao for nome in _orgaos_gestao()):
        return "gestao"
    if papel and any(nome in papel for nome in CARGOS_GESTAO_NOMES):
        return "gestao"
    return "outro"


def _melhor_classe(classes: Iterable[str]) -> str:
    presentes = set(classes)
    for classe in CLASSES:
        if classe in presentes:
            return classe
    return "outro"


def _mais_recente(cargos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return max(cargos, key=lambda cargo: _texto(cargo.get("data")), default={})


def _mais_antigo(cargos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    com_data = [cargo for cargo in cargos if _texto(cargo.get("data"))]
    return min(com_data, key=lambda cargo: _texto(cargo.get("data")), default={})


def _cargo_normalizado(cargo: Dict[str, Any]) -> Dict[str, Any]:
    """Cargo como o painel o lê: o que o registo diz e a que classe pertence."""
    return {
        "role": _texto(cargo.get("role")),
        "titulo": _titulo(cargo),
        "role_org": _texto(cargo.get("role_org")),
        "evento": _texto(cargo.get("event")),
        "data": _data(cargo.get("date")),
        "ato": _texto(cargo.get("acto")),
        "publicacao": _texto(cargo.get("publication_id")),
        "quota": cargo.get("quota"),
        "causa": _texto(cargo.get("causa")),
        "tribunal": _texto(cargo.get("tribunal")),
        "classe": _classe_cargo(cargo),
    }


#: Marcas que as publicações colam ao cargo («Vogal Causa: renúncia Data: …»): o
#: título acaba na primeira delas — o resto é o motivo e a data, não o título.
_RUIDO_DO_CARGO = ("causa:", "data:", "nif/nipc:", "nif:", "nipc:", "concelho:")


def _titulo(cargo: Dict[str, Any]) -> str:
    """Título do cargo, limpo do ruído que a publicação cola ao papel.

    «Vogal Causa: renúncia Data: 2022.04.30» é um título — «Vogal». Sem a limpeza,
    o grafo e as listas mostrariam a frase da publicação como se fosse o cargo.
    """
    papel = _texto(cargo.get("role"))
    baixo = _fold(papel)
    for marca in _RUIDO_DO_CARGO:
        corte = baixo.find(marca)
        if corte > 0:
            papel = papel[:corte].strip(" ,;-–")
            baixo = _fold(papel)
    if papel:
        return papel
    orgao = _texto(cargo.get("role_org"))
    return orgao


def _titulos(pessoa: Dict[str, Any]) -> List[str]:
    """Títulos da pessoa nas empresas do pedido, do mais recente para o mais antigo."""
    titulos: List[str] = []
    for empresa in pessoa.get("empresas") or []:
        for cargo in empresa.get("cargos") or []:
            titulo = _texto(cargo.get("titulo")) or _titulo(cargo)
            if titulo and titulo not in titulos:
                titulos.append(titulo)
    return titulos


# ---------------------------------------------------------------------------
# Recolha por empresa
# ---------------------------------------------------------------------------
def _nome_da_empresa(nif: str) -> str:
    """Nome da empresa no cadastro (para uma empresa sem cargos registados)."""
    try:
        resolucao = service.resolver(nif, size=1)
    except Exception as exc:  # noqa: BLE001 - sem nome, o painel mostra o NIF
        logger.warning("Descoberta de pessoas: nome de %s falhou: %s", nif, exc)
        return ""
    item = next(iter(resolucao.get("items") or []), None)
    return _texto((item or {}).get("nome"))


def _pessoas_da_empresa(nif: str, nome: str = "") -> Dict[str, Any]:
    """Pessoas com cargos na empresa (ficha de empresa do PessoasIQ)."""
    iniciado = time.perf_counter()
    try:
        ficha = es_client.company_people_from_index(nif, size=MAX_PESSOAS_POR_EMPRESA)
    except Exception as exc:  # noqa: BLE001 - uma empresa má não derruba o painel
        logger.warning("Descoberta de pessoas: cargos de %s falharam: %s", nif, exc)
        return {
            "nif": nif,
            "nome": nome or nif,
            "pessoas": [],
            "total": 0,
            "truncado": False,
            "erro": str(exc),
            "ms": int((time.perf_counter() - iniciado) * 1000),
        }
    pessoas = ficha.get("people") or []
    total = int(ficha.get("total") or len(pessoas))
    return {
        "nif": nif,
        "nome": ficha.get("name") or nome or nif,
        "pessoas": pessoas,
        "total": total,
        "truncado": total > len(pessoas),
        "erro": ficha.get("error"),
        "ms": int((time.perf_counter() - iniciado) * 1000),
    }


def _cire_da_empresa(nif: str) -> Dict[str, Any]:
    """Processos do CIRE da empresa, com as pessoas nomeadas em cada um."""
    iniciado = time.perf_counter()
    try:
        resultado = cire_service.search(nif=nif, size=MAX_PROCESSOS)
    except Exception as exc:  # noqa: BLE001 - o CIRE é uma fonte, não um requisito
        logger.warning("Descoberta de pessoas: CIRE de %s falhou: %s", nif, exc)
        return {"nif": nif, "processos": [], "pessoas": {}, "total": 0, "erro": str(exc), "ms": 0}
    if resultado.get("error"):
        return {"nif": nif, "processos": [], "pessoas": {}, "total": 0, "erro": resultado["error"], "ms": 0}

    processos: List[Dict[str, Any]] = []
    pessoas: Dict[str, List[Dict[str, Any]]] = {}
    for documento in resultado.get("items") or []:
        processo = {
            "processo": _texto(documento.get("processo_numero") or documento.get("processo")),
            "especie": _texto(documento.get("especie")),
            "ato": _texto(documento.get("ato")),
            "tribunal": _texto(documento.get("tribunal")),
            "data": _data(documento.get("data_publicacao")),
            "insolvente": _texto(documento.get("insolvente")),
        }
        intervenientes = []
        for interveniente in documento.get("intervenientes") or []:
            if not isinstance(interveniente, dict):
                continue
            papel = _texto(interveniente.get("papel"))
            pessoa_nif = _texto(interveniente.get("nif"))
            nome = _texto(interveniente.get("nome"))
            if not pessoa_nif and not nome:
                continue
            intervenientes.append({"nome": nome, "nif": pessoa_nif, "papel": papel})
            if pessoa_nif:
                pessoas.setdefault(pessoa_nif, []).append({**processo, "papel": papel})
        processo["intervenientes"] = len(intervenientes)
        processos.append(processo)

    return {
        "nif": nif,
        "processos": processos,
        "pessoas": pessoas,
        "total": int(resultado.get("total") or len(processos)),
        "erro": None,
        "ms": int((time.perf_counter() - iniciado) * 1000),
    }


def _devedores_das_pessoas(nifs: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Verifica as listas de devedores para os NIF indicados, em paralelo."""
    alvos = [nif for nif in dict.fromkeys(_texto(nif) for nif in nifs) if nif]
    if not alvos:
        return {}
    cliente = None
    try:
        cliente = es_client.get_es_client()
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("Descoberta de pessoas: cliente de devedores indisponível: %s", exc)

    encontrados: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_PARALELO, len(alvos))) as pool:
        futuros = {pool.submit(devedores_service.por_nif, nif, es=cliente): nif for nif in alvos}
        for futuro in as_completed(futuros):
            nif = futuros[futuro]
            try:
                resultado = futuro.result()
            except Exception as exc:  # noqa: BLE001 - a lista é um extra, não um requisito
                logger.warning("Descoberta de pessoas: devedores de %s falharam: %s", nif, exc)
                continue
            if resultado.get("error"):
                continue
            encontrados[nif] = {
                "total": int(resultado.get("total") or 0),
                "devedor": bool(resultado.get("devedor")),
                "entidades": resultado.get("entidades") or [],
                "escaloes": resultado.get("escaloes") or [],
                "maior_valor_min": resultado.get("maior_valor_min"),
            }
    return encontrados


# ---------------------------------------------------------------------------
# Fusão das empresas numa lista de pessoas
# ---------------------------------------------------------------------------
def _recolher_empresas(
    pedidos: Sequence[Dict[str, str]], fontes: Sequence[str], timeout: float = FONTE_TIMEOUT
) -> List[Dict[str, Any]]:
    """Recolhe as fontes de todas as empresas em paralelo, sem perder nenhuma."""
    empresas: Dict[str, Dict[str, Any]] = {}
    for pedido in pedidos:
        nif = pedido["nif"]
        empresas[nif] = {
            "nif": nif,
            "nome": pedido.get("nome") or nif,
            "pessoas": [],
            "total": 0,
            "truncado": False,
            "erro": None,
            "estado": "vazio",
            "ms": None,
            "processos": [],
            "processos_total": 0,
            "cire_erro": None,
            "cire_pessoas": 0,
            "cire_map": {},
        }

    # `cargos`, `quotas` e `universo` saem da mesma leitura de `finance_people`:
    # pedem-se uma vez por empresa e as três classes derivam-se depois.
    futuros: Dict[Future, Tuple[str, str]] = {}
    pool = ThreadPoolExecutor(max_workers=min(MAX_PARALELO, max(1, len(pedidos) * 2)))
    pendentes: set = set()
    try:
        for pedido in pedidos:
            nif = pedido["nif"]
            futuro = pool.submit(_pessoas_da_empresa, nif, pedido.get("nome") or "")
            futuros[futuro] = ("cargos", nif)
            pendentes.add(futuro)
            if "cire" in fontes:
                futuro = pool.submit(_cire_da_empresa, nif)
                futuros[futuro] = ("cire", nif)
                pendentes.add(futuro)

        try:
            for futuro in as_completed(futuros, timeout=timeout):
                pendentes.discard(futuro)
                tipo, nif = futuros[futuro]
                _registar_empresa(empresas[nif], tipo, futuro)
        except FutureTimeoutError:
            for futuro in pendentes:
                tipo, nif = futuros[futuro]
                logger.warning("Descoberta de pessoas: %s de %s excedeu %.0fs", tipo, nif, timeout)
                if tipo == "cargos":
                    empresas[nif]["erro"] = f"tempo excedido ({timeout:.0f}s)"
                    empresas[nif]["estado"] = "tempo"
                else:
                    empresas[nif]["cire_erro"] = f"tempo excedido ({timeout:.0f}s)"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return [empresas[pedido["nif"]] for pedido in pedidos]


def _registar_empresa(empresa: Dict[str, Any], tipo: str, futuro: Future) -> None:
    try:
        resultado = futuro.result()
    except Exception as exc:  # noqa: BLE001 - a falha de uma empresa é reportada, não levantada
        logger.warning("Descoberta de pessoas: recolha falhou: %s", exc)
        if tipo == "cargos":
            empresa["erro"] = str(exc)
            empresa["estado"] = "erro"
        else:
            empresa["cire_erro"] = str(exc)
        return

    if tipo == "cargos":
        empresa["pessoas"] = resultado.get("pessoas") or []
        empresa["total"] = resultado.get("total") or 0
        empresa["truncado"] = bool(resultado.get("truncado"))
        empresa["ms"] = resultado.get("ms")
        if not empresa.get("nome") or empresa["nome"] == empresa["nif"]:
            empresa["nome"] = resultado.get("nome") or empresa["nome"]
        if resultado.get("erro"):
            empresa["erro"] = resultado["erro"]
            empresa["estado"] = "erro"
        else:
            empresa["estado"] = "ok" if empresa["pessoas"] else "vazio"
        return

    empresa["processos"] = resultado.get("processos") or []
    empresa["processos_total"] = resultado.get("total") or 0
    empresa["cire_map"] = resultado.get("pessoas") or {}
    empresa["cire_pessoas"] = len(empresa["cire_map"])
    empresa["cire_erro"] = resultado.get("erro")


def _fundir(empresas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta as pessoas das empresas do pedido numa ficha por NIF."""
    indices = {empresa["nif"]: indice for indice, empresa in enumerate(empresas)}
    pessoas: Dict[str, Dict[str, Any]] = {}

    for empresa in empresas:
        for registo in empresa.get("pessoas") or []:
            nif = _texto(registo.get("nif"))
            if not nif:
                continue
            pessoa = pessoas.get(nif)
            if pessoa is None:
                pessoa = pessoas[nif] = {
                    "nif": nif,
                    "nome": _texto(registo.get("name")) or nif,
                    "is_company": bool(registo.get("is_company")),
                    "empresas": [],
                    "outras_empresas": [],
                    "origens": [],
                    "classes": [],
                    "quota": None,
                    "cargos_pedido": 0,
                    "cargos_universo": 0,
                    "empresas_universo": 0,
                    "ultimo": "",
                    "cire": [],
                    "devedores": None,
                }
            indice_empresa = indices[empresa["nif"]]
            cargos = [_cargo_normalizado(cargo) for cargo in (registo.get("roles") or [])]
            classes = [cargo["classe"] for cargo in cargos] or [_classe_cargo(registo)]
            for classe in classes:
                if classe not in pessoa["classes"]:
                    pessoa["classes"].append(classe)
            for cargo in cargos:
                if cargo["quota"] not in (None, "", 0):
                    quota = float(cargo["quota"])
                    pessoa["quota"] = quota if pessoa["quota"] is None else max(pessoa["quota"], quota)
            for origem in registo.get("origens") or ([registo.get("origin")] if registo.get("origin") else []):
                origem = _texto(origem)
                if origem and origem not in pessoa["origens"]:
                    pessoa["origens"].append(origem)
            for outra in registo.get("outras_empresas") or []:
                nif_outra = _texto(outra.get("nif"))
                if nif_outra and nif_outra not in indices and nif_outra != nif:
                    if not any(item["nif"] == nif_outra for item in pessoa["outras_empresas"]):
                        pessoa["outras_empresas"].append({"nif": nif_outra, "nome": _texto(outra.get("nome"))})

            recente = _mais_recente(cargos) if cargos else {}
            antigo = _mais_antigo(cargos) if cargos else {}
            pessoa["empresas"].append(
                {
                    "nif": empresa["nif"],
                    "nome": empresa["nome"],
                    "cargos": cargos,
                    "cargos_total": int(registo.get("cargos_empresa") or len(cargos) or 1),
                    "cargo_atual": _texto(registo.get("cargo")),
                    "titulo": _titulo(recente) or _texto(registo.get("cargo")),
                    "role_org": _texto(registo.get("role_org")),
                    "evento": _texto(registo.get("event")),
                    "desde": _texto(antigo.get("data")),
                    "ultimo": _texto(recente.get("data")) or _data(registo.get("date")),
                    "ato": _texto(recente.get("ato")) or _texto(registo.get("acto")),
                    "classes": classes,
                    "indice": indice_empresa,
                }
            )
            pessoa["cargos_pedido"] += int(registo.get("cargos_empresa") or len(cargos) or 1)
            pessoa["cargos_universo"] = max(pessoa["cargos_universo"], int(registo.get("roles_total") or 0))
            pessoa["empresas_universo"] = max(pessoa["empresas_universo"], int(registo.get("companies_total") or 0))
            pessoa["is_company"] = pessoa["is_company"] or bool(registo.get("is_company"))

    for pessoa in pessoas.values():
        _fechar_pessoa(pessoa)
    return sorted(pessoas.values(), key=_ordem)


def _fechar_pessoa(pessoa: Dict[str, Any]) -> None:
    """Deriva da lista de empresas o resumo que o painel mostra por pessoa."""
    cargos_todos = [cargo for empresa in pessoa["empresas"] for cargo in empresa["cargos"]]
    recente = _mais_recente(cargos_todos) if cargos_todos else {}
    antigo = _mais_antigo(cargos_todos) if cargos_todos else {}
    pessoa["empresas"].sort(key=lambda empresa: empresa["indice"])
    pessoa["classe"] = _melhor_classe(pessoa["classes"])
    pessoa["classe_label"] = CLASSE_LABEL[pessoa["classe"]]
    pessoa["gestao"] = "gestao" in pessoa["classes"]
    pessoa["capital"] = "capital" in pessoa["classes"]
    pessoa["processo"] = "processo" in pessoa["classes"]
    pessoa["empresas_pedido"] = len(pessoa["empresas"])
    pessoa["ligacao"] = pessoa["empresas_pedido"] > 1
    pessoa["cargo_atual"] = _texto(recente.get("role") or pessoa["empresas"][-1]["cargo_atual"])
    pessoa["role_org"] = _texto(recente.get("role_org") or pessoa["empresas"][-1]["role_org"])
    pessoa["desde"] = _texto(antigo.get("data"))
    pessoa["ultimo"] = _texto(recente.get("data"))
    pessoa["ato"] = _texto(recente.get("ato"))
    # O título é o que se mostra por cima do nome no grafo e nas listas: o cargo
    # limpo («Presidente», «Vogal»), não a frase da publicação.
    pessoa["titulos"] = _titulos(pessoa)
    pessoa["titulo"] = pessoa["titulos"][0] if pessoa["titulos"] else ""
    pessoa["outras_empresas"].sort(key=lambda item: item["nome"])
    pessoa["evidencia"] = _evidencia(pessoa)


def _evidencia(pessoa: Dict[str, Any]) -> List[str]:
    """Frases de evidência por pessoa, todas derivadas dos cargos lidos."""
    linhas: List[str] = []
    for empresa in pessoa["empresas"]:
        cargo = empresa["titulo"] or empresa["cargo_atual"] or "cargo registado"
        orgao = f" ({empresa['role_org']})" if empresa["role_org"] else ""
        quando = f" ({empresa['ultimo']})" if empresa["ultimo"] else ""
        linhas.append(f"{cargo}{orgao} em {empresa['nome']}{quando}")
    if pessoa["quota"] is not None:
        linhas.append(f"Quota registada: {pessoa['quota']:g}")
    if pessoa["outras_empresas"]:
        linhas.append(
            f"Mais {len(pessoa['outras_empresas'])} empresa(s) no universo: "
            + ", ".join(item["nome"] or item["nif"] for item in pessoa["outras_empresas"][:3])
        )
    if pessoa["cire"]:
        papeis = sorted({item["papel"] for item in pessoa["cire"] if item.get("papel")})
        linhas.append(f"Nos processos do CIRE como {', '.join(papeis) or 'interveniente'}")
    if pessoa["devedores"] and pessoa["devedores"].get("devedor"):
        linhas.append("Figura nas listas de devedores: " + ", ".join(pessoa["devedores"]["entidades"]))
    return linhas


def _ordem(pessoa: Dict[str, Any]) -> Tuple[int, int, int, int, int, str]:
    """Ordem de leitura: gestão primeiro, depois quem liga empresas, depois o resto."""
    return (
        0 if pessoa.get("gestao") else 1 if pessoa.get("capital") else 2,
        0 if pessoa.get("ligacao") else 1,
        -int(pessoa.get("empresas_pedido") or 0),
        -int(pessoa.get("cargos_pedido") or 0),
        -int(pessoa.get("empresas_universo") or 0),
        pessoa.get("nome") or "",
    )


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------
def _titulares_de_devedores(pessoas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Os titulares mais relevantes: é neles que vale a pena consultar as listas."""
    return [pessoa for pessoa in pessoas if not pessoa.get("is_company")][:MAX_DEVEDORES]


def _cargos_distribuicao(pessoas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Distribuição por cargo: quantas pessoas e quantas empresas cada um toca."""
    cargos: Dict[str, Dict[str, Any]] = {}
    for pessoa in pessoas:
        vistos: Dict[str, set] = {}
        for empresa in pessoa["empresas"]:
            for cargo in empresa["cargos"]:
                papel = _texto(cargo.get("role")) or "sem cargo indicado"
                registo = cargos.setdefault(
                    papel,
                    {"cargo": papel, "pessoas": 0, "empresas": set(), "classe": cargo.get("classe")},
                )
                registo["empresas"].add(empresa["nif"])
                vistos.setdefault(papel, set()).add(pessoa["nif"])
        for papel, nifs in vistos.items():
            cargos[papel]["pessoas"] += len(nifs)
    saida = [
        {**registo, "empresas": len(registo["empresas"])}
        for registo in sorted(cargos.values(), key=lambda item: (-item["pessoas"], item["cargo"]))
    ]
    return saida[:MAX_BARRAS_CARGO]


def _ligacoes(pessoas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quem aparece em duas ou mais empresas do pedido — o que as liga."""
    ligacoes = []
    for pessoa in pessoas:
        if not pessoa.get("ligacao"):
            continue
        ligacoes.append(
            {
                "nif": pessoa["nif"],
                "nome": pessoa["nome"],
                "is_company": pessoa["is_company"],
                "empresas": [
                    {
                        "nif": empresa["nif"],
                        "nome": empresa["nome"],
                        "cargo": empresa["titulo"] or empresa["cargo_atual"],
                        "role_org": empresa["role_org"],
                    }
                    for empresa in pessoa["empresas"]
                ],
                "empresas_pedido": pessoa["empresas_pedido"],
                "cargos": pessoa["cargos_pedido"],
                "titulo": pessoa["titulo"],
                "titulos": pessoa["titulos"],
                "classe": pessoa["classe"],
                "classe_label": pessoa["classe_label"],
            }
        )
    ligacoes.sort(key=lambda item: (-item["empresas_pedido"], -item["cargos"], item["nome"]))
    return ligacoes


def _kpis(empresas: Sequence[Dict[str, Any]], pessoas: Sequence[Dict[str, Any]], cargos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    com_cargos = [empresa for empresa in empresas if empresa.get("pessoas")]
    devedores = [pessoa for pessoa in pessoas if (pessoa.get("devedores") or {}).get("devedor")]
    cargos_lidos = sum(int(empresa.get("total") or len(empresa.get("pessoas") or [])) for empresa in empresas)
    processos = sum(len(empresa.get("processos") or []) for empresa in empresas)
    profundidade = round(sum(int(pessoa["cargos_pedido"]) for pessoa in pessoas) / len(pessoas), 2) if pessoas else None
    return {
        "empresas": len(empresas),
        "empresas_com_pessoas": len(com_cargos),
        "empresas_sem_pessoas": len(empresas) - len(com_cargos),
        "pessoas": len(pessoas),
        "cargos": cargos_lidos,
        "gestao": sum(1 for pessoa in pessoas if pessoa.get("gestao")),
        "capital": sum(1 for pessoa in pessoas if pessoa.get("capital")),
        "processo": sum(1 for pessoa in pessoas if pessoa.get("processo")),
        "em_varias": sum(1 for pessoa in pessoas if pessoa.get("ligacao")),
        "universo_multi": sum(1 for pessoa in pessoas if int(pessoa.get("empresas_universo") or 0) > 1),
        "acumulacao": sum(1 for pessoa in pessoas if int(pessoa.get("empresas_universo") or 0) >= LIMIAR_EMPRESAS_UNIVERSO),
        "processos": processos,
        "cire_pessoas": sum(1 for pessoa in pessoas if pessoa.get("cire")),
        "devedores": len(devedores),
        "cargo_top": cargos[0] if cargos else None,
        "profundidade": profundidade,
    }


def _atencao(empresas: Sequence[Dict[str, Any]], pessoas: Sequence[Dict[str, Any]], ligacoes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """O que verificar primeiro — as mesmas severidades do painel das empresas."""
    itens: List[Dict[str, Any]] = []

    def juntar(severidade: str, titulo: str, detalhe: str, verificar: str) -> None:
        itens.append({"severidade": severidade, "titulo": titulo, "detalhe": detalhe, "verificar": verificar})

    for ligacao in ligacoes:
        empresas_nome = ", ".join(empresa["nome"] for empresa in ligacao["empresas"])
        severidade = "alerta" if ligacao["classe"] in ("gestao", "capital") else "aviso"
        juntar(
            severidade,
            f"{ligacao['nome']} liga {ligacao['empresas_pedido']} empresas do pedido",
            f"Cargo em {empresas_nome}. Uma pessoa com cargo em duas das empresas liga-as: o risco de uma não é independente do da outra.",
            "Confirmar que é a mesma pessoa (o NIF coincide) e desde quando tem cargo em cada empresa.",
        )

    sem_pessoas = [empresa for empresa in empresas if not empresa.get("pessoas") and not empresa.get("erro")]
    for empresa in sem_pessoas:
        juntar(
            "aviso",
            f"Sem cargos registados em {empresa['nome']}",
            "Não há publicações de registo comercial com órgãos sociais desta empresa na plataforma. Não é ausência de gestão: é ausência de registo.",
            "Recolher as publicações societárias desta empresa antes de concluir que não tem titulares.",
        )

    for empresa in empresas:
        if empresa.get("erro"):
            juntar(
                "aviso",
                f"Recolha incompleta em {empresa['nome']}",
                f"A leitura dos cargos falhou ({empresa['erro']}): as pessoas desta empresa podem estar em falta.",
                "Repetir a descoberta ou confirmar o NIF antes de usar a lista.",
            )
        if empresa.get("truncado"):
            juntar(
                "info",
                f"{empresa['nome']}: lista limitada a {len(empresa.get('pessoas') or [])} de {empresa.get('total')} pessoas",
                "A empresa tem mais pessoas com cargos do que as mostradas — a ordenação é por número de cargos.",
                "Reduzir o âmbito (uma empresa de cada vez) para ver a lista completa.",
            )

    for pessoa in pessoas:
        total_empresas = int(pessoa.get("empresas_universo") or 0)
        if total_empresas >= LIMIAR_EMPRESAS_UNIVERSO:
            juntar(
                "aviso",
                f"{pessoa['nome']} tem cargos em {total_empresas} empresas",
                "Acumulação de cargos no universo da plataforma (não só nas empresas deste pedido).",
                "Ver o universo da pessoa antes de a tratar como gestora desta empresa apenas.",
            )

    for pessoa in pessoas:
        if (pessoa.get("devedores") or {}).get("devedor"):
            entidades = ", ".join(pessoa["devedores"]["entidades"]) or "listas de devedores"
            juntar(
                "alerta",
                f"{pessoa['nome']} figura nas listas de devedores",
                f"Presença em {entidades} com {pessoa['devedores']['total']} registo(s).",
                "Confirmar o NIF na lista oficial e, se coincidir, ponderar antes de contratar com esta empresa.",
            )

    for pessoa in pessoas:
        papeis = {item.get("papel") for item in pessoa.get("cire") or []}
        if "Insolvente" in papeis:
            juntar(
                "alerta",
                f"{pessoa['nome']} é insolvente num processo do CIRE",
                "A pessoa (não a empresa) aparece como insolvente num processo em que uma das empresas do pedido é parte.",
                "Confirmar se é a mesma pessoa e o efeito do processo na capacidade de gerir a empresa.",
            )

    gestores = [pessoa for pessoa in pessoas if pessoa.get("gestao")]
    for empresa in empresas:
        nif = empresa["nif"]
        equipa = [pessoa for pessoa in gestores if any(item["nif"] == nif for item in pessoa["empresas"])]
        if len(equipa) == 1:
            juntar(
                "aviso",
                f"{empresa['nome']} tem um só titular de órgão social registado",
                f"Todo o poder registado está em {equipa[0]['nome']}: a empresa depende de uma pessoa.",
                "Confirmar a composição atual dos órgãos sociais na publicação mais recente.",
            )

    sem_gestao = [pessoa for pessoa in pessoas if pessoa.get("processo") and not pessoa.get("gestao")]
    if sem_gestao:
        juntar(
            "info",
            f"{len(sem_gestao)} pessoa(s) só aparecem por papéis de processo",
            "São credoras, insolventes ou administradores de insolvência nos processos das empresas — não são órgãos sociais.",
            "Não tratar estas pessoas como titulares; servem de contexto de mercado e de risco.",
        )

    sociedades = [pessoa for pessoa in pessoas if pessoa.get("is_company")]
    if sociedades:
        juntar(
            "info",
            f"{len(sociedades)} «pessoa(s)» são sociedades",
            "Aparecem no índice de pessoas com NIF coletivo (por exemplo, sociedades de revisores oficiais de contas).",
            "Confirmar o titular humano por trás da sociedade antes de a analisar como pessoa.",
        )

    recentes = [pessoa for pessoa in pessoas if _recente(pessoa)]
    if recentes:
        nomes = ", ".join(pessoa["nome"] for pessoa in recentes[:3])
        juntar(
            "info",
            f"{len(recentes)} cargo(s) registados nos últimos {LIMIAR_RECENTE_DIAS} dias",
            f"Mudança de gestão recente ({nomes}).",
            "Ler a publicação mais recente: uma mudança de órgãos sociais explica alterações nos contratos.",
        )

    itens.sort(key=lambda item: (SEVERIDADE_ORDEM.get(item["severidade"], 9), item["titulo"]))
    return itens


def _recente(pessoa: Dict[str, Any]) -> bool:
    """O cargo mais recente da pessoa é dos últimos meses?"""
    ultimo = _texto(pessoa.get("ultimo"))
    if len(ultimo) < 10:
        return False
    try:
        data = datetime.fromisoformat(ultimo).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - data).days <= LIMIAR_RECENTE_DIAS


def _leitura(
    empresas: Sequence[Dict[str, Any]],
    pessoas: Sequence[Dict[str, Any]],
    ligacoes: Sequence[Dict[str, Any]],
    kpis: Dict[str, Any],
    atencao: Sequence[Dict[str, Any]],
) -> str:
    """Frase de síntese: o que os números dizem para decidir."""
    if not pessoas:
        return (
            "Nenhuma pessoa encontrada para estas empresas: não há órgãos sociais registados na plataforma. "
            "Recolher as publicações societárias antes de concluir que não há titulares."
        )
    partes = [
        f"{kpis['empresas']} empresa(s) analisada(s)",
        f"{kpis['pessoas']} pessoa(s) com cargos registados",
    ]
    if kpis.get("em_varias"):
        partes.append(f"{kpis['em_varias']} em mais do que uma empresa")
    if ligacoes:
        primeira = ligacoes[0]
        partes.append(
            f"quem liga o conjunto: {primeira['nome']} "
            f"({primeira['empresas_pedido']} empresas: {', '.join(empresa['nome'] for empresa in primeira['empresas'])})"
        )
    acumulados = sorted(
        [pessoa for pessoa in pessoas if pessoa.get("empresas_universo")],
        key=lambda pessoa: -int(pessoa["empresas_universo"]),
    )
    if acumulados and int(acumulados[0]["empresas_universo"]) > 1:
        partes.append(f"maior universo: {acumulados[0]['nome']} ({acumulados[0]['empresas_universo']} empresas)")
    if kpis.get("devedores"):
        partes.append(f"{kpis['devedores']} titular(es) nas listas de devedores")
    if kpis.get("empresas_sem_pessoas"):
        partes.append(f"{kpis['empresas_sem_pessoas']} empresa(s) sem cargos registados")

    alertas = [item for item in atencao if item["severidade"] == "alerta"]
    conclusao = (
        f"{len(alertas)} ponto(s) de atenção graves a resolver primeiro."
        if alertas
        else "Sem alertas graves: a leitura pode assentar nos titulares acima."
    )
    return f"{', '.join(partes)}. {conclusao}"


def _grafo(empresas: Sequence[Dict[str, Any]], pessoas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Malha empresa ↔ pessoa: quem tem cargo em quem (e com que peso)."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    vistos: set = set()

    for empresa in empresas:
        node_id = f"empresa:{empresa['nif']}"
        n_pessoas = len(empresa.get("pessoas") or [])
        nodes.append(
            {
                "id": node_id,
                "key": empresa["nif"],
                "label": empresa["nome"],
                "dimension": "empresa",
                "type": "entidade",
                "role": f"empresa analisada · {n_pessoas} pessoa(s)",
                "count": n_pessoas,
                "total_value": 0.0,
            }
        )
        vistos.add(node_id)

    desenhadas = _para_grafo(pessoas)
    for pessoa in desenhadas:
        node_id = f"pessoa:{pessoa['nif']}"
        if node_id in vistos:
            continue
        vistos.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "key": pessoa["nif"],
                "label": pessoa["nome"],
                "dimension": "pessoa",
                "type": "pessoa",
                # O título é o que se lê por baixo do nome no nó: os cargos que a
                # pessoa tem nas empresas do pedido, sem o ruído das publicações.
                "role": _titulo_do_no(pessoa),
                "count": int(pessoa["cargos_pedido"]),
                "total_value": round(float(pessoa["quota"] or 0.0), 2),
            }
        )
        for empresa in pessoa["empresas"]:
            titulo = _texto(empresa.get("titulo")) or _texto(empresa.get("cargo_atual"))
            edges.append(
                {
                    "source": f"empresa:{empresa['nif']}",
                    "target": node_id,
                    "count": int(empresa["cargos_total"]),
                    "value": round(float(pessoa["quota"] or 0.0), 2),
                    # A ligação diz o título: é assim que se lê o papel da pessoa
                    # naquela empresa sem abrir a ficha.
                    "relation": f"tem como {titulo}" if titulo else "tem como titular",
                }
            )

    valor = sum(node["total_value"] for node in nodes)
    por_tipo: Dict[str, int] = {}
    for node in nodes:
        por_tipo[node["type"]] = por_tipo.get(node["type"], 0) + 1
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "empresa",
            "dimension_b": "pessoa",
            "metric": "contratos",
            "mode": "descoberta_pessoas",
            "complete": len(desenhadas) == len(pessoas),
            "scan_capped": len(desenhadas) < len(pessoas),
            "sample_order": "gestão, ligações e cargos",
            "sample_limit": MAX_GRAFO_PESSOAS,
            "documents_scanned": sum(int(empresa.get("total") or 0) for empresa in empresas),
            "documents_matching": len(pessoas),
            "scanned_value": round(valor, 2),
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(nodes),
            "kept_edges": len(edges),
            "omitted_edges": 0,
            "coverage_value_share": None,
            "coverage_count_share": None,
            "directed": True,
            "limits": {
                "pessoas": MAX_GRAFO_PESSOAS,
                "pessoas_por_empresa": MAX_PESSOAS_POR_EMPRESA,
                "pessoas_painel": MAX_PESSOAS_PAINEL,
            },
            "notes": [
                "Grafo de pessoas: as empresas do pedido ligadas a quem nelas tem cargos registados.",
                "Os papéis processuais do CIRE não criam laços societários — contam como evidência na ficha, não como ligação.",
            ],
            "filters": {"empresas": [empresa["nif"] for empresa in empresas]},
            "camadas": por_tipo,
            "valor_das_camadas": round(valor, 2),
        },
    }


def _para_grafo(pessoas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """As pessoas que cabem no desenho, pela ordem de relevância da lista."""
    return list(pessoas)[:MAX_GRAFO_PESSOAS]


def _titulo_do_no(pessoa: Dict[str, Any]) -> str:
    """Título(s) do nó da pessoa: os cargos que tem no pedido, os primeiros 3."""
    titulos = list(pessoa.get("titulos") or [])
    if not titulos and pessoa.get("cargo_atual"):
        titulos = [_texto(pessoa["cargo_atual"])]
    return " · ".join(titulos[:3]) or "cargo registado"


def _fontes_estado(
    empresas: Sequence[Dict[str, Any]],
    pessoas: Sequence[Dict[str, Any]],
    fontes: Sequence[str],
    devedores: Dict[str, Dict[str, Any]],
    erros: Dict[str, str],
    cire_pessoas: int = 0,
) -> List[Dict[str, Any]]:
    """Estado de cada fonte, como no painel das empresas: ok, vazio, erro ou tempo."""
    com_quota = [pessoa for pessoa in pessoas if pessoa.get("quota") is not None]
    com_universo = [pessoa for pessoa in pessoas if int(pessoa.get("empresas_universo") or 0) > 1]
    devedores_encontrados = [nif for nif, dados in devedores.items() if dados.get("devedor")]

    totais = {
        "cargos": sum(int(pessoa.get("cargos_pedido") or 0) for pessoa in pessoas),
        "quotas": len(com_quota),
        "universo": len(com_universo),
        "cire": cire_pessoas,
        "devedores": len(devedores_encontrados),
    }
    ms = {
        "cargos": sum(int(empresa.get("ms") or 0) for empresa in empresas) or None,
        "quotas": None,
        "universo": None,
        "cire": None,
        "devedores": None,
    }

    estado: List[Dict[str, Any]] = []
    for fonte_id in FONTE_IDS:
        if fonte_id not in fontes:
            continue
        spec = FONTE_BY_ID[fonte_id]
        erro = erros.get(fonte_id)
        total = totais.get(fonte_id) or 0
        if erro:
            situacao = "erro"
        elif fonte_id == "cire" and all(empresa.get("cire_erro") for empresa in empresas):
            situacao = "erro"
            erro = next((empresa.get("cire_erro") for empresa in empresas if empresa.get("cire_erro")), None)
        elif total:
            situacao = "ok"
        else:
            situacao = "vazio"
        estado.append(
            {
                "id": fonte_id,
                "label": spec["label"],
                "grupo": spec["grupo"],
                "descricao": spec["descricao"],
                "indice": spec.get("indice"),
                "estado": situacao,
                "total": total,
                "ms": ms.get(fonte_id),
                "erro": erro,
                "nota": (
                    f"Amostra dos {MAX_DEVEDORES} titulares mais relevantes."
                    if fonte_id == "devedores"
                    else f"Pessoas com NIF nos até {MAX_PROCESSOS} processos lidos por empresa; ficam anotadas as que são titulares."
                    if fonte_id == "cire"
                    else None
                ),
            }
        )
    return estado


# ---------------------------------------------------------------------------
# Pedido
# ---------------------------------------------------------------------------
def _pedidos(nifs: Optional[Sequence[str]], nomes: Optional[Sequence[str]]) -> List[Dict[str, str]]:
    """Resolve os NIFs e nomes pedidos numa lista de empresas, sem repetições."""
    pedidos: List[Dict[str, str]] = []
    vistos: set = set()
    for valor in list(nifs or []) + list(nomes or []):
        texto = _texto(valor)
        if not texto:
            continue
        chave = _texto(service.normalizar_nif(texto))
        if chave.isdigit() and len(chave) == 9:
            nif, nome = chave, ""
        else:
            resolucao = service.resolver(texto, size=1)
            candidato = next(iter(resolucao.get("items") or []), None)
            if not candidato or not candidato.get("nif"):
                continue
            nif, nome = _texto(candidato.get("nif")), _texto(candidato.get("nome"))
        if nif in vistos:
            continue
        vistos.add(nif)
        pedidos.append({"nif": nif, "nome": nome})
    return pedidos


def descobrir(
    *,
    nifs: Optional[Sequence[str]] = None,
    nomes: Optional[Sequence[str]] = None,
    pais: str = PAIS_DEFAULT,
    max_empresas: int = MAX_EMPRESAS,
    fontes: Optional[Sequence[str]] = None,
    incluir_grafo: bool = True,
    incluir_devedores: bool = True,
) -> Dict[str, Any]:
    """Descobre as pessoas ligadas a uma ou várias empresas.

    Levanta `ValueError` com uma mensagem legível quando o pedido não serve
    (país não suportado, nenhuma empresa identificável, fontes desconhecidas) —
    a rota transforma isso no erro HTTP certo.
    """
    codigo = _texto(pais or PAIS_DEFAULT).upper()
    if codigo not in PAISES_SUPORTADOS:
        raise ValueError(f"País não suportado: {codigo or '(vazio)'}. Use um de: {', '.join(PAISES_SUPORTADOS)}.")
    pretendidas = [fonte for fonte in (fontes or FONTE_IDS) if fonte in FONTE_BY_ID]
    desconhecidas = [fonte for fonte in (fontes or []) if fonte not in FONTE_BY_ID]
    if desconhecidas:
        raise ValueError(f"Fontes desconhecidas: {', '.join(desconhecidas)}.")
    if not pretendidas:
        raise ValueError("Indique pelo menos uma fonte de pessoas.")

    limite = max(MIN_EMPRESAS, min(int(max_empresas or MAX_EMPRESAS), MAX_EMPRESAS))
    pedidos = _pedidos(nifs, nomes)
    if not pedidos:
        raise ValueError("Não foi possível identificar nenhuma empresa com esse NIF ou nome.")
    pedidos = pedidos[:limite]

    iniciado = time.perf_counter()
    empresas = _recolher_empresas(pedidos, pretendidas)
    # Sem cargos registados não há nome de empresa para mostrar: vai buscá-lo ao
    # cadastro, para o painel não falar de empresas por número.
    for empresa in empresas:
        if empresa["nome"] == empresa["nif"]:
            nome = _nome_da_empresa(empresa["nif"])
            if nome:
                empresa["nome"] = nome
    pessoas = _fundir(empresas)

    erros: Dict[str, str] = {}
    if empresas and all(empresa.get("erro") for empresa in empresas):
        erros["cargos"] = empresas[0]["erro"] or "recolha falhou"

    # --- CIRE: anota quem é nomeado nos processos das empresas do pedido -----
    if "cire" in pretendidas:
        por_pessoa: Dict[str, List[Dict[str, Any]]] = {}
        for empresa in empresas:
            for nif, papeis in (empresa.get("cire_map") or {}).items():
                for papel in papeis:
                    por_pessoa.setdefault(nif, []).append(
                        {**papel, "empresa": empresa["nome"], "empresa_nif": empresa["nif"]}
                    )
        for pessoa in pessoas:
            pessoa["cire"] = sorted(
                por_pessoa.get(pessoa["nif"], []),
                key=lambda item: (item.get("data") or "", item.get("processo") or ""),
                reverse=True,
            )

    # --- Listas de devedores: só os titulares mais relevantes ---------------
    devedores: Dict[str, Dict[str, Any]] = {}
    if incluir_devedores and "devedores" in pretendidas:
        alvos = _titulares_de_devedores(pessoas)
        devedores = _devedores_das_pessoas([pessoa["nif"] for pessoa in alvos])
        for pessoa in pessoas:
            pessoa["devedores"] = devedores.get(pessoa["nif"])

    for pessoa in pessoas:
        pessoa["evidencia"] = _evidencia(pessoa)

    painel = pessoas[:MAX_PESSOAS_PAINEL]
    cargos = _cargos_distribuicao(painel)
    ligacoes = _ligacoes(painel)
    kpis = _kpis(empresas, painel, cargos)
    atencao = _atencao(empresas, painel, ligacoes)
    leitura = _leitura(empresas, painel, ligacoes, kpis, atencao)
    # Pessoas (NIF) vistas nos processos do CIRE das empresas do pedido — não são
    # necessariamente titulares: só as que coincidem com o painel ficam anotadas.
    cire_pessoas = {
        nif for empresa in empresas for nif in (empresa.get("cire_map") or {})
    }
    fontes_estado = _fontes_estado(empresas, painel, pretendidas, devedores, erros, len(cire_pessoas))

    avisos: List[str] = []
    for empresa in empresas:
        if empresa.get("erro"):
            avisos.append(f"{empresa['nome']}: {empresa['erro']}")
    if len(pessoas) > len(painel):
        avisos.append(
            f"Foram encontradas {len(pessoas)} pessoas e mostradas as {len(painel)} mais relevantes "
            "(órgãos sociais, ligações entre empresas e número de cargos)."
        )
    if not pessoas and empresas:
        avisos.append(
            "Nenhuma das empresas do pedido tem cargos de órgãos sociais registados na plataforma. "
            "Não é ausência de gestão: é ausência de publicações de registo comercial indexadas."
        )

    return {
        "pais": codigo,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "ms": int((time.perf_counter() - iniciado) * 1000),
        "pedido": {
            "empresas": len(pedidos),
            "analisadas": len([empresa for empresa in empresas if not empresa.get("erro")]),
            "max_empresas": limite,
            "fontes": pretendidas,
        },
        "empresas": [_empresa_painel(empresa) for empresa in empresas],
        "pessoas": painel,
        "kpis": kpis,
        "cargos": cargos,
        "ligacoes": ligacoes,
        "grafo": _grafo(empresas, painel) if incluir_grafo else None,
        "atencao": atencao,
        "fontes": fontes_estado,
        "leitura": leitura,
        "avisos": avisos,
    }


def _empresa_painel(empresa: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo da empresa para o painel (sem repetir as fichas das pessoas)."""
    pessoas = empresa.get("pessoas") or []
    return {
        "nif": empresa["nif"],
        "nome": empresa["nome"],
        "pessoas": int(empresa.get("total") or len(pessoas)),
        "lidas": len(pessoas),
        "truncado": bool(empresa.get("truncado")),
        "processos": len(empresa.get("processos") or []),
        "processos_total": int(empresa.get("processos_total") or 0),
        "cire_pessoas": int(empresa.get("cire_pessoas") or 0),
        "estado": empresa.get("estado"),
        "erro": empresa.get("erro"),
        "cire_erro": empresa.get("cire_erro"),
        "ms": empresa.get("ms"),
    }


# ---------------------------------------------------------------------------
# Ficha de uma pessoa
# ---------------------------------------------------------------------------
def ficha(nif: str, *, empresas: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Ficha de uma pessoa: todos os cargos no universo, com a evidência.

    `empresas` (opcional) marca quais dos cargos são das empresas de um pedido —
    é o que permite ler a mesma pessoa dentro e fora do conjunto analisado.
    """
    alvo = _texto(nif)
    if not alvo:
        return {"nif": "", "encontrada": False, "erro": "NIF em falta.", "avisos": ["Indique o NIF da pessoa."]}

    dados = es_client.get_person_by_nif(alvo)
    if dados.get("error"):
        return {
            "nif": alvo,
            "encontrada": False,
            "erro": dados["error"],
            "avisos": [f"Não foi possível abrir a ficha de {alvo}."],
        }

    cargos = [cargo for cargo in (dados.get("roles") or []) if isinstance(cargo, dict)]
    selecionadas = {_texto(item) for item in (empresas or []) if _texto(item)}
    por_empresa: Dict[str, Dict[str, Any]] = {}
    quotas: List[Dict[str, Any]] = []
    for cargo in cargos:
        chave = _texto(cargo.get("company_nif")) or "sem-nif"
        registo = por_empresa.setdefault(
            chave,
            {
                "nif": chave,
                "nome": _texto(cargo.get("company_name")) or chave,
                "cargos": [],
                "classes": [],
                "no_pedido": (not selecionadas) or chave in selecionadas,
            },
        )
        classe = _classe_cargo(cargo)
        registo["cargos"].append(_cargo_normalizado(cargo))
        if classe not in registo["classes"]:
            registo["classes"].append(classe)
        if cargo.get("quota") not in (None, "", 0):
            quotas.append(
                {
                    "empresa": registo["nome"],
                    "empresa_nif": chave,
                    "quota": float(cargo["quota"]),
                    "data": _data(cargo.get("date")),
                }
            )

    lista = []
    for registo in por_empresa.values():
        registo["cargos"].sort(key=lambda item: item["data"], reverse=True)
        registo["cargo_atual"] = registo["cargos"][0]["role"] if registo["cargos"] else ""
        registo["role_org"] = registo["cargos"][0]["role_org"] if registo["cargos"] else ""
        registo["ultimo"] = registo["cargos"][0]["data"] if registo["cargos"] else ""
        registo["desde"] = registo["cargos"][-1]["data"] if registo["cargos"] else ""
        registo["cargos_total"] = len(registo["cargos"])
        registo["classe"] = _melhor_classe(registo["classes"])
        registo["classe_label"] = CLASSE_LABEL[registo["classe"]]
        lista.append(registo)
    lista.sort(key=lambda item: (not item["no_pedido"], -item["cargos_total"], item["nome"]))

    classes = {classe for registo in lista for classe in registo["classes"]}
    meta_dados = dados.get("metadata") if isinstance(dados.get("metadata"), dict) else {}
    perfil = {
        "partido": _texto(meta_dados.get("party") or meta_dados.get("partido")),
        "cargo_publico": _texto(meta_dados.get("office") or meta_dados.get("cargo")),
        "legislatura": _texto(meta_dados.get("legislature") or meta_dados.get("legislatura")),
        "biografia": _texto(dados.get("biography")),
        "foto": _texto(dados.get("photo_url")),
        "tags": [str(tag) for tag in (dados.get("tags") or [])],
    }
    avisos: List[str] = []
    if not cargos:
        avisos.append("Esta pessoa não tem cargos indexados: só existe no índice sem publicações associadas.")
    if dados.get("derived"):
        avisos.append("Ficha reconstruída a partir das publicações societárias (ainda não estava no índice de pessoas).")
    if selecionadas and not any(registo["no_pedido"] for registo in lista):
        avisos.append("Esta pessoa não tem cargos nas empresas do pedido — os cargos listados são de outras empresas.")

    return {
        "nif": alvo,
        "nome": _texto(dados.get("name") or dados.get("name_keyword")) or alvo,
        "encontrada": True,
        "erro": None,
        "is_company": bool(dados.get("is_company")),
        "classe": _melhor_classe(classes) if classes else "outro",
        "classe_label": CLASSE_LABEL[_melhor_classe(classes) if classes else "outro"],
        "cargos_total": int(dados.get("roles_count") or len(cargos)),
        "empresas_total": int(dados.get("companies_count") or len(lista)),
        "primeiro": _data(dados.get("first_seen")),
        "ultimo": _data(dados.get("last_seen")),
        "origens": [str(origem) for origem in (dados.get("sources") or [])],
        "empresas": lista,
        "quotas": quotas,
        "perfil": perfil if any(perfil.values()) else None,
        "nas_empresas_pedido": [registo["nif"] for registo in lista if registo["no_pedido"]] if selecionadas else None,
        "avisos": avisos,
    }
