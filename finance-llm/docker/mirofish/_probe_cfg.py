"""Mostra as pastas de dados do MiroFish e o seu conteúdo.

Corre a partir de /app/backend (onde o pacote `app` é importável):
    docker exec -w /app/backend <container> python3 /tmp/_probe_cfg.py
"""
import os
import sys

sys.path.insert(0, "/app/backend")

from app.config import Config  # noqa: E402

for key in sorted(dir(Config)):
    if key.isupper() and any(token in key for token in ("FOLDER", "DIR", "PATH")):
        value = getattr(Config, key)
        if isinstance(value, str):
            exists = os.path.isdir(value)
            print(f"{key} = {value}  (dir={exists})")
            if exists and key == "UPLOAD_FOLDER":
                for entry in sorted(os.listdir(value))[:10]:
                    full = os.path.join(value, entry)
                    kind = "dir" if os.path.isdir(full) else "file"
                    print(f"    {kind}: {entry}")
