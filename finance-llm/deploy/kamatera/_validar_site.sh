#!/bin/sh
# As rotas /site/ chegam ao backend, ou caem no fallback da SPA?
#
# Corre na VM:  ssh ... "sh -s" < _validar_site.sh
#
# As rotas do site publico sao servidas pelo FastAPI (`backend:8000/site/*`) e o
# nginx do frontend faz-lhes proxy. Sem esse `location`, `/site/blog` cai no
# `try_files ... /index.html` da SPA e devolve a pagina do React -- que mostra
# "A validar a sessao...". Um `200` nao distingue os dois casos: e preciso ver o
# `content-type` e o conteudo.
#
# Este script existe como ficheiro porque um `for` com `$u` escrito dentro de uma
# string do PowerShell e expandido **no PC** (o `$u` era uma variavel da sessao,
# de um loop anterior) e o comando remoto chegava com o endereco errado.
set -u

BASE=http://127.0.0.1:4180

echo "=== o bloco /site/ esta mesmo na config do contentor? ==="
docker exec iqos-frontend grep -c 'location /site/' /etc/nginx/conf.d/default.conf

echo
echo "=== rotas ==="
for CAMINHO in /site /site/ /site/blog /site/rss.xml /site/sobre; do
    printf '  %-14s ' "$CAMINHO"
    curl -s -o /tmp/iqos_site_body -m 20 -w '%{http_code}  %{content_type}' "$BASE$CAMINHO"
    # O primeiro titulo do corpo diz de que pagina se trata. Se for a SPA, o
    # corpo e o index.html do Vite (tem <div id="root">); se for o site, e HTML
    # gerado pelo backend.
    MARCA=$(grep -o -m1 -E '<div id="root">|<title>[^<]*' /tmp/iqos_site_body 2>/dev/null | head -1)
    printf '  %s\n' "$MARCA"
done

echo
echo "=== o que o backend responde directamente (sem nginx) ==="
for CAMINHO in /site/ /site/blog; do
    printf '  %-14s ' "$CAMINHO"
    curl -s -o /dev/null -m 20 -w '%{http_code}  %{content_type}\n' "http://127.0.0.1:8002$CAMINHO"
done

rm -f /tmp/iqos_site_body
