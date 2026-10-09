#requires -Version 5.1
<#
.SYNOPSIS
    Transfere uma imagem Docker do PC para a VM do edge e carrega-a la.

.DESCRIPTION
    `docker save` -> gzip -> ficheiro -> VM -> `docker load`.

    Nao usa pipelines do PowerShell para os dados: o PowerShell descaracteriza
    streams binarios ao passar por comandos nativos (converte para texto e
    estraga o tar). Por isso a imagem vai a ficheiro e o redirecionamento e
    feito pelo `cmd.exe`, que copia bytes a serio.

    Nao toca em nada do que esta a correr: so escreve um ficheiro temporario em
    /tmp na VM e faz `docker load` (que acrescenta uma imagem, sem mexer nas
    que existem).

.EXAMPLE
    .\15-imagem-vm.ps1 -Imagem iq-os-frontend:latest
    .\15-imagem-vm.ps1 -Imagem iq-os-backend:latest -Manter
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Imagem,
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$RemoteTar = '/tmp/iqos-imagem.tar.gz',
    # Tamanho de cada bloco. 4 GB numa so ligacao ja falhou uma vez (a VM
    # reiniciou a meio, por causa de uma mudanca de CPU no painel) e obrigou a
    # recomecar do zero. Em blocos, uma queda custa no maximo um bloco.
    [int]$ChunkMB = 400,
    [int]$Tentativas = 3,
    # Reutiliza o tar/.gz ja exportados em $env:TEMP, em vez de repetir o
    # `docker save` (que nesta imagem leva ~4 min).
    [switch]$SaltarExport,
    # Por omissao apaga o tar da VM no fim (liberta o espaco).
    [switch]$Manter
)

$ErrorActionPreference = 'Stop'

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

# A imagem tem de existir localmente.
$exists = (docker images --format '{{.Repository}}:{{.Tag}}' | Where-Object { $_ -eq $Imagem })
if (-not $exists) { throw "nao ha imagem local '$Imagem' (usa docker images para veres as que existem)." }

$tar = Join-Path $env:TEMP 'iqos-imagem.tar'
$gz = "$tar.gz"

Write-Host ''
Write-Host "=== 1. Exportar $Imagem ===" -ForegroundColor Cyan
if ($SaltarExport -and (Test-Path $tar) -and ((Get-Item $tar).Length -gt 0)) {
    Write-Host '  (a reutilizar o tar existente -- -SaltarExport)'
} else {
    foreach ($f in @($tar, $gz)) { if (Test-Path $f) { Remove-Item $f -Force } }
    docker save -o $tar $Imagem
    if ($LASTEXITCODE -ne 0) { throw 'docker save falhou' }
}
$tamTar = (Get-Item $tar).Length
Write-Host ("  tar : {0,8:N1} MB" -f ($tamTar / 1MB))

Write-Host ''
Write-Host '=== 2. Comprimir ===' -ForegroundColor Cyan
if ($SaltarExport -and (Test-Path $gz) -and ((Get-Item $gz).Length -gt 0)) {
    Write-Host '  (a reutilizar o .gz existente)'
} else {
    # GZipStream do .NET: o `Compress-Archive` produz ZIP, que o `docker load`
    # nao aceita. Nota: os layers do Docker ja vem comprimidos, por isso isto
    # quase nao ganha nada (~100% do tamanho do tar); serve para integridade.
    $entrada = [IO.File]::OpenRead($tar)
    $saida = [IO.File]::Create($gz)
    $gzip = New-Object IO.Compression.GZipStream($saida, [IO.Compression.CompressionLevel]::Fastest)
    try { $entrada.CopyTo($gzip) } finally { $gzip.Dispose(); $entrada.Dispose(); $saida.Dispose() }
}
$tamGz = (Get-Item $gz).Length
Write-Host ("  gz  : {0,8:N1} MB  ({1:N0}% do tar)" -f ($tamGz / 1MB), (100 * $tamGz / $tamTar))

