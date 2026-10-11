"""Sonda de produtos de uma loja (CLI) — preço, imagem e descrição.

Corre o mesmo caminho que a interface usa (`benchmarks_service.sondar_loja`):
análise determinística da página + proposta da IA (quando pedida) + validação a
sério, e no fim mostra o que seria recolhido (com preços, imagens e descrições).

Uso (dentro do container, onde há browsers e chaves de IA)::

    python /app/logs/_sonda_produtos.py https://www.worten.pt/... --fetcher stealth
    python /app/logs/_sonda_produtos.py --lojas worten,fnac,darty
    python /app/logs/_sonda_produtos.py https://... --sem-ia --json saida.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List

sys.stdout.reconfigure(encoding="utf-8")

from api import benchmarks_service as servico  # noqa: E402
from api import scraper_service  # noqa: E402

#: Lojas conhecidas (as que o utilizador pediu + alternativas nacionais).
LOJAS: Dict[str, Dict[str, str]] = {
    "worten": {"url": "https://www.worten.pt/informatica-e-acessorios/computadores", "nome": "Worten"},
    "amazon-es": {"url": "https://www.amazon.es/s?k=portatil", "nome": "Amazon Espanha"},
    "fnac": {"url": "https://www.fnac.pt/informatica/h10", "nome": "Fnac"},
    "fnac-es": {"url": "https://www.fnac.es/Ordenadores-portatiles/Ordenadores-portatiles/na48", "nome": "Fnac Espanha"},
    "darty": {
        "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
        "nome": "Darty",
    },
    "pcdiga": {"url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop", "nome": "PCDiga"},
    "radiopopular": {
        "url": "https://www.radiopopular.pt/categoria/computadores-portateis",
        "nome": "Radio Popular",
    },
    "mediamarkt-pt": {"url": "https://www.mediamarkt.pt/collections/portateis", "nome": "MediaMarkt"},
    "auchan": {"url": "https://www.auchan.pt/pt/tecnologia/informatica/", "nome": "Auchan"},
}


def resumo(resultado: Dict[str, Any], fetcher: str) -> None:
    print(f"  ok={resultado.get('ok')} · origem={resultado.get('origem')} · fetcher={fetcher}")
    if resultado.get("erro"):
        print(f"  erro: {str(resultado['erro'])[:160]}")
    if resultado.get("avisos"):
        for aviso in resultado["avisos"]:
            print(f"  aviso: {str(aviso)[:160]}")
    robots = resultado.get("robots") or {}
    print(f"  robots: {robots.get('detalhe')}")
    if resultado.get("ai"):
        ia = resultado["ai"]
        print(f"  ia: {ia.get('provider_label')} · {ia.get('model')} · {str(ia.get('notes') or '')[:90]}")
    print(f"  campos: {', '.join(resultado.get('campos') or []) or '—'}")
    mapa = resultado.get("field_map") or {}
    if mapa:
        print(f"  mapa de campos: {json.dumps(mapa, ensure_ascii=False)}")
    tentativas = resultado.get("tentativas") or []
    if tentativas:
        print(f"  tentativas: {tentativas}")
    for oferta in (resultado.get("amostra") or [])[:4]:
        preco = oferta.get("price")
        imagem = (oferta.get("image") or "")[:52]
        descricao = (oferta.get("description") or "")[:60]
        print(f"    · {str(oferta.get('product_name'))[:52]:52} | {preco} {oferta.get('currency')}")
        print(f"      imagem: {imagem or '—'}")
        print(f"      descrição: {descricao or '—'}")


async def sondar(url: str, *, fetcher: str, nome: str, use_ai: bool, provider: str, model: str) -> Dict[str, Any]:
    print(f"\n=== {nome} · {url} (fetcher {fetcher})")
    resultado = await servico.sondar_loja(
        url,
        fetcher=fetcher,
        hint="produtos de informática com preço, imagem e descrição",
        use_ai=use_ai,
        provider=provider or None,
        model=model or None,
        nome_loja=nome,
    )
    resumo(resultado, fetcher)
    return resultado


async def principal() -> int:
    parser = argparse.ArgumentParser(description="Sonda produtos de uma loja (com IA opcional).")
    parser.add_argument("url", nargs="?", help="Endereço da listagem")
    parser.add_argument("--lojas", default="", help="Ids separados por vírgula (worten,fnac,darty,…)")
    parser.add_argument("--fetcher", default="http", help="http | dynamic | stealth")
    parser.add_argument("--fallback", default="", help="Se o fetcher principal falhar, tentar estes (ex.: dynamic,stealth)")
    parser.add_argument("--sem-ia", action="store_true", help="Só análise determinística")
    parser.add_argument("--provider", default="", help="Fornecedor de IA")
    parser.add_argument("--model", default="", help="Modelo de IA")
    parser.add_argument("--json", default="", help="Guardar o resultado neste ficheiro")
    args = parser.parse_args()

    disponibilidade = scraper_service.availability()
    print(
        "ambiente: scrapling={} fetchers={} browsers={}".format(
            disponibilidade.get("scrapling"), disponibilidade.get("fetchers"), disponibilidade.get("browsers")
        )
    )

    alvos: List[Dict[str, str]] = []
    if args.url:
        alvos.append({"url": args.url, "nome": args.url.split("/")[2] if "//" in args.url else args.url})
    for chave in [c.strip() for c in args.lojas.split(",") if c.strip()]:
        if chave in LOJAS:
            alvos.append(LOJAS[chave])
        else:
            print(f"  (ignorada: loja desconhecida «{chave}»)")

    resultados: List[Dict[str, Any]] = []
    fetchers = [args.fetcher] + [f.strip() for f in args.fallback.split(",") if f.strip()]
    for alvo in alvos:
        for indice, fetcher in enumerate(fetchers):
            resultado = await sondar(
                alvo["url"],
                fetcher=fetcher,
                nome=alvo.get("nome") or alvo["url"],
                use_ai=not args.sem_ia,
                provider=args.provider,
                model=args.model,
            )
            resultado["_fetcher"] = fetcher
            resultado["_loja"] = alvo.get("nome") or alvo["url"]
            resultados.append(resultado)
            if resultado.get("ok"):
                break
            if indice + 1 < len(fetchers):
                print(f"  → a tentar com o fetcher seguinte ({fetchers[indice + 1]})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as ficheiro:
            json.dump(resultados, ficheiro, ensure_ascii=False, indent=1)
        print(f"\nresultados guardados em {args.json}")

    bons = [r for r in resultados if r.get("ok")]
    print(f"\nresumo: {len(bons)}/{len(resultados)} sondagens com produtos extraídos")
    return 0 if bons else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
