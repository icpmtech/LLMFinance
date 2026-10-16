#!/usr/bin/env bash
# Prepara uma VM Ubuntu (22.04/24.04) com GPU NVIDIA para treinar com o Soup.
#
# Correr **dentro da VM** (o script instala Docker e o NVIDIA Container Toolkit):
#
#   scp training/soup/vm_setup.sh ubuntu@<ip>:
#   ssh ubuntu@<ip> 'bash vm_setup.sh'
#
# No fim faz um teste de fogo — um contentor CUDA a correr `nvidia-smi` — que é
# exactamente o que o `docker-compose.gpu.yml` do projecto precisa para funcionar.
set -euo pipefail

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

log "GPU visível no sistema"
if ! command -v nvidia-smi >/dev/null; then
    cat >&2 <<'AVISO'
Não há `nvidia-smi` nesta VM: falta o driver da NVIDIA.
Escolha uma imagem que já traga o driver (em qualquer fornecedor: «NVIDIA driver»,
«Deep Learning VM», «GPU image») — é o caminho sem dor de cabeça — ou instale-o à
mão (`sudo ubuntu-drivers install` + `sudo reboot`) e volte a correr este script.
AVISO
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

log "Docker"
if ! command -v docker >/dev/null; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg |
        sudo tee /etc/apt/keyrings/docker.asc >/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
        sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER" || true
    echo "(o grupo «docker» só pega num login novo; até lá, use sudo)"
fi
docker --version
docker compose version

log "NVIDIA Container Toolkit (é o que dá a GPU aos contentores)"
if ! dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
        sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' |
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
fi

log "Teste de fogo: contentor com CUDA a ver a GPU"
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 \
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

log "Resumo da máquina"
printf 'CPU:   %s cores\n' "$(nproc)"
printf 'RAM:   %s\n' "$(free -h --si | awk '/^Mem:/ {print $2}')"
printf 'Disco: %s livres em %s\n' "$(df -h --output=avail . | tail -1)" "$(pwd)"

cat <<'SEGUINTE'

Pronto. A partir daqui, dentro da VM:

  git clone https://github.com/icpmtech/LLMFinance.git && cd LLMFinance/finance-llm
  # o dataset exportado no portátil (ver docs/soup-vm.md, secção 5)
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train build soup
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train run --rm soup \
    train -y --config training/soup/soup-mistral-instruct.yaml
SEGUINTE
