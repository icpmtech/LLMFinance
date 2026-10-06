#requires -Version 5.1
<#
.SYNOPSIS
    Renova o tunel de origem Cloudflare do IQ OS e reaplica a origem no edge da Kamatera.

.DESCRIPTION
    Um quick tunnel pode morrer mesmo com o container `Up`: o Cloudflare reclama-o
    e os logs repetem
    `ERR Register tunnel error from server side error="Unauthorized: Tunnel not found"`.
    O endereco aleatorio deixa de existir e o edge passa a devolver 502.

    Este script faz, por esta ordem:
      1. confirma que o tunel de origem (PC) responde; se nao, recria-o;
      2. atualiza `origin-url.txt` com o hostname em uso;
      3. reaplica a origem no edge da VM (Caddy + dominio proprio sabemos.studio);
      4. guarda `https://sabemos.studio` em `public-url.txt`;
      5. testa tudo ponta-a-ponta.

    Notas: o `05-edge-up.sh` e os ficheiros `edge/compose.yml` e
    `edge/Caddyfile.template` tem de estar em `/opt/iqos/edge` na VM. As ligacoes
    SSH levam `-n` e sao repetidas — a rede para esta VM perde ligacoes de forma
    intermitente.

.EXAMPLE
    .\06-refresh-cloudflare.ps1
    .\06-refresh-cloudflare.ps1 -RecreateOrigin     # forca novo tunel de origem
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [switch]$RecreateOrigin,
    [int]$WaitSeconds = 90
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$compose = Join-Path $here 'origin\compose.yml'
$urlFile = Join-Path $here 'origin-url.txt'
$publicFile = Join-Path $here 'public-url.txt'
$sshBase = @('-i', $SshKey, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
    '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
    '-o', 'LogLevel=ERROR', '-n')

function Invoke-Vm {
    param([Parameter(Mandatory = $true)][string]$Command, [int]$Attempts = 20)
    for ($i = 1; $i -le $Attempts; $i++) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $out = & ssh @sshBase "$SshUser@$SshHost" $Command 2>&1
        $rc = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($rc -eq 0) { return ($out -join "`n") }
        Write-Output ("  ssh tentativa {0}/{1} falhou, a repetir" -f $i, $Attempts)
        Start-Sleep -Seconds 2
    }
    throw "ssh falhou apos $Attempts tentativas"
}

function Test-Tunnel([string]$Hostname) {
    if (-not $Hostname) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = & curl.exe -s -o NUL -m 15 -w "%{http_code}" "https://$Hostname/healthz"
    $ErrorActionPreference = $prev
    return ($code -eq '200')
}

function Get-OriginHostname {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $logs = (& docker logs iqos-origin-tunnel 2>&1 | Out-String)
    $ErrorActionPreference = $prev
    $m = [regex]::Match($logs, 'https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
    if ($m.Success) { return ([Uri]$m.Value).Host }
    return $null
}

Write-Output '=== 1. Tunel de origem (PC) ==='
$originHostname = $null
if (-not $RecreateOrigin -and (Test-Path $urlFile)) {
    $candidate = (Get-Content $urlFile -Raw).Trim()
    if (Test-Tunnel $candidate) {
        $originHostname = $candidate
        Write-Output "  tunel atual responde: $originHostname"
    }
    else {
        Write-Output "  o tunel atual nao responde ($candidate) - a recriar"
    }
}
if (-not $originHostname) {
    & docker compose -f $compose up -d --force-recreate tunnel | Out-Null
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and -not $originHostname) {
        Start-Sleep -Seconds 3
        $candidate = Get-OriginHostname
        if (Test-Tunnel $candidate) { $originHostname = $candidate }
    }
    if (-not $originHostname) { throw 'Nao consegui um tunel de origem vivo. Ver: docker logs iqos-origin-tunnel' }
    Write-Output "  novo tunel de origem: $originHostname"
}
$originHostname | Set-Content -Path $urlFile -Encoding ascii

Write-Output '=== 2. Enviar ficheiros do edge para a VM ==='
$caddyLocal = Join-Path $here 'edge\Caddyfile.template'
$composeLocal = Join-Path $here 'edge\compose.yml'
$caddyB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($caddyLocal))
$composeB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($composeLocal))
$pushEdge = @"
mkdir -p /opt/iqos/edge
printf %s '$caddyB64' | base64 -d > /opt/iqos/edge/Caddyfile.template
printf %s '$composeB64' | base64 -d > /opt/iqos/edge/compose.yml
sed -i 's/\r$//' /opt/iqos/edge/Caddyfile.template /opt/iqos/edge/compose.yml
wc -c /opt/iqos/edge/Caddyfile.template /opt/iqos/edge/compose.yml
"@
Write-Output (Invoke-Vm -Command $pushEdge)

Write-Output '=== 3. Edge na VM ==='
$remote = Invoke-Vm -Command "bash /opt/iqos/05-edge-up.sh $originHostname 2>&1 | tail -20"
Write-Output $remote

Write-Output '=== 4. Endereco publico ==='
'https://sabemos.studio' | Set-Content -Path $publicFile -Encoding ascii
$publicUrl = 'https://sabemos.studio'

Write-Output '=== 5. Verificacao ==='
foreach ($path in @('/healthz', '/', '/api/health', '/api/providers')) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = & curl.exe -s -o NUL -m 25 -w "%{http_code}" "$publicUrl$path"
    $ErrorActionPreference = $prev
    $tag = if ($code -in @('200', '401')) { 'OK  ' } else { 'FALHA' }
    Write-Output ("  [{0}] {1} -> {2}" -f $tag, $path, $code)
}

Write-Output ''
Write-Output "==> Endereco publico: $publicUrl"
Write-Output "==> Origem: $originHostname"
