# MiroFish — motor de previsão por inteligência de enxame (Swarm Intelligence).
#
# Esta imagem parte da imagem oficial publicada (`ghcr.io/666ghj/mirofish`), que
# já traz o runtime completo (Python 3.11 + Node 20.19 + uv + caches de
# dependências), **sobrepõe-lhe o código atual do projeto** e aplica quatro
# ajustes para o incorporar no IQ OS como página iframe:
#
#   1. interface em **português** (idioma por omissão, com fallback em inglês);
#   2. base da API **relativa** (senão a app só funciona em `localhost`);
#   3. respostas do **LLM em português** (os prompts do upstream são em chinês e
#      as personas/publicações saíam em chinês);
#   4. mensagens do backend (progresso e erros) em português.
#
# Porque é que o código é sobreposto
# ----------------------------------
# A imagem publicada (tags `latest` e `v0.1.2`, o mesmo digest) é um instantâneo
# **anterior à camada de tradução**: não tem `locales/` nem `frontend/src/i18n`,
# ou seja a interface só existe em chinês e não há maneira de a pôr em português
# sem trazer o código atual. O código vem do repositório oficial (por omissão
# `main`), configurável com `--build-arg MIROFISH_TARBALL=...`.
#
# Só se substituem os diretórios de código (`frontend/src`, `backend/app`,
# `locales`) e depois se reinstalam as dependências — o `node_modules`,
# `backend/.venv` e os caches da imagem base são reaproveitados, portanto a build
# descarrega apenas o que mudou.
#
# Porquê o ajuste da base da API
# ------------------------------
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
# O ajuste troca o valor por omissão por uma cadeia **vazia** (base relativa), que
# segue a origem da página: o nginx do IQ OS encaminha depois `/api/` para o
# backend do MiroFish (`mirofish:5001`).
#
#     baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001',
#  -> baseURL: import.meta.env.VITE_API_BASE_URL || '',
#
# Porque é que editar ficheiros basta: a imagem oficial arranca o frontend em
# modo *dev* (`npm run dev` → Vite dev server), que serve o **código-fonte** —
# o `frontend/src/api/index.js` e o `frontend/src/i18n/index.js` são lidos do
# disco a cada pedido, portanto os ajustes aplicam-se sem reconstruir o bundle.
# O `locales/pt.json` é lido pelo frontend (vue-i18n) e pelo backend no arranque.
#
# Espelho e versão fixa (se o pull da ghcr.io for lento):
#   docker compose --profile mirofish build \
#     --build-arg MIROFISH_BASE_IMAGE=ghcr.nju.edu.cn/666ghj/mirofish:v0.1.2 \
#     --build-arg MIROFISH_TARBALL=https://github.com/666ghj/MiroFish/archive/refs/tags/v0.1.2.tar.gz \
#     mirofish
ARG MIROFISH_BASE_IMAGE=ghcr.io/666ghj/mirofish:v0.1.2
FROM ${MIROFISH_BASE_IMAGE}

# Código do projeto (tarball do GitHub). `main` acompanha o desenvolvimento;
# usar o URL de uma tag para uma versão fixa.
ARG MIROFISH_TARBALL=https://github.com/666ghj/MiroFish/archive/refs/heads/main.tar.gz

# ---------------------------------------------------------------------------
# 1) Código atual sobre o da imagem
# ---------------------------------------------------------------------------
RUN set -eux; \
    mkdir -p /tmp/mirofish; \
    curl -fsSL "$MIROFISH_TARBALL" | tar -xz --strip-components=1 -C /tmp/mirofish; \
    rm -rf /app/locales /app/frontend/src /app/backend/app; \
    cp -a /tmp/mirofish/. /app/; \
    rm -rf /tmp/mirofish

# ---------------------------------------------------------------------------
# 2) Dependências alinhadas com esse código
#    (frontend: vue-i18n e Vite 7; backend: uv.lock atualizado)
# ---------------------------------------------------------------------------
RUN set -eux; \
    cd /app; \
    npm ci --no-audit --no-fund; \
    cd /app/frontend; \
    npm ci --no-audit --no-fund; \
    cd /app/backend; \
    uv sync --frozen

# ---------------------------------------------------------------------------
# 3) Interface em português
#
# O upstream só traz `zh` e `en` em `locales/`, mas o registo de idiomas
# (`locales/languages.json`) já conhece `pt`. Basta acrescentar a tradução — o
# frontend (vue-i18n) e o backend (que carrega `locales/*.json` e escolhe o
# idioma pelo cabeçalho `Accept-Language`) passam a ter português, incluindo as
# mensagens de erro da API e a instrução de idioma dada ao LLM.
# ---------------------------------------------------------------------------
COPY locales/pt.json /app/locales/pt.json

