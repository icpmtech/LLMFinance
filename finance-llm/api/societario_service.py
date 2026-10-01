"""Serviço do módulo de publicações de atos societários (Ministério da Justiça).

Junta o coletor (`collectors/publicacoes_mj.py`) ao índice Elasticsearch
(`finance_publicacoes_mj`): normaliza o que é recolhido, indexa e pesquisa.

A recolha pode ser **assistida** (pessoa resolve o captcha) ou **automática**
com o 2captcha (variável ``TWOCAPTCHA_API_KEY``). Além de critérios simples,
o serviço consegue iterar pelas **entidades indexadas** no ``finance_entities``
e recolher as publicações de cada NIF.

As publicações de um NIF relembram-se ao ritmo que se quiser; reingestões são
idempotentes (o ``_id`` é derivado de NIF + data + acto).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from collectors.publicacoes_mj import (
    DETALHE_PAGE,
    DISTRITOS,
    PAGE,
    RECAPTCHA_SITEKEY,
    TIPOS_PUBLICACAO,
    CaptchaRequiredError,
    PublicacoesMjClient,
)

logger = logging.getLogger(__name__)

# O formulário do portal só aceita intervalos de datas até 10 dias.
MAX_DATE_RANGE_DAYS = 10


def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para os clientes da API)."""
    return {
        "module": "societario",
        "source": "publicacoes.mj.pt",
        "source_label": "Publicações de Atos Societários (Ministério da Justiça)",
        "index": "finance_publicacoes_mj",
        "search_page": PAGE,
        "detalhe_page": DETALHE_PAGE,
        "recaptcha_sitekey": RECAPTCHA_SITEKEY,
        "captcha_required": True,
        "assisted": True,
        "max_date_range_days": MAX_DATE_RANGE_DAYS,
        "page_size": 20,
        "tipos_publicacao": [{"value": k, "label": v} for k, v in TIPOS_PUBLICACAO.items()],
        "distritos": [{"value": k, "label": v} for k, v in DISTRITOS.items()],
        "notes": (
            "A pesquisa do portal exige reCAPTCHA v2 (validado no servidor); a recolha é "
            "assistida. Depois de uma pesquisa validada, a paginação e o detalhe são "
            "recolhidos automaticamente e indexados em `finance_publicacoes_mj`. "
            "O intervalo de datas está limitado a 10 dias pelo próprio portal."
        ),
    }


