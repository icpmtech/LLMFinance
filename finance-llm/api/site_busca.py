"""Pesquisa pública do site e fichas de empresa e de contrato.

A página `/site/pesquisar` procura numa só caixa — como um motor de busca — o que
a plataforma sabe sobre **empresas**, **contratos públicos**, **notícias** e
**insolvências**, e cada resultado abre uma ficha renderizada no servidor:

- `/site/empresa/<nif>` — cadastro, contratos, insolvências e notícias;
- `/site/contrato/<idcontrato>` — o contrato, as partes e os valores.

Decisões:

- **Só leitura, e só o que é público.** Não há sessão nem CRM: são pesquisas ao
  Elasticsearch, as mesmas que alimentam a pesquisa unificada da plataforma
  (`api.search_service`), mas normalizadas para o desenho do site (título,
  endereço interno, resumo, data e etiquetas).
- **Um grupo em baixo não derruba a página.** Cada âmbito corre no seu
  `try/except`: o que falhar devolve `erro` naquele grupo e os restantes
  continuam.
- **As datas e os euros são formatados aqui** («28/09/2026», «310 653 €»): o
  renderizador não repete essa conversão em cada sítio.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from api.elasticsearch_client import (
    CIRE_INDEX,
    ENTITIES_INDEX,
    NON_NEWS_SOURCE_IDS,
    NON_NEWS_SOURCE_PREFIXES,
    get_company_by_nif,
    get_company_contracts,
    get_contract_by_id,
    get_es_client,
    search_contracts,
    search_entities,
    search_scraped,
)

logger = logging.getLogger(__name__)

#: Abas da página. `tudo` não é um grupo: significa «todos os âmbitos».
TIPOS: Tuple[Dict[str, str], ...] = (
    {"id": "tudo", "label": "Tudo"},
    {"id": "empresas", "label": "Empresas"},
    {"id": "contratos", "label": "Contratos"},
    {"id": "noticias", "label": "Notícias"},
    {"id": "insolvencias", "label": "Insolvências"},
)
TIPO_IDS = {tipo["id"] for tipo in TIPOS}

#: Resultados por âmbito na aba «Tudo». Na aba de um âmbito só, mostra mais.
LIMITE_POR_TIPO = 6
LIMITE_DO_TIPO = 20

#: Contratos e insolvências mostrados na ficha de uma empresa.
LIMITE_NA_FICHA = 12


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------
def _texto(valor: Any) -> str:
    """Texto de um campo que pode vir como lista, dicionário ou nulo."""
    if valor in (None, ""):
        return ""
    if isinstance(valor, (list, tuple, set)):
        vistos: List[str] = []
        for item in valor:
            parte = _texto(item)
            if parte and parte not in vistos:
                vistos.append(parte)
        return " · ".join(vistos)
    if isinstance(valor, dict):
        for chave in ("nome", "name", "description", "descricao", "raw"):
            if valor.get(chave):
                return _texto(valor[chave])
        return ""
    return " ".join(str(valor).split())


def _clip(valor: Any, limite: int = 240) -> str:
    texto = _texto(valor)
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return f"{corte}…"


def euros(valor: Any) -> str:
    """Valor em euros à portuguesa («310 653 €»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    return f"{numero:,.0f}".replace(",", " ") + " €"


def euros_curto(valor: Any) -> str:
    """Valor compacto para destaques («310,7 mil €», «1,2 M€»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    if abs(numero) >= 1_000_000_000:
        return f"{numero / 1_000_000_000:.1f}".replace(".", ",") + " mil M€"
    if abs(numero) >= 1_000_000:
        return f"{numero / 1_000_000:.1f}".replace(".", ",") + " M€"
    if abs(numero) >= 1_000:
        return f"{numero / 1_000:.1f}".replace(".", ",") + " mil €"
    return euros(numero)


def data(valor: Any) -> str:
    """Data legível («28/09/2026») a partir de ISO, `datetime` ou data."""
    if valor in (None, ""):
        return ""
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return texto[:10]


def _nif(termo: str) -> bool:
    return bool(termo) and termo.isdigit() and len(termo) == 9


def _dias(valor: Any) -> str:
    """Prazo em dias sem casas decimais («365», não «365.0»)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""
    return f"{numero:.0f}" if numero > 0 else ""


def _partes(texto: Any) -> List[Dict[str, str]]:
    """Partes de um contrato: `[{"nif": ..., "nome": ...}]`."""
    if isinstance(texto, dict):
        partes = texto.get("parsed") or []
    else:
        partes = texto or []
    saida: List[Dict[str, str]] = []
    for parte in partes:
        if isinstance(parte, dict):
            nome = _texto(parte.get("nome"))
            if nome:
                saida.append({"nif": str(parte.get("nif") or ""), "nome": nome})
    return saida


# --------------------------------------------------------------------------
# Resultados normalizados
# --------------------------------------------------------------------------
def _resultado(
    titulo: Any,
    href: str,
    *,
    sub: str = "",
    resumo: str = "",
    quando: Any = None,
    etiquetas: Optional[Iterable[Any]] = None,
    externo: bool = False,
) -> Dict[str, Any]:
    return {
        "titulo": _clip(titulo, 180) or "(sem título)",
        "href": href,
        "sub": _clip(sub, 180),
        "resumo": _clip(resumo, 240),
        "data": data(quando),
        "etiquetas": [_clip(etiqueta, 60) for etiqueta in (etiquetas or []) if _texto(etiqueta)][:4],
        "externo": bool(externo),
    }


def _grupo(grupo_id: str, rotulo: str, total: int, itens: List[Dict[str, Any]], erro: str = "") -> Dict[str, Any]:
    return {"id": grupo_id, "label": rotulo, "total": int(total or 0), "items": itens, "erro": erro or ""}


def _chave(valor: Any) -> str:
    """Nome comparável: sem acentos, sem maiúsculas e com espaços simples.

    É o que faz «galp açores» casar com «GALP AÇORES, UNIPESSOAL LDA.» — e o que
    ordena os resultados pelo que o nome tem de igual ao termo escrito.
    """
    texto = _texto(valor).lower()
    sem_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpo = "".join(letra if letra.isalnum() else " " for letra in sem_acentos)
    return " ".join(limpo.split())


# --------------------------------------------------------------------------
# Âmbitos
# --------------------------------------------------------------------------
def _empresas(termo: str, limite: int) -> Dict[str, Any]:
    """Cadastro de entidades. O NIF exato e o nome exato vêm à frente."""
    achado = search_entities(q=termo, size=max(limite * 3, 15))
    if achado.get("error"):
        return _grupo("empresas", "Empresas", 0, [], _texto(achado["error"]))

    chave = _chave(termo)
    linhas = achado.get("items") or []

    def ordem(linha: Dict[str, Any]) -> Tuple[int, float]:
        nome = _chave(linha.get("name"))
        if _nif(termo) and str(linha.get("nif") or "") == termo:
            return (0, 0.0)
        if nome == chave:
            return (1, 0.0)
        if nome.startswith(chave):
            return (2, 0.0)
        return (3, -float(linha.get("total_value") or 0))

    itens = []
    for linha in sorted(linhas, key=ordem)[:limite]:
        nif = str(linha.get("nif") or "")
        if not nif:
            continue
        contratos = int(linha.get("contracts_count") or 0)
        valor = linha.get("total_value")
        itens.append(
            _resultado(
                linha.get("name"),
                f"/site/empresa/{nif}",
                sub=" · ".join(
                    parte
                    for parte in (
                        f"NIF {nif}",
                        _texto(linha.get("country")),
                        _texto(linha.get("cae_principal")),
                    )
                    if parte
                ),
                resumo=(
                    f"{contratos} contrato(s) · {euros(valor)}"
                    if contratos
                    else "Sem contratos públicos indexados"
                ),
                etiquetas=[
                    "adjudicante" if linha.get("as_adjudicante_count") else "",
                    "adjudicatário" if linha.get("as_adjudicatario_count") else "",
                ],
            )
        )
    return _grupo("empresas", "Empresas", achado.get("total") or 0, itens)


def _contratos(termo: str, limite: int) -> Dict[str, Any]:
    """Contratos públicos, por relevância (objeto, partes e CPV)."""
    achado = search_contracts(q=termo, size=limite, sort_by="relevance", strict=True)
    if achado.get("error"):
        return _grupo("contratos", "Contratos", 0, [], _texto(achado["error"]))

    itens = []
    for linha in achado.get("items") or []:
        idcontrato = str(linha.get("idcontrato") or linha.get("doc_id") or "")
        if not idcontrato:
            continue
        entidade = _partes(linha.get("adjudicantes"))
        fornecedor = _partes(linha.get("adjudicatarios"))
        itens.append(
            _resultado(
                linha.get("objectoContrato") or linha.get("descContrato"),
                f"/site/contrato/{idcontrato}",
                sub=" → ".join(
                    filter(None, [entidade[0]["nome"] if entidade else "", fornecedor[0]["nome"] if fornecedor else ""])
                ),
                resumo=euros(linha.get("precoContratual")),
                quando=linha.get("dataCelebracaoContrato") or linha.get("dataPublicacao"),
                etiquetas=[
                    linha.get("Ano"),
                    _texto(linha.get("tipoContrato")),
                    (linha.get("cpv") or [{}])[0].get("code") if isinstance(linha.get("cpv"), list) and linha.get("cpv") else "",
                ],
            )
        )
    return _grupo("contratos", "Contratos", achado.get("total") or 0, itens)


def _noticias(termo: str, limite: int) -> Dict[str, Any]:
    """Notícias da imprensa recolhida (SAPO, Lusa, ECO, Observador…)."""
    achado = search_scraped(
        q=termo,
        size=limite,
        sort="relevance",
        exclude_prefixes=NON_NEWS_SOURCE_PREFIXES,
        exclude_ids=NON_NEWS_SOURCE_IDS,
    )
    if achado.get("error"):
        return _grupo("noticias", "Notícias", 0, [], _texto(achado["error"]))

    itens = []
    for linha in achado.get("items") or []:
        url = str(linha.get("url") or "")
        if not url:
            continue
        itens.append(
            _resultado(
                linha.get("title"),
                url,
                sub=_texto(linha.get("source_name") or linha.get("source_id")),
                resumo=linha.get("summary") or linha.get("text"),
                quando=linha.get("published_at") or linha.get("scraped_at"),
                externo=True,
            )
        )
    return _grupo("noticias", "Notícias", achado.get("total") or 0, itens)


#: Campos do CIRE procurados por texto livre (os mesmos da pesquisa unificada).
_CIRE_CAMPOS = (
    "insolvente^3",
    "intervenientes.nome^3",
    "referencia^3",
    "processo^2",
    "processo_numero^2",
    "tribunal^2",
    "ato^2",
    "especie",
    "texto",
)


def _nif_do_insolvente(publicacao: Dict[str, Any]) -> str:
    """NIF do insolvente de uma publicação (o primeiro interveniente nesse papel)."""
    insolvente = _chave(publicacao.get("insolvente"))
    for interveniente in publicacao.get("intervenientes") or []:
        if not isinstance(interveniente, dict):
            continue
        if _chave(interveniente.get("papel")) == "insolvente" and interveniente.get("nif"):
            return str(interveniente["nif"])
    for interveniente in publicacao.get("intervenientes") or []:
        if isinstance(interveniente, dict) and _chave(interveniente.get("nome")) == insolvente and interveniente.get("nif"):
            return str(interveniente["nif"])
    return ""


def _cire_por_relevancia(termo: str, limite: int) -> Dict[str, Any]:
    """Publicações do CIRE por relevância.

    `search_cire` ordena por data (é o que serve as páginas do módulo); numa
    pesquisa de texto livre o termo distintivo é o **nome**, e a data a
    desempatar — sem isto, «Sicasal» devolvia as insolvências mais recentes de
    quem quer que fosse.
    """
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    try:
        resposta = client.search(
            index=CIRE_INDEX,
            body={
                "size": max(1, min(limite, 50)),
                "track_total_hits": True,
                "query": {
                    "multi_match": {"query": termo, "fields": list(_CIRE_CAMPOS), "operator": "and"}
                },
                "sort": ["_score", {"data_publicacao": {"order": "desc", "missing": "_last"}}],
            },
        )
    except Exception as exc:  # noqa: BLE001 - um âmbito em baixo não derruba a pesquisa
        logger.warning("Pesquisa pública: CIRE falhou: %s", exc)
        return {"error": str(exc), "items": [], "total": 0}
    return {
        "total": resposta["hits"]["total"]["value"],
        "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resposta["hits"]["hits"]],
    }


def _insolvencias(termo: str, limite: int) -> Dict[str, Any]:
    """Insolvências e revitalizações (CIRE): o visado é o insolvente."""
    achado = _cire_por_relevancia(termo, limite)
    if achado.get("error"):
        return _grupo("insolvencias", "Insolvências", 0, [], achado["error"])

    itens = []
    for linha in achado.get("items") or []:
        nif = _nif_do_insolvente(linha)
        destino = f"/site/empresa/{nif}" if nif else str(linha.get("documento_url") or "")
        if not destino:
            continue
        itens.append(
            _resultado(
                linha.get("insolvente"),
                destino,
                sub=" · ".join(
                    filter(None, [_texto(linha.get("tipo")), _texto(linha.get("tribunal_comarca"))])
                ),
                resumo=" · ".join(
                    filter(None, [_texto(linha.get("ato")), _texto(linha.get("especie")), _texto(linha.get("processo_numero"))])
                ),
                quando=linha.get("data_publicacao"),
                etiquetas=[linha.get("tipo"), linha.get("especie")],
                externo=not nif,
            )
        )
    return _grupo("insolvencias", "Insolvências", achado.get("total") or 0, itens)


#: Ordem das abas → função que pesquisa o âmbito. Resolvido a cada pesquisa (e
#: não no import): é o que permite trocar um âmbito nos testes e manter a página
#: a funcionar quando um índice está em baixo.
def _ambitos() -> Dict[str, Any]:
    return {
        "empresas": _empresas,
        "contratos": _contratos,
        "noticias": _noticias,
        "insolvencias": _insolvencias,
    }


def pesquisar(termo: str, *, tipo: str = "tudo", limite: int = LIMITE_POR_TIPO) -> Dict[str, Any]:
    """Pesquisa pública: devolve os grupos do tipo pedido (ou de todos)."""
    consulta = " ".join(str(termo or "").split())
    escolhido = tipo if tipo in TIPO_IDS else "tudo"
    if not consulta:
        return {"termo": "", "tipo": escolhido, "total": 0, "grupos": [], "erro": ""}

    ambitos = _ambitos()
    if escolhido == "tudo":
        pedidos = list(ambitos.items())
        tamanho = max(1, min(int(limite or LIMITE_POR_TIPO), LIMITE_POR_TIPO))
    else:
        pedidos = [(escolhido, ambitos[escolhido])]
        tamanho = max(1, min(int(limite or LIMITE_DO_TIPO), LIMITE_DO_TIPO))

    grupos: List[Dict[str, Any]] = []
    for ambito_id, funcao in pedidos:
        try:
            grupos.append(funcao(consulta, tamanho))
        except Exception as exc:  # noqa: BLE001 - um âmbito em baixo não derruba a pesquisa
            logger.warning("Pesquisa pública: âmbito %s falhou: %s", ambito_id, exc)
            grupos.append(_grupo(ambito_id, ambito_id.title(), 0, [], f"{type(exc).__name__}: {exc}"))

    return {
        "termo": consulta,
        "tipo": escolhido,
        "total": sum(grupo["total"] for grupo in grupos),
        "grupos": grupos,
        "erro": "",
    }


# --------------------------------------------------------------------------
# Ficha de uma empresa
# --------------------------------------------------------------------------
def _nested_nif(nif: str, papel: Optional[str] = None) -> Dict[str, Any]:
    filtros: List[Dict[str, Any]] = [{"term": {"intervenientes.nif": nif}}]
    if papel:
        filtros.append({"term": {"intervenientes.papel": papel}})
    return {"nested": {"path": "intervenientes", "query": {"bool": {"filter": filtros}}}}


def _cire_da_empresa(nif: str, limite: int = LIMITE_NA_FICHA) -> Dict[str, Any]:
    """Publicações do CIRE de uma empresa, separadas pelo papel que ela tem.

    O CIRE lista **todas** as partes de cada processo (credores incluídos), pelo
    que uma empresa grande aparece em centenas de publicações onde não é
    insolvente. Mostrar isso como «insolvências da empresa» seria falso: aqui
    contam-se e listam-se à parte os processos em que ela é o **insolvente**.
    """
    client = get_es_client()
    if not client:
        return {"erro": "Elasticsearch indisponível", "insolvente": _grupo("insolvente", "Insolvente", 0, []), "outros": _grupo("outros", "Outras", 0, [])}
    try:
        insolventes = client.search(
            index=CIRE_INDEX,
            body={
                "size": max(1, min(limite, 50)),
                "track_total_hits": True,
                "query": _nested_nif(nif, "Insolvente"),
                "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
            },
        )
        outros = client.search(
            index=CIRE_INDEX,
            body={
                "size": max(1, min(limite, 50)),
                "track_total_hits": True,
                "query": {
                    "bool": {
                        "filter": [_nested_nif(nif)],
                        "must_not": [_nested_nif(nif, "Insolvente")],
                    }
                },
                "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
            },
        )
    except Exception as exc:  # noqa: BLE001 - a ficha abre sem a secção do CIRE
        logger.warning("Ficha pública: CIRE de %s falhou: %s", nif, exc)
        return {"erro": str(exc), "insolvente": _grupo("insolvente", "Insolvente", 0, []), "outros": _grupo("outros", "Outras", 0, [])}

    def publicacoes(resposta: Dict[str, Any]) -> List[Dict[str, Any]]:
        itens = []
        for hit in resposta["hits"]["hits"]:
            linha = hit["_source"]
            itens.append(
                {
                    "data": data(linha.get("data_publicacao")),
                    "tipo": _texto(linha.get("tipo")),
                    "especie": _texto(linha.get("especie")),
                    "ato": _texto(linha.get("ato")),
                    "processo": _texto(linha.get("processo_numero") or linha.get("processo")),
                    "tribunal": _texto(linha.get("tribunal") or linha.get("tribunal_comarca")),
                    "documento": str(linha.get("documento_url") or ""),
                    "papel": _papel_do_nif(linha, nif),
                }
            )
        return itens

    return {
        "erro": "",
        "insolvente": _grupo(
            "insolvente",
            "Processos em que é insolvente",
            insolventes["hits"]["total"]["value"],
            publicacoes(insolventes),
        ),
        "outros": _grupo(
            "outros",
            "Outras publicações em que é interveniente",
            outros["hits"]["total"]["value"],
            publicacoes(outros),
        ),
    }


def _papel_do_nif(publicacao: Dict[str, Any], nif: str) -> str:
    for interveniente in publicacao.get("intervenientes") or []:
        if isinstance(interveniente, dict) and str(interveniente.get("nif") or "") == str(nif):
            return _texto(interveniente.get("papel"))
    return ""


def _noticias_da_empresa(nome: str, limite: int = 6) -> List[Dict[str, Any]]:
    """Notícias recentes que mencionam a empresa (imprensa recolhida).

    A razão social completa («GALP AÇORES, UNIPESSOAL LDA.») quase nunca aparece
    escrita assim numa notícia: sem resultados, a pesquisa repete-se com as duas
    primeiras palavras do nome, que é como a empresa é tratada na imprensa.
    """
    if len(nome) < 3:
        return []
    tentativas = [nome]
    palavras = [palavra for palavra in nome.split() if len(palavra) > 2]
    if len(palavras) > 2:
        tentativas.append(" ".join(palavras[:2]))

    for termo in tentativas:
        achado = search_scraped(
            q=termo,
            size=limite,
            sort="relevance",
            exclude_prefixes=NON_NEWS_SOURCE_PREFIXES,
            exclude_ids=NON_NEWS_SOURCE_IDS,
        )
        if achado.get("error"):
            return []
        itens = []
        for linha in achado.get("items") or []:
            url = str(linha.get("url") or "")
            if not url:
                continue
            itens.append(
                {
                    "titulo": _clip(linha.get("title"), 180),
                    "url": url,
                    "fonte": _texto(linha.get("source_name") or linha.get("source_id")),
                    "resumo": _clip(linha.get("summary") or linha.get("text"), 200),
                    "data": data(linha.get("published_at") or linha.get("scraped_at")),
                }
            )
        if itens:
            return itens
    return []


def _entidade_leve(nif: str) -> Dict[str, Any]:
    """Documento do cadastro sem os campos pesados (o `embedding` são 1536 números).

    `get_entity_by_nif` devolve o documento inteiro e demora segundos por causa
    do vetor; a ficha pública só precisa do país, do CAE e da origem.
    """
    client = get_es_client()
    if not client:
        return {}
    try:
        resposta = client.search(
            index=ENTITIES_INDEX,
            body={
                "size": 1,
                "query": {"term": {"nif": nif}},
                "_source": ["nif", "name", "country", "cae_principal", "source"],
            },
        )
    except Exception as exc:  # noqa: BLE001 - a ficha abre sem estes campos
        logger.warning("Ficha pública: cadastro leve de %s falhou: %s", nif, exc)
        return {}
    hits = resposta["hits"]["hits"]
    return dict(hits[0]["_source"]) if hits else {}


def _contratos_da_empresa(empresa: Dict[str, Any], nif: str, limite: int = LIMITE_NA_FICHA) -> List[Dict[str, Any]]:
    """Contratos recentes com o papel da empresa e a contraparte de cada um."""
    recentes = empresa.get("recent_contracts")
    if not isinstance(recentes, list):
        achado = get_company_contracts(nif=nif, size=limite)
        recentes = achado.get("items") or []

    itens = []
    for linha in recentes[:limite]:
        if not isinstance(linha, dict):
            continue
        idcontrato = str(linha.get("idcontrato") or linha.get("doc_id") or "")
        if not idcontrato:
            continue
        entidades = _partes(linha.get("adjudicantes"))
        fornecedores = _partes(linha.get("adjudicatarios"))
        e_adjudicante = any(parte["nif"] == nif for parte in entidades)
        contrapartes = fornecedores if e_adjudicante else entidades
        itens.append(
            {
                "id": idcontrato,
                "objeto": _clip(linha.get("objectoContrato") or linha.get("descContrato"), 200),
                "data": data(linha.get("dataCelebracaoContrato") or linha.get("dataPublicacao")),
                "valor": euros(linha.get("precoContratual")),
                "valor_num": linha.get("precoContratual") or 0,
                "papel": "Adjudicante" if e_adjudicante else "Adjudicatário",
                "contraparte": contrapartes[0]["nome"] if contrapartes else "",
                "contraparte_nif": contrapartes[0]["nif"] if contrapartes else "",
                "ano": linha.get("Ano"),
            }
        )
    return itens


def _nome_no_cire(nif: str) -> str:
    """Nome de quem só existe no CIRE (insolventes sem contratos no Portal BASE)."""
    client = get_es_client()
    if not client:
        return ""
    try:
        resposta = client.search(
            index=CIRE_INDEX,
            body={"size": 10, "query": _nested_nif(nif), "_source": ["insolvente", "intervenientes"]},
        )
    except Exception as exc:  # noqa: BLE001 - sem nome não há ficha
        logger.warning("Ficha pública: nome de %s no CIRE falhou: %s", nif, exc)
        return ""
    encontrado = ""
    for hit in resposta["hits"]["hits"]:
        for interveniente in hit["_source"].get("intervenientes") or []:
            if not isinstance(interveniente, dict) or str(interveniente.get("nif") or "") != nif:
                continue
            if _chave(interveniente.get("papel")) == "insolvente":
                return _texto(interveniente.get("nome"))
            encontrado = encontrado or _texto(interveniente.get("nome"))
    return encontrado


def empresa(nif: str) -> Optional[Dict[str, Any]]:
    """Tudo o que a ficha pública de uma empresa mostra (ou `None` se não existir)."""
    codigo = str(nif or "").strip()
    if not codigo:
        return None
    cadastro = get_company_by_nif(codigo) or {}
    if cadastro.get("error"):
        logger.warning("Ficha pública: cadastro de %s falhou: %s", codigo, cadastro["error"])
        return None

    leve = _entidade_leve(codigo)
    nome = _texto(cadastro.get("name"))
    # Sem nome (só o NIF repetido) a entidade não está no cadastro de contratos:
    # ainda pode existir — quem só aparece numa insolvência do CIRE tem ficha,
    # com os processos e sem contratos. Sem nome nenhum, não há página.
    if not nome or nome == codigo:
        nome = _texto(leve.get("name")) or _nome_no_cire(codigo)
    if not nome:
        return None

    adjudicante = cadastro.get("adjudicante") or {}
    adjudicatario = cadastro.get("adjudicatario") or {}
    return {
        "nif": codigo,
        "nome": nome,
        "pais": _texto(leve.get("country")) or _texto(cadastro.get("country")),
        "localizacao": _texto(cadastro.get("localizacao")),
        "morada": _texto(cadastro.get("morada")),
        "atividade": _texto(cadastro.get("atividade")),
        "forma_juridica": _texto(cadastro.get("forma_juridica")),
        "capital_social": euros(cadastro.get("capital_social_eur")) if cadastro.get("capital_social_eur") else "",
        "cae": _texto(cadastro.get("cae_principal")) or _texto(leve.get("cae_principal")),
        "fonte": _texto(leve.get("source")),
        "contratos_total": int(cadastro.get("contracts_total") or 0),
        "valor_total": cadastro.get("total_value") or 0,
        "valor_total_texto": euros_curto(cadastro.get("total_value")),
        "adjudicante": {
            "total": int(adjudicante.get("contracts_count") or 0),
            "valor": euros_curto(adjudicante.get("total_value")),
            "primeiro_ano": adjudicante.get("first_year"),
            "ultimo_ano": adjudicante.get("last_year"),
        },
        "adjudicatario": {
            "total": int(adjudicatario.get("contracts_count") or 0),
            "valor": euros_curto(adjudicatario.get("total_value")),
            "primeiro_ano": adjudicatario.get("first_year"),
            "ultimo_ano": adjudicatario.get("last_year"),
        },
        "contratos": _contratos_da_empresa(cadastro, codigo),
        "insolvencias": _cire_da_empresa(codigo),
        "noticias": _noticias_da_empresa(nome),
        "marcas": int(cadastro.get("trademarks_total") or 0),
        "firmas": int(cadastro.get("firmas_total") or 0),
    }


# --------------------------------------------------------------------------
# Ficha de um contrato
# --------------------------------------------------------------------------
def _cpv(cpv: Any) -> List[Dict[str, str]]:
    if isinstance(cpv, dict):
        cpv = [cpv]
    saida = []
    for item in cpv or []:
        if isinstance(item, dict) and item.get("code"):
            saida.append({"codigo": _texto(item.get("code")), "descricao": _texto(item.get("description"))})
        elif isinstance(item, str) and item.strip():
            saida.append({"codigo": item.strip(), "descricao": ""})
    return saida


def contrato(idcontrato: str) -> Optional[Dict[str, Any]]:
    """Tudo o que a ficha pública de um contrato mostra (ou `None`)."""
    codigo = str(idcontrato or "").strip()
    if not codigo:
        return None
    linha = get_contract_by_id(codigo)
    if not linha or linha.get("error"):
        if linha and linha.get("error") not in (None, "", "Contrato não encontrado"):
            logger.warning("Ficha pública: contrato %s falhou: %s", codigo, linha["error"])
        return None

    adjudicantes = _partes(linha.get("adjudicantes"))
    adjudicatarios = _partes(linha.get("adjudicatarios"))
    return {
        "id": codigo,
        "objeto": _texto(linha.get("objectoContrato") or linha.get("descContrato")) or "Contrato",
        "descricao": _texto(linha.get("descContrato")),
        "ano": linha.get("Ano"),
        "tipo": _texto(linha.get("tipoContrato")),
        "procedimento": _texto(linha.get("tipoprocedimento")),
        "regime": _texto(linha.get("regime")),
        "fundamentacao": _texto(linha.get("fundamentacao")),
        "preco": linha.get("precoContratual"),
        "preco_texto": euros(linha.get("precoContratual")),
        "preco_base": euros(linha.get("precoBaseProcedimento")) if linha.get("precoBaseProcedimento") else "",
        "preco_efetivo": euros(linha.get("PrecoTotalEfetivo")) if linha.get("PrecoTotalEfetivo") else "",
        "data_publicacao": data(linha.get("dataPublicacao")),
        "data_celebracao": data(linha.get("dataCelebracaoContrato")),
        "data_decisao": data(linha.get("dataDecisaoAdjudicacao")),
        "data_fecho": data(linha.get("dataFechoContrato")),
        "prazo": _dias(linha.get("prazoExecucao")),
        "local": _texto(linha.get("localExecucao")),
        "nuts": _texto(linha.get("NUTs")),
        "cpv": _cpv(linha.get("cpv")),
        "adjudicantes": adjudicantes,
        "adjudicatarios": adjudicatarios,
        "pmes": _texto(linha.get("adjudicatarioPMEs")),
        "ecologico": _texto(linha.get("ContratEcologico")),
        "centralizado": _texto(linha.get("ProcedimentoCentralizado")),
        "concorrentes": _texto(linha.get("concorrentes")),
        "pecas": str(linha.get("linkPecasProc") or ""),
    }
