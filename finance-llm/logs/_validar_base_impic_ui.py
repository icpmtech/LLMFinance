"""Valida na interface o separador «Portal Base» da aplicação de administração.

Confirma, no browser (`/admin` → separador «Portal Base»):

1. o catálogo de ficheiros do dados.gov.pt (anos, tamanhos, cache local);
2. o **formato** do ZIP do ano atual (membro JSON, forma, campos, índice destino);
3. a amostra de contratos já normalizados;
4. a importação de um ensaio, com o progresso a chegar a «concluido» e o
   contador «No Elasticsearch» a bater com o limite pedido;
5. que trocar de ano relê o formato desse ano.

Uso::

    python logs/_validar_base_impic_ui.py [base] [--limite 1500]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

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
        capture_output=True, text=True, timeout=180,
    )
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("TOKEN="):
            return linha.split("=", 1)[1].strip()
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Valida o separador «Portal Base» da administração.")
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:4180")
    parser.add_argument(
        "--limite",
        type=int,
        default=500,
        help="contratos do ensaio (abaixo de 1000 não tem separador de milhares no rótulo do botão)",
    )
    args = parser.parse_args()

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

        pagina.goto(f"{args.base}/admin", wait_until="load", timeout=120000)
        main = pagina.locator("main")

        # 1. O separador existe e abre. A aplicação valida a sessão antes de
        # desenhar a administração, por isso espera-se pelo botão (não por um
        # `wait_for_timeout` fixo, que já deu falso negativo).
        separador = main.get_by_role("button", name="Portal Base", exact=True)
        try:
            separador.wait_for(state="visible", timeout=120000)
            print("separador «Portal Base»: visível")
        except Exception:
            problemas.append("o separador «Portal Base» não aparece na administração")
            pagina.screenshot(path=str(DESTINO / "24_admin_base_impic.png"))
            print("PROBLEMAS:", problemas)
            return 1
        separador.click()
        pagina.wait_for_selector("table", timeout=60000)
        pagina.wait_for_selector("text=Membro JSON", timeout=120000)
        pagina.wait_for_timeout(2500)

        texto = main.inner_text()
        linhas = main.locator("table").first.locator("tbody tr").count()
        print(f"catálogo: {linhas} linha(s) de anos")
        print("formato:", "array JSON" in texto, "| membro:", "Contratos2026.json" in texto)
        if linhas < 15:
            problemas.append(f"o catálogo só mostra {linhas} anos")
        if "Contratos2026.json" not in texto:
            problemas.append("o formato do ZIP do ano atual não mostra o membro Contratos2026.json")
        if "array JSON" not in texto:
            problemas.append("a forma do JSON (array JSON) não é mostrada")
        if "normalize_contract" not in texto:
            problemas.append("a normalização usada não é indicada")

        campos = main.locator("table").nth(1).locator("tbody tr").count()
        print(f"campos de cada contrato: {campos}")
        if campos < 20:
            problemas.append(f"a tabela de campos só tem {campos} linha(s)")

        # Amostra normalizada
        if "Primeiros contratos" not in texto:
            problemas.append("a amostra de contratos já normalizados não aparece")

        pagina.screenshot(path=str(DESTINO / "24_admin_base_impic.png"))

        # 2. Importação de ensaio
        campo_limite = main.locator("input[placeholder='ex.: 3000']")
        if campo_limite.count() == 0:
            problemas.append("não há campo de limite para o ensaio")
            return 1
        campo_limite.first.fill(str(args.limite))
        pagina.wait_for_timeout(500)
        botao = main.locator(f"button:has-text('Importar {args.limite} contratos')")
        if botao.count() == 0:
            print("botões de importação:", main.locator("button:has-text('Importar')").all_inner_texts())
            problemas.append("o botão de importação com o limite pedido não aparece")
            return 1
        botao.first.click()
        print("importação lançada…")

        # O pedido é aceite de imediato e corre em segundo plano no servidor.
        pagina.wait_for_selector("text=iniciada em segundo plano", timeout=30000)
        try:
            # Best-effort: um ensaio pequeno pode acabar antes de se ver a correr.
            pagina.wait_for_selector("text=a correr", timeout=5000)
            pagina.screenshot(path=str(DESTINO / "25_admin_base_impic_importacao.png"))
            print("estado «a correr» observado")
        except Exception:
            print("estado «a correr» não deu tempo de ser visto (ensaio curto)")
        pagina.wait_for_selector("text=concluido", timeout=600000)
        pagina.wait_for_timeout(3000)
        texto_fim = main.inner_text()
        print("depois da importação:", [linha for linha in texto_fim.splitlines() if "contratos indexados" in linha][:2])
        if f"{args.limite} contratos indexados" not in texto_fim:
            problemas.append(f"a mensagem final não confirma os {args.limite} contratos indexados")
        pagina.screenshot(path=str(DESTINO / "26_admin_base_impic_concluido.png"))

        # 3. Trocar de ano relê o formato
        seletor = main.locator("select").first
        seletor.select_option("2025")
        pagina.wait_for_timeout(4000)
        texto_2025 = main.inner_text()
        print("formato de 2025:", "Formato do ZIP de 2025" in texto_2025, "| membro 2025:", "Contratos2025.json" in texto_2025)
        if "Formato do ZIP de 2025" not in texto_2025:
            problemas.append("trocar o ano não relê o formato desse ano")
        pagina.screenshot(path=str(DESTINO / "27_admin_base_impic_2025.png"))

        erros_filtrados = [e for e in erros if "favicon" not in e.lower()]
        print(f"erros de consola: {len(erros_filtrados)}")
        for erro in erros_filtrados[:5]:
            print("  ·", erro[:200])
        if erros_filtrados:
            problemas.append(f"{len(erros_filtrados)} erro(s) de consola")

    print()
    if problemas:
        print("PROBLEMAS:")
        for item in problemas:
            print("  -", item)
        return 1
    print("Interface validada: catálogo, formato, amostra, importação e troca de ano.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
