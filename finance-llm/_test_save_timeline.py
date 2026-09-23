from api.elasticsearch_client import (
    get_es_client,
    ensure_indices,
    get_entity_by_nif,
    save_entity_societario_timeline,
)

client = get_es_client()
ensure_indices(client)
print("ensure ok")
entity = get_entity_by_nif("503323390")
print("doc_id:", entity.get("doc_id"))
res = save_entity_societario_timeline("503323390", "# Test\nmarkdown", 1, "test")
print("save result:", res)
print("after:", get_entity_by_nif("503323390").get("societario_timeline"))
