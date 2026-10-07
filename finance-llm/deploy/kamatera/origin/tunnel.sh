#!/bin/sh
# Tunel SSH reverso: publica a stack local (PC) no loopback da VM do edge.
#
#     VM 127.0.0.1:$REMOTE_PORT  ->  $LOCAL_TARGET (a stack do PC)
#
# O Caddy da VM faz `reverse_proxy http://127.0.0.1:$REMOTE_PORT`, pelo que
# https://sabemos.studio serve a SPA + API sem Cloudflare e com um endereco que
# nunca muda.
#
# Corre em Docker (`restart: unless-stopped`): sobrevive ao fecho do terminal e
# a reinicios do PC. O ciclo `while` religa quando a ligacao cai.
set -eu

: "${SSH_HOST:?falta SSH_HOST}"
SSH_USER="${SSH_USER:-root}"
REMOTE_PORT="${REMOTE_PORT:-8080}"
LOCAL_TARGET="${LOCAL_TARGET:-host.docker.internal:4180}"
RETRY_SECONDS="${RETRY_SECONDS:-5}"

mkdir -p /root/.ssh
chmod 700 /root/.ssh

# A chave entra por volume read-only; copiamos para garantir as permissoes
# (o ssh recusa chaves legiveis por outros). O nome do ficheiro vem do
# `SSH_KEY_FILE` porque a chave nao se chama `id_ed25519`.
KEY_NAME="${SSH_KEY_FILE:-id_ed25519}"
KEY="/root/.ssh/$KEY_NAME"
if [ ! -f "/key/$KEY_NAME" ]; then
    echo "[tunnel] ERRO: nao encontro a chave /key/$KEY_NAME" >&2
    echo "[tunnel]       ficheiros em /key: $(ls /key 2>/dev/null | tr '\n' ' ')" >&2
    exit 1
fi
cp "/key/$KEY_NAME" "$KEY"
chmod 600 "$KEY"

touch /root/.ssh/known_hosts

log() { echo "[tunnel] $(date -Is) $*"; }

# Se uma sessao anterior morreu sem FIN, o sshd da VM fica com o listen preso e
# a religacao falha com "remote port forwarding failed". Nada mais usa este
# porto na VM, por isso e seguro libertar antes de cada tentativa.
clean_port() {
    ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 \
        -o UserKnownHostsFile=/root/.ssh/known_hosts \
        -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR \
        "$SSH_USER@$SSH_HOST" \
        "pids=\$(ss -ltnpH 'sport = :$REMOTE_PORT' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2); [ -n \"\$pids\" ] && kill \$pids 2>/dev/null; exit 0" \
        >/dev/null 2>&1 || true
}

log "a ligar $SSH_USER@$SSH_HOST  -R 127.0.0.1:$REMOTE_PORT -> $LOCAL_TARGET"

while true; do
    ssh -N -T \
        -i "$KEY" \
        -o BatchMode=yes \
        -o ExitOnForwardFailure=yes \
        -o ConnectTimeout=10 \
        -o ServerAliveInterval=15 \
        -o ServerAliveCountMax=4 \
        -o TCPKeepAlive=yes \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile=/root/.ssh/known_hosts \
        -o LogLevel=ERROR \
        -R "127.0.0.1:$REMOTE_PORT:$LOCAL_TARGET" \
        "$SSH_USER@$SSH_HOST" || true

    log "tunel caiu (exit $?); a libertar o porto remoto e a repetir em ${RETRY_SECONDS}s"
    clean_port
    sleep "$RETRY_SECONDS"
done
