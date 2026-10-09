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

**Nao cabe na VM atual** — mas a diferenca e sobretudo de **disco**, nao de RAM.
Medido com `docker stats`, `/sys/fs/cgroup/memory.stat` e `memory.peak`:

| Recurso | Stack IQ OS | VM `iq-os-edge-01` | Falta |
|---|---|---|---|
| RAM real (anon, sem cache) | **2,6 GB** | 2 GB | 0,6 GB |
| Disco | **120 GB** (tudo) | 20 GB | 100 GB |
| vCPU | picos curtos no `backend` | 1 tipo A (sem garantia) | — |

**Cuidado com o `docker stats`:** para o Elasticsearch reportava 5,8 a 8,5 GB,
mas apenas **880 MB sao memoria real** (`anon`) — o resto e cache de ficheiros do
indice Lucene (31 GB), que o kernel liberta quando precisa. Dimensionar a VM com
esse numero da uma maquina 4x maior do que o necessario.

RAM real por contentor (`anon`): `elasticsearch` 880 MB, `backend` 791 MB,
`n8n` 206 MB, `searxng` 33 MB, `frontend` 12 MB -> **nucleo = 1,9 GB**.
Perfis opcionais: `hermes-agent` 358 MB, `osif` 243 MB, `mirofish` 82 MB,
`mcp` 20 MB -> **stack completa = 2,6 GB**. A maquina ainda leva ~0,4 GB
(Ubuntu + dockerd), ou seja **~3 GB no total**.

Disco: `data/` 37 GB + volume do Elasticsearch 31 GB (derivado, pode ser
reconstruido) + `model/` 3 GB + cache whisper 1 GB + imagens **38 GB**
(so `iq-os-backend` sao 13,7 GB e o `mirofish` outros 14,2 GB). O script
`08-custo-vm.ps1` recalcula tudo isto.

Nota: no PC o `es-data` ocupa 31 GB e o Elasticsearch usa 6,4 GB de cache para
o percorrer. Com pouca RAM a cache encolhe e as pesquisas em segmentos frios
passam a ler do NVMe — mais lentas, nao avariadas.

1. Redimensionar pela API (sem reinstalar). Recomendado: **2 vCPU tipo A /
   8 GB RAM / 150 GB** — cabe tudo com folga e sobra RAM para cache do indice.
   O minimo absoluto para o nucleo e **4 GB / 120 GB**:
   ```bash
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'ram=8192' https://cloudcli.cloudwm.com/service/server/<id>/ram
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'cpu=2A'   https://cloudcli.cloudwm.com/service/server/<id>/cpu
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'size=150&index=0&provision=1' \
     https://cloudcli.cloudwm.com/service/server/<id>/disk
   ```
   Nota: o tipo `A` (o mais barato) **nao garante CPU** — `2A` = 2 cores de
   burst, nao 2 cores dedicados. Para CPU garantida usa `2B`, que custa ~4,5x
   mais por vCPU. Cada `PUT` e assincrono: acompanhar com
   `GET /service/queue?id=<id>`, e confirmar no fim com
   `POST /service/server/info {"name":"iq-os-edge-01"}`.
2. Antes de redimensionar o disco, largar espaco: o `docker builder cache` local
   tem 42 GB e ha imagens de backups antigos (88 GB no total, 50 imagens).
   No PC, so a stack IQ OS usa ~38 GB de imagens. A 120 GB, largar o `mirofish`
   (14 GB de imagem, perfil opcional) ou nao copiar o indice do ES da a folga
   necessaria.
3. Copiar o repositorio (sem `data/`, `model/`, `logs/`) para `/opt/iqos` e
   `docker compose up -d --build`.
4. O `data/` (37 GB) tem de ser copiado a parte; o `scp` desta rede encrava.
   O indice do Elasticsearch (31 GB) e derivado: mais vale reconstrui-lo na VM
   do que copia-lo.
5. Apontar o edge para a propria maquina: `ORIGIN_TARGET=http://host.docker.internal:4180`
   (ou usar a stack nativamente e dispensar o edge + o tunel).

### Custo: manter o PC ligado vs mudar para a VM

