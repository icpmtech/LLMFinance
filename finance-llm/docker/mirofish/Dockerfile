# MiroFish — motor de previsão por inteligência de enxame (Swarm Intelligence).
#
# Imagem oficial do projeto (https://github.com/666ghj/MiroFish) com **um patch
# de uma linha**, necessário para o incorporar no IQ OS como página iframe.
#
# Porquê o patch
# --------------
# A SPA do MiroFish chama a API num URL **absoluto** quando `VITE_API_BASE_URL`
# não está definido:
#
#     baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'
#
# Incorporada por iframe no proxy de nginx do IQ OS (`http://<host>:8893/`, ver
# `docker/nginx.conf`), a palavra `localhost` passaria a apontar para a máquina
# do **browser** e não para o container: a app só funcionaria em `127.0.0.1` e,
# com a plataforma servida por HTTPS (túnel/edge), os pedidos seriam ainda
# bloqueados por conteúdo misto.
#
# O patch troca o valor por omissão por um caminho **relativo**, que segue a
# origem da página: o nginx do IQ OS encaminha depois `/api/` para o backend do
# MiroFish (`mirofish:5001`).
#
# Porque é que editar um ficheiro basta: a imagem oficial arranca o frontend em
# modo *dev* (`npm run dev` → Vite dev server), que serve o **código-fonte** —
# o `frontend/src/api/index.js` é lido do disco a cada pedido, portanto a
# alteração aplica-se sem reconstruir o bundle.
#
# Espelho (se o pull da ghcr.io for lento):
#   docker compose --profile mirofish build \
#     --build-arg MIROFISH_BASE_IMAGE=ghcr.nju.edu.cn/666ghj/mirofish:latest mirofish
ARG MIROFISH_BASE_IMAGE=ghcr.io/666ghj/mirofish:latest
FROM ${MIROFISH_BASE_IMAGE}

# `grep` antes e depois do `sed`: se o upstream mudar a linha, a build falha em
# vez de seguir com um patch silenciosamente inútil.
RUN set -eux; \
    f=/app/frontend/src/api/index.js; \
    grep -q "import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'" "$f"; \
    sed -i "s|import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'|import.meta.env.VITE_API_BASE_URL ?? ''|" "$f"; \
    grep -q "import.meta.env.VITE_API_BASE_URL ?? ''" "$f"
