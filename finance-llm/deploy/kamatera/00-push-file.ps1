#requires -Version 5.1
<#
.SYNOPSIS
    Envia um ficheiro para a VM Kamatera por ssh + base64 (sem scp).

.DESCRIPTION
    O `scp` fica preso nesta rede; o `ssh` funciona. O ficheiro vai em base64
    (sem problemas de aspas/encoding) e os finais de linha sao normalizados
    para LF no destino.

.EXAMPLE
    .\00-push-file.ps1 -Local deploy\kamatera\05-edge-up.sh -Dest /opt/iqos/05-edge-up.sh
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Local,
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519"
)

$ErrorActionPreference = 'Stop'
$src = (Resolve-Path -LiteralPath $Local).Path
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($src))
$dir = $Dest -replace '/[^/]+$', ''

$remote = "mkdir -p $dir; printf %s '$b64' | base64 -d > $Dest; sed -i 's/\r$//' $Dest; ls -l $Dest"

& ssh -i $SshKey -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR "$SshUser@$SshHost" $remote
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }
