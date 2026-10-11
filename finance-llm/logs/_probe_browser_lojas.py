"""Abre uma loja com **Playwright/Chromium** e diz o que lá está (e guarda o HTML).

Serve para o caso em que o pedido simples (ou o fetcher do Scrapling) é recusado
— Fnac com DataDome, Amazon com o «Robot Check» — e se quer ver o que um
**browser a sério** recebe. Não inventa: mostra o código HTTP, o título, os
sinais de bloqueio/captcha que encontrar no HTML, quantos candidatos a cartão de
produto existem e com que seletores, além dos preços que consegue ler.

Uso (no contentor ou no host, onde houver Playwright):

    python -u /app/logs/_probe_browser_lojas.py "https://www.fnac.pt/informatica/h10" --nome fnac
    python -u /app/logs/_probe_browser_lojas.py "https://www.amazon.es/s?k=portatil" --nome amazon-es --guardar /app/debug_loja
    python -u /app/logs/_probe_browser_lojas.py "https://..." --headful --espera 12
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

#: Sinais de que a página é uma barreira, não uma listagem.
SINAIS_BLOQUEIO = {
    "datadome": r"datadome|geo\.captcha|ct\.captcha",
    "cloudflare": r"cf-mitigated|cloudflare|Just a moment",
    "captcha": r"captcha|recaptcha|hcaptcha|are you a human|not a robot",
    "amazon-robot-check": r"Robot Check|Type the characters you see|api-services-support@amazon",
    "sem-js": r"enable JS|JavaScript is disabled|Please enable JavaScript",
    "consentimento": r"consent|cookies? (pol|policy)|aceitar e (continuar|fechar)",
}

#: Seletores de cartão de produto a experimentar (contagem por seletor).
SELETORES_CARTAO = (
    "article.product-card",
    "article[data-testid]",
    "div[data-component-type='s-search-result']",
    "div.s-result-item[data-asin]",
    "[data-testid='product-card']",
    "li.product-item",
    "div.product-card",
    "article",
)

PRECO_RE = re.compile(
    r"(?:€|EUR|R\$|US\$|\$|£)\s*\d[\d\s.,]*"
    r"|\d[\d\s.,]*\s*(?:€|EUR|\$|£)",
)


def analisar(url: str, *, nome: str, headless: bool, espera: float, scroll: bool, guardar: Path | None) -> Dict[str, Any]:
    resultado: Dict[str, Any] = {"url": url, "nome": nome}
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=headless)
        contexto = navegador.new_context(
            user_agent=UA,
            locale="pt-PT",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"},
        )
        pagina = contexto.new_page()
        pedidos: List[Dict[str, Any]] = []
        pagina.on(
            "response",
            lambda r: pedidos.append({"status": r.status, "url": r.url[:120], "datadome": r.headers.get("x-datadome", "")}),
        )
        resposta = pagina.goto(url, wait_until="domcontentloaded", timeout=90000)
        resultado["http"] = resposta.status if resposta else None
        resultado["http_final"] = resposta.headers.get("cf-mitigated") if resposta else None
        pagina.wait_for_timeout(int(espera * 1000))
        if scroll:
            try:
                for _ in range(6):
                    pagina.mouse.wheel(0, 1600)
                    pagina.wait_for_timeout(700)
                pagina.mouse.wheel(0, -12000)
                pagina.wait_for_timeout(1200)
            except Exception:
                pass
        resultado["titulo"] = pagina.title()
        html = pagina.content()
        resultado["html_bytes"] = len(html)
        texto = ""
        try:
            texto = pagina.inner_text("body")[:4000]
        except Exception:
            pass

        bloqueios = [chave for chave, padrao in SINAIS_BLOQUEIO.items() if re.search(padrao, html, re.IGNORECASE)]
        resultado["bloqueios"] = bloqueios
        resultado["texto_inicio"] = " ".join(texto.split())[:240]

        cartoes: Dict[str, int] = {}
        for seletor in SELETORES_CARTAO:
            try:
                quantidade = pagina.locator(seletor).count()
            except Exception:
                continue
            if quantidade:
                cartoes[seletor] = quantidade
        resultado["cartoes"] = cartoes

        precos = [p.strip() for p in PRECO_RE.findall(texto)][:12]
        resultado["precos_no_texto"] = precos
        resultado["respostas_403_429"] = [p for p in pedidos if p["status"] in (403, 429)][:6]
        resultado["datadome_headers"] = [p for p in pedidos if p.get("datadome")][:4]

        if guardar:
            guardar.mkdir(parents=True, exist_ok=True)
            ficheiro = guardar / f"{nome}.html"
            ficheiro.write_text(html, encoding="utf-8")
            resultado["html_guardado"] = str(ficheiro)
            try:
                pagina.screenshot(path=str(guardar / f"{nome}.png"), full_page=False)
                resultado["ecra"] = str(guardar / f"{nome}.png")
            except Exception:
                pass
        contexto.close()
        navegador.close()
    return resultado


def principal() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Abrir uma loja com Playwright/Chromium e descrever o que recebeu.")
    parser.add_argument("url")
    parser.add_argument("--nome", default="loja", help="Nome curto (para o ficheiro guardado)")
    parser.add_argument("--headful", action="store_true", help="Abrir janela visível (em vez de headless)")
    parser.add_argument("--espera", type=float, default=6, help="Segundos de espera após o carregamento")
    parser.add_argument("--sem-scroll", action="store_true", help="Não percorrer a página (lazy loading)")
    parser.add_argument("--guardar", default="", help="Pasta para guardar o HTML e um ecrã")
    args = parser.parse_args()

    resultado = analisar(
        args.url,
        nome=args.nome,
        headless=not args.headful,
        espera=args.espera,
        scroll=not args.sem_scroll,
        guardar=Path(args.guardar) if args.guardar else None,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    bloqueado = bool(resultado.get("bloqueios"))
    tem_produtos = any(valor >= 5 for valor in (resultado.get("cartoes") or {}).values())
    return 0 if (not bloqueado and tem_produtos) else 1


if __name__ == "__main__":
    sys.exit(principal())
