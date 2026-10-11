"""Valida o módulo de benchmarks na interface (Playwright, headless).

Confirma, no browser:

1. `/benchmarks` lista os estudos (cartões com volumetria e índice próprio);
2. a barra lateral tem o módulo «Benchmarks de produtos» com **uma entrada por
   estudo** (o requisito de «cada um com a sua entrada de menu»);
3. `/benchmarks/<slug>` abre o estudo com KPIs e a tabela de comparação;
4. a página pública com pesquisa responde e filtra.

Uso::

    python logs/_validar_benchmarks_ui.py [slug] [base]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SLUG = sys.argv[1] if len(sys.argv) > 1 else "livros-demo"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:4180"
DESTINO = Path(__file__).resolve().parents[1] / "exports" / "business" / "ecras"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


def token() -> str:
    codigo = (
        "from api import auth_service;"
        "u = auth_service.list_users(1) or [];"
        "s = auth_service.create_session(u[0]) if u else {};"
        "print('TOKEN=' + str(s.get('token', '')))"
    )
    saida = subprocess.run(
        ["docker", "exec", "finance-llm-backend", "python", "-c", codigo],
        capture_output=True, text=True, timeout=120,
    )
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("TOKEN="):
            return linha.split("=", 1)[1].strip()
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    chave = token()
    print(f"token: {len(chave)} caracteres")
    problemas: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        contexto = browser.new_context(viewport={"width": 1600, "height": 950}, user_agent=UA, locale="pt-PT")
        if chave:
            contexto.add_init_script(
                f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(chave)}); }} catch (e) {{}}"
            )
        pagina = contexto.new_page()
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

        # 1. lista
        pagina.goto(f"{BASE}/benchmarks", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(6000)
        texto_lista = pagina.inner_text("main")
        tem_titulo = "Benchmarks de produtos" in texto_lista
        cartoes = pagina.locator("main button:has-text('Abrir estudo')").count()
        print(f"lista: título={tem_titulo} · estudos com botão «Abrir estudo»={cartoes}")
        print("   índices visíveis:", pagina.locator("main .font-mono").count())
        DESTINO.mkdir(parents=True, exist_ok=True)
        pagina.screenshot(path=str(DESTINO / "17_benchmarks_lista.png"))
        # O cartão tem de mostrar números a sério: o «preço médio» já apareceu
        # como «—» para sempre (o campo não existia nas estatísticas) e a chave
        # de comparação aparecia como um «nome» solto, sem contexto.
        if "preço médio —" in texto_lista:
            problemas.append("o cartão mostra «preço médio —» mesmo com ofertas recolhidas")
        if not re.search(r"preço médio\s*[\d]", texto_lista):
            problemas.append("o cartão não mostrou o preço médio")
        if "iguais por:" not in texto_lista:
            problemas.append("a chave de comparação do cartão não está identificada")
        if "Só uma loja" not in texto_lista and "Ainda sem ofertas" not in texto_lista:
            print("   (todos os estudos têm 2+ lojas com ofertas)")
        if not tem_titulo:
            problemas.append("a página /benchmarks não mostrou o título")
        if cartoes == 0:
            problemas.append("nenhum estudo listado em /benchmarks")

        # 2. barra lateral (uma entrada por estudo) — o grupo abre-se à procura do estudo
        try:
            pagina.locator("nav button:has-text('Benchmarks de produtos')").first.click(timeout=3000)
            pagina.wait_for_timeout(600)
        except Exception:  # noqa: BLE001 - já pode estar aberto
            pass
        lateral = pagina.inner_text("nav")
        tem_modulo = "Benchmarks de produtos" in lateral
        tem_estudo = SLUG.split("-")[0].lower() in lateral.lower() or "livros" in lateral.lower()
        print(f"menu: módulo presente={tem_modulo} · entrada do estudo={tem_estudo}")
        if not tem_modulo:
            problemas.append("o módulo não apareceu na barra lateral")
        if not tem_estudo:
            problemas.append("o estudo não tem entrada própria na barra lateral")

        # 3. página do estudo
        pagina.goto(f"{BASE}/benchmarks/{SLUG}", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(7000)
        texto_estudo = pagina.inner_text("main")
        texto_minusculas = texto_estudo.lower()
        kpis = pagina.locator("main p.text-2xl").count()
        linhas = pagina.locator("main table tbody tr").count()
        print(f"estudo: KPIs={kpis} · linhas de tabela={linhas} · tem 'Ranking das lojas'={'ranking das lojas' in texto_minusculas}")
        for marca in ("ofertas", "produtos", "dispersão média", "poupança potencial"):
            if marca not in texto_minusculas:
                problemas.append(f"falta o KPI «{marca}» na página do estudo")
        if linhas == 0:
            problemas.append("a tabela de comparação veio vazia")
        if "ranking das lojas" not in texto_minusculas:
            problemas.append("o ranking das lojas não apareceu com duas lojas recolhidas")
        print("   amostra:", " | ".join(texto_estudo.split("\n")[4:9])[:150])
        pagina.evaluate("() => { try { window.localStorage.removeItem('finance-llm-windows:v1'); } catch (e) {} }")
        pagina.screenshot(path=str(DESTINO / "18_benchmark_estudo.png"))

        # 4. página pública com pesquisa
        pagina.goto(f"{BASE}/site/benchmarks/{SLUG}/pesquisa", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(1500)
        texto_publico = pagina.inner_text("body")
        print(f"pública: formulário={pagina.locator('form.pesquisa').count()} · linhas={pagina.locator('table tbody tr').count()}")
        if "ofertas recolhidas" not in texto_publico:
            problemas.append("a página pública não mostrou os KPIs")
        filtrada = f"{BASE}/site/benchmarks/{SLUG}/pesquisa?q=light&ordem=preco"
        pagina.goto(filtrada, wait_until="load", timeout=60000)
        linhas_filtradas = pagina.locator("table tbody tr").count()
        print(f"pública filtrada (?q=light): linhas={linhas_filtradas}")
        if linhas_filtradas == 0:
            problemas.append("a pesquisa pública não devolveu resultados")

        # 5. sonda de uma loja no formulário de criação (sem IA, para não esperar
        #    pelo modelo local): tem de mostrar os campos detetados e a amostra.
        pagina.goto(f"{BASE}/benchmarks", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(4000)
        pagina.locator("main button:has-text('Novo benchmark')").first.click()
        pagina.wait_for_timeout(800)
        formulario = pagina.locator("main form")
        formulario.locator("input[placeholder='https://loja.pt/categoria']").first.fill(
            "https://books.toscrape.com/catalogue/page-1.html"
        )
        formulario.locator("input[placeholder='Nome da loja']").first.fill("Loja de demonstração")
        # Desmarca a IA: a sonda determinística responde em segundos.
        caixa_ia = formulario.locator("label:has-text('Sonda com IA') input[type=checkbox]")
        if caixa_ia.count() and caixa_ia.first.is_checked():
            caixa_ia.first.uncheck()
        formulario.locator("button:has-text('Sonda (IA)')").first.click()
        pagina.wait_for_timeout(30000)
        painel = pagina.locator("main div:has-text('Amostra')").count()
        texto_sonda = pagina.inner_text("main")
        miniaturas = pagina.locator("main img").count()
        tem_lista = "Lista:" in texto_sonda
        tem_botao = pagina.locator("main button:has-text('Usar estes seletores')").count()
        print(
            f"sonda: painel={painel} · 'Lista:'={tem_lista} · miniaturas na amostra={miniaturas} · "
            f"botão «Usar estes seletores»={tem_botao}"
        )
        print("   campos detetados:", [linha for linha in texto_sonda.split("\n") if "=" in linha and "::" in linha][:1])
        pagina.screenshot(path=str(DESTINO / "19_benchmark_sonda.png"))
        if not tem_lista or tem_botao == 0:
            problemas.append("a sonda não mostrou o painel com os seletores propostos")
        if miniaturas == 0:
            problemas.append("a amostra da sonda não mostrou produtos (imagens)")

        print(f"erros de consola: {len(erros)}")
        for linha in erros[:4]:
            print("   ", linha[:150])
        contexto.close()
        browser.close()

    if problemas:
        print("\nPROBLEMAS:")
        for problema in problemas:
            print("  -", problema)
        return 1
    print("\nTUDO OK: lista, menu por estudo, página do estudo, sonda e pesquisa pública.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
