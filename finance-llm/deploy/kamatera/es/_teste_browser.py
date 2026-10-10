"""Abre mesmo um browser no contentor, para provar que o Chromium funciona.

Nao basta o binario existir: faltam por vezes bibliotecas de sistema
(`libnss3`, `libatk`, `libgbm`...) e o erro so aparece no `launch`. Este script
lanca o Chromium a serio, navega para uma pagina e devolve o titulo.

Correr:
    docker exec iqos-backend python /app/logs/_teste_browser.py
"""

import sys
import time

print("-- playwright --")
try:
    from playwright.sync_api import sync_playwright
except Exception as e:  # noqa: BLE001
    print(f"  import falhou: {e}")
    sys.exit(1)

with sync_playwright() as p:
    caminho = p.chromium.executable_path
    import os

    print(f"  executavel : {caminho}")
    print(f"  existe     : {os.path.exists(caminho)}")

    t = time.time()
    try:
        browser = p.chromium.launch(headless=True)
        print(f"  launch     : ok em {time.time()-t:.1f}s")
    except Exception as e:  # noqa: BLE001
        print(f"  launch     : FALHOU em {time.time()-t:.1f}s")
        print(f"  erro       : {str(e)[:600]}")
        sys.exit(2)

    try:
        page = browser.new_page()
        page.goto("https://example.com", timeout=45000)
        print(f"  navegacao  : ok, titulo = {page.title()!r}")
    except Exception as e:  # noqa: BLE001
        print(f"  navegacao  : FALHOU: {str(e)[:300]}")
    finally:
        browser.close()

# O caminho que o `api/scraper_service._browsers_installed()` usa e o mesmo que
# este teste. Se aqui funciona, o `/scraper/status` deve passar a dizer
# `"browsers": true`.
print()
print("-- contexto persistente (o que o Scrapling usa) --")
with sync_playwright() as p:
    t = time.time()
    try:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir="/tmp/_iqos_perfil_teste",
            headless=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://example.com", timeout=45000)
        print(f"  ok em {time.time()-t:.1f}s, titulo = {page.title()!r}")
        ctx.close()
    except Exception as e:  # noqa: BLE001
        print(f"  FALHOU: {str(e)[:400]}")
        sys.exit(3)
