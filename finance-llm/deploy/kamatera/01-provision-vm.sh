# Executado NA VM (Ubuntu 24.04) — prepara o host para a solucao em Docker.
#
# Instala Docker Engine + plugin Compose, cria um swap de 2 GB (a VM mais barata
# tem 2 GB de RAM; o swap evita OOM durante builds) e liga o servico.
#
# Uso:  scp este ficheiro para a VM e correr "bash 01-provision-vm.sh"
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
    echo "==> a instalar Docker Engine + Compose"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
else
    echo "==> Docker ja instalado"
fi

systemctl enable --now docker

# Swap de 2 GB (idempotente).
if ! swapon --show | grep -q '/swapfile'; then
    echo "==> a criar swap de 2 GB"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

echo "==> versoes"
docker --version
docker compose version
free -h
df -h / | tail -1