def validate_date_range(data_ini: Optional[str], data_fim: Optional[str]) -> None:
    """Valida o intervalo de datas (máx. 10 dias, como no portal)."""
    if not data_ini and not data_fim:
        return
    if bool(data_ini) != bool(data_fim):
        raise ValueError("Indique as duas datas (início e fim) ou nenhuma.")
    try:
        start = datetime.strptime(data_ini or "", "%Y-%m-%d").date()  # type: ignore[arg-type]
        end = datetime.strptime(data_fim or "", "%Y-%m-%d").date()  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError("Datas inválidas: use o formato AAAA-MM-DD.") from exc
    if end < start:
        raise ValueError("A data final não pode ser anterior à inicial.")
    if (end - start).days > MAX_DATE_RANGE_DAYS:
        raise ValueError(f"O portal limita a pesquisa a {MAX_DATE_RANGE_DAYS} dias de intervalo.")


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normaliza os documentos antes da indexação (rótulo do tipo, NIF e data)."""
    normalized: List[Dict[str, Any]] = []
    for item in items:
        doc = dict(item)
        if not doc.get("pub_id"):
            continue
        if doc.get("nif") is not None:
            doc["nif"] = str(doc["nif"]).strip() or None
        tipo = doc.get("tipo")
        if tipo is not None:
            doc["tipo"] = str(tipo)
            doc["tipo_label"] = TIPOS_PUBLICACAO.get(str(tipo))
        data = doc.get("data_publicacao")
        if data:
            doc["data_publicacao"] = normalize_date(data)
        normalized.append({k: v for k, v in doc.items() if v is not None})
    return normalized


def normalize_date(value: str) -> Optional[str]:
    """Aceita ``AAAA-MM-DD`` e ``DD/MM/AAAA`` e devolve ISO 8601."""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value or None


def ingest(
    items: List[Dict[str, Any]],
    replace_for_nif: Optional[str] = None,
    drop_stale: bool = True,
) -> Dict[str, Any]:
    """Indexa publicações recolhidas no índice societário.

    Alimenta também o PessoasIQ: as pessoas/cargos extraídos das publicações
    passam a existir no índice `finance_people`, para que as fichas abertas a
    partir do dossiê da empresa não dependam de uma segunda ação manual.

    ``drop_stale`` só deve ser ``True`` quando a recolha abrange **todas** as
    publicações da entidade (sem janela de datas).
    """
    from api.elasticsearch_client import index_people_from_societario, index_societario_items

    docs = normalize_items(items)
    result = index_societario_items(docs, replace_for_nif=replace_for_nif, drop_stale=drop_stale)
    result["received"] = len(items)
    if result.get("error"):
        return result

    nifs = {str(d.get("nif")) for d in docs if d.get("nif")}
    target = replace_for_nif or (next(iter(nifs)) if len(nifs) == 1 else None)
    people = index_people_from_societario(nif=target, replace_for_nif=target)
    result["people"] = {
        "indexed_count": people.get("indexed_count", 0),
        "total": people.get("total", 0),
        "errors": people.get("errors", 0),
        "error": people.get("error"),
    }
    return result


def collect(
    *,
    nif: Optional[str] = None,
    entidade: Optional[str] = None,
    tipo: str = "0",
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    data_ini: Optional[str] = None,
    data_fim: Optional[str] = None,
    recaptcha_token: Optional[str] = None,
    result_html: Optional[str] = None,
    cookies: Optional[Dict[str, str]] = None,
    with_details: bool = True,
    max_pages: int = 50,
    min_interval: float = 1.0,
    ingest_result: bool = True,
) -> Dict[str, Any]:
    """Recolhe as publicações de um critério e (por omissão) indexa-as.

    Precisa de ``recaptcha_token`` **ou** de ``result_html`` (a página de
    resultados já pesquisada no browser, com os ``cookies`` da sessão).
    """
    if not nif and not entidade and not distrito and not concelho and not data_ini:
        raise ValueError("Indique pelo menos um critério (NIF, entidade, sede ou data).")
    if not recaptcha_token and not result_html:
        raise ValueError("A pesquisa do portal exige reCAPTCHA: indique `recaptcha_token` ou `result_html`.")
    validate_date_range(data_ini, data_fim)
    if nif:
        nif = str(nif).strip()

    criteria: Dict[str, Any] = {
        "nif": nif,
        "entidade": entidade,
        "tipo": str(tipo or "0"),
        "distrito": distrito,
        "concelho": concelho,
        "data_ini": data_ini,
        "data_fim": data_fim,
    }
    client = PublicacoesMjClient(cookies=cookies, min_interval=min_interval)

    declared_total = 0
    pages = 0
    try:
        if result_html is not None:
            declared_total = client.result_range(result_html).get("total", 0)
        publications = client.collect(
            recaptcha_token=recaptcha_token,
            result_html=result_html,
            with_details=with_details,
            max_pages=max_pages,
            **criteria,
        )
    except CaptchaRequiredError:
        raise

    items = [pub.to_dict() for pub in publications]
    pages = (len(items) + 19) // 20
    out: Dict[str, Any] = {
        "criteria": {k: v for k, v in criteria.items() if v},
        "collected": len(items),
        "pages": pages,
        "declared_total": declared_total,
        "with_details": with_details,
        "items": items,
    }
    if ingest_result and items:
        out["ingest"] = ingest(items, replace_for_nif=nif, drop_stale=not bool(data_ini and data_fim))
    return out


def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa publicações indexadas (delega no cliente Elasticsearch)."""
    from api.elasticsearch_client import search_societario

    return search_societario(**kwargs)


