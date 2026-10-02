# OSIF (OSINT Framework v2) dentro do IQ OS

Integração do [fr4nc1stein/osint-framework](https://github.com/fr4nc1stein/osint-framework)
(OSIF v2.0, AGPL-3.0) como app incorporada no IQ OS.

## Como está montado

| Peça | Onde |
| --- | --- |
| Código do upstream | `docker/osif/src/` — **clone local**, fora do git do IQ OS |
| Imagem do backend/worker | `docker/osif/src/backend/Dockerfile` (upstream) |
| Imagem do frontend | `docker/osif/frontend.Dockerfile` (contexto `docker/osif/`) |
| Compose | `docker-compose.yml`, perfil **`osif`** (5 containers + bucket MinIO) |
| Proxy de incorporação | `docker/nginx.conf`, servidor na porta **8894** |
| Página na SPA | `chat-ui/src/iframePages.ts` → «OSINT Framework (OSIF)» |

O iframe abre `http://<host>:8894/` (nginx do IQ OS). Esse servidor reencaminha
`/` para `osif-frontend:80` (SPA Vue compilada) e `/api/`, `/ws/`, `/health`,
`/ready` para `osif-backend:6000`. A SPA do OSIF usa caminhos **relativos**
(`baseURL: ''` em `src/api/client.js`), por isso o proxy na mesma origem funciona
sem reescrever nada da aplicação.

## Arrancar

```powershell
# 1. Código do upstream (só na primeira vez, ou com -Force para atualizar)
powershell -ExecutionPolicy Bypass -File docker/osif/fetch.ps1

# 2. Stack completa: postgres + redis + minio + backend + worker + frontend
docker compose --profile osif up -d --build

# 3. Verificar
docker compose --profile osif ps
curl http://127.0.0.1:8894/health      # {"status":"healthy",...}
```

Depois, na SPA, a página **OSINT Framework (OSIF)** aparece no grupo
«Páginas iframe» da barra lateral (e no dock). O `docker compose up` do núcleo
**não** arranca o OSIF — é preciso o `--profile osif`.

## Portas

| Serviço | Container | Host |
| --- | --- | --- |
| SPA (proxy de incorporação) | `osif-frontend:80` | `8894` |
| API REST + WebSocket | `osif-backend:6000` | `6110` (`OSIF_API_PORT`) |
| MinIO (consola) | `osif-minio:9001` | `9111` (`OSIF_MINIO_CONSOLE_PORT`) |
| PostgreSQL / Redis | internos | não publicados |

## Chaves (todas opcionais)

Sem chaves funcionam os módulos `dns_records`, `subdomain_enum`, `whois_lookup`,
`ip_geolocation`, `urlscan_lookup`, `email_domain`. As restantes
(`shodan_lookup`, `virustotal_domain`, `abuseipdb`, `email_hunter`, `hibp_breach`)
passam a funcionar quando as chaves estiverem no `.env` (ou no separador
*Integrations* da própria app, onde ficam cifradas em PostgreSQL):

```
SHODAN_API_KEY=
VIRUSTOTAL_API_KEY=      # o upstream também aceita VT_API
ABUSEIPDB_API_KEY=
TOMBA_API_KEY=
TOMBA_SECRET_KEY=
HUNTER_API_KEY=
HIBP_API_KEY=
```

## Notas

- O upstream está fixado ao commit `e20dcee2abfaa57e51406fcd9155ba05d26f7c8b`
  (main, depois da tag `v2.0.0`). Atualizar = `fetch.ps1 -Force` + rebuild.
- O frontend é construído com um `default.conf` próprio (só estáticos) para não
  depender de `backend:6000` no arranque — ver `frontend-nginx.conf`.
- O `console` (REPL estilo Metasploit) do upstream não é arrancado: precisa de
  TTY. Pode correr-se à parte com
  `docker compose --profile osif run --rm osif-backend sh` ou pela imagem
  `Dockerfile.console` do upstream.
- Licença: AGPL-3.0 (a mesma do upstream). O código não é modificado; só é
  compilado e servido noutra porta.
