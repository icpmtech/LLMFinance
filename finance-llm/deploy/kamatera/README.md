# Deploy do IQ OS na Kamatera (VM mais economica)

Edge publico do IQ OS numa VM Kamatera barata, com a stack a continuar a correr
no PC. Tudo o que corre na VM e no PC esta em Docker.

## Topologia

```
                internet
                    |
        https://<aleatorio>.trycloudflare.com     <- cloudflared (quick tunnel, na VM)
                    |
        +---------------------------+
        |  VM Kamatera (EU-MD)      |
        |  iqos-edge (nginx)        |   sem portas publicas: o tunel e so de saida
        |  iqos-tunnel (cloudflared)|
        +---------------------------+
                    |
        https://<aleatorio>.trycloudflare.com     <- cloudflared (quick tunnel, no PC)
                    |
        +---------------------------+
        |  PC (stack IQ OS)         |
        |  iqos-origin (nginx)      |   127.0.0.1:4180  -> SPA (chat-ui/dist)
        |    + /api/ -> backend     |   127.0.0.1:8002  -> API FastAPI
        +---------------------------+
```

Porque e que a VM nao corre a stack toda: a maquina mais barata da Kamatera tem
1 vCPU / 2 GB de RAM / 20 GB de disco, e a stack pede ~40 GB de dados + indices
Elasticsearch + modelos. A VM fica como **ponto de entrada publico** com TLS
gratuito (Cloudflare quick tunnel); os dados ficam onde ja estao.

## Ficheiros

| Ficheiro | Onde corre | Para que serve |
| --- | --- | --- |
| `01-provision-vm.sh` | VM | Instala Docker Engine + Compose e cria 2 GB de swap |
| `02-publish-origin.ps1` | PC | Publica a origem (4180) num quick tunnel e guarda `origin-url.txt` |
| `03-configure-edge.ps1` | PC | Escreve `edge.env`, envia-o e arranca o edge na VM |
| `04-verify.ps1` | PC | Verifica origem, edge e endereco publico |
| `origin/` | PC | nginx que serve a SPA e faz proxy do `/api/` para o backend |
| `edge/` | VM | nginx (reverse proxy) + cloudflared (quick tunnel publico) |

## Arranque (passo a passo)

```powershell
cd C:\LLMFinance\finance-llm

# 1. VM (uma vez): copiar e correr o provisionamento
scp -i "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519" deploy\kamatera\01-provision-vm.sh root@45.147.251.188:/opt/iqos/
ssh -i "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519" root@45.147.251.188 "bash /opt/iqos/01-provision-vm.sh"

# 2. Origem local (PC): nginx com a SPA + proxy da API
docker compose -f deploy/kamatera/origin/compose.yml up -d

# 3. Publicar a origem e configurar o edge
powershell -File deploy\kamatera\02-publish-origin.ps1
powershell -File deploy\kamatera\03-configure-edge.ps1

# 4. Verificar
powershell -File deploy\kamatera\04-verify.ps1
```

O endereco publico fica em `public-url.txt`.

## Notas e armadilhas

- **O hostname do quick tunnel muda a cada arranque.** Sempre que correres o
  `02-publish-origin.ps1`, tem de se correr o `03-configure-edge.ps1` para
  atualizar o `edge.env` na VM.
- `edge.env` **tem de ir com finais de linha LF**: um `\r` colado ao valor entra
  no `server_name`/SNI e o proxy falha. O `03` escreve o ficheiro com
  `[IO.File]::WriteAllText` por isso mesmo.
- `NGINX_ENVSUBST_FILTER` no `compose.yml` e obrigatorio: sem ele o `envsubst` do
  entrypoint do nginx tambem substituiria `$host`, `$remote_addr`, etc.
- No nginx de origem, `proxy_pass ${BACKEND_ORIGIN}/;` (com barra final) retira o
  prefixo `/api` — e o que a stack faz (`docker/nginx.conf`): `/api/health` ->
  `/health` no backend.
- O `resolver 127.0.0.11` + `set $origin` no edge faz a resolucao **em tempo de
  pedido**; sem isto o nginx nao arranca se o hostname de origem ainda nao existir.
- **O PC nao pode adormecer**, senao a origem cai. Em Windows:
  `powercfg /change standby-timeout-ac 0`.
- DNS corporativo pode filtrar `*.trycloudflare.com` (`Resolve-DnsName` falha);
  o tunel funciona na mesma — testar com
  `curl --resolve <host>:443:104.16.231.132 https://<host>/`.
- Um quick tunnel nao tem Cloudflare Access: quem tiver o endereco chega a
  aplicacao (a autenticacao por conta de utilizador do IQ OS continua ativa).

## Custos

VM `iq-os-edge-01` (EU-MD Madrid, 1 vCPU tipo A, 2 GB RAM, 20 GB NVMe):
`priceMonthlyOn = 6` -> **6 USD/mes** (ou 0.008 USD/hora, faturacao horaria).
Os quick tunnels do Cloudflare sao gratuitos.

## Subir a stack completa para a VM (opcional)

Se quiseres correr o IQ OS inteiro na cloud, o caminho e:

1. Redimensionar a VM (API Kamatera, sem reinstalar):
   ```bash
   # CPU e RAM
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'ram=8192' https://cloudcli.cloudwm.com/service/server/<id>/ram
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'cpu=2A'   https://cloudcli.cloudwm.com/service/server/<id>/cpu
   # Disco (com provision=1, a maquina reinicia)
   curl -H "AuthClientId: $ID" -H "AuthSecret: $SECRET" -X PUT \
     -d 'size=100&index=0&provision=1' \
     https://cloudcli.cloudwm.com/service/server/<id>/disk
   ```
   Minimo realista para a stack: **8 GB RAM / 100 GB disco** (data/ 36 GB +
   model/ 3 GB + imagem do backend ~11 GB).
2. Copiar o repositorio (sem `data/`, `model/`, `logs/`) para `/opt/iqos` e
   `docker compose up -d --build`.
3. Manter o edge como esta, apontando `ORIGIN_HOSTNAME` para `localhost`, ou
   servir diretamente pela porta 4180.
