"""O contentor corre o código do host ou o da imagem? (verificação direta)

Compara o ficheiro `/app/api/scraper_ai.py` **dentro** do contentor com o do
host: se `text_only`/`_valores_do_seletor` existirem lá, o código está montado
(as minhas edições contam sem reconstruir a imagem); se não, o contentor corre a
cópia da imagem e só uma reconstrução as aplica.

Uso::

    python -u /app/logs/_diag_codigo_montado.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FICHEIROS = (
    "/app/api/scraper_ai.py",
    "/app/api/benchmarks_service.py",
    "/app/api/benchmarks_routes.py",
)

for caminho in FICHEIROS:
    ficheiro = Path(caminho)
    if not ficheiro.exists():
        print(f"{caminho}: não existe")
        continue
    texto = ficheiro.read_text(encoding="utf-8", errors="replace")
    marcas = [m for m in ("_valores_do_seletor", "analyze_products", "sondar_loja", "text_only") if m in texto]
    digest = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]
    print(f"{caminho}: {ficheiro.stat().st_size} bytes · sha1={digest} · marcas={marcas}")

print("montado /app ?", os.path.ismount("/app"), "| /app/logs tem", len(list(Path("/app/logs").glob("*.py"))), "scripts")