Write-Host ''
Write-Host "=== 3. Enviar para a VM (blocos de $ChunkMB MB) ===" -ForegroundColor Cyan
Write-Host "  -> $RemoteTar"

$parteTam = [int64]$ChunkMB * 1MB
$idx = 0
$offset = [int64]0
$enviados = [System.Collections.Generic.List[string]]::new()
$fs = [IO.File]::OpenRead($gz)
try {
    while ($offset -lt $tamGz) {
        $n = [Math]::Min($parteTam, $tamGz - $offset)
        $remoto = '{0}.{1:D3}' -f $RemoteTar, $idx
        $parte = Join-Path $env:TEMP ('iqos-parte-{0:D3}' -f $idx)

        $fs.Position = $offset
        $buf = New-Object byte[] $n
        $lido = 0
        while ($lido -lt $n) {
            $r = $fs.Read($buf, $lido, $n - $lido)
            if ($r -le 0) { break }
            $lido += $r
        }
        [IO.File]::WriteAllBytes($parte, $buf)

        $ok = $false
        for ($t = 1; $t -le $Tentativas -and -not $ok; $t++) {
            Write-Host ("  bloco {0,-3} {1,7:N1} MB  tentativa {2}" -f $idx, ($n / 1MB), $t) -NoNewline
            # O `cmd.exe` faz o redireccionamento binario; o PowerShell corrompe
            # streams binarios em pipelines nativas.
            $linha = 'docker exec -i {0} ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o LogLevel=ERROR {1}@{2} "cat > {3}" < "{4}"' -f `
                $TunnelContainer, $SshUser, $SshHost, $remoto, $parte
            cmd.exe /c $linha
            if ($LASTEXITCODE -eq 0) {
                $tamVm = [int64]((Invoke-Vm "wc -c < $remoto").Output.Trim())
                if ($tamVm -eq $n) { $ok = $true; Write-Host '  ok' -ForegroundColor Green }
                else { Write-Host "  incompleto ($tamVm de $n)" -ForegroundColor Yellow }
            } else {
                Write-Host '  ligacao caiu' -ForegroundColor Yellow
            }
            if (-not $ok) { Start-Sleep -Seconds 5 }
        }
        if (-not $ok) { throw "o bloco $idx falhou depois de $Tentativas tentativas." }

        $enviados.Add($remoto)
        Remove-Item $parte -Force -ErrorAction SilentlyContinue
        $offset += $n
        $idx++
    }
} finally { $fs.Dispose() }

Write-Host ''
Write-Host '  a juntar os blocos na VM...'
$tamVmTotal = (Invoke-Vm ("cat {0}.* > {0} && rm -f {0}.* && wc -c < {0}" -f $RemoteTar)).Output.Trim()
Write-Host ("  na VM: {0:N1} MB" -f ([double]$tamVmTotal / 1MB))
if ([int64]$tamVmTotal -ne $tamGz) {
    throw "o ficheiro chegou incompleto: $tamVmTotal bytes na VM, $tamGz no PC."
}

Write-Host ''
Write-Host '=== 4. Carregar na VM ===' -ForegroundColor Cyan
$r = Invoke-Vm "docker load -i $RemoteTar 2>&1"
$r.Output -split "`n" | ForEach-Object { Write-Host "  $_" }
if ($r.ExitCode -ne 0) { throw 'docker load falhou' }

if (-not $Manter) {
    Invoke-Vm "rm -f $RemoteTar" | Out-Null
    Write-Host "  (tar temporario removido da VM)"
}

Write-Host ''
Write-Host '=== 5. Confirmar ===' -ForegroundColor Cyan
$r = Invoke-Vm "docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -F '$Imagem'"
$r.Output -split "`n" | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Invoke-Vm 'df -h / | tail -1' | ForEach-Object { $_.Output -split "`n" | ForEach-Object { Write-Host "  $_" } }
Write-Host ''

Remove-Item $tar, $gz -Force -ErrorAction SilentlyContinue
Write-Host 'Imagem disponivel na VM.' -ForegroundColor Green
Write-Host ''
