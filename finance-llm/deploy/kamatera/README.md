# Deploy do IQ OS na Kamatera (VM mais economica)

Estado deste deploy (2026-10-06):

| Item | Valor |
| --- | --- |
| VM | `iq-os-edge-01` — Kamatera, datacenter `EU-MD` (Madrid) |
| ID | `4b9ccce0-0cba-43ef-9574-9079e87184ad` |
| IP | `45.147.251.188` (SSH + HTTP/HTTPS abertos) |
| Recursos | 1 vCPU tipo A, 2 GB RAM, 20 GB NVMe, swap 2 GB |
| Preco | **6 USD/mes** (hourly: 0.008 USD/h) |
| Docker | Engine 29.8.2 + Compose v5.6.0 |
| Dominio publico | https://sabemos.studio |
| Origem publica (PC) | quick tunnel Cloudflare (ver `origin-url.txt`) |

Verificacao ponta-a-ponta (do PC, via internet):

```
/healthz       -> 200  (Caddy no edge)
/              -> 200  (SPA)
/api/health    -> 200  (backend FastAPI, atraves do tunel de origem)
/api/providers -> 401  (guarda de autenticacao a funcionar)
```

## Arquitetura

```
                          internet
                              |
              https://sabemos.studio
                              |
              +-------------------------------+
              | VM Kamatera (EU-MD, 6 USD/mes)|
              |   iqos-caddy   (Caddy)        |   portas 80/443
              |     Let's Encrypt automatico  |
              +-------------------------------+
                              |
     https://<aleatorio>.trycloudflare.com
                              |
              +-------------------------------+
              | PC (stack IQ OS completa)     |
              |   finance-llm-frontend :4180  |   nginx da stack (SPA + /api)
              |   finance-llm-backend  :8003  |   FastAPI
              |   finance-llm-elasticsearch   |
              |   iqos-origin-tunnel  (cloudflared)
              +-------------------------------+
```

