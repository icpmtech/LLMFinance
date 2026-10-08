"""Que tempo limite é que falha afinal? Repete o mesmo pedido e mostra a causa.

`cloud_chat` apanha `httpx.TimeoutException` (que cobre connect, read, write e
pool) e diz sempre «não respondeu a tempo». Aqui mede-se o tempo até à falha e o
tipo exato da exceção, para se saber o que aumentar.
"""
import asyncio
import copy
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from api import cloud_chat, deep_search_service as ds, providers_service as providers  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

TENTATIVAS = int(sys.argv[1]) if len(sys.argv) > 1 else 10

es = get_es_client()
hits = es.search(index=providers.PROVIDER_KEYS_INDEX, body={"size": 20, "_source": ["keys"]})["hits"]["hits"]
user_id = next(h["_id"] for h in hits if (h.get("_source") or {}).get("keys", {}).get("deepseek"))
chave, _ = providers.resolve_key(user_id, "deepseek")
spec = providers.PROVIDERS_BY_ID["deepseek"]
modelo = providers.resolve_provider_model(user_id, "deepseek") or spec.get("default_model")

PERGUNTA = "Compara o valor destes contratos com contratos semelhantes no mercado."
recolha = ds.retrieve(PERGUNTA, sources=["contracts"], mode="hybrid", per_source=12, max_sources=12)
mercado = ds.mercado_por_cpv([(s.get("meta") or {}).get("cpv") for s in recolha["sources"]])
fontes = []
for i in range(60):
    fonte = copy.deepcopy(recolha["sources"][i % len(recolha["sources"])])
    fonte["n"] = i + 1
    fontes.append(fonte)
messages = ds.build_messages(PERGUNTA, fontes, None, mercado=mercado)
print(f"prompt de {sum(len(m['content']) for m in messages):,} caracteres · {TENTATIVAS} tentativas")
print(f"timeouts: connect={cloud_chat.REQUEST_TIMEOUT.connect} read={cloud_chat.REQUEST_TIMEOUT.read} "
      f"write={cloud_chat.REQUEST_TIMEOUT.write} pool={cloud_chat.REQUEST_TIMEOUT.pool}\n")

falhas = {}


async def principal():
    for n in range(1, TENTATIVAS + 1):
        t0 = time.perf_counter()
        pedacos = 0
        erro = None
        tipo_causa = ""
        try:
            async for _ in cloud_chat.stream_answer(
                provider="deepseek", spec=spec, model=modelo, messages=messages,
                api_key=chave, temperature=0.2, max_tokens=1400,
            ):
                pedacos += 1
        except Exception as exc:  # noqa: BLE001
            causa = exc.__cause__
            tipo_causa = type(causa).__name__ if causa else "(sem causa)"
            erro = f"{type(exc).__name__} <- {tipo_causa}: {causa}"
        d = time.perf_counter() - t0
        if erro:
            falhas[tipo_causa] = falhas.get(tipo_causa, 0) + 1
            print(f"{n:>2}. FALHOU em {d:5.1f}s ({pedacos} pedaços) · {erro}")
        else:
            print(f"{n:>2}. ok em {d:5.1f}s ({pedacos} pedaços)")
        await asyncio.sleep(0.5)


asyncio.run(principal())

if falhas:
    print("\nresumo das causas:", ", ".join(f"{k}={v}" for k, v in falhas.items()))
else:
    print("\nnenhuma falha nesta amostra")
