"""Ajustes pontuais no container MiroFish em execução (título do documento).

Corre com:
    docker cp docker/mirofish/_patch_titles.py <container>:/tmp/ && docker exec <container> python3 /tmp/_patch_titles.py

Existe para poder aplicar o título novo sem recriar o container — recriar
mataria as simulações em execução. Os mesmos ajustes estão no `Dockerfile`
(aí aplicados por `sed` na build).
"""
from pathlib import Path

TITLE = "IQ OS · Simulações"
old_title = "MiroFish - Prever Tudo"

path = Path("/app/frontend/index.html")
html = path.read_text(encoding="utf-8")
if TITLE in html:
    print("já aplicado")
else:
    html = html.replace(f"<title>{old_title}</title>", f"<title>{TITLE}</title>")
    path.write_text(html, encoding="utf-8")
    print("título atualizado para", TITLE)

# Verificação: o ficheiro tem de conter o título novo depois da escrita.
final = path.read_text(encoding="utf-8")
assert TITLE in final, "o título não ficou aplicado"
print("confirmado")
