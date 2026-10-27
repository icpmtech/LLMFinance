"""Snippet do widget de apoio nas páginas servidas pelo backend.

O site do CMS (`/site/...`) e a loja (`/loja/...`) são HTML montado no servidor
e não passam pela SPA. Este snippet carrega o widget autocontido
(`api/support_widget.js`, servido em `/support/widget.js`) através do prefixo
`/api`, que o nginx (produção) e o proxy do Vite (desenvolvimento) encaminham
para o backend.

A SPA monta o mesmo widget por `chat-ui/src/components/SupportChat.tsx`, com a
base da API que tiver configurada (`VITE_API_URL` ou `/api`).
"""
from __future__ import annotations

WIDGET_PATH = "/api/support/widget.js"
SUPPORT_API_BASE = "/api"

SUPPORT_SNIPPET = (
    f'<script>window.__IQOS_SUPPORT_API__="{SUPPORT_API_BASE}";</script>'
    f'<script async src="{WIDGET_PATH}" data-iqos-support '
    f'data-api-base="{SUPPORT_API_BASE}"></script>'
)
