#requires -Version 5.1
<#
.SYNOPSIS
    Envia a pasta `edge/` para a VM Kamatera sem usar scp.

.DESCRIPTION
    Nesta rede o `scp` fica preso; este script usa o canal `ssh` que funciona e
    transmite cada ficheiro em base64 (sem problemas de aspas/encoding) e
    normaliza os finais de linha para LF.

.EXAMPLE
    .\00-push-edge-files.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [string]$RemoteDir = '/opt/iqos'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'edge'
if (-not (Test-Path $src)) { throw "Nao encontro a pasta $src" }

$parts = New-Object System.Collections.Generic.List[string]
$parts.Add("mkdir -p $RemoteDir/edge")

foreach ($f in (Get-ChildItem -Path $src -Recurse -File)) {
    $rel = $f.FullName.Substring($src.Length).TrimStart('\').Replace('\', '/')
    $dest = "$RemoteDir/edge/$rel"
    $dir = $dest -replace '/[^/]+$', ''
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($f.FullName))
    $parts.Add("mkdir -p $dir")
    $parts.Add("printf %s '$b64' | base64 -d > $dest")
    $parts.Add("sed -i 's/\r$//' $dest")
    Write-Host ("  -> {0} ({1} bytes)" -f $rel, $f.Length)
}

$parts.Add("find $RemoteDir/edge -type f | sort")

$remote = $parts -join '; '
Write-Host "a enviar $($parts.Count) operacoes por ssh para $SshUser@$SshHost ..."

& ssh -i $SshKey -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR "$SshUser@$SshHost" $remote
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }
