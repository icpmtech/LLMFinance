#requires -Version 5.1
<#
.SYNOPSIS
    Verifica o deploy do IQ OS na Kamatera: stack local, tunel SSH e edge publico.

.DESCRIPTION
    Testa, pela ordem em que o trafego flui:
      1. stack/nginx local em 127.0.0.1:4180
      2. tunel SSH reverso (PC -> VM), visto do lado da VM
      3. containers do edge na VM (por SSH, melhor esforco)
      4. endereco publico do edge
    Usa `curl` porque o `Invoke-WebRequest` do PS 5.1 e mais fragil com TLS
    e com DNS filtrado.

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

Write-Host "`n=== 2. Tunel SSH reverso (PC -> VM) ===" -ForegroundColor Cyan
$ok = $false
for ($i = 1; $i -le $Attempts -and -not $ok; $i++) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    # Visto de dentro da VM: o tunel publica a stack local em 127.0.0.1:8080.
    $out = & ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=8 -o LogLevel=ERROR "$SshUser@$SshHost" `
        "curl -s -o /dev/null -w 'tunel 8080: %{http_code}\n' --max-time 20 http://127.0.0.1:8080/healthz" 2>&1
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -eq 0) { $ok = $true; ($out -join "`n") | Write-Host }
}
if (-not $ok) {
    Write-Host 'AVISO: nao cheguei a VM por SSH. No PC, arranca o 07-origin-tunnel.ps1.' -ForegroundColor Yellow
}

Write-Host "`n=== 3. Edge na VM (por SSH) ===" -ForegroundColor Cyan
$ok = $false
for ($i = 1; $i -le $Attempts -and -not $ok; $i++) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = & ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=8 -o LogLevel=ERROR "$SshUser@$SshHost" `
        "docker ps --format '{{.Names}} {{.Status}}'" 2>&1
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -eq 0) { $ok = $true; ($out -join "`n") | Write-Host }
}
if (-not $ok) { Write-Host "nao consegui ligar por SSH apos $Attempts tentativas (rede instavel)" -ForegroundColor Yellow }

Write-Host "`n=== 4. Endereco publico (edge) ===" -ForegroundColor Cyan
$publicFile = Join-Path $here 'public-url.txt'
if (Test-Path $publicFile) {
    $public = (Get-Content $publicFile -Raw).Trim()
    if ($public -notmatch '^https?://') { $public = "https://$public" }
    Test-Url 'edge /healthz' "$public/healthz"
    Test-Url 'edge /' "$public/"
    Test-Url 'edge /api/health' "$public/api/health"
    Test-Url 'edge /api/providers (401)' "$public/api/providers" -Expect 401
    Write-Host "`nAbrir: $public/" -ForegroundColor Yellow
}
else { Write-Host 'public-url.txt nao existe (corre 03-configure-edge.ps1)' -ForegroundColor DarkGray }
