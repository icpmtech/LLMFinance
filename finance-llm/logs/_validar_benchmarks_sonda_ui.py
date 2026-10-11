"""Valida na interface a **sonda**, a **configuração** e a **edição dos estudos**.

Confirma, no browser:

1. `/benchmarks` tem as entradas «Sonda de lojas», «Configuração» e um botão
   «Editar» em cada estudo;
2. «Editar» abre o formulário **preenchido** com o estudo (nome, lojas, mapa);
3. `/benchmarks/sonda` sonda uma página e mostra a amostra (imagem + preço);
4. `/benchmarks/configuracao` mostra as opções e o catálogo de lojas, e guarda
   uma alteração.

Uso::

    python logs/_validar_benchmarks_sonda_ui.py [base]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4180"
DESTINO = Path(__file__).resolve().parents[1] / "exports" / "business" / "ecras"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
#: Página pública de treino (sem browser nem permissões em causa).
ALVO = "https://books.toscrape.com/catalogue/page-1.html"


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
    problemas: list[str] = []
    DESTINO.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as navegador:
        contexto = navegador.chromium.launch().new_context(
            viewport={"width": 1600, "height": 950}, user_agent=UA, locale="pt-PT"
        )
        if chave:
            contexto.add_init_script(
                f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(chave)}); }} catch (e) {{}}"
            )
        pagina = contexto.new_page()
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

        # 1. lista com as novas entradas e o botão de edição
        pagina.goto(f"{BASE}/benchmarks", wait_until="load", timeout=90000)
        pagina.wait_for_timeout(6000)
        main = pagina.locator("main")
        texto_lista = main.inner_text()
        tem_sonda = main.locator("button:has-text('Sonda de lojas')").count()
        tem_config = main.locator("button:has-text('Configuração')").count()
        tem_editar = main.locator("button:has-text('Editar')").count()
        print(f"lista: «Sonda de lojas»={tem_sonda} · «Configuração»={tem_config} · «Editar»={tem_editar}")
        if not tem_sonda or not tem_config:
            problemas.append("faltam os botões «Sonda de lojas»/«Configuração» na página dos benchmarks")
        if tem_editar == 0:
            problemas.append("nenhum cartão tem botão «Editar»")
        pagina.screenshot(path=str(DESTINO / "20_benchmarks_admin_lista.png"))

        # 2. editar um estudo a partir do cartão (formulário pré-preenchido)
        if tem_editar:
            main.locator("button:has-text('Editar')").first.click()
            pagina.wait_for_timeout(1500)
            texto_form = main.inner_text()
            titulo_form = "Editar «" in texto_form
            campo_nome = main.locator("input[placeholder='ex.: Portáteis 16 GB']").first
            valor_nome = campo_nome.input_value()
            loja_nome = main.locator("input[placeholder='Nome da loja']").first.input_value()
            botao = main.locator("button:has-text('Guardar alterações')").count()
            print(f"edição: título={titulo_form} · nome={valor_nome!r} · 1ª loja={loja_nome!r} · botão={botao}")
            if not titulo_form or botao == 0:
                problemas.append("«Editar» não abriu o formulário de edição")
            if not valor_nome.strip():
                problemas.append("o formulário de edição abriu vazio")
            pagina.screenshot(path=str(DESTINO / "21_benchmarks_editar.png"))

            # Guardar a sério e repor: é isto que prova que a edição pelo cartão
            # grava (e não só abre o formulário).
            if valor_nome.strip():
                try:
                    campo_nome.fill(f"{valor_nome} · edição")
                    main.locator("button:has-text('Guardar alterações')").first.click()
                    pagina.wait_for_timeout(6000)
                    guardado = "· edição" in main.inner_text()
                    print(f"   guardado: {guardado}")
                    if not guardado:
                        problemas.append("guardar a edição no cartão não se refletiu na lista")
                    # repor o nome original
                    main.locator("button:has-text('Editar')").first.click()
                    pagina.wait_for_timeout(1500)
                    main.locator("input[placeholder='ex.: Portáteis 16 GB']").first.fill(valor_nome)
                    main.locator("button:has-text('Guardar alterações')").first.click()
                    pagina.wait_for_timeout(6000)
                    reposto = "· edição" not in main.inner_text()
                    print(f"   reposto: {reposto}")
                    if not reposto:
                        problemas.append("não foi possível repor o nome original do estudo")
                except Exception as falha:  # noqa: BLE001
                    problemas.append(f"a edição pelo cartão falhou: {type(falha).__name__}")
            else:
                main.locator("button:has-text('Cancelar')").first.click()
                pagina.wait_for_timeout(600)

        # 3. página da sonda: sondar uma página pública de treino (sem IA = rápido)
        pagina.goto(f"{BASE}/benchmarks/sonda", wait_until="load", timeout=90000)
        pagina.wait_for_timeout(5000)
        main = pagina.locator("main")
        main.locator("input[placeholder='https://www.loja.pt/categoria/produtos']").first.fill(ALVO)
        main.locator("input[placeholder='ex.: Worten']").first.fill("Livraria de teste")
        caixa_ia = main.locator("label:has-text('Pedir proposta à IA') input[type=checkbox]")
        if caixa_ia.count() and caixa_ia.first.is_checked():
            caixa_ia.first.uncheck()
        main.locator("button:has-text('Sondar')").first.click()
        pagina.wait_for_timeout(45000)
        texto_sonda = main.inner_text()
        imgs = main.locator("img").count()
        tem_amostra = "produto(s) de amostra" in texto_sonda
        tem_lista = "Lista:" in texto_sonda
        print(f"sonda: amostra={tem_amostra} · lista={tem_lista} · imagens={imgs}")
        if not tem_amostra or not tem_lista:
            problemas.append("a página da sonda não mostrou o resultado (amostra/lista)")
        if imgs == 0:
            problemas.append("a amostra da sonda não trouxe imagens")
        pagina.screenshot(path=str(DESTINO / "22_benchmarks_sonda.png"))

        # 4. página de configuração: opções + catálogo, e guardar
        pagina.goto(f"{BASE}/benchmarks/configuracao", wait_until="load", timeout=90000)
        try:
            # O catálogo só aparece depois de a API responder (duas chamadas +
            # consultas ao Elasticsearch): esperar por ele em vez de contar às
            # cegas — foi isso que deu «catálogo vazio» numa corrida anterior.
            pagina.wait_for_selector("button:has-text('Sondar e guardar')", timeout=30000)
        except Exception:  # noqa: BLE001 - o problema é reportado abaixo
            pass
        pagina.wait_for_timeout(1000)
        main = pagina.locator("main")
        texto_config = main.inner_text()
        lojas = main.locator("button:has-text('Sondar e guardar')").count()
        tem_fetcher = "Como descarregar" in texto_config
        tem_ia = "Proposta por IA" in texto_config
        print(f"configuração: lojas no catálogo={lojas} · fetcher={tem_fetcher} · IA={tem_ia}")
        if not tem_fetcher or not tem_ia:
            problemas.append("a página de configuração não mostrou as opções de recolha/IA")
        if lojas == 0:
            problemas.append("o catálogo de lojas apareceu vazio")
        campo_pausa = main.locator("input[type=number]").nth(1)
        campo_pausa.fill("3")
        main.locator("button:has-text('Guardar')").first.click()
        pagina.wait_for_timeout(4000)
        if "Configuração guardada" not in main.inner_text():
            problemas.append("guardar a configuração não confirmou")
        pagina.screenshot(path=str(DESTINO / "23_benchmarks_config.png"))

        print(f"erros de consola: {len(erros)}")
        for linha in erros[:4]:
            print("   ", linha[:150])
        contexto.close()

    if problemas:
        print("\nPROBLEMAS:")
        for problema in problemas:
            print("  -", problema)
        return 1
    print("\nTUDO OK: lista com edição, página da sonda e página de configuração.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
