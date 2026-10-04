# Deploy do IQ OS na Kamatera (VM mais economica)

Estado deste deploy (2026-10-02):

| Item | Valor |
| --- | --- |
| VM | `iq-os-edge-01` — Kamatera, datacenter `EU-MD` (Madrid) |
| ID | `4b9ccce0-0cba-43ef-9574-9079e87184ad` |
| IP | `45.147.251.188` (so SSH; o edge nao abre portas) |
| Recursos | 1 vCPU tipo A, 2 GB RAM, 20 GB NVMe, swap 2 GB |
| Preco | **6 USD/mes** (hourly: 0.008 USD/h) |
| Docker | Engine 29.8.2 + Compose v5.6.0 |
| Endereco publico | https://analog-chronicles-bag-transparency.trycloudflare.com |
| Origem publica (PC) | https://generally-practices-expensive-operation.trycloudflare.com |

Verificacao ponta-a-ponta (do PC, via internet):

```
/healthz       -> 200  0.99s   (nginx do edge)
/              -> 200  0.75s   (SPA)
/api/health    -> 200  0.78s   (backend FastAPI, atraves dos dois tuneis)
/api/providers -> 401  1.01s   (guarda de autenticacao a funcionar)
```

## Arquitetura

```
                          internet
                              |
     https://analog-...-transparency.trycloudflare.com
                              |
              +-------------------------------+
              | VM Kamatera (EU-MD, 6 USD/mes)|
              |   iqos-tunnel  (cloudflared)  |   sem portas publicas
              |   iqos-edge    (nginx)        |   (o tunel e so de saida)
              +-------------------------------+
                              |
     https://generally-...-operation.trycloudflare.com
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
modelos. A VM fica como **ponto de entrada publico com TLS gratuito**
(Cloudflare quick tunnel) e os dados ficam no PC.

## Ficheiros

| Ficheiro | Onde corre | Para que serve |
| --- | --- | --- |
| `01-provision-vm.sh` | VM | Instala Docker Engine + Compose e cria 2 GB de swap |
| `02-publish-origin.ps1` | PC | Sobe origem + tunel (Docker) e guarda `origin-url.txt` |
| `03-configure-edge.ps1` | PC | Envia o `05` para a VM e aplica o hostname da origem |
| `04-verify.ps1` | PC | Verifica origem, edge e endereco publico |
| `05-edge-up.sh` | VM | Swap + `edge.env` + `docker compose up` do edge |
| `00-push-file.ps1` | PC | Envia um ficheiro para a VM (ssh + base64, sem scp) |
| `origin/` | PC | tunel Cloudflare (+ nginx de origem minima, perfil `lite`) |
| `edge/` | VM | nginx (reverse proxy) + cloudflared (quick tunnel publico) |

## Arranque (passo a passo)

```powershell
cd C:\LLMFinance\finance-llm

# 0. Stack local a servir 127.0.0.1:4180 (docker compose up -d na raiz)

# 1. VM (uma vez): instalar Docker + swap
powershell -File deploy\kamatera\00-push-file.ps1 -Local deploy\kamatera\01-provision-vm.sh -Dest /opt/iqos/01-provision-vm.sh
ssh -i "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519" root@45.147.251.188 "bash /opt/iqos/01-provision-vm.sh"

# 2. Publicar a origem local (tunel em Docker, sobrevive ao terminal)
powershell -File deploy\kamatera\02-publish-origin.ps1

# 3. Aplicar no edge da VM
powershell -File deploy\kamatera\03-configure-edge.ps1

# 4. Verificar
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
  o tunel de origem for recriado, correr o `03-configure-edge.ps1`.
- **`$PSScriptRoot` nao pode ser usado no valor por omissao de um parametro**
  (PowerShell 5.1). Resolver dentro do corpo do script.
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

## Operacao

```bash
# estado do edge
ssh root@45.147.251.188 "docker ps; docker logs iqos-tunnel | tail -5"

# reiniciar o edge depois de mudar a origem
ssh root@45.147.251.188 "bash /opt/iqos/05-edge-up.sh <novo-hostname>"

# parar tudo no edge
ssh root@45.147.251.188 "cd /opt/iqos/edge && docker compose down"
```

## Custos e proximos passos

- VM: **6 USD/mes**. Quick tunnels Cloudflare: gratuitos. Sem portas publicas
  alem do SSH.
- O PC nao pode adormecer (a origem cai):
  `powershell -File deploy\kamatera\00-keep-awake.ps1` — ja aplicado (suspensao,
  hibernacao e desligar do ecra a "nunca", AC e DC, esquema Balanced).
  Reverter com `-Restore`.
- Um quick tunnel nao tem Cloudflare Access: quem tiver o endereco chega a
  aplicacao (a autenticacao por conta de utilizador do IQ OS continua ativa).
  Para um hostname fixo, usar `deploy/gcp/01-setup-tunnels.ps1` (tunel nomeado).

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
