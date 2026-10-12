"""Recolha do **Portal da Transparência da ERC** (entidades, pessoas e OCS).

O portal (`portaltransparencia.erc.pt`) é um site Umbraco/ASP.NET com as tabelas
renderizadas no servidor (não há JSON de listagem). As páginas usadas são:

- ``/entidades-ocs/?idActividade=all`` — as ~1.400 entidades proprietárias de
  órgãos de comunicação social, com a tabela ``#tabelaEntidades`` (todas as
  linhas vêm no HTML; o DataTables só pagina no browser);
- ``/entidades-ocs/<slug>/?IdEntidade=<guid>&geral=<secção>`` — a ficha da
  entidade: ``geral`` (actividade, distrito, capital social…), ``orgs``
  (``#orgaosSociaisTable`` — as **pessoas** dos órgãos sociais), ``ocs``
  (``#tabelaEntidadeOcs`` — os órgãos de comunicação social detidos) e ``estru``
  (estrutura de propriedade, preenchida por API);
- ``/pessoas-regulado/?idEntidade=<guid>&geral=<secção>`` — a ficha da pessoa:
  ``geral`` (distrito, actividade), ``orgs`` (empresas onde tem cargos) e
  ``part`` (participações diretas, preenchidas por API).

As tabelas de estrutura de propriedade e de dados financeiros são preenchidas
por JSON, servido por:

- ``/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemEstaEmpresa`` — as
  ligações de capital de uma entidade: devolve todas as conexões e o papel do
  sujeito indica o sentido (a contraparte detém a entidade ou é detida por ela);
- ``/Umbraco/Api/EstruturaCapitalSocial/GetEmpresasQueDetemParticipacao`` — as
  participações diretas de uma pessoa (exige ``nomeCompleto`` e ``findBy``);
  devolve as empresas que a pessoa detém;
- ``/Umbraco/Api/CaracterizacaoFinanceira/GetDadosFinanceira`` — os dados
  financeiros de um exercício (activo, passivo, resultados, capital próprio…).

Este módulo é **só de leitura e normalização**: não guarda estado nem fala com o
Elasticsearch. A recolha completa (com pausa entre pedidos, persistência em
JSONL e indexação) é orquestrada por `api/erc_service.py`.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://portaltransparencia.erc.pt"
ENTIDADES_PATH = "/entidades-ocs/"
PESSOAS_PATH = "/pessoas-regulado/"

LISTING_PATH = ENTIDADES_PATH
LISTING_PARAMS = {"idActividade": "all"}

API_CAPITAL_SOCIAL = "/Umbraco/Api/EstruturaCapitalSocial/"
API_FINANCEIRA = "/Umbraco/Api/CaracterizacaoFinanceira/GetDadosFinanceira"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Códigos de tipo de registo usados pela API do portal.
TIPO_EMPRESA = "1"
TIPO_PESSOA = "2"

#: Papéis (`roleid`) que exprimem, no lado do **sujeito**, uma detenção ativa
#: («Detém diretamente»). Lista do próprio portal (`checkForDetem`).
PAPEIS_DETEM = frozenset({
    "c268d5e8-28a3-e511-80d7-6c3be5beee0c",
    "98d73e9d-28a3-e511-80d7-6c3be5beee0c",
    "07a62852-28a3-e511-80d7-6c3be5beee0c",
    "af0b1d7b-28a3-e511-80d7-6c3be5beee0c",
    "b38c3fd4-28a3-e511-80d7-6c3be5beee0c",
    "e393d207-29a3-e511-80d7-6c3be5beee0c",
    "acfe7987-841b-e611-80c8-00505684056e",
})

#: Papéis (`roleid`) que exprimem, no lado do **sujeito**, uma detenção passiva
#: («Diretamente detidas»). Lista do próprio portal (`checkForDetida`).
PAPEIS_DETIDAS = frozenset({
    "9cd69938-29a3-e511-80d7-6c3be5beee0c",
    "eda192a3-287e-e511-80fa-3863bb3630d8",
    "56f21c46-287e-e511-80fa-3863bb3630d8",
    "62d89783-287e-e511-80fa-3863bb3630d8",
    "16170161-287e-e511-80fa-3863bb3630d8",
    "cb97174c-287e-e511-80fa-3863bb3630d8",
    "f6cb8a7c-287e-e511-80fa-3863bb3630d8",
    "f315cd28-287e-e511-80fa-3863bb3630d8",
    "6028e78f-287e-e511-80fa-3863bb3630d8",
    "b4cdde6c-28a3-e511-80d7-6c3be5beee0c",
})

#: Rótulos derivados dos `id` dos radios de «Dados Gerais».
_ACTIVIDADE_LABELS = {
    "radios_actividadePrincipal_cs": "Comunicação Social",
    "radios_actividadePrincipal_outra": "Outra",
}

_ESPACOS = re.compile(r"\s+")
_MOEDA_LIXO = re.compile(r"[^\d.,]")


def _clean(value: Any) -> str:
    """Colapsa espaços e remove espaços nas pontas (o portal tem vários)."""
    return _ESPACOS.sub(" ", str(value or "")).strip()


def parse_money(value: Any) -> Optional[float]:
    """Converte «5 100,00 €» no número ``5100.0`` (formato português)."""
    if value is None:
        return None
    raw = _MOEDA_LIXO.sub("", str(value))
    if not raw:
        return None
    # «1.234.567,89» → 1234567.89: o ponto é separador de milhares.
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _checked_radio(soup: BeautifulSoup, prefix: str) -> Optional[str]:
    """`id` do radio marcado cujo `id` começa por `prefix` (ou ``None``)."""
    for node in soup.find_all("input", {"type": "radio", "checked": True}):
        node_id = node.get("id") or ""
        if node_id.startswith(prefix):
            return node_id
    return None


def _input_value(soup: BeautifulSoup, node_id: str) -> Optional[str]:
    node = soup.find("input", id=node_id)
    if not node:
        return None
    value = _clean(node.get("value"))
    return value or None


def _sim_nao(soup: BeautifulSoup, prefix: str) -> Optional[bool]:
    """Verdadeiro/falso a partir do radio marcado (`prefix_sim` / `prefix_nao`)."""
    node_id = _checked_radio(soup, prefix)
    if node_id is None:
        return None
    return node_id.endswith("_sim")


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _cell_text(cells: List[Any], index: int) -> Optional[str]:
    """Texto limpo de uma célula (``None`` se a coluna não existir)."""
    if index >= len(cells):
        return None
    return _clean(cells[index].get_text(" ", strip=True)) or None


def _entidade_id_from_href(href: Optional[str]) -> Optional[str]:
    """Extrai o `IdEntidade` de um `href` do portal.

    O portal escreve a chave de várias formas (`IdEntidade`, `IDentidade`), por
    isso a comparação é insensível a maiúsculas.
    """
    if not href:
        return None
    match = re.search(r"idEntidade=([0-9a-fA-F-]{36})", href, re.I)
    return match.group(1).lower() if match else None


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Extrai as entidades proprietárias de OCS da listagem completa.

    Cada item tem ``id`` (GUID), ``nome``, ``slug``, ``url``, ``tipo_sociedade``,
    ``actividade_principal`` e ``distrito``.
    """
    soup = soup_of(html)
    table = soup.find("table", id="tabelaEntidades")
    if not table:
        return []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        href = link.get("href") if link else None
        entidade_id = _entidade_id_from_href(href)
        nome = _clean(link.get_text(" ", strip=True) if link else cells[0].get_text(" ", strip=True))
        if not entidade_id or not nome or entidade_id in seen:
            continue
        seen.add(entidade_id)
        slug = (href or "").split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        out.append({
            "id": entidade_id,
            "nome": nome,
            "slug": slug,
            "url": f"{BASE_URL}{ENTIDADES_PATH}{slug}/" if slug else f"{BASE_URL}{ENTIDADES_PATH}",
            "tipo_sociedade": _cell_text(cells, 1),
            "actividade_principal": _cell_text(cells, 2),
            "distrito": _cell_text(cells, 3),
        })
    return out


def parse_entity_geral(html: str) -> Dict[str, Any]:
    """Campos de «Dados Gerais» de uma entidade (e o `nrRegisto` dos separadores)."""
    soup = soup_of(html)
    titulo = soup.select_one("div.dadosGerais")
    nome = _clean(titulo.get_text(" ", strip=True)) if titulo else None
    nr_registo = None
    for link in soup.select("a[href*='nrRegisto=']"):
        match = re.search(r"nrRegisto=(\d+)", link.get("href") or "")
        if match:
            nr_registo = match.group(1)
            break
    return {
        "nome": nome,
        "actividade_principal": _ACTIVIDADE_LABELS.get(_checked_radio(soup, "radios_actividadePrincipal_") or ""),
        "contabilidade_organizada": _sim_nao(soup, "radios_Contabilidade_Organizada_"),
        "tipo_sociedade": _input_value(soup, "TipodeSociedade"),
        "detem_ocs": _sim_nao(soup, "radios_Detem_OCS_"),
        "capital_social": _input_value(soup, "capitalSocial"),
        "distrito": _input_value(soup, "distrito"),
        "nr_registo": nr_registo,
    }


def _tabs(soup: BeautifulSoup) -> List[str]:
    """Secções (`geral`) dos separadores presentes numa ficha."""
    seen: List[str] = []
    for link in soup.select("a[href*='geral=']"):
        match = re.search(r"geral=([A-Za-z]+)", link.get("href") or "")
        if match and match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def parse_entity_tabs(html: str) -> List[str]:
    """Secções dos separadores da ficha de uma entidade (`geral`, `orgs`, `ocs`, …)."""
    return _tabs(soup_of(html))


