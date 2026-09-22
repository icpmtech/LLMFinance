"""Sonda: identificadores das entidades na ficha de região (para abrir fichas)."""
from api.elasticsearch_client import get_contract_region_detail

for pais, code, ano in (("ES", "ES300", 2023), ("PT", "Bragança", 2023)):
    res = get_contract_region_detail(pais=pais, code=code, ano=ano, top_n=4)
    print("=" * 72)
    print(pais, code, ano, "erro:", res.get("error"))
    for kind in ("awarders", "suppliers"):
        rows = res.get(kind) or []
        print(" ", kind)
        for row in rows[:4]:
            print(
                "   ",
                str(row.get("nif")),
                "|",
                (row.get("name") or "")[:46].encode("ascii", "replace").decode(),
                "|",
                row.get("count"),
            )
