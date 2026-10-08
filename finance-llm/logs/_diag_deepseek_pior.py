"""Pior caso: quanto tempo o DeepSeek leva a começar a responder.

O prompt da pesquisa profunda cresce com o número de fontes (até `CITABLE_MAX`)
e com o histórico do seguimento. Aqui mede-se o tempo até ao 1.º pedaço para
12/30/60 fontes, que é o que decide se se chega aos 180 s do `httpx` (`read`).
"""
import asyncio
import copy
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import cloud_chat, deep_search_service as ds, providers_service as providers  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client()
resposta = es.search(
    index=providers.PROVIDER_KEYS_INDEX, body={"size": 20, "_source": ["user_id", "keys"]}
)
user_id = next(
    h["_id"]
    for h in resposta["hits"]["hits"]
    if (h.get("_source") or {}).get("keys", {}).get("deepseek")
)
chave, _ = providers.resolve_key(user_id, "deepseek")
spec = providers.PROVIDERS_BY_ID["deepseek"]
modelo = providers.resolve_provider_model(user_id, "deepseek") or spec.get("default_model")

PERGUNTA = "Compara o valor destes contratos com contratos semelhantes no mercado."
recolha = ds.retrieve(PERGUNTA, sources=["contracts"], mode="hybrid", per_source=12, max_sources=12)
mercado = ds.mercado_por_cpv([(s.get("meta") or {}).get("cpv") for s in recolha["sources"]])
base = recolha["sources"]
HISTORICO = [
    {"role": "user", "content": "Qual é o valor total adjudicado à CLARANET II SOLUTIONS?"},
    {"role": "assistant", "content": "Segundo as fontes, 624 938 766 € em 3 952 contratos [1][2]."},
]


def com_n(n: int):
    """`n` fontes (repete as reais, como um lote grande faria)."""
    lista = []
    for i in range(n):
        fonte = copy.deepcopy(base[i % len(base)])
        fonte["n"] = i + 1
        lista.append(fonte)
    return lista


async def medir(n: int, com_historico: bool):
    messages = ds.build_messages(PERGUNTA, com_n(n), HISTORICO if com_historico else None, mercado=mercado)
    caracteres = sum(len(m["content"]) for m in messages)
    t0 = time.perf_counter()
    primeiro = None
    pedacos = 0
    erro = None
    try:
        async for _ in cloud_chat.stream_answer(
            provider="deepseek",
            spec=spec,
            model=modelo,
            messages=messages,
            api_key=chave,
            temperature=0.2,
            max_tokens=1400,
        ):
            if primeiro is None:
                primeiro = time.perf_counter() - t0
            pedacos += 1
    except Exception as exc:  # noqa: BLE001
        erro = f"{type(exc).__name__}: {exc}"
    total = time.perf_counter() - t0
    marca = " +histórico" if com_historico else ""
    print(
        f"  {n:>2} fontes{marca:<11} prompt {caracteres:>6,} car · "
        f"1.º pedaço {('%5.1fs' % primeiro) if primeiro else '  ----'} · "
        f"total {total:5.1f}s · {pedacos} pedaços"
        + (f" · ERRO {erro}" if erro else "")
    )


async def principal():
    print(f"DeepSeek ({modelo}) · timeouts read={cloud_chat.REQUEST_TIMEOUT.read}s")
    for n in (12, 30, 60):
        await medir(n, False)
    await medir(60, True)
    print("\n(se todos os 1.º pedaço ficarem muito abaixo de 180 s, o tempo limite do "
          "httpx não é a causa das falhas: são paragens do próprio fornecedor)")


asyncio.run(principal())
