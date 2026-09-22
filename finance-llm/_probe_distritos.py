"""Sonda: filtro por distrito vs. agregado do mapa (duas grafias no portal)."""
from api.elasticsearch_client import get_contracts_iberia_map, get_entity_role_summary, search_contracts

for distrito in ["Bragança", "Braganca", "Setúbal", "Setubal", "Viana do Castelo", "Região Autónoma dos Açores", "Lisboa"]:
    total = search_contracts(region=distrito, size=1).get("total")
    print("%-32s -> %s" % (distrito.encode("ascii", "replace").decode(), total))

resumo = get_entity_role_summary(role="all", region="Bragança", top_n=5)
print(
    "Bragança summary: contratos=%s valor=%s uniq_adjudicantes=%s uniq_adjudicatarios=%s"
    % (
        resumo.get("total_contracts"),
        round(resumo.get("total_value") or 0),
        resumo.get("unique_adjudicantes"),
        resumo.get("unique_adjudicatarios"),
    )
)
print("top:", [(e["name"][:40], e["contracts_total"]) for e in resumo.get("top_entities", [])])

mapa = get_contracts_iberia_map(pais="pt")
print(
    "mapa:",
    [
        (r["code"].encode("ascii", "replace").decode(), r["count"])
        for r in mapa["regions"]
        if "Bragan" in r["code"] or "Set" in r["code"]
    ],
)
