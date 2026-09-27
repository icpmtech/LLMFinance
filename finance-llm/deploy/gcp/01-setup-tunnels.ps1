#requires -Version 5.1
<#
.SYNOPSIS
    Cria os dois túneis Cloudflare do IQ OS: o do edge (VM e2-micro) e o da
    origem (o teu PC, onde corre a stack).

.DESCRIPTION
    Corre no PC. Faz, por ordem:
      1. login no Cloudflare (uma vez, cria ~/.cloudflared/cert.pem)
      2. cria os túneis `iqos-edge` e `iqos-origin` (idempotente)
      3. cria os CNAMEs DNS para os dois hostnames
      4. escreve deploy/gcp/origin/config.yml (túnel da origem)
      5. imprime o que falta fazer (service token do Access + Cloud Shell)

    O túnel `iqos-edge` fica sem config local: o ficheiro de config é gerado na
    VM pelo script `03-configure-edge.sh`.

.EXAMPLE
    .\01-setup-tunnels.ps1 -PublicHost iqos.exemplo.com -OriginHost iqos-origin.exemplo.com
#>
[CmdletBinding()]
param(
    # Hostname público (o que abres no browser).
    [Parameter(Mandatory = $true)][string]$PublicHost,

    # Hostname da origem (stack local). Fica protegido por Cloudflare Access
    # com uma política «Service Auth»; só o edge consegue falar com ele.
    [Parameter(Mandatory = $true)][string]$OriginHost,

    # Onde a stack local responde. O nginx do docker compose serve a SPA e faz
    # proxy de /api/ para o backend.
    [string]$LocalOrigin = 'http://127.0.0.1:4180',

    [string]$EdgeTunnelName = 'iqos-edge',
    [string]$OriginTunnelName = 'iqos-origin',

    # Domínio na conta Cloudflare (para a verificação de DNS no fim).
    [string]$Zone = ($OriginHost -replace '^[^.]*\.', '')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$deployDir = $PSScriptRoot
$originDir = Join-Path $deployDir 'origin'
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
$certPem = Join-Path $cfDir 'cert.pem'

New-Item -ItemType Directory -Force -Path $originDir | Out-Null

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# 0. Pré-requisitos
# ---------------------------------------------------------------------------
Write-Step 'Verificar pré-requisitos'

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    throw "cloudflared não está no PATH. Instala com: winget install Cloudflare.cloudflared"
}
Write-Ok "cloudflared $((& $cf.Source --version) -replace '^cloudflared version ', '')"

# DNS é insensível a maiúsculas, mas os CNAMEs ficam mais legíveis normalizados.
$PublicHost = $PublicHost.Trim().ToLowerInvariant()
$OriginHost = $OriginHost.Trim().ToLowerInvariant()

foreach ($h in @($PublicHost, $OriginHost)) {
    if ($h -notmatch '^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$') {
        throw "Hostname inválido: '$h'. Usa um FQDN em minúsculas, ex.: iqos.exemplo.com"
    }
}
if ($PublicHost -eq $OriginHost) { throw 'PublicHost e OriginHost têm de ser diferentes.' }
Write-Ok "público: $PublicHost"
Write-Ok "origem:  $OriginHost"

# ---------------------------------------------------------------------------
# 1. Login no Cloudflare
# ---------------------------------------------------------------------------
Write-Step 'Login no Cloudflare'
if (Test-Path $certPem) {
    Write-Ok "cert.pem já existe ($certPem)"
}
else {
    Write-Warn2 'Vai abrir o browser para escolheres a zona (domínio).'
    & $cf.Source tunnel login
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $certPem)) {
        throw "Login falhou (cert.pem não criado em $certPem)."
    }
    Write-Ok 'cert.pem criado'
}

# ---------------------------------------------------------------------------
# 2. Túneis (idempotente)
# ---------------------------------------------------------------------------
function Resolve-TunnelId {
    param([string]$Name)

    $raw = (& $cf.Source tunnel list 2>&1 | Out-String)
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -match [regex]::Escape($Name)) {
            if ($line -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})') {
                return $Matches[1]
            }
        }
    }
    return $null
}

