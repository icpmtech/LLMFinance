"""Sonda: cria o índice das peças da Vortal no ES da VM com o mesmo corpo do local.

O `ensure_indices` cria o índice na primeira utilização, mas a VM deve tê-lo
**antes** da primeira recolha (para o painel de monitorização não o dar como
inexistente). O corpo é copiado do índice local — o mesmo que o código cria —
para não haver duas definições a divergir.

Uso: ..\\.venv\\Scripts\\python.exe _probe_vortal_indice_vm.py
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import VORTAL_PECAS_INDEX, ensure_indices, get_es_client  # noqa: E402

TUNEL = "iqos-origin-tunnel"
ALVO = "root@45.147.251.188"
CHAVE = "/root/.ssh/id_ed25519"

# 1. Corpo do índice a partir do índice local (criado pelo próprio código).
local = get_es_client()
ensure_indices(local)
mapping = local.indices.get_mapping(index=VORTAL_PECAS_INDEX)[VORTAL_PECAS_INDEX]["mappings"]
configuracoes = local.indices.get_settings(index=VORTAL_PECAS_INDEX)[VORTAL_PECAS_INDEX]["settings"]["index"]
corpo = {
    "settings": {
        "number_of_shards": int(configuracoes.get("number_of_shards", 1)),
        "number_of_replicas": int(configuracoes.get("number_of_replicas", 0)),
        **({"analysis": configuracoes["analysis"]} if configuracoes.get("analysis") else {}),
    },
    "mappings": mapping,
}
texto = json.dumps(corpo, ensure_ascii=False)
print("corpo:", len(texto), "bytes | campos:", len(mapping.get("properties", {})))
codificado = base64.b64encode(texto.encode("utf-8")).decode("ascii")

comando = (
    f"echo {codificado} | base64 -d > /tmp/vortal_index.json && "
    f"curl -s -o /tmp/vortal_create.out -w '%{{http_code}}' -X PUT 'http://127.0.0.1:9200/{VORTAL_PECAS_INDEX}' "
    f"-H 'Content-Type: application/json' --data-binary @/tmp/vortal_index.json; echo; cat /tmp/vortal_create.out | head -c 400; echo; "
    f"curl -s 'http://127.0.0.1:9200/{VORTAL_PECAS_INDEX}/_mapping' | head -c 200; echo; "
    f"curl -s 'http://127.0.0.1:9200/_cat/indices/{VORTAL_PECAS_INDEX}?h=index,docs.count,store.size'"
)

resultado = subprocess.run(
    ["docker", "exec", TUNEL, "ssh", "-i", CHAVE, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR", ALVO, comando],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print("código:", resultado.returncode)
print(resultado.stdout.strip()[:1500])
if resultado.stderr.strip():
    print("stderr:", resultado.stderr.strip()[:400])
