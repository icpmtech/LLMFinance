FROM python:3.12-alpine

WORKDIR /app

# Sem dependencias externas: so a biblioteca padrao, como no `landing`. A
# imagem fica em ~50 MB e nao traz nenhum cliente do Docker -- fala com a API
# pelo socket unix com o `http.client` da biblioteca padrao.
COPY server.py ./
COPY index.html app.css app.js ./

ENV PYTHONUNBUFFERED=1 \
    PORT=8091 \
    BASE_PATH=/monitor \
    MONITOR_BIND=127.0.0.1

EXPOSE 8091

# O `landing` usa 30s; aqui nao ha pressa e um healthcheck frequente so polui.
HEALTHCHECK --interval=60s --timeout=4s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8091/monitor/healthz || exit 1

CMD ["python", "server.py"]