function Ensure-Tunnel {
    param([string]$Name)

    $id = Resolve-TunnelId -Name $Name
    if ($id) {
        Write-Ok "túnel '$Name' já existe ($id)"
        return $id
    }

    $out = (& $cf.Source tunnel create $Name 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o túnel '$Name':`n$out" }
    if ($out -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})') {
        $id = $Matches[1]
    }
    if (-not $id) { throw "Não consegui extrair o UUID do túnel '$Name' de:`n$out" }

    Write-Ok "túnel '$Name' criado ($id)"
    return $id
}

Write-Step 'Criar túneis'
$edgeId = Ensure-Tunnel -Name $EdgeTunnelName
$originId = Ensure-Tunnel -Name $OriginTunnelName

$edgeCreds = Join-Path $cfDir "$edgeId.json"
$originCreds = Join-Path $cfDir "$originId.json"
foreach ($f in @($edgeCreds, $originCreds)) {
    if (-not (Test-Path $f)) { throw "Ficheiro de credenciais em falta: $f" }
}
Write-Ok "credenciais do edge:   $edgeCreds"
Write-Ok "credenciais da origem: $originCreds"

# ---------------------------------------------------------------------------
# 3. DNS
# ---------------------------------------------------------------------------
function Ensure-DnsRoute {
    param([string]$Name, [string]$Hostname)

    $raw = (& $cf.Source tunnel route dns --overwrite-dns $Name $Hostname 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao criar o DNS para $Hostname. A zona '$Zone' pertence à conta?`n$raw"
    }
    Write-Ok "DNS $Hostname -> $Name"
}

Write-Step 'Criar registos DNS (CNAME)'
Ensure-DnsRoute -Name $EdgeTunnelName -Hostname $PublicHost
Ensure-DnsRoute -Name $OriginTunnelName -Hostname $OriginHost

# ---------------------------------------------------------------------------
# 4. Config do túnel de origem
# ---------------------------------------------------------------------------
Write-Step 'Escrever a config do túnel de origem'

$configPath = Join-Path $originDir 'config.yml'
$config = @"
# Túnel de ORIGEM do IQ OS — gerado por 01-setup-tunnels.ps1.
# Publica a stack local ($LocalOrigin) no hostname $OriginHost.
#
# Este ficheiro é privado (está no .gitignore): contém o caminho das credenciais.
tunnel: $originId
credentials-file: $originCreds

ingress:
  - hostname: $OriginHost
    service: $LocalOrigin
    originRequest:
      connectTimeout: 30s
      # O chat usa SSE e as importações de contratos são longas.
      noTLSVerify: false
      keepAliveTimeout: 90s
      disableChunkedEncoding: false
  # Obrigatório: qualquer outro hostname recebe 404 (não expõe nada por engano).
  - service: http_status:404
"@
# Sem BOM: o parser YAML do cloudflared não aceita BOM no início do ficheiro.
[IO.File]::WriteAllText($configPath, $config, (New-Object Text.UTF8Encoding $false))
Write-Ok "config escrita em $configPath"

$infoPath = Join-Path $originDir 'edge-tunnel-info.txt'
$info = @"
# Valores necessários no Cloud Shell (script 02/03) — não versionado.

PUBLIC_HOST=$PublicHost
ORIGIN_HOST=$OriginHost

# Nome e UUID do túnel do edge
EDGE_TUNNEL_NAME=$EdgeTunnelName
EDGE_TUNNEL_UUID=$edgeId
EDGE_CREDENTIALS_FILE=$edgeCreds

# Túnel de origem (fica só no PC)
ORIGIN_TUNNEL_NAME=$OriginTunnelName
ORIGIN_TUNNEL_UUID=$originId
LOCAL_ORIGIN=$LocalOrigin
"@
[IO.File]::WriteAllText($infoPath, $info, (New-Object Text.UTF8Encoding $false))
Write-Ok "resumo escrito em $infoPath"

# ---------------------------------------------------------------------------
# 5. Próximos passos
# ---------------------------------------------------------------------------
$proximos = @"

================================================================================
FALTA UM PASSO MANUAL (obrigatório) — proteger o hostname de origem
================================================================================
O hostname de origem ($OriginHost) está publicado na internet. Sem isto,
qualquer pessoa chega ao backend sem passar pelo IQ OS.

  1. Zero Trust > Access > Service Auth > Create Service Token
     Nome: iqos-edge
     Guarda o Client ID (<id>.access) e o Client Secret — só aparecem uma vez.

  2. Zero Trust > Access > Applications > Add an application > Self-hosted
     Application name: IQ OS origem
     Public hostname: $OriginHost
     Policy: Action = Service Auth, Include = Service Token = iqos-edge
     (sem regras de Allow para browsers — só o edge entra)

  3. Copia esses dois valores para deploy/gcp/edge/edge.env
     (modelo em deploy/gcp/edge/edge.env.example)

Recomendado (mesma secção): põe também uma Access application no hostname
público $PublicHost com política de email (One-time PIN ou Google), para não
deixar a plataforma aberta a quem tenha o URL.

================================================================================
A SEGUIR
================================================================================
1) Arrancar a stack local + túnel de origem:
     cd $deployDir
     .\04-start-origin.ps1
   (para ficar sempre a correr como serviço do Windows, ver -AsService)

2) Provisionar o edge na Google Cloud (Cloud Shell — não precisas de instalar
   o gcloud no PC):
     - abre https://shell.cloud.google.com
     - envia a pasta deploy/gcp (UPLOAD > Folder)
     - corre:  bash 02-provision-vm.sh

3) Configurar o edge na VM (ainda no Cloud Shell):
     bash 03-configure-edge.sh

4) Validar do PC:
     .\05-verify.ps1 -PublicHost $PublicHost -OriginHost $OriginHost
"@
Write-Host $proximos -ForegroundColor Gray