O custo de deixar o PC ligado 24/7 (assumindo 0,20 EUR/kWh) e **8,8 EUR/mes a
60 W**, **13,1 EUR/mes a 90 W**, **19,0 EUR/mes a 130 W** — ou seja, entre
**105 e 228 EUR/ano**. E frequentemente mais caro do que a propria VM.

Estimativa de custo Kamatera em USD (taxas derivadas de dois pontos publicos:
VM atual 1A/2GB/20GB = 6,00 USD/mes, e a calculadora do site da 1B/512MB/5GB =
10,00 USD/mes; disco a 0,05 USD/GB/mes, 5 TB de trafego incluidas):

| Configuracao | Tipo | vCPU/RAM/Disco | USD/mes | USD/ano |
|---|---|---|---|---|
| Atual no PC (so o edge na VM) | A | 1 / 2 GB / 20 GB | 6 | 72 |
| So o nucleo, apertado | A | 2 / 8 GB / 120 GB | ~22 | ~264 |
| **Recomendado: tudo** | A | 2 / 8 GB / 150 GB | ~24 | ~282 |
| Tudo, 4 cores | A | 4 / 8 GB / 150 GB | ~28 | ~330 |
| Tudo, folgado | A | 4 / 12 GB / 200 GB | ~36 | ~432 |
| Tudo, CPU dedicada | B | 4 / 8 GB / 150 GB | ~56 | ~672 |

**Estimativa.** A Kamatera nao tem endpoint de orcamento. As taxas usadas
(vCPU tipo A 2,00 / tipo B 9,00 USD; RAM 1,50 USD/GB; disco 0,05 USD/GB)
reproduzem exatamente os dois pontos publicos conhecidos — 1A/2GB/20GB = 6,00 e
1B/512MB/5GB = 10,00 USD/mes — mas a divisao entre vCPU e RAM dentro de cada
tipo e inferida. Define `KAMATERA_CLIENT_ID` e `KAMATERA_SECRET` no ambiente e
corre `deploy\kamatera\08-custo-vm.ps1` para ler o preco real do servidor atual.

#### Da com 22 USD/mes? Da — mas nao e uma decisao de dinheiro

**Tecnicamente da.** Com 2 vCPU / 8 GB / 120 GB a stack completa cabe: 2,6 GB
de containers + 0,4 GB de sistema deixa ~5 GB para cache do indice. O que se
perde em relacao ao PC e a cache: aqui o Elasticsearch tem 6,4 GB de cache para
o indice de 31 GB, na VM seriam ~5 GB. Pesquisas em segmentos frios passam a ler
do NVMe — mais lentas, mas funcionam.

**Nao da** se copiares o indice (31 GB) sem largar o `mirofish` (14 GB): nesse
caso os 120 GB ficam sem folga nenhuma. Ou se reconstroi o indice, ou se larga
o `mirofish`, ou se sobem os 30 GB de disco extra (+1,50 USD/mes).

**O dinheiro fica ela por ela.** Deixar o PC ligado 24/7 custa 8,8 a 19,0 EUR/mes
de luz (60-130 W a 0,20 EUR/kWh) mais os 6 USD/mes da VM que ja pagas: ~19 EUR/mes.
A VM de 24 USD fica em ~22 EUR/mes. Praticamente o mesmo.

O que se compra com os 22-24 USD nao e poupanca: e **nao depender de a maquina de
casa estar ligada**, e poder desligar o PC sem o site cair. Se o PC fica ligado
de qualquer maneira, o hibrido atual e o mais barato e este trabalho nao vale a
pena.

Ressalvas antes de decidir: o tipo `A` e **CPU de burst** (nao garantida) — um
forecast com torch em 2 cores partilhados sera visivelmente mais lento; e ja ha
swap em uso no PC (`n8n` 107 MB, `searxng` 75 MB, `mirofish` 190 MB, ES 331 MB),
portanto o PC tambem nao esta folgado.

## Espelho do Elasticsearch na VM

O `iqos-elasticsearch` corre na VM com a **mesma imagem que o stack local**
(`docker.elastic.co/elasticsearch/elasticsearch:8.11.0`), ao lado do edge e sem
tocar em nada: o Caddy, a landing, o tunel e o ES do PC ficam como estavam.

