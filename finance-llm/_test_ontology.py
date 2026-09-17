"""Teste manual da camada de ontologia contra o Elasticsearch real.

Correr:  python _test_ontology.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ontology_registry as registry  # noqa: E402
from api import ontology_service as onto  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    es = get_es_client()
    print("Elasticsearch:", "OK" if es else "INDISPONÍVEL")

    section("Registo")
    ontology = registry.load_ontology()
    print("tipos:", len(ontology["object_types"]), "ligações:", len(ontology["link_types"]), "ações:", len(ontology["actions"]))
    for obj in ontology["object_types"]:
        print(f"  - {obj['id']:20s} {obj['label']:24s} dominio={obj['domain']:12s} binds={obj['binding']['kind']:12s} props={len(obj.get('properties', []))}")
    print("ficheiro:", registry.ONTOLOGY_PATH, registry.ONTOLOGY_PATH.exists())

    section("Consulta por tipo")
    for type_id in [obj["id"] for obj in ontology["object_types"]]:
        started = time.time()
        try:
            res = onto.query_objects(type_id, size=2, es=es)
            elapsed = (time.time() - started) * 1000
            first = res["items"][0] if res["items"] else None
            summary = json.dumps(first, ensure_ascii=False, default=str)[:220] if first else "-"
            print(f"  {type_id:20s} total={res['total']:<8} erro={res.get('error', '-'):<24} {elapsed:6.0f}ms  {summary}")
        except Exception as exc:
            print(f"  {type_id:20s} EXCEÇÃO: {type(exc).__name__}: {exc}")

    section("Objeto individual")
    for type_id, object_id in [("contrato", None), ("ticker", "EDP.LS")]:
        if type_id == "contrato":
            found = onto.query_objects("contrato", size=1, es=es)
            object_id = (found["items"][0]["_id"] if found["items"] else None)
        if not object_id:
            print(f"  {type_id}: sem amostra")
            continue
        detail = onto.get_object(type_id, object_id, es=es, with_links=True)
        links = detail.get("links", {}).get("links", [])
        print(f"  {type_id}/{object_id}: found={detail['found']} label={detail.get('object', {}).get('_label')!r} ligações={len(links)}")
        for link in links:
            print(f"      {link['direction']:8s} {link['id']:28s} -> {link['other_label']:22s} itens={len(link.get('items', []))} {link.get('notes') or ''}")

    section("Resolução de entidades")
    for text in ["Como está a EDP em 2025?", "Contratos do NIF 500233810", "Notícias da GALP", "Quem é Pedro Nuno Santos?", "faturação da SONAE"]:
        started = time.time()
        res = onto.resolve_entities(text, limit=4, es=es)
        elapsed = (time.time() - started) * 1000
        print(f"  {text!r} ({elapsed:.0f}ms, {res.get('queries')} consultas) menções={res['mentions']}")
        for entry in res["entities"]:
            print(f"      {entry['confidence']:.2f} {entry['type_label']:22s} {str(entry['object'].get('_label'))[:50]!r} ({entry['matched_on']})")

    section("Contexto para IA")
    started = time.time()
    context = onto.ai_context("Quais os contratos da EDP e as notícias da GALP em 2025?", es=es)
    print(f"  {int((time.time() - started) * 1000)}ms | objetos={len(context['objects'])} relações={len(context['relations'])}")
    print(context["grounding"])

    section("Validação anti-alucinação")
    good = "A EDP tem contratos registados e a GALP tem notícias indexadas em 2025."
    bad = "A empresa Inventada Lda, NIF 123456789, ganhou 999 M€ em 2025."
    for answer in (good, bad):
        result = onto.validate_answer(answer, context=context, es=es)
        print(f"  {answer!r}\n    supported={result['supported']} score={result['score']}")
        for check in result["checks"]:
            print(f"      [{check['status']}] {check['kind']}={check['value']} {check['message']}")

    section("Ferramentas geradas")
    tools = onto.generated_tools()
    print("  ", [tool["name"] for tool in tools])
    print("  tipos no catálogo:", len(tools[0]["catalog"]))

    section("Ações")
    for action in ontology["actions"]:
        print(f"  {action['id']:34s} {action['kind']:15s} {action.get('url') or action.get('target')}")
    try:
        resolved = onto.resolve_action("empresa.contratos", object_id="500233810", type_id="empresa", es=es)
        print("  empresa.contratos ->", resolved["method"], resolved["url"], resolved["body"], resolved["values"])
    except Exception as exc:
        print("  empresa.contratos EXCEÇÃO:", type(exc).__name__, exc)

    section("Ligações por tipo")
    for type_id in ("empresa", "contrato", "noticia", "conta", "pessoa"):
        links = onto.links_for_type(type_id)
        print(f"  {type_id}: {len(links)} ligações ->", ", ".join(f"{link['id']}({link['direction'][:3]})" for link in links[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
