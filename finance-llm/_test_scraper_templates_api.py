"""Verificação das rotas de templates da recolha (API a correr na 8002).

Só rotas de leitura: as de escrita exigem sessão e são verificadas em
`_test_scraper_templates_flow.py`.

Uso:  python _test_scraper_templates_api.py
Grava o relatório em `_test_scraper_templates_api.txt` (UTF-8).
"""
from __future__ import annotations

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8002"
OUT = Path(__file__).resolve().parent / "_test_scraper_templates_api.txt"
lines: list[str] = []


def emit(text: str = "") -> None:
    lines.append(text)
    print(text)


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=120, follow_redirects=True) as client:
        emit(f"health: {client.get('/health').json().get('status')}")

        meta = client.get("/scraper/meta").json()
        emit(f"meta.template_categories: {meta.get('template_categories')}")

        status = client.get("/scraper/status").json()
        emit(
            "status: scrapling={0} browsers={1} fetchers={2} es={3} jobs={4}".format(
                status.get("scrapling"),
                status.get("browsers"),
                status.get("fetchers"),
                status.get("elasticsearch"),
                (status.get("scheduler") or {}).get("jobs_total"),
            )
        )

        galeria = client.get("/scraper/templates").json()
        emit(f"templates: {galeria['total']} em {len(galeria['categories'])} categorias")
        for item in galeria["items"]:
            emit(
                "  {id:22s} {fetcher:8s} detail={detail!s:5s} cron={cron:12s} campos={fields}".format(
                    id=item["id"],
                    fetcher=item["fetcher"],
                    detail=item["detail"],
                    cron=item["cron"],
                    fields=",".join(item["fields"]),
                )
            )

        filtrado = client.get("/scraper/templates", params={"category": "Mercados (internacional)"}).json()
        emit(f"filtro por categoria: {filtrado['total']} template(s)")

        detalhe = client.get("/scraper/templates/eco").json()["item"]
        emit(f"detalhe eco: chaves do source={len(detalhe.get('source', {}))}")

        inexistente = client.get("/scraper/templates/nao-existe")
        emit(f"template inexistente: HTTP {inexistente.status_code}")

        # As rotas de escrita exigem sessão (401 sem token).
        sem_sessao = client.post("/scraper/templates/quotes-demo/preview", params={"limit": 2})
        emit(f"preview sem sessão: HTTP {sem_sessao.status_code} ({(sem_sessao.json() or {}).get('detail')})")

        sp = client.get("/scraper/stats").json()
        emit(
            "stats: fontes={sources_total} execucoes={runs_total} itens={items_scraped} "
            "indexados={items_indexed} com_texto={items_with_text}".format(**sp)
        )

        resumo = client.get("/openapi/summary").json()
        grupos = resumo.get("groups")
        total = len(grupos) if isinstance(grupos, (list, tuple, dict)) else grupos
        emit(f"openapi/summary: chaves={sorted(resumo)[:8]} grupos={total}")

    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