```powershell
.\11-es-vm.ps1        # instala (vm.max_map_count, compose) e arranca o ES
.\11-es-vm.ps1 -Logs  # segue o log
```

- escuta **so em 127.0.0.1:9200** (`network.host=127.0.0.1` + `network_mode: host`),
  por isso nao fica exposto a Internet;
- o tunel reverso (`origin/tunnel.sh`) encaminha tambem `127.0.0.1:9201` para o
  ES do PC, e o `reindex.remote.whitelist` do container aponta para la;
- o ES local e apenas **lido** -- nada no PC muda.

Com o ES a correr a VM fica em 1180 MB usados e 786 MB livres. Como a VM tem
**2 GB**, este espelho e o maximo que cabe; subir a RAM faz-se so no painel.

### Migrar os indices

```powershell
.\12-es-migrar.ps1 -MaxGB 3 -Dry     # ver o plano, sem escrever nada
.\12-es-migrar.ps1 -MaxGB 3          # migrar (ordem: do leve para o pesado)
.\12-es-migrar.ps1 -MaxGB 3 -Force   # refazer os que ja existam
```

Primeira passagem: **45 indices, 3,5 M documentos, contagens a bater indice a
indice**. Ficaram de fora `contratos` (20,1 GB) e `contratos_es` (4,8 GB) -- com
100 GB de disco ainda nao cabem com folga.

Correccao: para o **espelho do Elasticsearch** eles cabem -- os 82 GB livres
chegam (o espelho completo fica em ~31 GB de indice + 8 GB de sistema + 3 GB de
imagens). O que os torna pesados e o tempo, nao o disco: passam horas pelo
upload de casa.

```powershell
.\12-es-migrar.ps1 -MaxGB 21    # inclui contratos e contratos_es
```

Os ~120 GB de que se falava na analise de custos eram para a **stack inteira**
(os 37 GB de `data/` + 3 GB de `model/` + 38 GB de imagens), nao para o ES.

### Armadilhas (todas com sintomas enganadores)

| Sintoma | Causa real |
|---|---|
| ES devolve **500** ao criar o indice: `"mappings" is null` | o `GET /<indice>` devolve `{"<indice>": {mappings, settings}}`; ler `.mappings` na raiz da `null` |
| ES devolve **400** ao `_reindex`: `doesn't support slices > 1` | copia a partir de origem remota e sempre um so fluxo |
| `migrar.sh: Illegal option -o pipefail` | `/bin/sh` no Ubuntu e dash -- e preciso chamar `bash` |
| `$'\r': command not found` | o PowerShell injecta CR ao escrever em pipeline nativa, mesmo depois de um `-replace`; limpar com `sed` na VM |

### Validar

```powershell
.\13-es-validar.ps1    # so leitura: contagens + mapeamentos, indice a indice
```

Resultado: **43 dos 45 indices batem certo** -- contagem *e* mapeamento. Os
outros dois divergem por **escrita nova na origem**, nao por perda de dados:

| Indice | Destino | Origem | Documento mais recente |
|---|---|---|---|
| `finance_events` | 5397 | 5408 | destino `16:23:32Z` / origem `21:10:47Z` |
| `finance_scraped` | 42350 | 42529 | idem |

O destino tem exactamente o que foi copiado; o PC continuou a escrever depois.
E o esperado num espelho pontual de um sistema vivo -- para manter o espelho
alinhado e preciso re-sincronizar, e como os dois indices tem campo de data
(`timestamp` e `data`), da para fazer por incremento em vez de recopiar tudo.

## Migrar os restantes servicos

Um de cada vez, cada um como projeto Docker proprio em
`/opt/iqos/servicos/<nome>`, com a porta presa a 127.0.0.1:

```powershell
.\14-servico-vm.ps1 -Listar            # que servicos existem
.\14-servico-vm.ps1 -Nome searxng      # migra e valida
.\14-servico-vm.ps1 -Nome n8n -Logs    # segue o log
.\14-servico-vm.ps1 -Nome n8n -Parar   # para
```

