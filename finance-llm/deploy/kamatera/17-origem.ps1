#requires -Version 5.1
<#
.SYNOPSIS
    Alterna a origem do site entre o PC (pelo tunel) e a propria VM.

.DESCRIPTION
    O Caddy do edge serve https://sabemos.studio a partir de um upstream
    configuravel (`ORIGEM_UPSTREAM`, ver o cabecalho do `edge/Caddyfile`):

      pc  -> 127.0.0.1:8080   a stack do PC, publicada pelo tunel SSH reverso
      vm  -> 127.0.0.1:4180   a SPA que corre nesta VM

    Escreve o `edge/.env` na VM e recria so o contentor do Caddy. O tunel, os
    servicos migrados e o stack do PC nao sao tocados.

    ATENCAO ao modo `vm`: a VM ainda **nao tem backend**. A SPA serve-se e os
    ficheiros estaticos carregam, mas `/api/...` da 502 e o `handle_errors` do
    Caddy mostra a pagina de apresentacao. Para o site ficar completo a partir da
    VM falta migrar o backend (e os 37 GB de `data/`).

.EXAMPLE
    .\17-origem.ps1                    # ver qual esta activo
    .\17-origem.ps1 -Modo vm           # passar a servir so da VM
    .\17-origem.ps1 -Modo pc           # voltar ao PC
#>
[CmdletBinding()]
param(
    [ValidateSet('pc', 'vm')]
    [string]$Modo,

    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$EdgeDir = '/opt/iqos/edge'
)

$ErrorActionPreference = 'Stop'

$UPSTREAM = @{
    'pc' = '127.0.0.1:8080'
    'vm' = '127.0.0.1:4180'
}

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

function Show-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $r = Invoke-Vm $RemoteCommand
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Host "  $_" } }
    return $r
}

if (-not (docker ps --filter "name=$TunnelContainer" --format '{{.Names}}')) {
    throw "o container $TunnelContainer nao esta a correr (ver 07-origin-tunnel.ps1)."
}

# --- Estado actual ----------------------------------------------------------
$actual = (Invoke-Vm "grep -h ORIGEM_UPSTREAM $EdgeDir/.env 2>/dev/null || echo 'ORIGEM_UPSTREAM=127.0.0.1:8080 (por omissao, sem .env)'").Output.Trim()
$emUso = (Invoke-Vm "docker exec iqos-caddy printenv ORIGEM_UPSTREAM 2>/dev/null || echo '(nao definida)'").Output.Trim()

Write-Host ''
Write-Host '=== Origem actual ===' -ForegroundColor Cyan
Write-Host "  no .env       : $actual"
Write-Host "  no Caddy      : $emUso"
$modoActual = if ($emUso -match '4180') { 'vm' } elseif ($emUso -match '8080') { 'pc' } else { '?' }
Write-Host "  modo          : $modoActual" -ForegroundColor Yellow

if (-not $Modo) {
    Write-Host ''
    Write-Host '  Para mudar:' -ForegroundColor DarkGray
    Write-Host '    .\17-origem.ps1 -Modo vm   # servir so da VM' -ForegroundColor DarkGray
    Write-Host '    .\17-origem.ps1 -Modo pc   # voltar ao PC' -ForegroundColor DarkGray
    Write-Host ''
    return
}

$novo = $UPSTREAM[$Modo]
if ($emUso -eq $novo) {
    Write-Host ''
    Write-Host "Ja esta no modo '$Modo' ($novo). Nada a fazer." -ForegroundColor Green
    Write-Host ''
    return
}

Write-Host ''
Write-Host "=== A mudar para '$Modo' ($novo) ===" -ForegroundColor Cyan
if ($Modo -eq 'vm') {
    Write-Host '  AVISO: a VM ainda nao tem backend -- /api dara 502 e o Caddy' -ForegroundColor Yellow
    Write-Host '         mostrara a pagina de apresentacao no lugar dos dados.' -ForegroundColor Yellow
    Write-Host ''
}

# O `.env` fica ao lado do compose, que e onde o `docker compose` o le.
Show-Vm "printf 'ORIGEM_UPSTREAM=$novo\n' > $EdgeDir/.env && cat $EdgeDir/.env" | Out-Null

Write-Host ''
Write-Host '=== A recriar o Caddy ===' -ForegroundColor Cyan
Show-Vm "cd $EdgeDir && docker compose up -d --force-recreate caddy 2>&1" | Out-Null

Write-Host ''
Write-Host '=== A aguardar ===' -ForegroundColor Cyan
$pronto = $false
for ($i = 1; $i -le 12; $i++) {
    $st = (Invoke-Vm "docker inspect iqos-caddy --format {{.State.Health.Status}} 2>/dev/null").Output.Trim()
    if ($st -eq 'healthy') { Write-Host "  caddy healthy na tentativa $i" -ForegroundColor Green; $pronto = $true; break }
    Write-Host "  tentativa $i : $st"
    Start-Sleep -Seconds 5
}
if (-not $pronto) { Write-Host '  o Caddy nao ficou saudavel -- ver `17-origem.ps1` e o log do contentor.' -ForegroundColor Red }

Write-Host ''
Write-Host '=== Validacao pelo dominio publico ===' -ForegroundColor Cyan
foreach ($u in @('https://sabemos.studio/healthz', 'https://sabemos.studio/', 'https://sabemos.studio/api/health', 'https://sabemos.studio/landing')) {
    try {
        $r = Invoke-WebRequest -Uri $u -TimeoutSec 20 -UseBasicParsing
        Write-Host ("  {0,-40} HTTP {1}" -f $u, $r.StatusCode) -ForegroundColor Green
    } catch {
        Write-Host ("  {0,-40} {1}" -f $u, $_.Exception.Message) -ForegroundColor Yellow
    }
}

Write-Host ''
$confirmado = (Invoke-Vm "docker exec iqos-caddy printenv ORIGEM_UPSTREAM").Output.Trim()
Write-Host "  ORIGEM_UPSTREAM no Caddy: $confirmado" -ForegroundColor Green
Write-Host ''
