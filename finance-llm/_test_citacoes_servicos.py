"""Testa a recolha completa **paralela por serviço** num punhado de serviços.

Exercita o caminho real (`collect_por_servico`) sem varrer os 257 serviços: usa 6
serviços, até 3 páginas cada, 3 sessões e sem gravar ficheiro.

Uso:
    python _test_citacoes_servicos.py [n_servicos] [workers]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import citacoes_service as servico  # noqa: E402
from collectors.citius_citacoes import CitacoesEditalClient  # noqa: E402

NSERV = int(sys.argv[1]) if len(sys.argv) > 1 else 6
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3

with CitacoesEditalClient(min_interval=0.0) as bootstrap:
    bootstrap.fetch_form()
    todos_servicos = [opcao["label"] for opcao in bootstrap.tribunais()][1:]

# Serviços pequenos e grandes, para o paralelismo ser testado a sério.
escolhidos = [
    "Açores - Tribunal de Execução das Penas dos Açores",
    "Águeda - Ministério Público da Comarca de Aveiro",
    "Abrantes - Tribunal Judicial da Comarca de Santarém",
    "Águeda - Tribunal Judicial da Comarca de Aveiro",
    "Almada - Tribunal Judicial da Comarca de Lisboa",
    "Angra do Heroísmo - Tribunal Judicial da Comarca dos Açores",
    "Braga - Tribunal Judicial da Comarca de Braga",
    "Coimbra - Tribunal Judicial da Comarca de Coimbra",
][:NSERV]

vistos: list[dict] = []
inicio = time.monotonic()
resultado = servico.collect_por_servico(
    meses=60,
    workers=WORKERS,
    max_pages_per_service=3,
    min_interval=1.0,
    persist=False,
    servicos=escolhidos,
    on_progress=lambda info: (
        vistos.append(info)
        if info.get("stage") == "collecting" and len(vistos) % 20 == 0
        else None
    ),
)
durou = time.monotonic() - inicio

meta = resultado["meta"]
print(f"serviços testados: {len(escolhidos)} ({WORKERS} sessões em paralelo)")
print(f"declarados: {meta['declared_total']} | recolhidos: {meta['collected']} | páginas: {meta['pages']}")
print(f"serviços percorridos: {meta['servicos_feitos']}/{meta['servicos_total']} | {durou:.1f}s")
print("erros:", meta["errors"][:3] or "nenhum")

itens = resultado["payload"]["items"]
datas = sorted({i["data_publicacao"] for i in itens if i.get("data_publicacao")})
print(f"datas: {datas[:3]} → {datas[-3:]}")
print("chaves do 1.º item:", sorted(itens[0].keys()))
duplicados = len(itens) - len({i["pub_id"] for i in itens})
print("pub_id duplicados:", duplicados)
por_tribunal: dict[str, int] = {}
for item in itens:
    chave = item.get("tribunal") or item.get("tribunal_sede") or "(sem tribunal)"
    por_tribunal[chave] = por_tribunal.get(chave, 0) + 1
print("por serviço:", sorted(por_tribunal.items(), key=lambda kv: -kv[1])[:6])
print("progressos recebidos:", len(vistos))