Cada servico e um projeto Docker separado, por isso `up` so mexe nos contentores
desse projeto: o Caddy, a landing, o ES e o tunel ficam intocados. O
`docker ps` mostra o uptime de cada contentor, e e por ai que se prova que nada
foi reiniciado.

Feitos: **Elasticsearch**, **SearXNG**, **n8n**, **frontend**.

Ha servicos cuja imagem e construida localmente (frontend, backend, osif): esses
precisam de ser transferidos antes de arrancar. O `15-imagem-vm.ps1` faz isso com
`docker save` -> gzip -> ficheiro -> VM -> `docker load`. Nao usa pipelines do
PowerShell para os dados, porque o PowerShell descaracteriza streams binarios ao
passar por comandos nativos; a imagem vai a ficheiro e o redirecionamento e feito
pelo `cmd.exe`. Nota: os layers do Docker ja vem comprimidos, por isso o gzip nao
ganha nada (55,8 MB -> 55,7 MB no frontend).

### Rede partilhada

Cada servico e um projeto composes proprio, logo **nao partilhariam rede** e nao
se resolveriam por nome -- o frontend nao veria o `backend`, o backend nao veria
o `elasticsearch`. Por isso todos entram numa rede externa `iqos-net`, criada
pelo `14-servico-vm.ps1`:

```yaml
networks:
  default:
    name: iqos-net
    external: true
```

Atencao a uma armadilha do frontend: o nginx tem `proxy_pass http://backend:8000`
gravado na imagem e faz **`[emerg] host not found in upstream "backend"`** --
recusa arrancar se o nome nao resolver. Enquanto o backend nao estiver na VM ha
um `extra_hosts: backend:host-gateway` a dar-lhe um destino. **Quando o backend
migrar para a rede `iqos-net`, essa linha tem de sair**, senao o nome fica preso
ao gateway e nunca chega ao backend.

### Recursos da VM

A VM foi redimensionada **pelo painel** da Kamatera (a API nao serve para isto,
ver acima): **8 GB de RAM** (7941 MB) e **148 GB de disco**. O CPU ficou em
**1 core** -- `nproc` = 1. Isso nao aperta a RAM, mas o `backend` faz torch e
scipy e vai notar.

Com o swap em 17 MB (era 332 MB), a pressao de memoria desapareceu. Tudo cabe,
por ordem de peso (medido no PC):

| Servico | RAM | Imagem | Nota |
|---|---|---|---|
| mcp | 20 MB | 13,7 GB | reusa a imagem do backend |
| mirofish | 82 MB | 14,2 GB | imagem publica no ghcr |
| osif (6 contentores) | 243 MB | 1,4 GB (construidas) | stack autonoma |
| hermes-agent | 358 MB | 4,0 GB | imagem publica |
| backend | 791 MB | 13,7 GB (construida) | precisa tambem de `data/` 37 GB + `model/` 3 GB |

Somados dao 1506 MB, muito abaixo dos 6088 MB livres. O cuidado que fica e o CPU
de 1 core a partilhar tudo -- e o `backend`, com torch e scipy, e o que mais o
vai sentir.

Nota: estas instancias **nao sao copias**. Os volumes comecam vazios (o n8n da
VM nao tem fluxos, o searxng nao tem cache). E infraestrutura pronta a receber
dados, nao um clone do que corre no PC.

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
DELETE /service/server/<id>/terminate                    # terminar
```

**As rotas de escrita nao existem no `cloudcli`.** Testado com credenciais
validas: `PUT /service/server/<id>/disk` no `cloudcli` devolve **404**, e no host
`console.kamatera.com` a mesma rota devolve 500/400 -- a assinatura dos
parametros e outra. O `cloudcli` serve leitura (`/servers`, `/server/info`,
`/queue`); o redimensionamento faz-se **pelo painel**, que e mais simples e
nao precisa de credenciais no PC.

Nota util: quando o disco cresce pelo painel, a Kamatera **cresce tambem a
particao e o sistema de ficheiros** -- nao foi preciso `growpart`/`resize2fs`.
Cresceu de 20 GB para 100 GB com o `/` a acompanhar.
