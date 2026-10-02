#requires -Version 5.1
<#
.SYNOPSIS
    Configura o edge do IQ OS na VM Kamatera e mostra o endereco publico.

.DESCRIPTION
    1. Le o hostname da origem de `origin-url.txt` (criado por 02-publish-origin.ps1).
    2. Escreve `edge.env` (com finais de linha LF!).
    3. Copia-o para /opt/iqos/edge/ na VM.
    4. Arranca o compose (nginx + cloudflared quick tunnel).
    5. Le o endereco publico *.trycloudflare.com do log do cloudflared.

.EXAMPLE
    .\03-configure-edge.ps1
    .\03-configure-edge.ps1 -SshHost 45.147.251.188 -SshKey "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519"
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [string]$RemoteDir = '/opt/iqos/edge',
    [int]$WaitSeconds = 60
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$urlFile = Join-Path $here 'origin-url.txt'

if (-not (Test-Path $urlFile)) { throw "Falta $urlFile. Corre primeiro 02-publish-origin.ps1." }
$originHost = (Get-Content $urlFile -Raw).Trim()
if ($originHost -notmatch '\.trycloudflare\.com$') { throw "Hostname de origem invalido: '$originHost'" }

# edge.env tem de ir com LF (um \r colado ao valor entrava no nome do host).
$envPath = Join-Path $here 'edge\edge.env'
$content = "# Gerado por 03-configure-edge.ps1`nORIGIN_HOSTNAME=$originHost`n"
[IO.File]::WriteAllText($envPath, $content)
Write-Host "edge.env -> ORIGIN_HOSTNAME=$originHost"

$sshArgs = @('-i', $SshKey, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new')

& scp @sshArgs $envPath "${SshUser}@${SshHost}:${RemoteDir}/edge.env"
if ($LASTEXITCODE -ne 0) { throw 'scp de edge.env falhou' }
Write-Host 'edge.env copiado para a VM'

& ssh @sshArgs "${SshUser}@${SshHost}" "cd $RemoteDir && docker compose up -d --remove-orphans"
if ($LASTEXITCODE -ne 0) { throw 'docker compose up falhou' }

Write-Host "a aguardar o endereco publico (ate $WaitSeconds s)..."
$public = $null
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $logs = & ssh @sshArgs "${SshUser}@${SshHost}" "docker logs iqos-tunnel 2>&1 | tail -60" 2>$null
    $m = [regex]::Match(($logs -join "`n"), 'https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
    if ($m.Success) { $public = $m.Value; break }
}
if (-not $public) { throw "Nao encontrei o endereco publico nos logs do cloudflared. Ver: ssh ... 'docker logs iqos-tunnel'" }

$publicHost = ([Uri]$public).Host
$publicHost | Set-Content -Path (Join-Path $here 'public-url.txt') -Encoding ascii

Write-Host ''
Write-Host "==> Edge IQ OS publicado em: $public" -ForegroundColor Yellow
Write-Host "==> (guardado em public-url.txt)" -ForegroundColor DarkGray
