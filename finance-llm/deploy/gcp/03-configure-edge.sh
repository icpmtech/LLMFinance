#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# IQ OS — configurar o edge na VM (nginx + túnel Cloudflare)
#
# Envia os ficheiros do edge para a VM, instala o cloudflared como serviço e
# arranca o container nginx. Idempotente: podes correr outra vez depois de
# mudar o `edge.env`.
#
# CORRE NO CLOUD SHELL, com a pasta deploy/gcp enviada para lá:
#     bash 03-configure-edge.sh
#
# Variáveis (todas opcionais, com deteção automática):
#     PROJECT_ID, VM_NAME, ZONE, EDGE_TUNNEL_UUID, EDGE_CREDENTIALS_JSON
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDGE_DIR="${EDGE_DIR:-$HERE/edge}"
VM_NAME="${VM_NAME:-iqos-edge}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-${REGION}-a}"
REMOTE_DIR='/opt/iqos-edge'
STAGE_NAME='iqos-edge-stage'

log()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mOK\033[0m  %s\n' "$*"; }
warn() { printf '    \033[33m!!\033[0m  %s\n' "$*"; }
die()  { printf '    \033[31mXX\033[0m  %s\n' "$*" >&2; exit 1; }

gc() { gcloud compute "$@" --project "$PROJECT_ID" --zone "$ZONE" --tunnel-through-iap --quiet; }
remote() { gc ssh "$VM_NAME" --command "$1" >/dev/null 2>&1; }

log 'Verificar ficheiros do edge'
for f in compose.yml edge.env offline.html templates/default.conf.template; do
  [ -f "$EDGE_DIR/$f" ] || die "Falta $EDGE_DIR/$f — envia a pasta deploy/gcp completa para o Cloud Shell (UPLOAD > Folder)."
done
ok "edge/ completo em $EDGE_DIR"

# Hostname público: vem do resumo escrito por 01-setup-tunnels.ps1.
INFO_FILE="$HERE/origin/edge-tunnel-info.txt"
if [ -z "${PUBLIC_HOST:-}" ] && [ -f "$INFO_FILE" ]; then
  PUBLIC_HOST="$(tr -d '\r' < "$INFO_FILE" | sed -n 's/^PUBLIC_HOST=//p')"
fi
[ -n "${PUBLIC_HOST:-}" ] \
  || die 'Falta PUBLIC_HOST (cria deploy/gcp/origin/edge-tunnel-info.txt com 01-setup-tunnels.ps1, ou passa PUBLIC_HOST=iqos.exemplo.com).'
ok "público: $PUBLIC_HOST"
if grep -q 'exemplo.com' "$EDGE_DIR/edge.env"; then
  die 'edge.env ainda tem os valores de exemplo (exemplo.com). Preenche ORIGIN_HOSTNAME e o service token do Access.'
fi

# Os ficheiros podem vir do Windows com CRLF: um `\r` no fim de uma linha do
# edge.env cola-se ao valor da variável e o hostname/service token ficam inválidos.
STAGE="/tmp/$STAGE_NAME"
rm -rf "$STAGE"; mkdir -p "$STAGE/templates"
for f in compose.yml edge.env offline.html; do
  tr -d '\r' < "$EDGE_DIR/$f" > "$STAGE/$f"
done
tr -d '\r' < "$EDGE_DIR/templates/default.conf.template" > "$STAGE/templates/default.conf.template"

set -a; . "$STAGE/edge.env"; set +a
[ -n "${ORIGIN_HOSTNAME:-}" ] || die 'ORIGIN_HOSTNAME vazio em edge.env'
[ -n "${CF_ACCESS_CLIENT_ID:-}" ] || die 'CF_ACCESS_CLIENT_ID vazio em edge.env'
[ -n "${CF_ACCESS_CLIENT_SECRET:-}" ] || die 'CF_ACCESS_CLIENT_SECRET vazio em edge.env'
ok "origem: $ORIGIN_HOSTNAME"

log 'Verificar credenciais do túnel do edge'
if [ -z "${EDGE_CREDENTIALS_JSON:-}" ]; then
  EDGE_CREDENTIALS_JSON="$(find "$HERE" "$HOME" -maxdepth 2 -name '*.json' \
      -regextype posix-extended -regex '.*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json' \
      2>/dev/null | head -n1 || true)"
fi
[ -n "${EDGE_CREDENTIALS_JSON:-}" ] && [ -f "$EDGE_CREDENTIALS_JSON" ] \
  || die 'Não encontrei o <UUID>.json do túnel iqos-edge. Faz UPLOAD do ficheiro ~/.cloudflared/<UUID>.json do teu PC.'
EDGE_TUNNEL_UUID="${EDGE_TUNNEL_UUID:-$(basename "$EDGE_CREDENTIALS_JSON" .json)}"
[[ "$EDGE_TUNNEL_UUID" =~ ^[0-9a-f-]{36}$ ]] || die "UUID inválido: $EDGE_TUNNEL_UUID"
ok "túnel $EDGE_TUNNEL_UUID ($EDGE_CREDENTIALS_JSON)"

log 'Projeto e VM'
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
[ -n "$PROJECT_ID" ] || die 'Sem PROJECT_ID (gcloud config set project ...)'
gcloud compute instances describe "$VM_NAME" --project "$PROJECT_ID" --zone "$ZONE" >/dev/null 2>&1 \
  || die "VM '$VM_NAME' não existe em $ZONE. Corre primeiro 02-provision-vm.sh"
ok "$VM_NAME em $PROJECT_ID/$ZONE"

remote 'true' || die 'Não consigo abrir sessão SSH na VM (IAP). Verifica a firewall e o papel de utilizador.'

log 'Preparar ficheiros'
cat > "$STAGE/cloudflared-config.yml" <<EOF
# Config do túnel do EDGE (gerada por 03-configure-edge.sh).
# Publica a internet neste nginx; e o nginx que fala com a origem.
tunnel: $EDGE_TUNNEL_UUID
credentials-file: /etc/cloudflared/$EDGE_TUNNEL_UUID.json

ingress:
  # Entrada pública -> nginx local (só escuta em 127.0.0.1:8080)
  - hostname: $PUBLIC_HOST
    service: http://127.0.0.1:8080
    originRequest:
      connectTimeout: 30s
      keepAliveTimeout: 90s
  - service: http_status:404
EOF
ok 'config do túnel gerada'

log 'Enviar para a VM'
gc scp --recurse "$STAGE" "$VM_NAME:/tmp/" >/dev/null
gc scp "$EDGE_CREDENTIALS_JSON" "$VM_NAME:/tmp/$EDGE_TUNNEL_UUID.json" >/dev/null
ok 'ficheiros copiados'

log 'Instalar e arrancar'
gc ssh "$VM_NAME" --command "
set -e
sudo mkdir -p $REMOTE_DIR /etc/cloudflared
sudo cp -f /tmp/$STAGE_NAME/compose.yml $REMOTE_DIR/compose.yml
sudo cp -f /tmp/$STAGE_NAME/offline.html $REMOTE_DIR/offline.html
sudo cp -f /tmp/$STAGE_NAME/edge.env $REMOTE_DIR/edge.env
sudo cp -rf /tmp/$STAGE_NAME/templates $REMOTE_DIR/templates
sudo chmod 600 /tmp/$EDGE_TUNNEL_UUID.json
sudo mv -f /tmp/$EDGE_TUNNEL_UUID.json /etc/cloudflared/$EDGE_TUNNEL_UUID.json
sudo cp -f /tmp/$STAGE_NAME/cloudflared-config.yml /etc/cloudflared/config.yml
sudo cloudflared tunnel ingress validate --config /etc/cloudflared/config.yml

# Serviço do cloudflared (túnel só de saída, sem portas abertas no host)
sudo cloudflared service uninstall >/dev/null 2>&1 || true
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl restart cloudflared

# Container do nginx
cd $REMOTE_DIR && sudo docker compose up -d --remove-orphans
" || die 'Falhou a configuração na VM (vê o erro acima).'

log 'Verificar na VM'
sleep 5
gc ssh "$VM_NAME" --command 'curl -fsS http://127.0.0.1:8080/healthz && sudo systemctl is-active cloudflared && sudo docker compose -f /opt/iqos-edge/compose.yml ps --format "{{.Name}} {{.Status}}"' \
  || die 'O nginx ou o cloudflared não estão a responder na VM.'

cat <<EOF

================================================================================
EDGE CONFIGURADO
================================================================================
  VM          : $VM_NAME ($PROJECT_ID/$ZONE)
  edge        : nginx em 127.0.0.1:8080 + túnel $EDGE_TUNNEL_UUID
  origem      : https://$ORIGIN_HOSTNAME (via Access service token)
  público     : ${PUBLIC_HOST:-<PUBLIC_HOST por definir>}

O egress da VM para o Cloudflare conta para os 200 GiB/mês gratuitos do
Standard Tier — a SPA e as respostas da API passam todos por aqui.

A SEGUIR (no PC):
  .\05-verify.ps1 -PublicHost ${PUBLIC_HOST:-iqos.exemplo.com} -OriginHost $ORIGIN_HOSTNAME

Se mudares o edge.env, volta a correr este script (é idempotente).
EOF
