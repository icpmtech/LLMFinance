"""Regista o blueprint do IQ OS (apagar e exportar simulações) no backend.

O `backend/app` do MiroFish é substituído pelo do upstream na build, por isso o
módulo `app/api/iqos_export.py` é copiado e este script acrescenta a duas linhas
que o dão a conhecer ao Flask:

    from .api.iqos_export import iqos_bp
    app.register_blueprint(iqos_bp, url_prefix='/api/iqos')

É idempotente (correr duas vezes não duplica o registo) e falha a build se o
ponto de inserção desaparecer: sem ele, as rotas ficariam na imagem sem
resposta, e um 404 silencioso é pior do que uma build vermelha.

Correr dentro do contentor (feito na build da imagem, ver `Dockerfile`).
"""
from __future__ import annotations

import pathlib
import sys

INIT = pathlib.Path("/app/backend/app/__init__.py")

#: Onde o registo é inserido: logo a seguir aos blueprints do upstream.
ANCHOR = "    app.register_blueprint(report_bp, url_prefix='/api/report')\n"

MARKER = "from .api.iqos_export import iqos_bp"

BLOCK = (
    "\n"
    "    # Extensão do IQ OS: apagar simulações e exportar para Excel/PDF.\n"
    "    from .api.iqos_export import iqos_bp\n"
    "    app.register_blueprint(iqos_bp, url_prefix='/api/iqos')\n"
)


def main() -> int:
    if not INIT.exists():
        print(f"[iqos_admin_patch] {INIT} não existe", file=sys.stderr)
        return 1

    text = INIT.read_text(encoding="utf-8")
    if MARKER in text:
        # Verificação: já registado, mas tem de estar mesmo a registar o blueprint.
        if "app.register_blueprint(iqos_bp" not in text:
            print("[iqos_admin_patch] marcador presente mas registo em falta", file=sys.stderr)
            return 1
        print("[iqos_admin_patch] já registado")
        return 0

    if ANCHOR not in text:
        print(
            "[iqos_admin_patch] ponto de inserção não encontrado "
            "(o upstream mudou o registo dos blueprints)",
            file=sys.stderr,
        )
        return 1

    INIT.write_text(text.replace(ANCHOR, ANCHOR + BLOCK, 1), encoding="utf-8")

    # Confirmação no disco: sem isto, uma falha de escrita passaria despercebida.
    final = INIT.read_text(encoding="utf-8")
    if MARKER not in final or "iqos_bp, url_prefix='/api/iqos'" not in final:
        print("[iqos_admin_patch] o registo não ficou no ficheiro", file=sys.stderr)
        return 1

    print("[iqos_admin_patch] blueprint /api/iqos registado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
