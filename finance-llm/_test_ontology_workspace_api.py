"""Teste ponta-a-ponta (dev) da área de trabalho da ontologia.

Cria uma conta de QA, uma ontologia nova, liga uma fonte (índice real de
contratos), gera o tipo de objeto a partir dos campos reais, consulta objetos,
cria projeto e ficha, gera factos/redação e explora o grafo.

Uso: python _test_ontology_workspace_api.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

import httpx

BASE = "http://127.0.0.1:8002"
STAMP = datetime.now().strftime("%H%M%S")


def show(title: str, payload: object, limit: int = 600) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    print(f"\n=== {title} ===")
    print(text[:limit] + ("…" if len(text) > limit else ""))


def main() -> int:
    with httpx.Client(timeout=60.0) as client:
        email = f"qa.ontologia.{STAMP}@iqos.dev"
        response = client.post(
            f"{BASE}/auth/register",
            json={"name": "QA Ontologia", "email": email, "password": "QaOntologia!2026", "title": "QA", "organization": "IQ OS"},
        )
        if response.status_code >= 400:
            print("registo falhou:", response.status_code, response.text[:200])
            return 1
        session = response.json()
        token = session["token"]
        headers = {"authorization": f"Bearer {token}"}
        print("sessão:", session["user"]["email"], "| papel:", session["user"]["role"])

        # 1. catálogo e criação de ontologia
        show("ontologias (antes)", client.get(f"{BASE}/ontology/ontologies").json(), 300)
        created = client.post(
            f"{BASE}/ontology/ontologies",
            headers=headers,
            json={"name": f"Energia {STAMP}", "description": "Contratos de energia: fontes, tipos e fichas.", "accent": "16,185,129"},
        )
        if created.status_code >= 400:
            print("criar ontologia falhou:", created.status_code, created.text[:300])
            return 1
        ontologia = created.json()["ontology"]
        oid = ontologia["id"]
        print("ontologia criada:", oid, "|", ontologia["name"])

        # 2. fonte nova (índice real) + diagnóstico
        source = client.post(
            f"{BASE}/ontology/sources",
            params={"ontology": oid},
            headers=headers,
            json={
                "id": "contratos",
                "kind": "elasticsearch",
                "label": "Contratos do portal base",
                "description": "Contratos públicos com partes, valores e CPV.",
                "index": "contratos",
            },
        )
        if source.status_code >= 400:
            print("fonte falhou:", source.status_code, source.text[:300])
            return 1
        show("fonte criada", source.json()["source"], 260)

        probe = client.post(f"{BASE}/ontology/sources/contratos/probe", params={"ontology": oid}, headers=headers).json()
        diagnostic = probe["diagnostic"]
        print("diagnóstico:", diagnostic.get("state"), "| documentos:", diagnostic.get("documents"), "| campos:", len(diagnostic.get("fields") or []))
        for field in (diagnostic.get("fields") or [])[:12]:
            print(f"   {field['name']:38} {field['type']:8} {'(nested)' if field.get('nested') else ''}")

        # 3. tipo de objeto gerado a partir da fonte (aplicado)
        inferred = client.post(
            f"{BASE}/ontology/sources/contratos/infer",
            params={"ontology": oid},
            headers=headers,
            json={"id": "contrato_energia", "label": "Contrato de energia", "domain": "energia", "apply": True},
        )
        if inferred.status_code >= 400:
            print("inferir falhou:", inferred.status_code, inferred.text[:300])
            return 1
        tipo = inferred.json()["applied"]["object_type"]
        print("tipo criado:", tipo["id"], "| pk:", tipo["primary_key"], "| título:", tipo["title_field"], "| propriedades:", len(tipo["properties"]))

        # 4. consulta real de objetos no tipo novo
        query = client.post(
            f"{BASE}/ontology/objects/{tipo['id']}/query",
            params={"ontology": oid},
            json={"size": 3, "search": None},
        )
        print("consulta:", query.status_code)
        if query.status_code == 200:
            payload = query.json()
            print("total:", payload.get("total"), "| itens:", len(payload.get("items") or []))
            for item in (payload.get("items") or [])[:2]:
                print("   -", str(item.get("_label"))[:90])

        # 5. IA: desenho (sem modelo configurado → inferência dos dados) e sugestões de ligação
        design = client.post(
            f"{BASE}/ontology/ai/design",
            params={"ontology": oid},
            headers=headers,
            json={"description": "Quero analisar contratos de energia por entidade pública e por região.", "source_ids": ["contratos"], "domain": "energia"},
        )
        print("\ndesenho:", design.status_code)
        if design.status_code == 200:
            result = design.json()
            print("modo:", result.get("mode"), "| backend:", result.get("backend"))
            print("totais:", result.get("totals"), "| avisos:", result.get("warnings")[:2])
            print("notas:", result.get("notes")[:2])
            print("preview:", result.get("preview"))

        links = client.post(
            f"{BASE}/ontology/ai/suggest-links",
            headers=headers,
            json={},
        )
        print("\nligações sugeridas (ontologia base):", links.status_code)
        if links.status_code == 200:
            payload = links.json()
            print("totais:", payload.get("totals"), "| notas:", payload.get("notes")[:1])
            for link in (payload.get("link_types") or [])[:6]:
                print("   -", link["from"], "->", link["to"], "|", link.get("label", "")[:50])

        # 6. projeto + ficha + factos + redação
        project = client.post(
            f"{BASE}/ontology/projects",
            params={"ontology": oid},
            headers=headers,
            json={
                "name": "Transição energética",
                "description": "Projeto de análise de contratos de energia.",
                "source_ids": ["contratos"],
                "type_ids": [tipo["id"]],
                "tags": ["energia", "contratos"],
                "accent": "16,185,129",
            },
        )
        print("\nprojeto:", project.status_code)
        if project.status_code >= 400:
            print(project.text[:300])
            return 1
        pobj = project.json()["project"]
        print("projeto:", pobj["id"], "|", pobj["name"])

        first = None
        if query.status_code == 200 and (query.json().get("items") or []):
            first = query.json()["items"][0]
        dossier = client.post(
            f"{BASE}/ontology/dossiers",
            params={"ontology": oid},
            headers=headers,
            json={
                "title": "Ficha de contrato de energia",
                "project_id": pobj["id"],
                "summary": "Análise do contrato selecionado.",
                "subject": {"type_id": tipo["id"], "object_id": str((first or {}).get("_id") or "")} if first else None,
                "sections": [{"id": "resumo", "title": "Resumo executivo", "kind": "text", "content": ""}],
                "tags": ["energia"],
            },
        )
        print("ficha:", dossier.status_code, dossier.text[:160] if dossier.status_code >= 400 else "")
        dobj = dossier.json()["dossier"]

        if first:
            facts = client.post(f"{BASE}/ontology/dossiers/{dobj['id']}/facts", params={"ontology": oid}, headers=headers)
            print("factos:", facts.status_code)
            if facts.status_code == 200:
                data = facts.json()
                print("relações:", [(group["label"], group["total"]) for group in data["links"]][:4])
                print("amostra de factos:", data["facts"][:4])
            draft = client.post(
                f"{BASE}/ontology/dossiers/{dobj['id']}/draft",
                params={"ontology": oid},
                headers=headers,
                json={"section": "Resumo executivo", "apply": True},
            )
            print("redação:", draft.status_code)
            if draft.status_code == 200:
                result = draft.json()
                print("modo:", result.get("mode"), "| backend:", result.get("backend"), "| secções gravadas:", len((result.get("dossier") or {}).get("sections") or []))
                print("texto:", (result.get("text") or "")[:400])

        # 7. grafo de exploração sobre a ontologia base (dados reais)
        print("\n=== grafo de exploração ===")
        resposta = client.post(f"{BASE}/ontology/graph/explore", json={"type_id": "empresa", "object_id": "500000000", "depth": 2, "node_limit": 25, "links_per_object": 3})
        if resposta.status_code >= 400:
            print("grafo:", resposta.status_code, resposta.text[:200])
        else:
            grafo = resposta.json()
            print("nós:", grafo["stats"]["nodes"], "| arestas:", grafo["stats"]["edges"], "| profundidade:", grafo["stats"]["depth_reached"])
            print("amostra:", [(node["type_id"], node["label"][:28]) for node in grafo["nodes"][:6]])
            print("avisos:", grafo["warnings"][:3])

        # 8. listagens finais
        show("fontes", client.get(f"{BASE}/ontology/sources", params={"ontology": oid}).json(), 400)
        show("projetos", client.get(f"{BASE}/ontology/projects", params={"ontology": oid}).json(), 350)
        show("resumo", client.get(f"{BASE}/ontology/summary", params={"ontology": oid}).json(), 420)
        print("\nemail de QA:", email)
    return 0


if __name__ == "__main__":
    sys.exit(main())