def company_publicacoes(nif: str, size: int = 100, from_: int = 0) -> Dict[str, Any]:
    """Publicações de uma entidade (por NIF)."""
    from api.elasticsearch_client import company_publicacoes as _company_publicacoes

    return _company_publicacoes(nif, size=size, from_=from_)


def company_people(nif: str) -> Dict[str, Any]:
    """Pessoas/cargos extraídos das publicações societárias de uma entidade.

    Não indexa — apenas devolve os registos agregados para apresentação.
    """
    from api.elasticsearch_client import company_publicacoes as _company_publicacoes
    from collectors.people_extractor import extract_from_publicacoes

    pubs = _company_publicacoes(nif, size=1000)
    if pubs.get("error"):
        return pubs
    items = pubs.get("items", [])
    if not items:
        return {"nif": nif, "total": 0, "people": []}
    people = extract_from_publicacoes(items)
    return {"nif": nif, "total": len(people), "people": people}


def status() -> Dict[str, Any]:
    """Volumetria do índice societário."""
    from api.elasticsearch_client import societario_status

    return societario_status()


def targets(limit: int = 50, from_: int = 0, min_contracts: int = 1, exclude_collected: bool = True) -> Dict[str, Any]:
    """Entidades com contratos no Portal BASE — os alvos da recolha assistida."""
    from api.elasticsearch_client import societario_targets

    return societario_targets(
        limit=limit, from_=from_, min_contracts=min_contracts, exclude_collected=exclude_collected
    )


def today() -> str:
    """Data de hoje em ISO 8601 (apoio a testes e relatórios)."""
    return date.today().isoformat()


# --- recolha automática por entidades indexadas ------------------------


def _janelas(desde: str, ate: str, dias: int = 10) -> List[Tuple[str, str]]:
    """Divide um intervalo em janelas de até ``dias`` (limite do portal).

    As datas são devolvidas no formato ``DD/MM/AAAA`` exigido pelo formulário
    do portal. O input continua a ser ISO 8601 (``AAAA-MM-DD``).
    """
    inicio = datetime.strptime(desde, "%Y-%m-%d").date()
    fim = datetime.strptime(ate, "%Y-%m-%d").date()
    if fim < inicio:
        raise ValueError("A data final não pode ser anterior à inicial.")
    passo = timedelta(days=dias - 1)
    out: List[Tuple[str, str]] = []
    atual = inicio
    while atual <= fim:
        ultimo = min(atual + passo, fim)
        out.append((atual.strftime("%d/%m/%Y"), ultimo.strftime("%d/%m/%Y")))
        atual = ultimo + timedelta(days=1)
    return out


def _as_portal_date(value: Optional[str]) -> Optional[str]:
    """Converte uma data ISO 8601 para o formato ``DD/MM/AAAA`` do portal."""
    if not value:
        return value
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date().strftime("%d/%m/%Y")
    except ValueError:
        return value