def parse_person_tabs(html: str) -> List[str]:
    """Secções dos separadores da ficha de uma pessoa (`geral`, `part`, `orgs`)."""
    return _tabs(soup_of(html))


def parse_person_geral(html: str) -> Dict[str, Any]:
    """Campos de «Dados Gerais» de uma pessoa regulada."""
    soup = soup_of(html)
    titulo = soup.select_one("div.dadosGerais")
    return {
        "nome": _clean(titulo.get_text(" ", strip=True)) if titulo else None,
        "actividade_principal": _ACTIVIDADE_LABELS.get(_checked_radio(soup, "radios_actividadePrincipal_") or ""),
        "detem_ocs": _sim_nao(soup, "radios_Detem_OCS_"),
        "distrito": _input_value(soup, "distrito"),
    }


def parse_entity_orgs(html: str) -> List[Dict[str, Any]]:
    """Pessoas dos órgãos sociais de uma entidade (``#orgaosSociaisTable``).

    Cada item tem ``id`` (GUID da pessoa), ``nome``, ``tipo_orgao`` e ``funcao``.
    """
    soup = soup_of(html)
    table = soup.find("table", id="orgaosSociaisTable")
    if not table:
        return []
    out: List[Dict[str, Any]] = []
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        link = cells[0].find("a")
        pessoa_id = _entidade_id_from_href(link.get("href") if link else None)
        nome = _clean(cells[0].get_text(" ", strip=True))
        if not nome:
            continue
        out.append({
            "id": pessoa_id,
            "nome": nome,
            "tipo_orgao": _clean(cells[1].get_text(" ", strip=True)) or None,
            "funcao": _clean(cells[2].get_text(" ", strip=True)) or None,
        })
    return out


def parse_person_orgs(html: str) -> List[Dict[str, Any]]:
    """Empresas onde a pessoa tem cargos (``#orgaosSociaisTable`` da ficha da pessoa).

    Cada item tem ``id`` (GUID da entidade), ``nome``, ``tipo_orgao``, ``funcao``
    e ``tipo_orgao_id``.
    """
    soup = soup_of(html)
    table = soup.find("table", id="orgaosSociaisTable")
    if not table:
        return []
    out: List[Dict[str, Any]] = []
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        link = cells[0].find("a")
        entidade_id = _entidade_id_from_href(link.get("href") if link else None)
        nome = _clean(cells[0].get_text(" ", strip=True))
        if not nome:
            continue
        out.append({
            "id": entidade_id,
            "nome": nome,
            "tipo_orgao": _clean(cells[1].get_text(" ", strip=True)) or None,
            "tipo_orgao_id": _clean(cells[2].get_text(" ", strip=True)) or None,
            "funcao": _clean(cells[3].get_text(" ", strip=True)) or None,
            "funcao_id": _clean(cells[4].get_text(" ", strip=True)) or None if len(cells) > 4 else None,
        })
    return out


def parse_entity_ocs(html: str) -> List[Dict[str, Any]]:
    """Órgãos de comunicação social detidos (``#tabelaEntidadeOcs``)."""
    soup = soup_of(html)
    table = soup.find("table", id="tabelaEntidadeOcs")
    if not table:
        return []
    out: List[Dict[str, Any]] = []
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        designacao = _clean(cells[0].get_text(" ", strip=True))
        if not designacao:
            continue
        out.append({
            "designacao": designacao,
            "tipo": _cell_text(cells, 1),
            "entidade_proprietaria": _cell_text(cells, 2),
            "distrito": _cell_text(cells, 3),
        })
    return out


