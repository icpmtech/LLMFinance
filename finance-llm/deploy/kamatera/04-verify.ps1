#requires -Version 5.1
<#
.SYNOPSIS
    Verifica o deploy: origem local, edge na VM (por SSH) e endereco publico.

.EXAMPLE
    .\04-verify.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519"
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sshArgs = @('-i', $SshKey, '-o', 'BatchMode=yes')

function Test-Url([string]$Name, [string]$Url, [int]$Expect = 200) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20
        $ok = ($r.StatusCode -eq $Expect)
        $tag = if ($ok) { 'OK  ' } else { 'AVISO' }
        Write-Host ("[{0}] {1,-32} {2} ({3})" -f $tag, $Name, $r.StatusCode, $Url)
    }
    catch {
        $code = $_.Exception.Response.StatusCode.value__
        $label = if ($code) { $code } else { $_.Exception.Message }
        Write-Host ("[FALHA] {0,-32} {1} ({2})" -f $Name, $label, $Url) -ForegroundColor Red
    }
}

Write-Host "`n=== 1. Origem local (PC) ===" -ForegroundColor Cyan
Test-Url 'origem SPA' 'http://127.0.0.1:4180/' 200
Test-Url 'origem API' 'http://127.0.0.1:4180/api/health' 200
Test-Url 'origem API (auth)' 'http://127.0.0.1:4180/api/providers' 401

$originFile = Join-Path $here 'origin-url.txt'
if (Test-Path $originFile) {
    $originHost = (Get-Content $originFile -Raw).Trim()
    Write-Host "`n=== 2. Origem publica (quick tunnel do PC) ===" -ForegroundColor Cyan
    Test-Url 'tunel origem /healthz' "https://$originHost/healthz" 200
}

Write-Host "`n=== 3. Edge na VM (por SSH) ===" -ForegroundColor Cyan
& ssh @sshArgs "${SshUser}@${SshHost}" "docker ps --format 'table {{.Names}}\t{{.Status}}'; echo '--- nginx -> /healthz ---'; docker exec iqos-edge wget -q -O - http://127.0.0.1/healthz; echo '--- proxy -> origem ---'; docker exec iqos-edge wget -q -O - --no-check-certificate https://\$(grep ORIGIN_HOSTNAME /opt/iqos/edge/edge.env | cut -d= -f2)/healthz"

Write-Host "`n=== 4. Endereco publico (edge) ===" -ForegroundColor Cyan
$publicFile = Join-Path $here 'public-url.txt'
if (Test-Path $publicFile) {
    $publicHost = (Get-Content $publicFile -Raw).Trim()
    Test-Url 'edge publico /healthz' "https://$publicHost/healthz" 200
    Test-Url 'edge publico SPA' "https://$publicHost/" 200
    Test-Url 'edge publico API' "https://$publicHost/api/health" 200
    Write-Host "`nAbrir: https://$publicHost/" -ForegroundColor Yellow
}
else {
    Write-Host 'public-url.txt ainda nao existe (corre 03-configure-edge.ps1).' -ForegroundColor DarkGray
}
