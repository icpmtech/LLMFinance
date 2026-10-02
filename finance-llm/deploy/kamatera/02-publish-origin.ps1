#requires -Version 5.1
<#
.SYNOPSIS
    Publica a stack IQ OS do PC num endereco temporario Cloudflare (quick tunnel)
    e guarda o hostname para o edge da Kamatera usar como origem.

.DESCRIPTION
    O tunel corre **em Docker** (servico `tunnel` do origin\compose.yml): assim
    sobrevive ao fecho do terminal e reinicia sozinho. Este script le o endereco
    publico dos logs do container e escreve `origin-url.txt` (so o hostname).

    O hostname muda sempre que o container do tunel e recriado; nesse caso e
    preciso voltar a aplicar o novo valor no edge da VM (05-edge-up.sh).

.EXAMPLE
    .\02-publish-origin.ps1
#>
[CmdletBinding()]
param(
    # Vazio => origin\compose.yml ao lado deste script. ($PSScriptRoot nao pode
    # ser usado no valor por omissao de um parametro no PowerShell 5.1.)
    [string]$ComposeFile = '',
    [string]$Origin = 'http://127.0.0.1:4180',
    [int]$WaitSeconds = 90
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$urlFile = Join-Path $here 'origin-url.txt'
if (-not $ComposeFile) { $ComposeFile = Join-Path $here 'origin\compose.yml' }

# 1) Confirmar que a origem local responde.
try {
    $r = Invoke-WebRequest -Uri "$Origin/healthz" -UseBasicParsing -TimeoutSec 8
    Write-Host "origem OK ($($r.StatusCode)): $Origin" -ForegroundColor Green
}
catch {
    throw "A origem $Origin nao responde: $($_.Exception.Message). Arranca-a com: docker compose -f `"$ComposeFile`" up -d origin"
}

# 2) Subir origem + tunel.
& docker compose -f $ComposeFile up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'docker compose up falhou' }

# 3) Ler o endereco publico dos logs do cloudflared.
Write-Host "a aguardar o endereco publico (ate $WaitSeconds s)..."
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$public = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    # O logrus do cloudflared escreve TUDO em stderr: com ErrorActionPreference
    # a Stop, o PowerShell transforma isso num erro terminante.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $logs = (& docker logs iqos-origin-tunnel 2>&1 | Out-String)
    $ErrorActionPreference = $prev
    $m = [regex]::Match($logs, 'https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
    if ($m.Success) { $public = $m.Value; break }
}
if (-not $public) { throw 'Nao encontrei o endereco publico. Ver: docker logs iqos-origin-tunnel' }

$hostname = ([Uri]$public).Host
$hostname | Set-Content -Path $urlFile -Encoding ascii

Write-Host ''
Write-Host "==> Origem publica: $public" -ForegroundColor Yellow
Write-Host "==> hostname guardado em origin-url.txt: $hostname" -ForegroundColor Yellow
Write-Host '==> Aplicar no edge da VM: bash /opt/iqos/05-edge-up.sh <hostname>' -ForegroundColor DarkGray
