"""Quanto tempo demora mesmo a agregacao de `/contracts/analytics` na VM.

Porque e que isto existe
------------------------
O endpoint devolve `502 {"detail": "Connection timed out"}` ao fim de ~30,15 s.
Nao e o nginx: o proprio backend regista o 502 no seu log. E o
`get_contract_analytics` usa `get_es_client()` com o `request_timeout` **padrao de
30 s** (`elasticsearch_client.py:4164`), e na VM de 2 vCPU a agregacao nao cabe
nesse tempo.

No PC, com 14 nucleos logicos, a mesma agregacao cabe nos 30 s -- foi por isso
que isto so apareceu depois de os 2,25 M contratos ficarem na VM e a pagina ser
servida de la.

O ficheiro esta colocado de forma a que o contentor o veja: o compose do backend
monta `./logs:/app/logs`, logo

    /opt/iqos/servicos/backend/logs/_diag_analytics.py   (na VM)
    /app/logs/_diag_analytics.py                          (no contentor)

Correr:
    docker exec iqos-backend python /app/logs/_diag_analytics.py
"""

import sys
import time

sys.path.insert(0, "/app")

from api.elasticsearch_client import get_contract_analytics, get_es_client  # noqa: E402

# Chamada HTTP ao proprio servidor, de dentro do contentor. Se a funcao acima
# corre em 5 s mas isto der 502, o problema esta no caminho da rota (ou no
# servidor), nao no Elasticsearch.
import json  # noqa: E402
import urllib.request  # noqa: E402

print("-- HTTP interno a rota real --")
for url in (
    "http://127.0.0.1:8000/contracts/analytics?top_entities=8&top_cpv=8",
    "http://127.0.0.1:8000/contracts/analytics?top_entities=2&top_cpv=2",
):
    t = time.time()
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            corpo = r.read().decode("utf-8", "replace")[:160]
        print(f"  {time.time()-t:6.1f}s  {r.status}  {corpo}")
    except Exception as e:  # noqa: BLE001
        print(f"  {time.time()-t:6.1f}s  ERRO {type(e).__name__}: {str(e)[:130]}")
print()


# Timeout folgado de proposito: quero o tempo real, nao o tempo ate desistir.
es = get_es_client(request_timeout=900)
if es is None:
    print("ERRO: nao consegui criar o cliente do Elasticsearch")
    sys.exit(2)

# Reproducao EXACTA do que a rota faz: sem `es`, o que leva o `get_contract_analytics`
# a criar o seu proprio cliente com o `request_timeout` padrao de **30 s**.
# A mensagem "Connection timed out" e do urllib3 e refere-se ao **estabelecimento
# da ligacao**, nao a leitura -- e isso aponta para o cliente, nao para a query.
print("-- reproducao exacta da rota (sem `es`) --")
for tentativa in (1, 2):
    t = time.time()
    try:
        res = get_contract_analytics(top_entities=8, top_cpv=8, role="all")
        print(f"  tentativa {tentativa}: {time.time()-t:6.1f}s  erro={res.get('error')}")
    except Exception as e:  # noqa: BLE001
        print(f"  tentativa {tentativa}: {time.time()-t:6.1f}s  EXCECAO {type(e).__name__}: {e}")
print()

# Versoes do teste acima com valores que NUNCA correram, para forcar falha de
# cache. Senao o tempo medido e o da cache, nao o do calculo -- e foi isso que
# me enganou: a rota parecia instantanea aqui e dava 502 no browser.
print("-- falhas de cache forcadas (cliente PADRAO de 30 s, como a rota) --")
for top in (3, 5, 11, 13):
    t = time.time()
    try:
        res = get_contract_analytics(top_entities=top, top_cpv=top, role="all")
        print(f"  top={top:<3d} {time.time()-t:6.1f}s  erro={res.get('error')}")
    except Exception as e:  # noqa: BLE001
        print(f"  top={top:<3d} {time.time()-t:6.1f}s  EXCECAO {type(e).__name__}: {str(e)[:70]}")
print()

# A chave do diagnostico: o endpoint `/contracts/analytics` passa `role="all"`
# por omissao (esta no `Query("all", ...)` da rota), enquanto o valor por omissao
# **da funcao** e `role=None`. Sao caminhos de codigo diferentes -- e o comentario
# do `ENTITY_ROLE_SUMMARY` fala de "~20 s para um so papel e ~100 s para o resumo
# completo". Comparar os dois lado a lado diz qual deles e o caro.
casos = [
    ("role=None   top=8  (funcao)", dict(top_entities=8, top_cpv=8)),
    ("role='all'  top=8  (rote)", dict(top_entities=8, top_cpv=8, role="all")),
    ("role='all'  top=1  (rote)", dict(top_entities=1, top_cpv=1, role="all")),
    ("role='all'  ecological", dict(top_entities=10, top_cpv=10, ecological=True, role="all")),
    ("role='all'  max_price", dict(top_entities=8, top_cpv=8, max_price=50000, role="all")),
]

print(f"{'caso':34s} {'tempo':>9s}  resultado")
print("-" * 78)

pior = 0.0
for nome, kw in casos:
    t = time.time()
    try:
        res = get_contract_analytics(es=es, **kw)
        el = time.time() - t
        pior = max(pior, el)
        erro = res.get("error")
        if erro:
            print(f"{nome:34s} {el:8.1f}s  ERRO: {str(erro)[:90]}")
        else:
            total = res.get("total")
            if total is None:
                total = res.get("count")
            if total is None:
                # Nao sei a chave exata; mostra as que parecem contagens.
                chaves = [k for k in res if "total" in k or "count" in k][:4]
                total = {k: res[k] for k in chaves}
            print(f"{nome:34s} {el:8.1f}s  ok  total={total}")
    except Exception as e:  # noqa: BLE001
        el = time.time() - t
        pior = max(pior, el)
        print(f"{nome:34s} {el:8.1f}s  EXCECAO {type(e).__name__}: {str(e)[:90]}")

print("-" * 78)
print(f"pior caso: {pior:.1f}s")

# O valor a usar no `get_es_client` tem de ser folgado em relacao ao pior caso:
# o `request_timeout` e por pedido, e uma agregacao que caiba por pouco volta a
# falhar quando o indice crescer.
print(f"sugestao de request_timeout: {max(120, int(pior * 2))}s")
