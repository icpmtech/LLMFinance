"""Distritos e regiões de Portugal (normalização para filtros geográficos).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional
from api.es.core import _fold_text, _strip_accents, is_unspecified

logger = logging.getLogger(__name__)




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
