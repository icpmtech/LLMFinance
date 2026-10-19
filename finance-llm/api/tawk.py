"""Widget de apoio ao cliente (Tawk.to) das páginas públicas.

O site do CMS (`/site/...`) e a loja (`/loja/...`) são HTML autónomo, montado no
servidor, e não passam pela SPA; a SPA (landing, login e registo) monta o mesmo
widget pelo React (`chat-ui/src/components/TawkChat.tsx`). A propriedade tem de
ser a mesma dos dois lados — é a que está configurada no painel do Tawk.to.
"""
from __future__ import annotations

#: Propriedade do Tawk.to (`<property_id>/<widget_id>`).
TAWK_PROPERTY = "6ac786035f2ded34cbd1cbeb/1k4dm7048"

#: Snippet oficial do Tawk.to, para o `<head>`. Cria o `<script>` de forma
#: assíncrona e mantém `Tawk_API`/`Tawk_LoadStart` globais, como o original.
TAWK_SNIPPET = (
    "<script>"
    "var Tawk_API=window.Tawk_API||{},Tawk_LoadStart=new Date();"
    "(function(){"
    "var s1=document.createElement('script'),s0=document.getElementsByTagName('script')[0];"
    "s1.async=true;"
    f"s1.src='https://embed.tawk.to/{TAWK_PROPERTY}';"
    "s1.charset='UTF-8';"
    "s1.setAttribute('crossorigin','*');"
    "s0.parentNode.insertBefore(s1,s0);"
    "})();"
    "</script>"
)
