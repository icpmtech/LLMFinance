"""Teste do backend CIRE: recolha para JSON, importação para o Elasticsearch e pesquisa."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import cire_service  # noqa: E402


def main() -> None:
    print("=== meta ===")
    m = cire_service.meta()
    print("fonte:", m["source_label"])
    print("índice:", m["index"], "| página:", m["page_size"], "docs | pasta:", m["storage"])
    print("grupos:", [g["label"] for g in m["grupos_actos"]])

    print("\n=== recolha (1 dia, 2 páginas) ===")
    res = cire_service.collect(
        desde="2026-09-23", ate="2026-09-23", max_pages=2, min_interval=1.0,
        on_progress=lambda info: print("  progresso:", {k: v for k, v in info.items() if k != "window"}),
    )
    meta_info = res["meta"]
    print("run_id:", res["run_id"])
    print("ficheiro:", meta_info["file"])
    print("meta:", meta_info["meta_file"])
    print("itens:", meta_info["collected"], "| páginas:", meta_info["pages"],
          "| declarado:", meta_info["declared_total"], "| erros:", meta_info["errors"])

    path = Path(meta_info["file"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    print("JSON em disco:", path.exists(), "| itens no JSON:", len(payload["items"]))
    primeiro = payload["items"][0]
    print("1.º item:", primeiro["referencia"], "|", primeiro["tribunal"], "|", primeiro["data_publicacao"])
    print("   intervenientes:", [f"{i['papel']}={i['nome']}" for i in primeiro["intervenientes"]][:3])

    print("\n=== importação para o Elasticsearch ===")
    ing = cire_service.ingest_run(res["run_id"])
    print("resultado:", {k: v for k, v in ing.items() if k != "errors"})

    print("\n=== pesquisa no índice ===")
    s = cire_service.search(size=5)
    print("total:", s.get("total"), "| itens:", len(s.get("items", [])))
    if s.get("items"):
        it = s["items"][0]
        print("exemplo:", it.get("referencia"), "|", it.get("tribunal"), "|", it.get("tipo"))
    print("facetas:", {k: v[:3] for k, v in (s.get("facets") or {}).items() if v})

    nif_exemplo = primeiro["nifs"][0] if primeiro.get("nifs") else None
    if nif_exemplo:
        por_nif = cire_service.search(nif=nif_exemplo, size=5)
        print(f"\npesquisa por NIF {nif_exemplo}: total={por_nif.get('total')}")
    texto = primeiro.get("insolvente") or ""
    if texto:
        por_texto = cire_service.search(q=texto, size=5)
        print(f"pesquisa por texto «{texto}»: total={por_texto.get('total')}")

    print("\n=== estado do índice ===")
    st = cire_service.status()
    print({k: st.get(k) for k in ("documents", "nifs", "referencias", "min_date", "max_date", "with_documento")})
    print("tipos:", st.get("by_tipo"))
    print("comarcas:", (st.get("top_comarcas") or [])[:3])

    print("\n=== recolhas em disco ===")
    for r in cire_service.runs_with_index_counts(limit=5):
        print(f"  {r['run_id']}: {r.get('collected')} recolhidos, {r.get('index_count')} no índice, "
              f"{r.get('criteria')}")


if __name__ == "__main__":
    main()
