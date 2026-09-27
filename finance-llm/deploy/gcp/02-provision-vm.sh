#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# IQ OS — edge na Google Cloud (e2-micro, free tier)
#
# Cria: projeto (opcional), billing link, API do Compute, firewall (SSH só por
# IAP) e a VM e2-micro com Debian 12 + Docker + cloudflared.
#
# CORRE NO CLOUD SHELL (https://shell.cloud.google.com) — não precisas de
# instalar o gcloud no PC:
#     bash 02-provision-vm.sh
#
# Tudo é configurável por variáveis de ambiente, ex.:
#     PROJECT_ID=iqos-edge-2711 REGION=us-east1 bash 02-provision-vm.sh
# ---------------------------------------------------------------------------
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-iqos-edge}"
VM_NAME="${VM_NAME:-iqos-edge}"
# Free tier do Compute Engine só existe em us-central1, us-east1 e us-west1.
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-${REGION}-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-micro}"
# 30 GB é o limite do free tier (pd-standard).
DISK_GB="${DISK_GB:-30}"
NETWORK="${NETWORK:-default}"
SUBNET="${SUBNET:-default}"
# Standard Tier: o tráfego de saída é gratuito até 200 GiB/mês (o free tier
# "1 GB" do Premium Tier esgotava-se em poucos dias de uso da SPA).
NETWORK_TIER="${NETWORK_TIER:-STANDARD}"
FIREWALL_RULE="${FIREWALL_RULE:-iqos-edge-ssh-iap}"
IAP_RANGE='35.235.240.0/20'

