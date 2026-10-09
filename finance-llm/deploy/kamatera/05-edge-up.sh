# Executado NA VM: prepara o host (swap) e arranca o edge (Caddy + dominio proprio).
#
# Uso:  bash /opt/iqos/05-edge-up.sh
#
# O upstream do Caddy e `127.0.0.1:8080`, onde o PC publica a stack pelo
# **tunel SSH reverso** (`07-origin-tunnel.ps1` no PC). Nao ha Cloudflare,
# por isso nao ha hostname aleatorio nenhum para propagar.
set -euo pipefail

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

# 2) O tunel SSH reverso do PC (07-origin-tunnel.ps1) publica a stack em
#    127.0.0.1:8080 desta VM. Se a sessao morrer sem FIN (WiFi/rede movel), o
#    sshd mantem o listen preso e a religacao falha com
#    "remote port forwarding failed for listen port 8080". Com estes valores o
#    sshd deteta o cliente morto em ~45 s e liberta a porta sozinho.
if ! grep -q '^ClientAliveInterval' /etc/ssh/sshd_config; then
    echo "==> a afinar o sshd (ClientAliveInterval/ClientAliveCountMax)"
    printf '\n# IQ OS: libertar tuneis SSH reversos de clientes mortos\nClientAliveInterval 15\nClientAliveCountMax 3\n' >>/etc/ssh/sshd_config
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
fi

# 3) Arrancar o edge.
cd /opt/iqos/edge
# Pasta dos registos do formulario da landing (bind mount do servico `landing`).
mkdir -p /opt/iqos/edge/data
# `--build`: a landing e construida aqui (imagem minuscula), por isso uma
# alteracao a pagina so entra com rebuild. O Caddy vem de imagem publica.
docker compose up -d --build --remove-orphans

# O Caddyfile entra por bind mount de um **unico ficheiro**. O Docker resolve o
# caminho para um inode no arranque do container: se o ficheiro for substituido
# (por exemplo com `sed -i`), o container continua a ver o inode antigo e um
# `caddy reload` recarrega a config velha sem dar erro. Por isso aqui o Caddy e
# recriado, que e o que volta a resolver o mount.
docker compose up -d --force-recreate caddy

echo "==> a aguardar o Caddy ficar saudavel"
for _ in $(seq 1 20); do
    sleep 3
    # A API de administracao (localhost:2019) confirma que a config esta carregada.
    if docker exec iqos-caddy wget -q -O /dev/null http://127.0.0.1:2019/config/ 2>/dev/null; then
        break
    fi
done

echo
echo "==> containers"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo
echo "==> tunel de origem (PC -> VM, 127.0.0.1:8080)"
if timeout 5 bash -c '</dev/tcp/127.0.0.1/8080' 2>/dev/null; then
    echo "OK: tunel SSH ativo"
else
    echo "AVISO: nada a escutar em 127.0.0.1:8080 — arranca o 07-origin-tunnel.ps1 no PC" >&2
fi
echo
echo "==> endereco publico"
echo "https://sabemos.studio"
echo
echo "==> recursos"
free -h
df -h / | tail -1
