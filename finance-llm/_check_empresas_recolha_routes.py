"""Verifica as rotas do módulo de recolha de empresas no esquema OpenAPI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.main import app  # noqa: E402

schema = app.openapi()
paths = sorted(p for p in schema["paths"] if p.startswith("/empresas-recolha"))
print(json.dumps(paths, ensure_ascii=False, indent=2))
