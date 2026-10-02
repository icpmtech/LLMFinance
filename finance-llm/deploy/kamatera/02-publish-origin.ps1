#requires -Version 5.1
<#
.SYNOPSIS
    Publica a stack IQ OS do PC num endereco temporario Cloudflare (quick tunnel)
    e guarda o hostname para o edge da Kamatera usar como origem.

.DESCRIPTION
    Arranca `cloudflared tunnel --url http://127.0.0.1:4180` em segundo plano,
    espera pelo endereco publico e escreve:
      - origin-url.txt  -> apenas o hostname (ex.: abc-def-ghi.trycloudflare.com)
      - origin-tunnel.pid -> PID do cloudflared (para o parar depois)
      - origin-tunnel.err.log -> log do cloudflared (escreve o URL em stderr)

    O hostname muda a cada arranque: sempre que este script corre, e preciso
    atualizar o `edge.env` na VM (03-configure-edge.ps1) e reiniciar o nginx.

.EXAMPLE
    .\02-publish-origin.ps1
#>
[CmdletBinding()]
param(
    # O que fica exposto. 4180 = nginx de origem (SPA + proxy /api).
    [string]$Origin = 'http://127.0.0.1:4180',
    [int]$WaitSeconds = 90
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $here 'origin-tunnel.err.log'
$outLog = Join-Path $here 'origin-tunnel.out.log'
$pidFile = Join-Path $here 'origin-tunnel.pid'
$urlFile = Join-Path $here 'origin-url.txt'

# 1) Parar o tunel anterior, se existir.
if (Test-Path $pidFile) {
    $old = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($old -and ($old -match '^\d+$')) {
        Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue
        Write-Host "tunel anterior (PID $old) parado"
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2) Confirmar que a origem responde antes de gastar um tunel.
try {
    $r = Invoke-WebRequest -Uri $Origin -UseBasicParsing -TimeoutSec 8
    Write-Host "origem OK ($($r.StatusCode)): $Origin" -ForegroundColor Green
}
catch {
    throw "A origem $Origin nao responde: $($_.Exception.Message). Arranca-a com: docker compose -f deploy\kamatera\origin\compose.yml up -d"
}

# 3) Arrancar o cloudflared destacado (o URL sai no stderr).
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue)
if (-not $cf) { throw 'cloudflared nao esta no PATH. Instala com: winget install Cloudflare.cloudflared' }
Remove-Item $log, $outLog -Force -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath $cf.Source `
    -ArgumentList @('tunnel', '--url', $Origin, '--no-autoupdate') `
    -RedirectStandardError $log -RedirectStandardOutput $outLog `
    -WindowStyle Hidden -PassThru
$proc.Id | Set-Content -Path $pidFile -Encoding ascii
Write-Host "cloudflared arrancado (PID $($proc.Id))"

# 4) Esperar pelo hostname publico.
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$url = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Path $log) {
        $m = [regex]::Match((Get-Content $log -Raw), 'https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
        if ($m.Success) { $url = $m.Value; break }
    }
    if ($proc.HasExited) { throw "cloudflared terminou. Ver $log" }
}

if (-not $url) { throw "Nao consegui obter o endereco publico em $WaitSeconds s. Ver $log" }

$hostname = ([Uri]$url).Host
$hostname | Set-Content -Path $urlFile -Encoding ascii

Write-Host ''
Write-Host "==> Origem publica: $url" -ForegroundColor Yellow
Write-Host "==> hostname guardado em origin-url.txt: $hostname" -ForegroundColor Yellow
