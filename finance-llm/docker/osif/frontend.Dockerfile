# OSIF (OSINT Framework v2) — frontend Vue 3, compilado e servido por nginx.
#
# O contexto de build é `docker/osif/` (e não `docker/osif/src/frontend/`) por uma
# razão: assim pode sobrepor-se a configuração do nginx da aplicação. O nginx do
# upstream faz `proxy_pass http://backend:6000` em `/api` e `/ws` **sem variável**,
# o que o obriga a resolver o nome no arranque; com o serviço chamado
# `osif-backend` (não `backend`) o nginx não arrancava. Aqui o `default.conf` é
# substituído por um que serve **apenas ficheiros estáticos**; o proxy para a API
# é feito no nginx do IQ OS (porta de incorporação, ver `docker/nginx.conf`).
FROM node:20-alpine AS builder

WORKDIR /app

ARG VITE_MAPBOX_TOKEN=
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN

COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY src/frontend/ .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY frontend-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