# Idioma por omissão da interface: `pt` (em vez de `zh`) e fallback em inglês
# para as chaves que venham a faltar depois de uma atualização do upstream.
RUN set -eux; \
    f=/app/frontend/src/i18n/index.js; \
    grep -q "localStorage.getItem('locale') || 'zh'" "$f"; \
    sed -i "s#localStorage.getItem('locale') || 'zh'#localStorage.getItem('locale') || 'pt'#" "$f"; \
    grep -q "localStorage.getItem('locale') || 'pt'" "$f"; \
    grep -q "fallbackLocale: 'zh'" "$f"; \
    sed -i "s#fallbackLocale: 'zh'#fallbackLocale: 'en'#" "$f"; \
    grep -q "fallbackLocale: 'en'" "$f"

# Título, descrição e idioma do documento: o vue-i18n trata do conteúdo da app,
# mas estes três valores são estáticos no `index.html` (o título é o que aparece
# no separador do browser quando a app é aberta fora do iframe).
RUN set -eux; \
    f=/app/frontend/index.html; \
    grep -q '<html lang="zh">' "$f"; \
    sed -i 's#<html lang="zh">#<html lang="pt">#' "$f"; \
    sed -i "s#localStorage.getItem('locale') || 'zh'#localStorage.getItem('locale') || 'pt'#" "$f"; \
    sed -i 's#<title>[^<]*</title>#<title>MiroFish - Prever Tudo</title>#' "$f"; \
    sed -i 's#content="MiroFish - [^"]*"#content="MiroFish - Sistema de Simulação de Opinião em Redes Sociais"#' "$f"; \
    grep -q '<html lang="pt">' "$f"; \
    grep -q "<title>MiroFish - Prever Tudo</title>" "$f"; \
    grep -q "Simulação de Opinião" "$f"; \
    grep -q "localStorage.getItem('locale') || 'pt'" "$f"

# ---------------------------------------------------------------------------
# 4) Base da API relativa (ver nota no topo do ficheiro)
# ---------------------------------------------------------------------------

# `grep` antes e depois do `sed`: se o upstream mudar a linha, a build falha em
# vez de seguir com um ajuste silenciosamente inútil.
#
# Nota: o `sed` usa `#` como delimitador (o texto tem `||`) e substitui apenas o
# URL absoluto — o que sobra é `import.meta.env.VITE_API_BASE_URL || ''`.
RUN set -eux; \
    f=/app/frontend/src/api/index.js; \
    grep -q "import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'" "$f"; \
    sed -i "s#'http://localhost:5001'#''#" "$f"; \
    grep -q "import.meta.env.VITE_API_BASE_URL || ''" "$f"

# ---------------------------------------------------------------------------
# 5) Respostas do LLM em português
#
# Os *prompts* do upstream são em chinês (ontologia, personas, configuração do
# mundo, relatório) e o modelo respondia no idioma do prompt: as personas e as
# publicações dos agentes saíam em chinês, apesar da interface e do
# material-semente em português.
#
# `pt_language.py` injeta uma diretiva de idioma no único ponto por onde passam
# todos os pedidos (`LLMClient._create_completion`), ativa pelo ambiente
# `MIROFISH_REPLY_LANGUAGE` (definida no `docker-compose.yml`). É idempotente e
# não altera o corpo do método original.
# ---------------------------------------------------------------------------
COPY pt_language.py /tmp/pt_language.py
COPY pt_backend_strings.py /tmp/pt_backend_strings.py
RUN set -eux; \
    (command -v python3 >/dev/null && python3 /tmp/pt_language.py) || python /tmp/pt_language.py; \
    grep -q "_IQ_OS_REPLY_LANGUAGE" /app/backend/app/utils/llm_client.py; \
    (command -v python3 >/dev/null && python3 /tmp/pt_backend_strings.py) || python /tmp/pt_backend_strings.py; \
    grep -q "concluídos: {entity.name}" /app/backend/app/services/oasis_profile_generator.py; \
    ! grep -q '已完成 {current}/{total}' /app/backend/app/services/oasis_profile_generator.py; \
    rm -f /tmp/pt_language.py /tmp/pt_backend_strings.py

# ---------------------------------------------------------------------------
# 6) Frontend (Vite dev server, :3000) + backend (Flask, :5001) no mesmo
#    container — o mesmo comando da imagem oficial.
# ---------------------------------------------------------------------------
WORKDIR /app
CMD ["npm", "run", "dev"]
