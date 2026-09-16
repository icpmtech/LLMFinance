"""Teste end-to-end do enriquecimento (marcas INPI + firmas RNPC) numa empresa."""
import json
import sys

sys.path.insert(0, ".")

from api.elasticsearch_client import (  # noqa: E402
    FIRMAS_INDEX,
    TRADEMARKS_INDEX,
    ensure_indices,
    get_company_by_nif,
    get_company_firmas,
    get_company_trademarks,
    get_es_client,
    index_company_firmas,
    index_company_trademarks,
    search_companies,
)

es = get_es_client()
print("ES ok:", es is not None)
if not es:
    raise SystemExit("Elasticsearch indisponível")

ensure_indices(es)
print("índices:", {i: es.indices.exists(index=i) for i in (TRADEMARKS_INDEX, FIRMAS_INDEX)})

# Escolher uma empresa conhecida com muitos contratos
res = search_companies(size=5)
print("\nempresas de amostra:")
for c in res.get("items", [])[:5]:
    print(" -", c.get("nif"), c.get("name"), c.get("contracts_total"))

target = next((c for c in res.get("items", []) if c.get("nif")), None)
if not target:
    raise SystemExit("Sem empresas indexadas")

nif, name = target["nif"], target["name"]
print(f"\nalvo: {nif} | {name}")

company = get_company_by_nif(nif)
print("empresa:", company.get("name"))

# --- Marcas INPI ---
from collectors.inpi_marcas import InpiMarcasClient, search_trademarks_by_entity  # noqa: E402

client = InpiMarcasClient(min_interval=0.4)
tms = search_trademarks_by_entity(client, nome=name, nif=nif, intervencao="TIT", include_detail=True, max_results=5)
docs = [t.to_dict() for t in tms]
print(f"\nmarcas obtidas: {len(docs)}")
for d in docs[:3]:
    print(" -", d["nord"], d["mark_name"], "|", d["current_phase"], "|", d["nice_classes"])
r = index_company_trademarks(nif, name, docs, es=es)
print("indexação marcas:", {k: r.get(k) for k in ("indexed_count", "errors", "error")})

# --- Firmas RNPC ---
from collectors.pns_firmas import fetch_firmas_for_company  # noqa: E402

data = fetch_firmas_for_company(name, include_detail=True, max_results=5)
firmas = data.get("firmas", [])
print(f"\nfirmas obtidas: {len(firmas)}")
for f in firmas[:3]:
    print(" -", f["nipc"], f["nome"], "|", f["concelho_sede"], "|", f["cae_principal"], "|", f["score"])
r2 = index_company_firmas(nif, name, firmas, es=es)
print("indexação firmas:", {k: r2.get(k) for k in ("indexed_count", "errors", "error")})

# --- Ler de volta ---
es.indices.refresh(index=[TRADEMARKS_INDEX, FIRMAS_INDEX])
back_tm = get_company_trademarks(company_nif=nif, es=es)
back_fi = get_company_firmas(company_nif=nif, es=es)
print(f"\nleitura marcas na ficha de {nif}: total={back_tm.get('total')}")
for it in back_tm.get("items", [])[:3]:
    print("  *", it.get("mark_name"), it.get("company_nif"))
print(f"leitura firmas na ficha de {nif}: total={back_fi.get('total')}")
for it in back_fi.get("items", [])[:3]:
    print("  *", it.get("nome"), it.get("nipc"))
