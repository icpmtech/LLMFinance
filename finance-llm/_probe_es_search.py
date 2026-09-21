"""Sonda: valida filtros e ordenação da pesquisa de contratos de Espanha."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import elasticsearch_client as esc  # noqa: E402


def show(label, **kw):
    r = esc.search_contratos_es(with_facets=False, size=0, **kw)
    print(f"{label:<28} total={r.get('total')}  err={r.get('error')}")


show("tudo")
show("ano 2023", ano=2023)
show("fonte licitaciones", fonte="licitaciones")
show("tipo Obras (3)", tipo="3")
show("estado Resuelta", estado="Resuelta")
show("cpv prefixo 45", cpv_code="45")
show("valor 1M-10M", min_value=1000000, max_value=10000000)
show("texto megafonia", q="megafonia")
show("organo Alzira", organo="Ayuntamiento de Alzira")
show("nif B98411234", adjudicatario_nif="B98411234")
show("datas 2023", start_date="2023-01-01", end_date="2023-12-31")

r = esc.search_contratos_es(sort_by="valor_adjudicado", sort_order="desc", size=3, with_facets=False)
print("top valores:", [(i["id_expediente"], i.get("valor_adjudicado")) for i in r["items"]])
r = esc.search_contratos_es(sort_by="fecha_publicacion", sort_order="asc", size=2, with_facets=False)
print("mais antigos:", [(i.get("fecha_publicacion"), i["fonte"]) for i in r["items"]])
r = esc.search_contratos_es(ano=2023, with_facets=True, size=1)
print("faceta fonte:", r["facets"]["fonte"])
print("faceta tipo:", r["facets"]["tipo"][:4])
print("faceta cpv:", r["facets"]["cpv"][:3])
print("faceta organo:", [b["value"][:40] for b in r["facets"]["organo"][:3]])
