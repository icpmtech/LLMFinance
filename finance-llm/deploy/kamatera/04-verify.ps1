#requires -Version 5.1
<#
.SYNOPSIS
    Verifica o deploy do IQ OS na Kamatera: origem local, tuneis e edge publico.

.DESCRIPTION
    Testa, pela ordem em que o trafego flui:
      1. stack/nginx local em 127.0.0.1:4180
      2. quick tunnel da origem (PC)
      3. containers do edge na VM (por SSH, melhor esforco)
      4. endereco publico do edge
    O `curl` e usado porque o `Invoke-WebRequest` do PS 5.1 nao gosta de hosts
    *.trycloudflare.com resolvidos por DNS filtrado.

.EXAMPLE
    .\04-verify.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [int]$Attempts = 12
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Url {
    param([string]$Name, [string]$Url, [int[]]$Expect = @(200))
    $raw = & curl.exe -s -o NUL -w "%{http_code} %{time_total}s" --max-time 25 $Url 2>$null
    $code = ($raw -split ' ')[0]
    if ($Expect -contains [int]$code) {
        Write-Host ("[OK   ] {0,-26} {1}" -f $Name, $raw) -ForegroundColor Green
    }
    else {
        Write-Host ("[AVISO] {0,-26} {1}  ({2})" -f $Name, $raw, $Url) -ForegroundColor Yellow
    }
}

Write-Host "`n=== 1. Stack local (PC) ===" -ForegroundColor Cyan
Test-Url 'SPA' 'http://127.0.0.1:4180/'
Test-Url 'API /api/health' 'http://127.0.0.1:4180/api/health'
Test-Url 'API /api/providers (401)' 'http://127.0.0.1:4180/api/providers' -Expect 401

Write-Host "`n=== 2. Quick tunnel da origem (PC) ===" -ForegroundColor Cyan
$originFile = Join-Path $here 'origin-url.txt'
if (Test-Path $originFile) {
    $origin = (Get-Content $originFile -Raw).Trim()
    Test-Url 'origem /healthz' "https://$origin/healthz"
    Test-Url 'origem /' "https://$origin/"
}
else { Write-Host 'origin-url.txt nao existe (corre 02-publish-origin.ps1)' -ForegroundColor DarkGray }

Write-Host "`n=== 3. Edge na VM (por SSH) ===" -ForegroundColor Cyan
$ok = $false
for ($i = 1; $i -le $Attempts -and -not $ok; $i++) {
    $out = & ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=8 -o LogLevel=ERROR "$SshUser@$SshHost" `
        "docker ps --format '{{.Names}} {{.Status}}'; sed -n 's/^ORIGIN_HOSTNAME=//p' /opt/iqos/edge/edge.env" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $ok = $true
        ($out -join "`n") | Write-Host
    }
}
if (-not $ok) { Write-Host "nao consegui ligar por SSH apos $Attempts tentativas (rede instavel)" -ForegroundColor Yellow }

Write-Host "`n=== 4. Endereco publico (edge) ===" -ForegroundColor Cyan
$publicFile = Join-Path $here 'public-url.txt'
if (Test-Path $publicFile) {
    $public = (Get-Content $publicFile -Raw).Trim()
    Test-Url 'edge /healthz' "https://$public/healthz"
    Test-Url 'edge /' "https://$public/"
    Test-Url 'edge /api/health' "https://$public/api/health"
    Test-Url 'edge /api/providers (401)' "https://$public/api/providers" -Expect 401
    Write-Host "`nAbrir: https://$public/" -ForegroundColor Yellow
}
else { Write-Host 'public-url.txt nao existe (corre 03-configure-edge.ps1)' -ForegroundColor DarkGray }
