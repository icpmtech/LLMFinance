"""Diagnóstico: porque é que o DeepSeek «não responde a tempo»?

Mede, com a chave do utilizador configurada, dois pedidos:
  A) prompt mínimo  -> latência de base do fornecedor;
  B) prompt real da pesquisa profunda (fontes + referência de mercado).

Imprime apenas tempos e tamanhos — nunca a chave.
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import cloud_chat, deep_search_service as ds, providers_service as providers  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

INDICE = providers.PROVIDER_KEYS_INDEX
es = get_es_client()
print(f"indice de chaves: {INDICE}")

# `keys` não está indexado (enabled: false), por isso o `exists` não o encontra:
# é preciso ler o `_source` e escolher quem tem a chave DeepSeek.
resposta = es.search(index=INDICE, body={"size": 20, "_source": ["user_id", "keys"]})
donos = [
    h["_id"]
    for h in resposta["hits"]["hits"]
    if (h.get("_source") or {}).get("keys", {}).get("deepseek")
]
print(f"utilizadores com chave DeepSeek: {len(donos)} -> {donos}")

if not donos:
    print("Sem chave DeepSeek configurada: não é possível testar.")
    sys.exit(1)

user_id = donos[0]
chave, origem = providers.resolve_key(user_id, "deepseek")
print(f"chave: {'presente' if chave else 'AUSENTE'} ({origem}, {len(chave or '')} caracteres)")
spec = providers.PROVIDERS_BY_ID["deepseek"]
print(f"base_url={spec.get('base_url')} modelo={providers.resolve_provider_model(user_id, 'deepseek')}")
print(f"timeouts do httpx: connect={cloud_chat.REQUEST_TIMEOUT.connect} "
      f"read={cloud_chat.REQUEST_TIMEOUT.read} write={cloud_chat.REQUEST_TIMEOUT.write}")

modelo = providers.resolve_provider_model(user_id, "deepseek") or spec.get("default_model")


async def medir(nome: str, messages, max_tokens: int = 200):
    print(f"\n--- {nome} ---")
    print(f"  mensagens: {len(messages)} · caracteres: {sum(len(m['content']) for m in messages):,}".replace(",", " "))
    t0 = time.perf_counter()
    primeiro = None
    partes = []
    erro = None
    try:
        async for chunk in cloud_chat.stream_answer(
            provider="deepseek",
            spec=spec,
            model=modelo,
            messages=messages,
            api_key=chave,
            temperature=0.2,
            max_tokens=max_tokens,
        ):
            if primeiro is None:
                primeiro = time.perf_counter() - t0
            partes.append(chunk)
    except Exception as exc:  # noqa: BLE001
        erro = f"{type(exc).__name__}: {exc}"
    total = time.perf_counter() - t0
    print(f"  1.º pedaço: {primeiro:.1f}s" if primeiro else "  1.º pedaço: (nenhum)")
    print(f"  total: {total:.1f}s · pedaços: {len(partes)} · caracteres: {sum(len(p) for p in partes)}")
    if erro:
        print(f"  ERRO: {erro}")
    return "".join(partes), erro


async def principal():
    # A) mínimo
    await medir("A) prompt mínimo", [{"role": "user", "content": "Diz apenas: ok"}], max_tokens=20)

    # B) prompt real
    pergunta = "Compara o valor destes contratos com contratos semelhantes no mercado."
    t0 = time.perf_counter()
    recolha = ds.retrieve(pergunta, sources=["contracts"], mode="hybrid", per_source=8, max_sources=12)
    print(f"\nrecuperação: {len(recolha['sources'])} fontes em {(time.perf_counter()-t0):.1f}s")
    cpvs = [(s.get("meta") or {}).get("cpv") for s in recolha["sources"]]
    mercado = ds.mercado_por_cpv(cpvs)
    messages = ds.build_messages(pergunta, recolha["sources"][: ds.CITABLE_MAX], None, mercado=mercado)
    resposta, erro = await medir("B) prompt da pesquisa profunda", messages, max_tokens=1400)

    if resposta:
        print("\n--- primeiros 700 caracteres da resposta ---")
        print(resposta[:700])


asyncio.run(principal())