log()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mOK\033[0m  %s\n' "$*"; }
warn() { printf '    \033[33m!!\033[0m  %s\n' "$*"; }
die()  { printf '    \033[31mXX\033[0m  %s\n' "$*" >&2; exit 1; }

log 'Verificar o ambiente'
command -v gcloud >/dev/null || die 'gcloud não encontrado (corre isto no Cloud Shell).'
ok "conta: $(gcloud config get-value account 2>/dev/null)"

log "Projeto $PROJECT_ID"
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  ok 'já existe'
else
  gcloud projects create "$PROJECT_ID" --name='IQ OS Edge' \
    || die "Não consegui criar o projeto '$PROJECT_ID' (o ID é único a nível mundial — usa outro: PROJECT_ID=iqos-edge-XXXX bash $0)"
  ok 'criado'
fi
gcloud config set project "$PROJECT_ID" >/dev/null
ok "projeto ativo: $PROJECT_ID"

log 'Billing'
BILLING_ACCOUNT="${BILLING_ACCOUNT:-$(gcloud billing accounts list --filter='open=true' --format='value(name)' | head -n1 | cut -d/ -f2 || true)}"
[ -n "$BILLING_ACCOUNT" ] || die 'Sem conta de billing aberta. Cria uma em https://console.cloud.google.com/billing (o free tier exige billing ativo, mesmo sem custos).'
if gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  ok 'já ligado'
else
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
  ok "ligado a $BILLING_ACCOUNT"
fi

log 'Ativar API do Compute Engine'
gcloud services enable compute.googleapis.com --project "$PROJECT_ID"
ok 'compute.googleapis.com'

log 'Rede e firewall'
if ! gcloud compute networks describe "$NETWORK" --project "$PROJECT_ID" >/dev/null 2>&1; then
  warn "rede '$NETWORK' não existe — a criar iqos-edge-vpc (sem regras de entrada abertas)"
  NETWORK='iqos-edge-vpc'
  SUBNET="iqos-edge-${REGION}"
  gcloud compute networks create "$NETWORK" --project "$PROJECT_ID" --subnet-mode=custom >/dev/null
  gcloud compute networks subnets create "$SUBNET" --project "$PROJECT_ID" \
    --network "$NETWORK" --region "$REGION" --range 10.10.0.0/24 >/dev/null
  ok '$NETWORK criada'
else
  ok "rede '$NETWORK'"
fi

if gcloud compute firewall-rules describe "$FIREWALL_RULE" --project "$PROJECT_ID" >/dev/null 2>&1; then
  ok 'regra de firewall já existe'
else
  gcloud compute firewall-rules create "$FIREWALL_RULE" --project "$PROJECT_ID" \
    --network "$NETWORK" --allow tcp:22 --source-ranges "$IAP_RANGE" \
    --target-tags iqos-edge --description 'SSH apenas via Identity-Aware Proxy' >/dev/null
  ok 'SSH só por IAP (35.235.240.0/20)'
fi

# Aviso de higiene: a regra por omissão do GCP abre o 22 a todo o mundo.
if gcloud compute firewall-rules describe default-allow-ssh --project "$PROJECT_ID" >/dev/null 2>&1; then
  warn "existe 'default-allow-ssh' (0.0.0.0/0). Como usamos IAP, considera apagá-la:"
  warn "  gcloud compute firewall-rules delete default-allow-ssh --project $PROJECT_ID"
fi
warn 'Não é preciso abrir 80/443: o cloudflared é só de saída (túnel).'

log "Criar a VM $VM_NAME ($MACHINE_TYPE, ${DISK_GB} GB, $ZONE)"
[ "$MACHINE_TYPE" = 'e2-micro' ] || warn "com $MACHINE_TYPE já sais do free tier (e2-micro é o único gratuito)"
[ "$NETWORK_TIER" = 'STANDARD' ] && ok 'Standard Tier (egress grátis até 200 GiB/mês)'

cat > /tmp/iqos-edge-startup.sh <<'BOOTSTRAP'
#!/bin/sh
# Bootstrap da VM do edge: swap, Docker e cloudflared. Idempotente.
# Deliberadamente POSIX sh: o serviço de startup scripts do GCE pode correr o
# ficheiro com /bin/sh, onde `set -o pipefail` e process substitution falham.
set -eux
exec >>/var/log/iqos-edge-bootstrap.log 2>&1
export DEBIAN_FRONTEND=noninteractive

# --- swap 1 GB (rede de segurança num VM de 1 GB de RAM) ---
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg jq

# --- Docker + compose plugin ---
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

# --- cloudflared (túnel só de saída) ---
if ! command -v cloudflared >/dev/null 2>&1; then
  curl -fsSL -o /tmp/cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i /tmp/cloudflared.deb
fi

mkdir -p /opt/iqos-edge/templates
printf 'bootstrap ok %s\n' "$(date -Is)" > /opt/iqos-edge/.ready
BOOTSTRAP

SUBNET_FLAG=()
if [ "$NETWORK" != 'default' ]; then SUBNET_FLAG=(--subnet "$SUBNET"); fi

gcloud compute instances describe "$VM_NAME" --project "$PROJECT_ID" --zone "$ZONE" >/dev/null 2>&1 \
  && ok 'instância já existe (não vou recriar)' \
  || {
    gcloud compute instances create "$VM_NAME" \
      --project "$PROJECT_ID" --zone "$ZONE" \
      --machine-type "$MACHINE_TYPE" \
      --image-family debian-12 --image-project debian-cloud \
      --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-standard \
      --network "$NETWORK" "${SUBNET_FLAG[@]}" \
      --network-tier "$NETWORK_TIER" \
      --tags iqos-edge \
      --labels app=iqos,role=edge \
      --metadata-from-file startup-script=/tmp/iqos-edge-startup.sh
    ok 'criada'
  }

log 'Esperar pelo bootstrap (docker + cloudflared)'
READY=''
for _ in $(seq 1 40); do
  if gcloud compute ssh "$VM_NAME" --project "$PROJECT_ID" --zone "$ZONE" \
       --tunnel-through-iap --command 'test -f /opt/iqos-edge/.ready' --quiet >/dev/null 2>&1; then
    READY=1; break
  fi
  printf '.'
  sleep 15
done
echo ''
[ -n "$READY" ] || die "O bootstrap não terminou. Vê o log na VM: sudo tail -50 /var/log/iqos-edge-bootstrap.log"
ok 'VM pronta'

IP="$(gcloud compute instances describe "$VM_NAME" --project "$PROJECT_ID" --zone "$ZONE" \
      --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null || true)"

cat <<EOF

================================================================================
VM PRONTA
================================================================================
  projeto : $PROJECT_ID
  instância: $VM_NAME ($ZONE, $MACHINE_TYPE, ${DISK_GB} GB pd-standard, $NETWORK_TIER)
  IP      : ${IP:-<sem IP externo>}

Custo esperado: a VM e o disco (30 GB pd-standard) caem no free tier; o único
valor fora dele é o IP externo, ~\$0.005/h ≈ \$3.65/mês. O egress fica gratuito
até 200 GiB/mês por estar em Standard Tier.

A SEGUIR (ainda no Cloud Shell):
  1) envia o token do túnel do edge para cá (fica em ~/.cloudflared/<UUID>.json
     no teu PC) — UPLOAD > File, ou arrasta para o Cloud Shell
  2) corre:  bash 03-configure-edge.sh
EOF
