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
| Origem (PC) | **tunel SSH reverso** em Docker (`iqos-origin-tunnel`) |

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
              |   iqos-caddy   (Caddy)        |   portas 80/443, network_mode: host
              |     Let's Encrypt automatico  |
              |     reverse_proxy 127.0.0.1:8080
              +-------------------------------+
                              |
                 tunel SSH reverso (PC inicia)
                 ssh -R 127.0.0.1:8080:127.0.0.1:4180
                              |
              +-------------------------------+
              | PC (stack IQ OS completa)     |
              |   iqos-origin-tunnel (Docker) |   cliente ssh do tunel
              |   finance-llm-frontend :4180  |   nginx da stack (SPA + /api)
              |   finance-llm-backend  :8002  |   FastAPI
              |   finance-llm-elasticsearch   |
              +-------------------------------+
```

Porque e que a stack **nao** corre na VM: a maquina mais barata da Kamatera tem
1 vCPU / 2 GB / 20 GB, e a stack pede ~40 GB de dados + indices Elasticsearch +
modelos. A VM fica como **ponto de entrada publico com TLS proprio**
(Caddy + Let's Encrypt) e os dados ficam no PC.

Porque e que **nao ha Cloudflare**: o quick tunnel era efemero (o hostname mudava
e o tunel morria com o container `Up`, deixando o site em 502/Error 1033).
O tunel SSH reverso nao tem terceiros pelo meio, tem um endereco fixo e o
proprio container religa sozinho quando a ligacao cai.

## Ficheiros

| Ficheiro | Onde corre | Para que serve |
| --- | --- | --- |
| `01-provision-vm.sh` | VM | Instala Docker Engine + Compose e cria 2 GB de swap |
| `03-configure-edge.ps1` | PC | Envia o `05` + `edge/Caddyfile` + `edge/compose.yml` para a VM e arranca o edge |
| `04-verify.ps1` | PC | Verifica stack local, tunel SSH, containers do edge e endereco publico |
| `05-edge-up.sh` | VM | Swap + afina o sshd + `docker compose up` do edge |
| `07-origin-tunnel.ps1` | PC | Sobe/para o tunel SSH reverso (Docker) e instala o arranque automatico |
| `00-push-file.ps1` | PC | Envia um ficheiro para a VM (ssh + base64, sem scp) |
| `00-keep-awake.ps1` | PC | Impede o PC de adormecer (a origem cai se ele dormir) |
| `origin/` | PC | tunel SSH reverso: `Dockerfile`, `tunnel.sh`, `compose.yml` |
| `edge/` | VM | Caddy (HTTPS proprio) `reverse_proxy` para `127.0.0.1:8080` + pagina offline |

## Arranque (passo a passo)

```powershell
cd C:\LLMFinance\finance-llm

# 0. Stack local a servir 127.0.0.1:4180 (docker compose up -d na raiz)

# 1. VM (uma vez): instalar Docker + swap + abrir portas 80/443 no firewall Kamatera
powershell -File deploy\kamatera\00-push-file.ps1 -Local deploy\kamatera\01-provision-vm.sh -Dest /opt/iqos/01-provision-vm.sh
ssh -i "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519" root@45.147.251.188 "bash /opt/iqos/01-provision-vm.sh"

# 2. DNS: apontar @ e www para o IP da VM (45.147.251.188)

# 3. Publicar a origem local (tunel SSH reverso em Docker)
powershell -File deploy\kamatera\07-origin-tunnel.ps1 -InstallTask

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
- **O hostname do quick tunnel mudava a cada recriacao** e o tunel morria com o
  container `Up` (`Unauthorized: Tunnel not found`), deixando o site em 502
  (Error 1033 no browser). Foi por isso que o Cloudflare foi **removido**: ver
  a seccao do tunel SSH reverso abaixo.
- **Um `ssh -N -R` lancado por PowerShell nao se aguenta**: morria ao fim de
  7-45 s em silencio (sem mensagem no journal do sshd da VM), deixando o listen
  8080 preso na VM e as religacoes a falhar com
  `remote port forwarding failed for listen port 8080`. Curiosamente, uma sessao
  `ssh` normal sobrevivia 150 s e uma `-R` isolada tambem — so com trafego real
  e em contexto PowerShell e que caia. **Solucao: correr o tunel num container
  Docker** (`origin/`), com o ciclo de religacao dentro do `tunnel.sh`.
- **A porta remota do `-R` fica presa** se a sessao morrer sem FIN. O
  `tunnel.sh` liberta-a na VM antes de religar, e o `05-edge-up.sh` afina o sshd
  (`ClientAliveInterval 15` / `ClientAliveCountMax 3`) para o proprio servidor
  largar clientes mortos em ~45 s.
- **O Caddy do edge tem de correr com `network_mode: host`**: o tunel SSH
  liga-se ao loopback **da VM**; com a bridge por omissao, `127.0.0.1` seria o
  loopback do container e o proxy nunca chegava ao tunel.
- **O healthcheck do Caddy nao pode testar o site publico**: um pedido a
  `http://127.0.0.1/healthz` leva 308 (redirect http->https) e o container
  ficava marcado `unhealthy` para sempre. Testar a API de administracao:
  `wget -q -O /dev/null http://127.0.0.1:2019/config/`.
- **Ficheiros `.sh`/`Dockerfile` criados no Windows vao com CRLF** e partem o
  shell (um `\r` colado ao fim da linha estraga redirecoes). Normalizar com
  `sed -i 's/\r$//'` no build ou no envio (`03-configure-edge.ps1`).
- **Nao usar `—` nem acentos dentro de strings em `.ps1`**: o PowerShell 5.1 le
  o ficheiro como CP1252, o 3.o byte do travessao (0x94) vira aspa e a string
  fecha a meio. Em comentarios passa; em strings rebenta o script.
- **Registar uma tarefa agendada exige elevacao** nesta maquina
  (`Access is denied`, 0x80070005). O arranque automatico do tunel usa a pasta
  `Startup` do utilizador, que nao precisa de permissoes.
- **O dominio proprio e servido pelo VM** (Caddy + Let's Encrypt), nao por um
  quick tunnel. As portas 80/443 tem de estar abertas no firewall da Kamatera.
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
  um `Start-Process` morre quando o terminal que o lancou e fechado — e, no caso
  do `ssh -R`, morria mesmo com o terminal aberto.
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
# estado do edge (VM) e do tunel (PC)
ssh root@45.147.251.188 "docker ps; ss -ltn | grep 8080"
docker logs --tail 20 iqos-origin-tunnel

# reiniciar o edge depois de mudar a configuracao
powershell -File deploy\kamatera\03-configure-edge.ps1

# parar tudo no edge
ssh root@45.147.251.188 "cd /opt/iqos/edge && docker compose down"

# parar o tunel de origem (PC)
powershell -File deploy\kamatera\07-origin-tunnel.ps1 -RemoveTask
```

Se o site mostrar a pagina "temporariamente indisponivel", o tunel caiu: ver
`docker logs iqos-origin-tunnel`. O container religa sozinho; se insistir,
reconstruir com `07-origin-tunnel.ps1`.

## Custos e proximos passos

- VM: **6 USD/mes**. Certificados Let's Encrypt: gratuitos. Tunel SSH de origem:
  gratuito e sem terceiros. Portas 80/443 abertas no firewall Kamatera.
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
