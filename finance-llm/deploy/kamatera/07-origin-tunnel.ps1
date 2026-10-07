#requires -Version 5.1
<#
.SYNOPSIS
    Tunel SSH reverso PC -> VM do edge. Substitui o quick tunnel do Cloudflare.

.DESCRIPTION
    Sobe (em Docker) o container `iqos-origin-tunnel`, que publica a stack local
    (127.0.0.1:4180) em `127.0.0.1:8080` da VM Kamatera:

        ssh -N -R 127.0.0.1:8080:host.docker.internal:4180 root@45.147.251.188

    O Caddy do edge faz `reverse_proxy http://127.0.0.1:8080`, pelo que
    https://sabemos.studio serve a SPA + API **sem Cloudflare** e com um
    endereco fixo (o quick tunnel morria e obrigava a propagar um hostname novo
    a cada queda).

    Correr em Docker (e nao como processo solto) e o que faz o tunel sobreviver
    ao fecho do terminal e a reinicios do PC: `restart: unless-stopped` + o
    ciclo de religacao dentro do container (`origin/tunnel.sh`).

.PARAMETER InstallTask
    Instala o arranque automatico com a sessao (pasta Startup do utilizador) e
    sobe o tunel agora.

.PARAMETER RemoveTask
    Para o tunel e remove o arranque automatico.

.PARAMETER Logs
    Segue o log do container (Ctrl+C para sair).

.EXAMPLE
    .\07-origin-tunnel.ps1 -InstallTask
    .\07-origin-tunnel.ps1 -Logs
    .\07-origin-tunnel.ps1 -RemoveTask
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [int]$RemotePort = 8080,
    [int]$LocalPort = 4180,
    [switch]$InstallTask,
    [switch]$RemoveTask,
    [switch]$Logs
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$originDir = Join-Path $here 'origin'
$composeFile = Join-Path $originDir 'compose.yml'
$envFile = Join-Path $originDir '.env'
$startupDir = [Environment]::GetFolderPath('Startup')
$launcher = Join-Path $startupDir 'IQOS Origin Tunnel.cmd'

# `docker compose` precisa de caminhos com `/`, nao com `\`.
$sshKeyDir = (Split-Path -Parent $SshKey).Replace('\', '/')

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
    & docker compose --env-file $envFile -f $composeFile @ComposeArgs
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($ComposeArgs -join ' ') falhou (exit $LASTEXITCODE)" }
}

function Write-OriginEnv {
    $content = @(
        '# Gerado por 07-origin-tunnel.ps1 - nao editar a mao.',
        "SSH_KEY_DIR=$sshKeyDir",
        "SSH_KEY_FILE=$(Split-Path -Leaf $SshKey)",
        "SSH_HOST=$SshHost",
        "SSH_USER=$SshUser",
        "REMOTE_PORT=$RemotePort",
        "LOCAL_TARGET=host.docker.internal:$LocalPort",
        'RETRY_SECONDS=5'
    ) -join "`n"
    Set-Content -Path $envFile -Value ($content + "`n") -Encoding ascii
}

if ($RemoveTask) {
    if (Test-Path $envFile) { Invoke-Compose down --remove-orphans }
    if (Test-Path $launcher) { Remove-Item -Force $launcher }
    Write-Host 'tunel parado e arranque automatico removido'
    return
}

Write-OriginEnv

if ($Logs) {
    Invoke-Compose logs -f --tail 50
    return
}

if ($InstallTask) {
    # Arranque automatico com a sessao: um .cmd na pasta Startup do utilizador
    # (uma tarefa agendada exigia elevacao, negada nesta maquina).
    $cmd = "@echo off`r`nrem Tunel SSH reverso PC -> VM do edge (sabemos.studio).`r`n" +
           "docker compose --env-file `"$envFile`" -f `"$composeFile`" up -d`r`n"
    Set-Content -Path $launcher -Value $cmd -Encoding ascii
    Write-Host "arranque automatico instalado: $launcher"
}

Write-Host 'a construir e a subir o tunel...'
Invoke-Compose up -d --build

Start-Sleep -Seconds 6
& docker ps --filter name=iqos-origin-tunnel --format '{{.Names}}  {{.Status}}'
Write-Host ''
Write-Host '==> Edge IQ OS: https://sabemos.studio' -ForegroundColor Yellow