def parse_estrutura(
    payload: Any,
    subject_id: Optional[str] = None,
    *,
    pessoa: bool = False,
) -> List[Dict[str, Any]]:
    """Converte uma resposta da estrutura de capital em ligações normalizadas.

    A API devolve *conexões* entre dois registos, com o sujeito do pedido sempre
    em ``record2`` em `GetEmpresasQueDetemEstaEmpresa` (e em
    `GetEmpresasQueDetemParticipacao`). O papel (`roleid`) **do lado do sujeito**
    indica o sentido da ligação: um papel de `PAPEIS_DETEM` («Detém diretamente»)
    significa que a contraparte **detém** o sujeito (é detentora); um papel de
    `PAPEIS_DETIDAS` («Diretamente detidas») significa que a contraparte **é
    detida** pelo sujeito. Ligações com outros papéis não são de detenção e são
    ignoradas.

    Nas participações de uma pessoa (`pessoa=True`) não há filtro por papel: todas
    as ligações devolvidas são empresas **detidas** pela pessoa (uma pessoa não é
    detida por uma empresa), e é isso que o portal mostra.

    Nota: a tabela «Entidades detidas» do portal filtra pelo papel do lado
    errado, pelo que aparece sempre vazia; aqui o sentido é derivado do papel do
    sujeito, como o portal o define para «Entidades detentoras», ficando os dois
    sentidos corretos.
    """
    if isinstance(payload, dict):
        items = payload.get("data") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    alvo = (subject_id or "").lower()
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        r1 = (item.get("record1id") or "").lower()
        r2 = (item.get("record2id") or "").lower()
        if alvo and r1 == alvo and r2 != alvo:
            sujeito, outro = "record1", "record2"
        elif alvo and r2 == alvo and r1 != alvo:
            sujeito, outro = "record2", "record1"
        else:
            sujeito, outro = "record2", "record1"

        papel_sujeito = item.get(f"{sujeito}roleid")
        if pessoa:
            tipo_relacao = "detida"
        elif papel_sujeito in PAPEIS_DETEM:
            tipo_relacao = "detentor"
        elif papel_sujeito in PAPEIS_DETIDAS:
            tipo_relacao = "detida"
        else:
            continue

        nome = _clean(item.get(f"{outro}id_name"))
        entidade_id = (item.get(f"{outro}id") or "").lower() or None
        if not nome:
            continue
        papel = _clean(item.get(f"{outro}roleid_name")) or None
        key = (entidade_id, papel, item.get("erc_percentagem"))
        if key in seen:
            continue
        seen.add(key)
        tipo = str(item.get(f"{outro}objecttypecode") or "")
        out.append({
            "id": entidade_id,
            "nome": nome,
            "e_empresa": tipo == TIPO_EMPRESA,
            "e_pessoa": tipo == TIPO_PESSOA,
            "tipo_relacao": tipo_relacao,
            "tipo_detencao": papel,
            "percentagem": _clean(item.get("erc_percentagem")) or None,
            "percentagem_valor": parse_money(item.get("erc_percentagem")),
            "direitos_voto": _clean(item.get("erc_direitosvoto")) or None,
            "direitos_voto_valor": parse_money(item.get("erc_direitosvoto")),
            "contraparte": r2 if sujeito == "record2" else r1,
        })
    return out


def parse_financeiro_anos(html: str) -> List[int]:
    """Exercícios publicados, lidos do `select` da secção «Dados Financeiros»."""
    soup = soup_of(html)
    anos: List[int] = []
    for select in soup.find_all("select"):
        for option in select.find_all("option"):
            value = _clean(option.get("value"))
            if len(value) == 4 and value.isdigit():
                ano = int(value)
                if 1990 <= ano <= 2100:
                    anos.append(ano)
    return sorted(set(anos))


