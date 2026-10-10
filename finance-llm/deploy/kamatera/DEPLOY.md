# Deploy incremental do frontend e do backend

Como pôr código novo na VM `iq-os-edge-01` sem transferir imagens.

```powershell
cd C:\LLMFinance\finance-llm\deploy\kamatera

.\19-deploy-codigo.ps1                    # backend + frontend + mcp (o normal)
.\19-deploy-codigo.ps1 -Servico frontend   # só o frontend
.\19-deploy-codigo.ps1 -Servico backend    # backend + mcp
.\19-deploy-codigo.ps1 -SemBuild           # reutiliza o dist já construído
.\19-deploy-codigo.ps1 -Planear            # mostra o que faria, sem enviar nada
.\19-deploy-codigo.ps1 -LimparCache        # e limpa a cache de build no fim
```

## Porque é que isto é "incremental"

A imagem do backend são **13,7 GB**. Enviá-la a cada mudança de código não é
deploy contínuo — são ~4 GB de tar, ~20 minutos a 4,4 MB/s, e uma queda da
ligação a meio obriga a recomeçar.

O que muda entre dois deploys é **código**, e o código são **11,9 MB** de
contexto. A diferença é de três ordens de grandeza, e é isso que este deploy
explora.

| | Imagem inteira (`15-imagem-vm.ps1`) | Incremental (`19-deploy-codigo.ps1`) |
| --- | --- | --- |
| Transferido | 4,0 GB (tar do backend) | **11,9 MB** |
| Tempo de transferência | ~15 min a 4,4 MB/s | **~3 s** |
| Dependências | reinstaladas se a cache cair | não são tocadas |
| Risco | `pandas`/`transformers` a mudar de versão sem aviso | nenhum |

## Como funciona

O truque está nos Dockerfiles incrementais, que já existiam:

```dockerfile
# Dockerfile.backend.incremental
ARG BASE=iq-os-backend:antes-deep-search
FROM ${BASE}
COPY . .
RUN pip install --no-cache-dir "edge-tts>=6.1.0" "faster-whisper>=1.0.0"
```

```dockerfile
# Dockerfile.frontend.incremental
ARG BASE=iq-os-frontend:antes-deep-search
FROM ${BASE}
COPY _frontend_dist /usr/share/nginx/html
```

Assentam na imagem que **já está validada na VM** e substituem só o código. As
versões de `pandas`, `transformers` e `numpy` ficam exactamente as que estavam a
funcionar — que é o que evita que um deploy de uma linha de Python mude o
ambiente inteiro por baixo.

O script, passo a passo:

| Passo | Onde | O que faz |
| --- | --- | --- |
| 1 | PC | `npm run build` do `chat-ui` com `VITE_API_URL=/api` |
| 2 | PC | empacota o contexto (~12 MB), com as exclusões do `.dockerignore` |
| 3 | PC → VM | envia o `.tgz` (uma ligação, com verificação de tamanho) |
| 4 | VM | `docker build` dos incrementais sobre a imagem que lá está |
| 5 | VM | recria só `iqos-backend`, `iqos-mcp` e `iqos-frontend` |
| 6 | PC | sonda HTTP + confirma a versão do bundle servido |

Nada disto toca no Caddy, no Elasticsearch, no túnel SSH nem no stack do PC.

## O que a validação verifica

```
frontend   ok     HTTP 200
backend    ok     HTTP 200
mcp        ok     HTTP 404
bundle     ok     assets/index-B-40BDWI.js (na imagem e servido)
```

- **frontend / backend / mcp** — sondas HTTP reais, com repetição (o contentor
  acabou de ser recriado e um `curl` imediato dá `000`, o que já fez um deploy
  bom parecer falhado). O `404` do mcp conta como bom: o endpoint responde a
  `POST` com JSON-RPC, não a um `GET`.
- **bundle** — compara o nome do ficheiro que o Vite gerou com o que a imagem
  tem e com o que sai pelo porto publicado. Um `200` no frontend **não** prova
  nada sobre a versão do código: o nginx responde `200` com o `index.html` que
  tiver. Este é o modo de falha que já aconteceu — build passa, contentor sobe,
  página serve o bundle antigo.

