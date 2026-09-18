"""Teste rápido (dev): proposta de tipo de objeto, ligações e limpeza de proposta da IA."""
from __future__ import annotations

import json

from api import ontology_ai as ai
from api import ontology_sources as src

fields = [
    {"name": "id", "label": "Id", "type": "keyword", "filterable": True, "searchable": True, "sortable": False},
    {"name": "nome", "label": "Nome", "type": "text", "searchable": True, "filterable": False, "sortable": False},
    {"name": "valor", "label": "Valor", "type": "number", "searchable": False, "filterable": True, "sortable": True},
    {"name": "adjudicatarios.parsed.nif", "label": "Nif", "type": "keyword", "nested": "adjudicatarios.parsed", "filterable": True},
    {"name": "adjudicantes.parsed.nif", "label": "Nif", "type": "keyword", "nested": "adjudicantes.parsed", "filterable": True},
]

source = {"id": "energia", "label": "Contratos de energia", "kind": "elasticsearch", "index": "energia_contratos"}
tipo = src.infer_object_type(source, fields=fields, samples={"id": ["A1"]})
print("tipo:", tipo["id"], "| plural:", tipo["plural"])
print("propriedades:", [(p["id"], p.get("field"), p.get("nested"), p["type"]) for p in tipo["properties"]])
print("binding:", json.dumps(tipo["binding"], ensure_ascii=False))

existente = [
    {
        "id": "empresa",
        "label": "Empresa",
        "domain": "contratacao",
        "properties": [
            {"id": "nif", "field": "nif", "type": "keyword"},
            {"id": "nome", "field": "nome", "type": "text"},
        ],
    },
    {"id": "ticker", "label": "Instrumento", "domain": "mercados", "properties": [{"id": "ticker", "field": "ticker", "type": "keyword"}]},
]
ligacoes = ai._heuristic_links([tipo], existente)
print("ligacoes:", [(link["id"], link["from"], "->", link["to"], link["binding"]["from_field"]) for link in ligacoes])

proposta = {
    "object_types": [
        {
            "id": "Energia Contrato",
            "label": "Contrato de energia",
            "properties": [
                {"id": "id", "label": "ID", "type": "keyword", "field": "id", "pk": True},
                {"id": "inventado", "label": "Inventado", "type": "text", "field": "campo_que_nao_existe"},
                {"id": "valor", "label": "Valor", "type": "text", "field": "valor"},
                {"id": "nif", "label": "NIF", "type": "keyword", "field": "adjudicatarios.parsed.nif", "filterable": True},
            ],
            "binding": {"kind": "es", "index": "energia_contratos", "source": "energia"},
            "title_field": "nome",
        }
    ],
    "link_types": [
        {"id": "energia_empresa", "from": "energia_contrato", "to": "empresa", "label": "Empresa do contrato"},
        {"id": "mau", "from": "energia_contrato", "to": "nao_existe", "label": "Ligacao invalida"},
    ],
}
bundle = [{"source": source, "diagnostic": {"ok": True, "fields": fields, "documents": 42}}]
limpa = ai.clean_proposal(proposta, bundle=bundle, domain="energia", ontology_id=None)
for item in limpa["object_types"]:
    print("limpo:", item["id"], "| dominio", item["domain"], "| pk", item["primary_key"], "| titulo", item["title_field"])
    for prop in item["properties"]:
        print("   ", prop["id"], prop["type"], prop.get("field"), "pk" if prop.get("pk") else "", "filtro" if prop.get("filterable") else "")
print("ligacoes limpas:", [(link["id"], link["from"], link["to"]) for link in limpa["link_types"]])
print("avisos:", limpa["warnings"])