def _list_entities_to_collect(
    *,
    limit: Optional[int] = None,
    min_contracts: int = 1,
    exclude_collected: bool = True,
    nifs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Lista entidades do índice ``finance_entities`` elegíveis para recolha."""
    from api.elasticsearch_client import get_es_client, societario_targets

    if nifs:
        client = get_es_client()
        if not client:
            return []
        # Pesquisa direta pelos NIFs indicados.
        resp = client.search(
            index="finance_entities",
            body={
                "size": len(nifs),
                "query": {"terms": {"nif": nifs}},
                "_source": ["nif", "name", "country_code", "contracts_count"],
            },
        )
        items = [h["_source"] for h in resp["hits"]["hits"] if h["_source"].get("nif")]
    else:
        targets = societario_targets(
            limit=limit or 200,
            from_=0,
            min_contracts=min_contracts,
            exclude_collected=exclude_collected,
        )
        items = targets.get("items", [])

    # Normaliza o nome: o coletor pesquisa por NIF, mas guarda também a designação.
    for item in items:
        item["nif"] = str(item.get("nif")).strip()
        item["name"] = (item.get("name") or "").strip() or None
    return [it for it in items if it["nif"]]


def collect_entities(
    *,
    api_key: Optional[str] = None,
    nifs: Optional[List[str]] = None,
    limit: Optional[int] = None,
    min_contracts: int = 1,
    exclude_collected: bool = True,
    data_ini: Optional[str] = None,
    data_fim: Optional[str] = None,
    tipo: str = "0",
    with_details: bool = True,
    max_pages: int = 50,
    min_interval: float = 1.0,
    recaptcha_timeout: int = 180,
    ingest_result: bool = True,
    stop_on_captcha: bool = False,
    proxy: Optional[str] = None,
    debug: bool = False,
) -> Dict[str, Any]:
    """Recolhe publicações do MJ para um conjunto de entidades indexadas.

    A resolução do reCAPTCHA é feita automaticamente via 2captcha
    (``TWOCAPTCHA_API_KEY`` ou ``api_key``). Cada entidade é pesquisada por NIF;
    se forem indicadas ``data_ini``/``data_fim``, o NIF é combinado com janelas
    temporais de 10 dias.
    """
    from collectors.publicacoes_mj_captcha import PublicacoesMjCaptchaClient

    entities = _list_entities_to_collect(
        limit=limit,
        min_contracts=min_contracts,
        exclude_collected=exclude_collected,
        nifs=nifs,
    )
    if not entities:
        return {"entities": 0, "collected": 0, "items": [], "errors": [], "message": "Nenhuma entidade elegível."}

    client = PublicacoesMjCaptchaClient(
        api_key=api_key,
        min_interval=min_interval,
        recaptcha_timeout=recaptcha_timeout,
        proxy=proxy,
        debug=debug,
    )

    windows: List[Tuple[str, str]] = [(None, None)]
    if data_ini and data_fim:
        windows = _janelas(data_ini, data_fim, MAX_DATE_RANGE_DAYS)

    all_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    total_collected = 0
    total_ingested = 0
    total_stale = 0

    for entity in entities:
        nif = entity["nif"]
        name = entity.get("name")
        for window in windows:
            criteria: Dict[str, Any] = {
                "nif": nif,
                "tipo": str(tipo or "0"),
            }
            if window[0] and window[1]:
                criteria["data_ini"] = window[0]
                criteria["data_fim"] = window[1]

            # O coletor espera datas no formato do portal.
            display_criteria = dict(criteria)
            display_criteria["data_ini"] = _as_portal_date(display_criteria.get("data_ini"))
            display_criteria["data_fim"] = _as_portal_date(display_criteria.get("data_fim"))

            logger.info("A recolher publicações MJ para %s (%s)", nif, name or "sem nome")
            try:
                publications = client.collect(
                    with_details=with_details,
                    max_pages=max_pages,
                    **display_criteria,
                )
            except CaptchaRequiredError as exc:
                logger.warning("Captcha rejeitado para %s: %s", nif, exc)
                errors.append({"nif": nif, "name": name, "error": str(exc)})
                if stop_on_captcha:
                    break
                continue
            except Exception as exc:
                logger.exception("Falha na recolha para %s", nif)
                errors.append({"nif": nif, "name": name, "error": str(exc)})
                continue

            items = [pub.to_dict() for pub in publications]
            total_collected += len(items)

            if ingest_result and items:
                result = ingest(items, replace_for_nif=nif, drop_stale=not bool(data_ini and data_fim))
                total_ingested += result.get("indexed_count", 0)
                total_stale += result.get("deleted_stale", 0)

            all_items.extend(items)

    return {
        "entities": len(entities),
        "collected": total_collected,
        "ingested": total_ingested,
        "deleted_stale": total_stale,
        "with_details": with_details,
        "items": all_items,
        "errors": errors,
    }
