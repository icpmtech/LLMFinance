FROM python:3.12-alpine

WORKDIR /app

# Sem dependencias externas: basta a biblioteca padrao.
COPY server.py ./
COPY index.html app.css app.js ./
COPY img ./img

ENV PYTHONUNBUFFERED=1 \
    REGISTOS_PATH=/data/registos.json \
    PORT=8090

VOLUME ["/data"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8090/healthz || exit 1

CMD ["python", "server.py"]
