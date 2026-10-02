# Executado NA VM: prepara o host (swap) e arranca o edge (nginx + cloudflared).
#
# Uso:  bash /opt/iqos/05-edge-up.sh <hostname-da-origem>
#   <hostname-da-origem> = o que o quick tunnel do PC publica, ex.:
#   uniprotkb-cents-kits-coupled.trycloudflare.com
set -euo pipefail

ORIGIN_HOSTNAME="${1:-}"
if [ -z "$ORIGIN_HOSTNAME" ]; then
    if [ -f /opt/iqos/edge/edge.env ]; then
        ORIGIN_HOSTNAME="$(sed -n 's/^ORIGIN_HOSTNAME=//p' /opt/iqos/edge/edge.env | tr -d '\r')"
    fi
fi
if [ -z "$ORIGIN_HOSTNAME" ]; then
    echo "ERRO: falta o hostname da origem (argumento 1)" >&2
    exit 1
fi
echo "==> origem: $ORIGIN_HOSTNAME"

# 1) Swap de 2 GB. Sem isto a VM de 2 GB fica sem memoria quando o Docker
#    arranca e o proprio sshd deixa de conseguir fazer fork (a sessao SSH
#    bloqueia no key exchange sem dar erro).
if ! swapon --show | grep -q '/swapfile'; then
    echo "==> a criar swap de 2 GB"
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# 2) edge.env (com LF; um \r colado ao valor entra no SNI e o proxy falha).
printf 'ORIGIN_HOSTNAME=%s\n' "$ORIGIN_HOSTNAME" > /opt/iqos/edge/edge.env

# 3) Arrancar o edge.
cd /opt/iqos/edge
docker compose up -d --remove-orphans

echo "==> a aguardar o tunel publicar o endereco"
for _ in $(seq 1 20); do
    sleep 3
    if docker logs iqos-tunnel 2>&1 | grep -qo 'https://[a-z0-9-]*\.trycloudflare\.com'; then
        break
    fi
done

echo
echo "==> containers"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo
echo "==> endereco publico"
docker logs iqos-tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | head -1 || true
echo
echo "==> recursos"
free -h
df -h / | tail -1