Porque e que a stack **nao** corre na VM: a maquina mais barata da Kamatera tem
1 vCPU / 2 GB / 20 GB, e a stack pede ~40 GB de dados + indices Elasticsearch +
modelos. A VM fica como **ponto de entrada publico com TLS proprio**
(Caddy + Let's Encrypt) e os dados ficam no PC.

## Ficheiros

| Ficheiro | Onde corre | Para que serve |
| --- | --- | --- |
| `01-provision-vm.sh` | VM | Instala Docker Engine + Compose e cria 2 GB de swap |
| `02-publish-origin.ps1` | PC | Sobe origem + tunel (Docker) e guarda `origin-url.txt` |
| `03-configure-edge.ps1` | PC | Envia o `05` para a VM e aplica o hostname da origem |
| `04-verify.ps1` | PC | Verifica origem, edge e endereco publico |
| `05-edge-up.sh` | VM | Swap + `edge.env` + `Caddyfile` + `docker compose up` do edge |
| `06-refresh-cloudflare.ps1` | PC | Renova o tunel de origem (se cair) e reaplica a origem no edge |
| `00-push-file.ps1` | PC | Envia um ficheiro para a VM (ssh + base64, sem scp) |
| `origin/` | PC | tunel Cloudflare (+ nginx de origem minima, perfil `lite`) |
| `edge/` | VM | Caddy (HTTPS proprio) proxy para o quick tunnel de origem |

## Arranque (passo a passo)

```powershell
cd C:\LLMFinance\finance-llm

# 0. Stack local a servir 127.0.0.1:4180 (docker compose up -d na raiz)

# 1. VM (uma vez): instalar Docker + swap + abrir portas 80/443 no firewall Kamatera
powershell -File deploy\kamatera\00-push-file.ps1 -Local deploy\kamatera\01-provision-vm.sh -Dest /opt/iqos/01-provision-vm.sh
ssh -i "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519" root@45.147.251.188 "bash /opt/iqos/01-provision-vm.sh"

# 2. DNS: apontar @ e www para o IP da VM (45.147.251.188)

# 3. Publicar a origem local (tunel em Docker, sobrevive ao terminal)
powershell -File deploy\kamatera\02-publish-origin.ps1

# 4. Aplicar no edge da VM
powershell -File deploy\kamatera\03-configure-edge.ps1

# 5. Verificar
powershell -File deploy\kamatera\04-verify.ps1
```

## Armadilhas encontradas (todas resolvidas)

- **`scp` fica preso nesta rede** (nem erro nem timeout; a ligacao nunca fecha).
  O `ssh` funciona, por isso os ficheiros vao em **base64 por ssh**
  (`00-push-file.ps1`, `03-configure-edge.ps1`).
- **As ligacoes SSH a esta VM sao intermitentes**: o SYN por vezes nao obtem
  resposta (`connect ... timed out`) e o TCP oscila entre 0.04 s e timeout, com
  a VM saudavel (`load average 0.06`). Todos os scripts fazem **retentativas**
  (ate 40 tentativas, 8 s de `ConnectTimeout`). No Python (`_ssh.py`, usado nos
  testes) e a mesma ideia.
- **Sem swap a VM de 2 GB bloqueia o proprio sshd**: depois de instalar o Docker
  o handshake SSH parava no `SSH2_MSG_KEXINIT` sem erro. O `05-edge-up.sh` cria
  2 GB de swap (idempotente) e o problema nao voltou.
- **O hostname do quick tunnel muda a cada recriacao do container.** Sempre que
  o tunel de origem for recriado, correr o `03-configure-edge.ps1` (ou, de uma vez,
  o `06-refresh-cloudflare.ps1`) .
- **Um quick tunnel pode morrer com o container `Up`**: o Cloudflare reclama-o e os
  logs repetem `ERR Register tunnel error ... "Unauthorized: Tunnel not found"`.
  O endereco deixa de existir e o edge passa a devolver 502. Remedio:
  `06-refresh-cloudflare.ps1` (recria o tunel e reaplica a origem).
- **Agora o dominio proprio e servido pelo VM**, nao por um quick tunnel publico.
  As portas 80/443 tem de estar abertas no firewall da Kamatera, senao o Let's
  Encrypt e o trafego HTTPS falham.
- **O ssh pode bloquear-se no handshake** (KEXINIT sem resposta) e ficar pendurado
  para sempre. Alem de `ConnectTimeout`, usar `ServerAliveInterval=5`,
  `ServerAliveCountMax=2` e `-n` (nao encaminhar o stdin local): assim uma sessao
  presa falha em ~10 s e o ciclo de retentativas avanca.
- **`docker logs` escreve em stderr** e com `$ErrorActionPreference='Stop'` isso
  vira erro terminante. Baixar para `Continue` em volta da chamada (o logrus do
  cloudflared escreve o URL em stderr — e dai o `2>&1`).
- **Porto 4180 colide** se o nginx de origem minima e a stack completa estiverem
  ambos a correr: o nginx de origem fica no perfil `lite` e nao arranca por
  omissao.
- **O tunel tem de correr em Docker** (e nao como processo solto do PowerShell):
  um `Start-Process` morre quando o terminal que o lancou e fechado e o endereco
  publico deixa de responder.
- `NGINX_ENVSUBST_FILTER` e obrigatorio nos templates do nginx, senao o
  `envsubst` do entrypoint limpa `$host`, `$remote_addr`, etc.
- No proxy `/api/` -> `${BACKEND_ORIGIN}/` a **barra final e essencial**: e o que
  retira o prefixo `/api` (a stack faz o mesmo em `docker/nginx.conf`).
- **`$PSScriptRoot` nao pode ser usado no valor por omissao de um parametro**
  (PowerShell 5.1). Resolver dentro do corpo do script.
- O envio de ficheiros em base64 dentro de um script (`powershell -File`) ficou
  preso nesta rede; os ficheiros pequenos enviam-se com `00-push-file.ps1` e, para
  o resto, corre-se o que ja esta na VM.

## Operacao

```bash
# estado do edge
ssh -n root@45.147.251.188 "docker ps; docker logs iqos-tunnel | tail -5"

# reiniciar o edge depois de mudar a origem
ssh root@45.147.251.188 "bash /opt/iqos/05-edge-up.sh <novo-hostname>"

# parar tudo no edge
ssh root@45.147.251.188 "cd /opt/iqos/edge && docker compose down"
```

## Custos e proximos passos

- VM: **6 USD/mes**. Certificados Let's Encrypt: gratuitos. Quick tunnel de
  origem: gratuito. Portas 80/443 abertas no firewall Kamatera.
- O PC nao pode adormecer (a origem cai):
  `powershell -File deploy\kamatera\00-keep-awake.ps1` — ja aplicado (suspensao,
  hibernacao e desligar do ecra a "nunca", AC e DC, esquema Balanced).
  Reverter com `-Restore`.
- A autenticacao continua a ser a do IQ OS; o dominio proprio nao acrescenta
  Cloudflare Access.

### Subir a stack completa para a VM

1. Redimensionar pela API (sem reinstalar):
   ```bash
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'ram=8192' https://cloudcli.cloudwm.com/service/server/<id>/ram
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'cpu=2B'   https://cloudcli.cloudwm.com/service/server/<id>/cpu
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'size=100&index=0&provision=1' \
     https://cloudcli.cloudwm.com/service/server/<id>/disk
   ```
   Minimo realista: **8 GB RAM / 100 GB** (data/ 36 GB + model/ 3 GB + imagem do
   backend ~11 GB). Nota: o tipo `A` (o mais barato) nao garante CPU.
2. Copiar o repositorio (sem `data/`, `model/`, `logs/`) para `/opt/iqos` e
   `docker compose up -d --build`.
3. Apontar o edge para a propria maquina: `ORIGIN_TARGET=http://host.docker.internal:4180`
   (ou usar a stack nativamente e dispensar o edge).

## API Kamatera (para referencia)

Base: `https://cloudcli.cloudwm.com/service` (a consola usa
`https://console.kamatera.com/service`, mas os parametros
`datacenter=1` / `sizes=1` / `capabilities=1` / `images=1` so existem no host
`cloudcli`). Autenticacao por cabecalhos **`AuthClientId`** + **`AuthSecret`**
(nos exemplos da documentacao aparecem `clientId`/`secret`, que devolvem
`None of security schemas did match`).

```bash
GET    /service/server?datacenter=1                      # datacenters
GET    /service/server?capabilities=1&datacenter=EU-MD   # cpu/ram/disco/trafego
GET    /service/server?sizes=1&datacenter=EU-MD          # tamanhos pre-definidos
GET    /service/server?images=1&datacenter=EU-MD         # imagens de disco
POST   /service/server                                   # criar servidor (JSON)
GET    /service/servers                                  # listar
POST   /service/server/info    {"name": "..."}           # detalhes + precos
GET    /service/queue?id=<id>                            # estado de um comando
POST   /service/server/reboot  {"id": "..."}
PUT    /service/server/<id>/ram|cpu|disk                 # redimensionar
DELETE /service/server/<id>/terminate                    # terminar
```
