"""Cliente, constantes de ambiente e utilitários partilhados do Elasticsearch.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Pesquisa por texto: exigir **todos** os termos
# ---------------------------------------------------------------------------
# Um `multi_match` sem `operator` faz OR entre os termos, o que dá números
# absurdos na Pesquisa total: «COVID-19» casava qualquer contrato com «19» no
# número (33 972 resultados falsos) e «obras públicas» casava 2,2 milhões. Aqui os
# termos passam a ter de coexistir; quando isso não devolve nada, a pesquisa é
# repetida em OR para não perder resultados legítimos com vocabulário disperso.


def _search_terms(q: Optional[str]) -> List[str]:
    """Termos com pelo menos dois caracteres (o resto é pontuação: «COVID-19» → covid, 19)."""
    return [term for term in re.split(r"[\s\-_/,.;:]+", str(q or "").strip()) if len(term) >= 2]




def _is_multi_term(q: Optional[str]) -> bool:
    return len(_search_terms(q)) > 1




def _apply_text_operator(node: Any, operator: str) -> Any:
    """Aplica `operator` a todos os `multi_match` da query, em profundidade."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "multi_match" and isinstance(value, dict):
                value["operator"] = operator
            else:
                _apply_text_operator(value, operator)
    elif isinstance(node, list):
        for item in node:
            _apply_text_operator(item, operator)
    return node




def _text_search(
    client: Elasticsearch,
    *,
    index: str,
    body: Dict[str, Any],
    q: Optional[str],
    fallback_or: bool = True,
) -> Dict[str, Any]:
    """Executa a pesquisa exigindo todos os termos; repete em OR se não houver nada.

    A segunda tentativa só acontece quando a primeira devolve **zero** — é o
    compromisso entre precisão (não devolver 2 milhões por causa de uma palavra)
    e cobertura (não devolver zero quando os termos existem mas dispersos).
    Com `fallback_or=False` a pesquisa fica só nos termos todos: é o que a
    pesquisa pública do site quer, para um termo sem sentido não devolver mil
    resultados que casam uma palavra solta.
    """
    if not _is_multi_term(q):
        return client.search(index=index, body=body)
    strict = _apply_text_operator(json.loads(json.dumps(body)), "and")
    response = client.search(index=index, body=strict)
    hits = response.get("hits") or {}
    total = hits.get("total") or 0
    total = total.get("value", 0) if isinstance(total, dict) else total
    if total or not fallback_or:
        return response
    return client.search(index=index, body=_apply_text_operator(json.loads(json.dumps(body)), "or"))




ROOT = Path(__file__).resolve().parents[2]  # raiz de `finance-llm`



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




def _today() -> str:
    return datetime.utcnow().isoformat()




def _slug(value: Any) -> str:
    """Texto simples para compor identificadores (sem acentos, só minúsculas e hífenes)."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60] or "sem-tema"




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




def _and_filters(query: Dict[str, Any], extra: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Acrescenta filtros `filter` a uma query já construída."""
    if not extra:
        return query
    return {"bool": {"must": [query], "filter": extra}}




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




def _unescape_label(value: Any) -> str:
    """Desfaz entidades HTML nos nomes publicados («SANTOS &amp; FILHOS» → «& FILHOS»).

    Os feeds do portal base e do PLACSP trazem o `&` escapado em nomes de
    entidades; sem isto a ficha da região mostrava `&amp;`.
    """
    text = str(value or "")
    for source, target in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(source, target)
    return text




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




def _safe_slug(slug: str) -> str:
    """Normaliza o slug para poder ser usado no nome de um índice."""
    limpo = re.sub(r"[^a-z0-9]+", "_", str(slug or "").strip().lower()).strip("_")
    return limpo[:60]
