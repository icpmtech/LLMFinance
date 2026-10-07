# Tunel SSH reverso PC -> VM do edge, sem Cloudflare.
FROM alpine:3.20

RUN apk add --no-cache openssh-client

COPY tunnel.sh /tunnel.sh
# O ficheiro vem do Windows com CRLF: um `\r` colado ao fim de cada linha parte
# as redirecoes e os `case`. Normalizar antes de usar.
RUN sed -i 's/\r$//' /tunnel.sh && chmod +x /tunnel.sh

ENTRYPOINT ["/bin/sh", "/tunnel.sh"]