## Custos, medidos

| Item | Valor |
| --- | --- |
| Contexto de build | 11,9 MB (limite de segurança: 150 MB) |
| Imagem do backend | 13,7 GB |
| Imagem do frontend | 279 MB |
| Disco da VM | 148 GB, 68% usado |
| Cache de build | ~14 GB (cresce ~GB por deploy) |

A cache de build é o único custo que cresce sozinho. O driver `docker` do
buildkit guarda um snapshot por build; depois de um deploy vi-a ir de 89 MB para
13,8 GB. Não é erro, mas enche o disco sem avisar — daí o `-LimparCache`.

## Quando **não** usar isto

O incremental só substitui código. Se o que mudou foi:

| Mudança | Usar |
| --- | --- |
| `requirements.txt` (dependências novas) | `Dockerfile.backend` (rebuild completo) |
| `package.json` / `package-lock.json` | `Dockerfile.frontend` (rebuild completo) |
| `docker/nginx.conf` | `Dockerfile.frontend` |
| Uma biblioteca de sistema (`apt`) | o Dockerfile completo correspondente |
| Só código Python ou TypeScript | **este script** |

E se a própria imagem base tiver de ser reconstruída a frio, ou for para uma
máquina que não a tem, aí é o `15-imagem-vm.ps1` (imagem inteira, por blocos,
com repetição).

## Problemas conhecidos

**O contexto cresce para GB sem aviso.** Já aconteceu: as partes NDJSON da
migração de contratos (`deploy/kamatera/es/_export`, 10,7 GB) entraram no
contexto e um deploy chegou a 7,4 GB de tar. A lista de exclusões existe em
**dois** sítios — `.dockerignore` e o script — e já divergiram. A salvaguarda dos
150 MB existe para que a próxima divergência seja ruidosa em vez de ser meia hora
de espera sem explicação.

**As camadas acumulam.** Cada build incremental **acrescenta** camadas, não
substitui. Ao fim de muitas dezenas de deploys a imagem fica maior do que
precisa. Um rebuild completo de vez em quando resolve.

**Um `COPY` de uma pasta para outra que já existe não apaga o que lá estava.**
O `COPY _frontend_dist /usr/share/nginx/html` sobrepõe ficheiros com o mesmo
nome, mas deixa os bundles antigos de builds anteriores dentro da imagem. Não
parte nada (o `index.html` aponta para o novo), mas engorda.

**A porta do backend é 8002, não 8000.** O contentor escuta na 8000, mas a VM
publica-o em `127.0.0.1:8002` (herdado do `FINANCE_API_PORT` do `.env` do PC
quando o serviço migrou). Este script sondava a 8000 e anunciava "1 serviço sem
resposta" num deploy que tinha corrido bem.

**`_frontend_dist` não pode entrar no `.dockerignore`.** O
`Dockerfile.frontend.incremental` faz `COPY _frontend_dist`, e um ficheiro
excluído do contexto faz a build falhar com `CopyIgnoredFile`. São ~20 MB a mais
no contexto do backend, e é o preço de o frontend construir sem repetir o
`npm ci`. (O cabeçalho do Dockerfile ainda diz o contrário — está desactualizado.)

## Ficheiros

| Ficheiro | Para que serve |
| --- | --- |
| `19-deploy-codigo.ps1` | este deploy (o script) |
| `Dockerfile.backend.incremental` | backend: `FROM` a imagem validada + `COPY . .` |
| `Dockerfile.frontend.incremental` | frontend: `FROM` a imagem validada + `COPY _frontend_dist` |
| `15-imagem-vm.ps1` | imagem inteira, por blocos (quando o incremental não serve) |
| `14-servico-vm.ps1` | parar/arrancar/ver um serviço na VM |
| `.dockerignore` | o que fica fora do contexto — **manter em sincronia** com a lista do script |
