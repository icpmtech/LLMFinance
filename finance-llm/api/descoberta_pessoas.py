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
6. **Contratos** — quem contrata com as empresas do pedido, para cruzar os
   titulares dos dois lados de um contrato (conflitos de interesse).

Cada pessoa sai com o **título** do cargo, uma pontuação de **risco** de 0 a 100
e os **conflitos de interesse** em que aparece.

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
#: Contratos lidos por empresa do pedido para encontrar contrapartes (conflitos).
MAX_CONTRATOS_CONFLITO = 200
#: Conflitos devolvidos no painel (os de maior valor).
MAX_CONFLITOS = 8
#: Quadros até este tamanho desenham as ligações pessoa↔pessoa da empresa; acima
#: disso seria uma teia (uma empresa com 20 titulares dá 190 ligações).
MAX_QUADRO_PARES = 12
#: Teto de ligações no grafo de co-titularidade.
MAX_ARESTAS_PESSOAS = 400
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
    {
        "id": "contratos",
        "label": "Contrapartes em contratos",
        "grupo": "contratacao",
        "descricao": "Quem contrata com as empresas do pedido: é por aqui que se vê um titular nos dois lados do contrato.",
        "indice": "contratos",
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

#: Componentes do risco da pessoa. Os pesos somam 1 e o score renormaliza pelos
#: componentes com dados (como no risco da empresa, `risco_service.avaliar`): uma
#: pessoa sem listas de devedores consultadas não é penalizada por isso — baixa é
#: a cobertura, não o risco.
COMPONENTES_RISCO: Tuple[Dict[str, Any], ...] = (
    {
        "id": "acumulacao",
        "label": "Acumulação de cargos",
        "peso": 0.18,
        "unidade": "empresas",
        "descricao": "Quantas empresas a plataforma conhece com cargos desta pessoa registados.",
        "metodo": "Contagem de empresas do índice de pessoas",
    },
    {
        "id": "insolvencias",
        "label": "Processos de insolvência",
        "peso": 0.22,
        "unidade": "processos",
        "descricao": "Processos do CIRE das empresas do pedido em que a pessoa é insolvente ou credora.",
        "metodo": "Papéis do interveniente no processo (CIRE)",
    },
    {
        "id": "devedores",
        "label": "Listas de devedores",
        "peso": 0.22,
        "unidade": "listas",
        "descricao": "Presença da pessoa nas listas de devedores das Finanças ou da Segurança Social.",
        "metodo": "Consulta às listas públicas por NIF",
    },
    {
        "id": "cessacoes",
        "label": "Cessação por renúncia",
        "peso": 0.14,
        "unidade": "cargos",
        "descricao": "Cargos cessados com causa de renúncia — saída sem substituto nomeado no mesmo ato.",
        "metodo": "Causa da cessação na publicação de registo",
    },
    {
        "id": "rotatividade",
        "label": "Mudança recente de gestão",
        "peso": 0.12,
        "unidade": "dias",
        "descricao": "Há quanto tempo foi o último cargo registado: uma gestão nova ainda não tem histórico.",
        "metodo": "Data do cargo mais recente",
    },
    {
        "id": "opacidade",
        "label": "Cargos sem órgão identificado",
        "peso": 0.12,
        "unidade": "% dos cargos",
        "descricao": "Parte dos cargos cuja publicação não diz o órgão social — não se sabe o que a pessoa faz.",
        "metodo": "Proporção de cargos sem órgão na publicação",
    },
)


def meta() -> Dict[str, Any]:
    """Catálogo de fontes, classes de cargo e limites do módulo."""
    return {
        "fontes": FONTES,
        "grupos": sorted({fonte["grupo"] for fonte in FONTES}),
        "pais": list(PAISES_SUPORTADOS),
        "classes": [{"id": classe, "label": CLASSE_LABEL[classe]} for classe in CLASSES],
        "orgaos_gestao": list(_orgaos_gestao()),
        "risco": {
            "metodo": METODO_RISCO,
            "metodo_label": METODO_RISCO_LABEL,
            "componentes": [
                {chave: spec[chave] for chave in ("id", "label", "peso", "unidade", "descricao", "metodo")}
                for spec in COMPONENTES_RISCO
            ],
        },
        "limites": {
            "empresas": MAX_EMPRESAS,
            "pessoas_por_empresa": MAX_PESSOAS_POR_EMPRESA,
            "pessoas_painel": MAX_PESSOAS_PAINEL,
            "pessoas_grafo": MAX_GRAFO_PESSOAS,
            "quadro": MAX_QUADRO_PARES,
            "arestas_pessoas": MAX_ARESTAS_PESSOAS,
            "processos": MAX_PROCESSOS,
            "devedores": MAX_DEVEDORES,
            "contratos_conflito": MAX_CONTRATOS_CONFLITO,
            "conflitos": MAX_CONFLITOS,
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
    """Títulos da pessoa nas empresas do pedido, do mais recente para o mais antigo.

    As publicações escrevem o mesmo cargo de várias formas («Vogal», «VOGAL»,
    «vogal»): guarda-se a primeira grafia e cai o resto.
    """
    titulos: List[str] = []
    vistos: set = set()
    for empresa in pessoa.get("empresas") or []:
        for cargo in empresa.get("cargos") or []:
            titulo = _texto(cargo.get("titulo")) or _titulo(cargo)
            chave = _fold(titulo)
            if titulo and chave not in vistos:
                vistos.add(chave)
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


def _ordem_painel(pessoa: Dict[str, Any]) -> Tuple[int, int, int, int, int, int, str]:
    """Ordem final, já com o risco: é o número que diz quem olhar primeiro."""
    risco = pessoa.get("risco") or {}
    return (
        0 if pessoa.get("gestao") else 1 if pessoa.get("capital") else 2,
        0 if pessoa.get("ligacao") else 1,
        -int(round(float(risco.get("score") or 0.0))),
        -int(pessoa.get("empresas_pedido") or 0),
        -int(pessoa.get("cargos_pedido") or 0),
        -int(pessoa.get("empresas_universo") or 0),
        pessoa.get("nome") or "",
    )


# ---------------------------------------------------------------------------
# Risco da pessoa
# ---------------------------------------------------------------------------
METODO_RISCO = "triagem_pessoas"
METODO_RISCO_LABEL = "Triagem (cargos, processos e listas públicas)"
#: Causas de cessação que contam como saída de risco.
CAUSAS_CESSAO = ("renuncia", "renuncia ao cargo", "demissao")


def _nivel_de(score: float) -> Dict[str, Any]:
    """Faixa de risco partilhada com o painel das empresas (`risco_service`)."""
    from api import risco_service  # noqa: PLC0415

    return risco_service.nivel_de(score)


def _pontos_acumulacao(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    empresas = int(pessoa.get("empresas_universo") or 0)
    if not empresas:
        return None, []
    for limiar, pontos in ((5, 100.0), (4, 80.0), (3, 55.0), (2, 30.0)):
        if empresas >= limiar:
            return pontos, [f"{empresas} empresas com cargos registados"]
    return 8.0, ["1 empresa com cargos registados"]


def _pontos_insolvencias(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    papeis = [item for item in pessoa.get("cire") or [] if isinstance(item, dict)]
    if not papeis:
        return 0.0, ["Sem processos do CIRE das empresas do pedido"]
    insolvente = [item for item in papeis if _fold(item.get("papel")) == "insolvente"]
    if insolvente:
        primeiro = insolvente[0]
        return 100.0, [
            f"Insolvente no processo {primeiro.get('processo') or '?'} "
            f"({primeiro.get('especie') or 'CIRE'}, {primeiro.get('data') or 'sem data'})"
        ]
    credor = [item for item in papeis if _fold(item.get("papel")) in ("credor", "devedor", "requerente")]
    if credor:
        return 30.0, [f"{len(credor)} processo(s) como {credor[0].get('papel')}"]
    return 10.0, [f"{len(papeis)} processo(s) do CIRE como interveniente"]


def _pontos_devedores(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    dados = pessoa.get("devedores")
    if not isinstance(dados, dict):
        return None, []
    if not dados.get("devedor"):
        return 0.0, ["Sem registo nas listas consultadas"]
    entidades = ", ".join(dados.get("entidades") or []) or "listas de devedores"
    valor = dados.get("maior_valor_min")
    pontos = 100.0 if not valor or float(valor) >= 50_000 else 70.0
    return pontos, [f"{dados.get('total') or 0} registo(s) em {entidades}"]


def _causa_do_cargo(cargo: Dict[str, Any]) -> str:
    """Causa da cessação: o campo próprio ou a que a publicação cola ao cargo.

    «Vogal Causa: renúncia Data: 2022.04.30» guarda a causa no próprio texto do
    cargo — é de lá que ela sai quando o campo `causa` vem vazio.
    """
    causa = _texto(cargo.get("causa"))
    if causa:
        return causa
    papel = _texto(cargo.get("role"))
    baixo = _fold(papel)
    corte = baixo.find("causa:")
    if corte < 0:
        return ""
    resto = papel[corte + len("causa:") :].strip(" ,;-")
    fim = _fold(resto).find("data:")
    return (resto[:fim] if fim > 0 else resto).strip(" ,;-")


def _pontos_cessacoes(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    renuncias: List[Tuple[str, str]] = []
    total = 0
    for empresa in pessoa.get("empresas") or []:
        for cargo in empresa.get("cargos") or []:
            total += 1
            causa = _fold(_causa_do_cargo(cargo))
            if causa and any(marca in causa for marca in CAUSAS_CESSAO):
                renuncias.append((empresa.get("nome") or empresa.get("nif") or "", cargo.get("data") or ""))
    if not total:
        return None, []
    if not renuncias:
        return 0.0, ["Sem cessação por renúncia nos cargos lidos"]
    recentes = [item for item in renuncias if (_idade_dias(item[1]) or 10**6) <= 730]
    primeira = (recentes or renuncias)[0]
    detalhe = f"{len(renuncias)} cargo(s) cessados por renúncia ({primeira[0]}, {primeira[1] or 'sem data'})"
    return (100.0 if recentes else 60.0), [detalhe]


def _pontos_rotatividade(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    dias = _idade_dias(_texto(pessoa.get("ultimo")))
    if dias is None:
        return None, []
    if dias <= 90:
        return 60.0, [f"Último cargo registado há {dias} dia(s) — gestão nova"]
    if dias <= 365:
        return 25.0, [f"Último cargo registado há {dias} dia(s)"]
    return 0.0, [f"Último cargo registado há {dias} dia(s)"]


def _pontos_opacidade(pessoa: Dict[str, Any]) -> Tuple[Optional[float], List[str]]:
    cargos = [cargo for empresa in pessoa.get("empresas") or [] for cargo in empresa.get("cargos") or []]
    if not cargos:
        return None, []
    sem_orgao = [cargo for cargo in cargos if not _texto(cargo.get("role_org"))]
    quota = len(sem_orgao) / len(cargos)
    if not sem_orgao:
        return 0.0, [f"Todos os {len(cargos)} cargo(s) dizem o órgão social"]
    return quota * 100.0, [f"{len(sem_orgao)} de {len(cargos)} cargo(s) sem órgão identificado na publicação"]


def _idade_dias(valor: str) -> Optional[int]:
    """Dias desde uma data ISO, ou `None` quando não há data legível."""
    texto = _texto(valor)[:10]
    if len(texto) < 10:
        return None
    try:
        data = datetime.fromisoformat(texto).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - data).days)


_RISCO_POR_COMPONENTE = {
    "acumulacao": _pontos_acumulacao,
    "insolvencias": _pontos_insolvencias,
    "devedores": _pontos_devedores,
    "cessacoes": _pontos_cessacoes,
    "rotatividade": _pontos_rotatividade,
    "opacidade": _pontos_opacidade,
}


def risco_da_pessoa(pessoa: Dict[str, Any]) -> Dict[str, Any]:
    """Risco da pessoa (0–100): componentes, cobertura e o que puxa o valor.

    Mesma gramática do risco da empresa (`risco_service.avaliar`): pesos somam 1,
    o score renormaliza pelos componentes com dados e o nível sai das mesmas
    faixas — o painel das pessoas e o das empresas leem-se na mesma escala.
    """
    componentes: List[Dict[str, Any]] = []
    # Sem um único cargo lido não há pessoa para avaliar: mostrar 0/100 seria dizer
    # «sem risco» quando o que falta é a evidência.
    com_cargos = any(empresa.get("cargos") for empresa in pessoa.get("empresas") or [])
    for spec in COMPONENTES_RISCO:
        pontos, evidencia = _RISCO_POR_COMPONENTE[spec["id"]](pessoa) if com_cargos else (None, [])
        componentes.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "peso": spec["peso"],
                "unidade": spec["unidade"],
                "descricao": spec["descricao"],
                "metodo": spec["metodo"],
                "pontos": None if pontos is None else round(float(pontos), 2),
                "evidencia": evidencia,
                "disponivel": pontos is not None,
            }
        )

    disponiveis = [item for item in componentes if item["disponivel"]]
    peso_total = sum(float(item["peso"]) for item in disponiveis)
    base = {
        "metodo": METODO_RISCO,
        "metodo_label": METODO_RISCO_LABEL,
        "componentes": componentes,
        "fatores": [],
    }
    if not disponiveis or peso_total <= 0:
        return {**base, "score": None, "nivel": None, "nivel_label": "Sem dados", "cor": "#94a3b8", "faixa": None, "cobertura": 0.0, "confianca": "sem dados"}

    score = sum(float(item["peso"]) * float(item["pontos"]) for item in disponiveis) / peso_total
    for item in componentes:
        item["peso_efetivo"] = round(float(item["peso"]) / peso_total, 4) if item["disponivel"] else 0.0
        item["contributo"] = (
            round(float(item["pontos"]) * float(item["peso_efetivo"]), 3) if item["disponivel"] else 0.0
        )
    nivel = _nivel_de(score)
    fatores = sorted(
        (item for item in disponiveis if (item["pontos"] or 0.0) >= 50.0),
        key=lambda item: -(item["contributo"] or 0.0),
    )[:4]
    confianca = "alta" if peso_total >= 0.85 else "média" if peso_total >= 0.6 else "baixa"
    return {
        **base,
        "score": round(score, 1),
        "nivel": nivel["id"],
        "nivel_label": nivel["label"],
        "cor": nivel["cor"],
        "faixa": nivel.get("faixa"),
        "cobertura": round(peso_total, 3),
        "confianca": confianca,
        "fatores": [
            {"id": item["id"], "label": item["label"], "pontos": item["pontos"], "contributo": item["contributo"]}
            for item in fatores
        ],
    }


# ---------------------------------------------------------------------------
# Conflitos de interesse (titulares dos dois lados do contrato)
# ---------------------------------------------------------------------------
def _partes(campo: Any) -> Dict[str, str]:
    """NIF → nome das partes de um contrato (`adjudicantes`/`adjudicatarios`)."""
    if isinstance(campo, dict):
        itens = campo.get("parsed") or []
    elif isinstance(campo, list):
        itens = campo
    else:
        return {}
    partes: Dict[str, str] = {}
    for item in itens:
        if isinstance(item, dict):
            nif, nome = _texto(item.get("nif")), _texto(item.get("nome"))
        else:
            texto = _texto(item)
            nif, nome = _texto(texto.split(" - ")[0]), texto
        if nif:
            partes[nif] = nome or nif
    return partes


def _contrapartes_de(nif: str) -> Dict[str, Dict[str, Any]]:
    """Com quem esta empresa contrata (nos dois sentidos), numa amostra de contratos.

    Lê os contratos em que a empresa é parte em qualquer papel e agrega as
    contrapartes: quando a empresa é adjudicatária, as contrapartes são os
    compradores (vende a); quando é adjudicante, são os fornecedores (compra a).
    """
    try:
        resultado = es_client.search_contracts(nif=nif, size=MAX_CONTRATOS_CONFLITO)
    except Exception as exc:  # noqa: BLE001 - uma empresa má não derruba o painel
        logger.warning("Descoberta de pessoas: contrapartes de %s falharam: %s", nif, exc)
        return {}
    if resultado.get("error"):
        return {}

    contrapartes: Dict[str, Dict[str, Any]] = {}

    def registar(outro_nif: str, outro_nome: str, direcao: str, valor: float) -> None:
        if not outro_nif or outro_nif == nif:
            return
        registo = contrapartes.setdefault(
            outro_nif,
            {"nif": outro_nif, "nome": outro_nome or outro_nif, "direcoes": [], "contratos": 0, "valor": 0.0},
        )
        if direcao not in registo["direcoes"]:
            registo["direcoes"].append(direcao)
        if outro_nome and not registo["nome"]:
            registo["nome"] = outro_nome
        registo["contratos"] += 1
        registo["valor"] += valor

    for documento in resultado.get("items") or []:
        if not isinstance(documento, dict):
            continue
        compradores = _partes(documento.get("adjudicantes"))
        vendedores = _partes(documento.get("adjudicatarios"))
        valor = float(documento.get("precoContratual") or documento.get("PrecoTotalEfetivo") or 0.0)
        if nif in vendedores:
            for outro_nif, outro_nome in compradores.items():
                registar(outro_nif, outro_nome, "vende a", valor)
        if nif in compradores:
            for outro_nif, outro_nome in vendedores.items():
                registar(outro_nif, outro_nome, "compra a", valor)
    return contrapartes


def _contrapartes_das_empresas(empresas: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Contrapartes de cada empresa do pedido, em paralelo."""
    if not empresas:
        return {}
    contrapartes: Dict[str, Dict[str, Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_PARALELO, len(empresas))) as pool:
        futuros = {pool.submit(_contrapartes_de, empresa["nif"]): empresa["nif"] for empresa in empresas}
        for futuro in as_completed(futuros):
            nif = futuros[futuro]
            try:
                contrapartes[nif] = futuro.result()
            except Exception as exc:  # noqa: BLE001 - a falha de uma empresa é reportada
                logger.warning("Descoberta de pessoas: contrapartes de %s falharam: %s", nif, exc)
                contrapartes[nif] = {}
    return contrapartes


def _conflitos(
    pessoas: Sequence[Dict[str, Any]],
    empresas: Sequence[Dict[str, Any]],
    contrapartes: Dict[str, Dict[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Quem tem cargo nos dois lados de um contrato com dinheiro público.

    Duas formas, ambas com a mesma pergunta por trás — *esta pessoa serve o
    comprador e o vendedor?*:

    - a pessoa tem cargo numa empresa do pedido e noutra que **contrata com ela**
      (fora do pedido, mas registada na plataforma);
    - a pessoa tem cargo em **duas empresas do pedido** que contratam entre si.
    """
    conflitos: List[Dict[str, Any]] = []
    vistos: set = set()

    def juntar(pessoa: Dict[str, Any], empresa: Dict[str, Any], outro: Dict[str, Any], dentro: bool) -> None:
        chave = (pessoa["nif"], empresa["nif"], outro["nif"], dentro)
        if chave in vistos:
            return
        vistos.add(chave)
        direcoes = outro.get("direcoes") or []
        severidade = "alerta" if pessoa.get("classe") in ("gestao", "capital") else "aviso"
        conflitos.append(
            {
                "nif": pessoa["nif"],
                "nome": pessoa["nome"],
                "classe": pessoa["classe"],
                "classe_label": pessoa["classe_label"],
                "empresa": {
                    "nif": empresa["nif"],
                    "nome": empresa["nome"],
                    "titulo": empresa["titulo"] or empresa["cargo_atual"],
                },
                "contraparte": {
                    "nif": outro["nif"],
                    "nome": outro.get("nome") or outro["nif"],
                    "dentro_do_pedido": dentro,
                },
                "direcao": direcoes[0] if direcoes else "",
                "direcoes": direcoes,
                "contratos": int(outro.get("contratos") or 0),
                "valor": round(float(outro.get("valor") or 0.0), 2),
                "severidade": severidade,
                "titulo": (
                    f"{pessoa['nome']} tem cargo em {empresa['nome']} e em {outro.get('nome') or outro['nif']}, "
                    + ("ambas do pedido, " if dentro else "")
                    + f"e uma contrata com a outra"
                ),
            }
        )

    for pessoa in pessoas:
        for empresa in pessoa.get("empresas") or []:
            mapa = contrapartes.get(empresa["nif"]) or {}
            if not mapa:
                continue
            for outra in pessoa.get("outras_empresas") or []:
                registo = mapa.get(outra["nif"])
                if registo:
                    juntar(pessoa, empresa, {**registo, "nome": registo.get("nome") or outra.get("nome")}, False)
            for irma in pessoa.get("empresas") or []:
                if irma["nif"] == empresa["nif"]:
                    continue
                registo = mapa.get(irma["nif"])
                if registo:
                    juntar(pessoa, empresa, {**registo, "nome": irma["nome"]}, True)

    conflitos.sort(key=lambda item: (-float(item["valor"] or 0), -int(item["contratos"] or 0), item["nome"]))
    return conflitos


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


def _kpis(
    empresas: Sequence[Dict[str, Any]],
    pessoas: Sequence[Dict[str, Any]],
    cargos: Sequence[Dict[str, Any]],
    conflitos: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    com_cargos = [empresa for empresa in empresas if empresa.get("pessoas")]
    devedores = [pessoa for pessoa in pessoas if (pessoa.get("devedores") or {}).get("devedor")]
    cargos_lidos = sum(int(empresa.get("total") or len(empresa.get("pessoas") or [])) for empresa in empresas)
    processos = sum(len(empresa.get("processos") or []) for empresa in empresas)
    profundidade = round(sum(int(pessoa["cargos_pedido"]) for pessoa in pessoas) / len(pessoas), 2) if pessoas else None
    riscos = [
        float(pessoa["risco"]["score"])
        for pessoa in pessoas
        if isinstance(pessoa.get("risco"), dict) and pessoa["risco"].get("score") is not None
    ]
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
        "conflitos": len(conflitos),
        "conflitos_graves": sum(1 for item in conflitos if item.get("severidade") == "alerta"),
        "risco_alto": sum(1 for score in riscos if score >= 40),
        "risco_critico": sum(1 for score in riscos if score >= 60),
        "risco_medio": round(sum(riscos) / len(riscos), 1) if riscos else None,
        "risco_max": round(max(riscos), 1) if riscos else None,
        "cargo_top": cargos[0] if cargos else None,
        "profundidade": profundidade,
    }


def _atencao(
    empresas: Sequence[Dict[str, Any]],
    pessoas: Sequence[Dict[str, Any]],
    ligacoes: Sequence[Dict[str, Any]],
    conflitos: Sequence[Dict[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """O que verificar primeiro — as mesmas severidades do painel das empresas."""
    itens: List[Dict[str, Any]] = []

    def juntar(severidade: str, titulo: str, detalhe: str, verificar: str) -> None:
        itens.append({"severidade": severidade, "titulo": titulo, "detalhe": detalhe, "verificar": verificar})

    for conflito in list(conflitos)[:MAX_CONFLITOS]:
        direcao = conflito.get("direcao") or "contrata com"
        dentro = " (ambas do pedido)" if conflito["contraparte"].get("dentro_do_pedido") else ""
        juntar(
            conflito.get("severidade") or "aviso",
            f"{conflito['nome']} nos dois lados: {conflito['empresa']['nome']} ↔ {conflito['contraparte']['nome']}{dentro}",
            f"Tem cargo em {conflito['empresa']['nome']} ({conflito['empresa']['titulo'] or 'cargo registado'}) e em "
            f"{conflito['contraparte']['nome']}, e uma {direcao} outra — {conflito['contratos']} contrato(s), "
            f"{conflito['valor']} € de valor registado na amostra.",
            "Ler os contratos entre as duas empresas e confirmar se o cargo existia à data e quem representou cada parte.",
        )

    for pessoa in pessoas:
        risco = pessoa.get("risco") or {}
        score = risco.get("score")
        if score is None:
            continue
        fatores = ", ".join(item["label"] for item in (risco.get("fatores") or [])[:3])
        if score >= 60:
            juntar(
                "alerta",
                f"Risco crítico em {pessoa['nome']} ({score}/100)",
                f"Componentes que puxam o risco: {fatores or 'sem fator isolado'}.",
                "Abrir a ficha da pessoa e confirmar cada componente antes de a envolver numa decisão.",
            )
        elif score >= 40:
            juntar(
                "aviso",
                f"Risco elevado em {pessoa['nome']} ({score}/100)",
                f"Componentes que puxam o risco: {fatores or 'sem fator isolado'}.",
                "Comparar com os pares do mesmo cargo antes de concluir.",
            )

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


def _grafo_pessoas(pessoas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Malha **pessoa ↔ pessoa**: quem se senta com quem na mesma empresa.

    Duas famílias de ligação: as empresas do pedido (os quadros que ali se
    cruzam) e as empresas do universo de cada pessoa — é nesta segunda que
    aparece a rede que o painel de uma empresa só não mostra. Quadros grandes
    ficam de fora do desenho (uma empresa com 20 titulares dá 190 ligações) e o
    painel diz quantos ficaram.
    """
    desenhadas = _para_grafo(pessoas)
    nodes: List[Dict[str, Any]] = []
    for pessoa in desenhadas:
        nodes.append(
            {
                "id": f"pessoa:{pessoa['nif']}",
                "key": pessoa["nif"],
                "label": pessoa["nome"],
                "dimension": "pessoa",
                "type": "pessoa",
                "role": _titulo_do_no(pessoa),
                "count": int(pessoa["cargos_pedido"]),
                "total_value": round(float(pessoa["quota"] or 0.0), 2),
            }
        )

    grupos: Dict[str, Dict[str, Any]] = {}
    for pessoa in desenhadas:
        for empresa in pessoa.get("empresas") or []:
            chave = f"pedido:{empresa['nif']}"
            registo = grupos.setdefault(
                chave,
                {"nome": empresa["nome"], "nif": empresa["nif"], "do_pedido": True, "membros": []},
            )
            if pessoa["nif"] not in registo["membros"]:
                registo["membros"].append(pessoa["nif"])
        for outra in pessoa.get("outras_empresas") or []:
            chave = f"fora:{outra['nif']}"
            registo = grupos.setdefault(
                chave,
                {"nome": outra.get("nome") or outra["nif"], "nif": outra["nif"], "do_pedido": False, "membros": []},
            )
            if pessoa["nif"] not in registo["membros"]:
                registo["membros"].append(pessoa["nif"])

    edges: List[Dict[str, Any]] = []
    limitados: List[str] = []
    for chave, grupo in sorted(grupos.items(), key=lambda item: -len(item[1]["membros"])):
        membros = grupo["membros"]
        if len(membros) < 2:
            continue
        if len(membros) > MAX_QUADRO_PARES:
            # Um quadro grande não se desenha todo (26 titulares dão 325 ligações):
            # ligam-se os mais relevantes e o painel diz quantos ficaram de fora.
            limitados.append(f"{grupo['nome']} ({len(membros)})")
            membros = membros[:MAX_QUADRO_PARES]
        for indice, origem in enumerate(membros):
            for destino in membros[indice + 1 :]:
                if len(edges) >= MAX_ARESTAS_PESSOAS:
                    break
                edges.append(
                    {
                        "source": f"pessoa:{origem}",
                        "target": f"pessoa:{destino}",
                        "count": 1,
                        "value": 0.0,
                        "relation": (
                            f"juntos em {grupo['nome']}" if grupo["do_pedido"] else f"fora do pedido: {grupo['nome']}"
                        ),
                    }
                )

    por_tipo: Dict[str, int] = {"pessoa": len(nodes)}
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "pessoa",
            "dimension_b": "pessoa",
            "metric": "contratos",
            "mode": "descoberta_pessoas_cotitularidade",
            "complete": len(desenhadas) == len(pessoas),
            "scan_capped": len(desenhadas) < len(pessoas),
            "sample_order": "gestão, ligações e cargos",
            "sample_limit": MAX_GRAFO_PESSOAS,
            "documents_scanned": len(pessoas),
            "documents_matching": len(desenhadas),
            "scanned_value": 0.0,
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(nodes),
            "kept_edges": len(edges),
            "omitted_edges": 0,
            "coverage_value_share": None,
            "coverage_count_share": None,
            "directed": False,
            "limits": {
                "pessoas": MAX_GRAFO_PESSOAS,
                "quadro": MAX_QUADRO_PARES,
                "arestas": MAX_ARESTAS_PESSOAS,
            },
            "notes": [
                "Grafo de co-titularidade: cada ligação é uma empresa partilhada por duas pessoas.",
                f"Quadros com mais de {MAX_QUADRO_PARES} titulares entram pelos mais relevantes.",
                *([f"Quadros limitados: {', '.join(limitados[:4])}."] if limitados else []),
            ],
            "filters": {"pessoas": len(desenhadas)},
            "camadas": por_tipo,
            "valor_das_camadas": 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Análise pelo Hermes
# ---------------------------------------------------------------------------
MAX_PEDIDO_CHARS = 1800
MAX_TITULARES_PEDIDO = 6


def pergunta_padrao(painel: Dict[str, Any]) -> str:
    """Pergunta do Hermes ancorada nos números do painel (determinística)."""
    kpis = painel.get("kpis") or {}
    empresas = painel.get("empresas") or []
    nomes = ", ".join(_texto(empresa.get("nome")) for empresa in empresas[:4]) or "as empresas pedidas"
    factos = [
        f"empresas: {kpis.get('empresas') or 0}",
        f"pessoas com cargos: {kpis.get('pessoas') or 0}",
        f"pessoas em mais de uma empresa: {kpis.get('em_varias') or 0}",
        f"órgãos sociais: {kpis.get('gestao') or 0}",
        f"titulares com risco elevado: {kpis.get('risco_alto') or 0}",
        f"conflitos de interesse: {kpis.get('conflitos') or 0}",
        f"titulares nas listas de devedores: {kpis.get('devedores') or 0}",
    ]
    ligacoes = painel.get("ligacoes") or []
    if ligacoes:
        factos.append(f"quem liga as empresas: {ligacoes[0].get('nome')} ({ligacoes[0].get('empresas_pedido')} empresas)")
    # Sem os nomes e os títulos, o Hermes só pode falar de contagens: dá-se-lhe quem.
    titulares = []
    for pessoa in (painel.get("pessoas") or [])[:MAX_TITULARES_PEDIDO]:
        titulo = _texto(pessoa.get("titulo"))
        nas_empresas = ", ".join(_texto(empresa.get("nome")) for empresa in (pessoa.get("empresas") or [])[:3])
        if not titulo or not nas_empresas:
            continue
        titulares.append(f"{_texto(pessoa.get('nome'))} — {titulo} ({nas_empresas})")
    if titulares:
        factos.append("titulares: " + " | ".join(titulares))
    return (
        f"Analisa quem está por trás de {nomes}: quem manda, quem liga as empresas, "
        "que conflitos e riscos existem e o que deve ser verificado a seguir. "
        f"Factos calculados na plataforma: {'; '.join(factos)}."
    )


async def analisar(
    painel: Dict[str, Any],
    *,
    pergunta: Optional[str] = None,
    profundidade: Optional[str] = None,
    fontes: Optional[Sequence[str]] = None,
    backend: Optional[str] = None,
    skill_id: Optional[str] = None,
    session: Any = None,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pede ao Hermes a análise citada do conjunto de pessoas.

    Sem `skill_id` é o Hermes que escolhe o método (como no painel das empresas);
    com `skill_id`, o método da skill é injetado no pedido.
    """
    from api import hermes_service as hermes  # noqa: PLC0415
    from api import skills_service as biblioteca  # noqa: PLC0415

    empresas = painel.get("empresas") or []
    if not empresas:
        raise ValueError("Painel sem empresas: não há conjunto de pessoas para analisar.")

    texto = (pergunta or "").strip() or pergunta_padrao(painel)
    if skill_id:
        skill = biblioteca.get_skill(str(skill_id))
        if skill is None:
            raise ValueError(f"Skill desconhecida: {skill_id}.")
        if not skill.get("enabled", True):
            raise ValueError(f"A skill «{skill.get('name') or skill_id}» está desativada.")
        metodo = biblioteca.prompt_block(skill, label="Skill escolhida na descoberta de pessoas")
        disponivel = max(0, MAX_PEDIDO_CHARS - len(texto) - 2)
        if disponivel > 0:
            texto = f"{metodo[:disponivel]}\n\n{texto}"

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
        "empresas": [empresa.get("nif") for empresa in empresas],
        "profundidade": profundidade or hermes.DEFAULT_DEPTH,
        "skill_imposta": skill_id or None,
        **resultado,
    }


def _fontes_estado(
    empresas: Sequence[Dict[str, Any]],
    pessoas: Sequence[Dict[str, Any]],
    fontes: Sequence[str],
    devedores: Dict[str, Dict[str, Any]],
    erros: Dict[str, str],
    cire_pessoas: int = 0,
    conflitos: Sequence[Dict[str, Any]] = (),
    contrapartes: int = 0,
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
        "contratos": len(conflitos),
    }
    ms = {
        "cargos": sum(int(empresa.get("ms") or 0) for empresa in empresas) or None,
        "quotas": None,
        "universo": None,
        "cire": None,
        "devedores": None,
        "contratos": None,
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
                    else f"{contrapartes} contraparte(s) nas empresas do pedido (até {MAX_CONTRATOS_CONFLITO} contratos por empresa)."
                    if fonte_id == "contratos"
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
    incluir_conflitos: bool = True,
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

    # --- Conflitos: quem está nos dois lados de um contrato -----------------
    contrapartes: Dict[str, Dict[str, Dict[str, Any]]] = {}
    conflitos: List[Dict[str, Any]] = []
    if incluir_conflitos and "contratos" in pretendidas:
        contrapartes = _contrapartes_das_empresas(empresas)
        conflitos = _conflitos(pessoas, empresas, contrapartes)

    # --- Risco por pessoa: só depois de ter cargos, processos e listas ------
    for pessoa in pessoas:
        pessoa["risco"] = risco_da_pessoa(pessoa)
        pessoa["conflitos"] = sum(1 for item in conflitos if item["nif"] == pessoa["nif"])
    pessoas.sort(key=_ordem_painel)

    for pessoa in pessoas:
        pessoa["evidencia"] = _evidencia(pessoa)

    painel = pessoas[:MAX_PESSOAS_PAINEL]
    cargos = _cargos_distribuicao(painel)
    ligacoes = _ligacoes(painel)
    kpis = _kpis(empresas, painel, cargos, conflitos)
    atencao = _atencao(empresas, painel, ligacoes, conflitos)
    leitura = _leitura(empresas, painel, ligacoes, kpis, atencao)
    # Pessoas (NIF) vistas nos processos do CIRE das empresas do pedido — não são
    # necessariamente titulares: só as que coincidem com o painel ficam anotadas.
    cire_pessoas = {
        nif for empresa in empresas for nif in (empresa.get("cire_map") or {})
    }
    contrapartes_lidas = len({nif for mapa in contrapartes.values() for nif in mapa})
    fontes_estado = _fontes_estado(
        empresas,
        painel,
        pretendidas,
        devedores,
        erros,
        len(cire_pessoas),
        conflitos,
        contrapartes_lidas,
    )

    avisos: List[str] = []
    for empresa in empresas:
        if empresa.get("erro"):
            avisos.append(f"{empresa['nome']}: {empresa['erro']}")
    if len(pessoas) > len(painel):
        avisos.append(
            f"Foram encontradas {len(pessoas)} pessoas e mostradas as {len(painel)} mais relevantes "
            "(órgãos sociais, ligações entre empresas, risco e número de cargos)."
        )
    if not pessoas and empresas:
        avisos.append(
            "Nenhuma das empresas do pedido tem cargos de órgãos sociais registados na plataforma. "
            "Não é ausência de gestão: é ausência de publicações de registo comercial indexadas."
        )
    if conflitos:
        avisos.append(
            f"{len(conflitos)} titular(es) com cargo nos dois lados de um contrato — é o primeiro ponto a verificar."
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
        "conflitos": conflitos[:MAX_CONFLITOS],
        "grafo": _grafo(empresas, painel) if incluir_grafo else None,
        "grafo_pessoas": _grafo_pessoas(painel) if incluir_grafo else None,
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