def parse_financeiro(payload: Any) -> List[Dict[str, Any]]:
    """Dados financeiros por exercício (`GetDadosFinanceira`)."""
    items = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ano = item.get("Erc_ano")
        try:
            ano_int = int(str(ano))
        except (TypeError, ValueError):
            continue
        out.append({
            "ano": ano_int,
            "ativo_total": parse_money(item.get("Erc_ativototal")),
            "passivo_total": parse_money(item.get("Erc_passivototal")),
            "passivos_totais": parse_money(item.get("Erc_passivostotais")),
            "capital_proprio": parse_money(item.get("Erc_capitalproprio")),
            "rendimentos_totais": parse_money(item.get("Erc_rendimentostotais")),
            "resultados_antes_custos": parse_money(item.get("Erc_resultadosantescustos")),
            "resultados_liquidos": parse_money(item.get("Erc_resultadosliquidos")),
            "confidencialidade": str(item.get("Erc_solicitopedidoconfidencialidade") or "").lower() == "true",
        })
    return out


# --------------------------------------------------------------------------
# Acesso HTTP
# --------------------------------------------------------------------------

def make_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-PT,pt;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
    )


def entity_url(slug: str, entidade_id: str) -> str:
    return f"{BASE_URL}{ENTIDADES_PATH}{slug}/?IdEntidade={entidade_id}"


def person_url(pessoa_id: str) -> str:
    return f"{BASE_URL}{PESSOAS_PATH}?idEntidade={pessoa_id}"


def fetch_text(client: httpx.Client, url: str, params: Optional[Dict[str, Any]] = None) -> str:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.text


def fetch_listing(client: httpx.Client) -> List[Dict[str, Any]]:
    """Descarrega e interpreta a listagem completa de entidades."""
    html = fetch_text(client, f"{BASE_URL}{LISTING_PATH}", params=LISTING_PARAMS)
    return parse_listing(html)


def fetch_estrutura(client: httpx.Client, entidade_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Estrutura de propriedade de uma entidade: ``(detentores, detidas)``.

    Um único pedido (`GetEmpresasQueDetemEstaEmpresa`) devolve todas as ligações
    de capital da entidade; o sentido de cada uma vem do papel do sujeito.
    """
    url = f"{BASE_URL}{API_CAPITAL_SOCIAL}GetEmpresasQueDetemEstaEmpresa"
    response = client.get(url, params={"idEntidade": entidade_id})
    response.raise_for_status()
    ligacoes = parse_estrutura(response.json(), entidade_id)
    detentores = [item for item in ligacoes if item["tipo_relacao"] == "detentor"]
    detidas = [item for item in ligacoes if item["tipo_relacao"] == "detida"]
    return detentores, detidas


def fetch_participacoes(client: httpx.Client, pessoa_id: str, nome: Optional[str] = None) -> List[Dict[str, Any]]:
    """Participações diretas de uma pessoa (o endpoint exige `nomeCompleto`).

    O portal envia o nome com ``+`` no lugar dos espaços e o identificador em
    minúsculas; como o `httpx` voltaria a codificar o ``+``, a query é montada à
    mão em vez de via `params`.
    """
    if not nome:
        return []
    query = f"idEntidade={pessoa_id}&nomeCompleto={quote_plus(nome)}&findBy=idEntidade"
    url = f"{BASE_URL}{API_CAPITAL_SOCIAL}GetEmpresasQueDetemParticipacao?{query}"
    response = client.get(url)
    if response.status_code >= 400:
        logger.debug("Participações de %s (%s): HTTP %s", nome, pessoa_id, response.status_code)
        return []
    try:
        return parse_estrutura(response.json(), pessoa_id, pessoa=True)
    except ValueError:
        return []


def fetch_financeiro(client: httpx.Client, entidade_id: str, ano: int, *, singular: bool = False) -> List[Dict[str, Any]]:
    """Dados financeiros de um exercício (lista vazia quando não há publicação)."""
    response = client.get(
        f"{BASE_URL}{API_FINANCEIRA}",
        params={"idEntidade": entidade_id, "anoFinanceiro": ano, "isEntidadeSingular": "true" if singular else "false"},
    )
    if response.status_code >= 400 or "Sem resultados" in response.text:
        return []
    try:
        return parse_financeiro(response.json())
    except ValueError:
        return []


def iter_pessoas(orgaos: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pessoas distintas (por GUID) a partir de uma lista de órgãos sociais."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in orgaos:
        pessoa_id = item.get("id")
        nome = item.get("nome")
        if not pessoa_id or not nome or pessoa_id in seen:
            continue
        seen.add(pessoa_id)
        out.append({"id": pessoa_id, "nome": nome})
    return out
