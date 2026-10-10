#requires -Version 5.1
<#
.SYNOPSIS
    Sobe o Elasticsearch na VM do edge, como espelho do ES local.

.DESCRIPTION
    Aditivo por desenho: cria `/opt/iqos/es` e arranca o container
    `iqos-elasticsearch` com a mesma imagem que o stack local
    (`docker.elastic.co/elasticsearch/elasticsearch:8.11.0`). Nao toca no
    Caddy, na landing, no `iqos-origin-tunnel`, nem em nada do PC.

    Faz tres coisas:
      1. `vm.max_map_count=262144` na VM (o ES recusa arrancar sem isto) --
         parametro de kernel, nao interfere com o que esta a correr.
      2. Envia o `es/compose.yml` para `/opt/iqos/es/`.
      3. `docker compose up -d` dentro desse diretorio.

    O `ssh` do host encrava nesta rede, por isso tudo passa pelo container do
    tunel (um `docker exec`, que abre uma sessao nova -- nao reinicia nada).

.EXAMPLE
    .\11-es-vm.ps1
    .\11-es-vm.ps1 -Logs
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$RemoteDir = '/opt/iqos/es',
    [int]$MaxMapCount = 262144,
    [switch]$SkipSysctl,
    [switch]$Logs
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeLocal = Join-Path $here 'es\compose.yml'
if (-not (Test-Path $composeLocal)) { throw "nao encontro $composeLocal" }

if (-not (docker ps --filter "name=^$TunnelContainer$" --format '{{.Names}}')) {
    throw "o container $TunnelContainer nao esta a correr (ver 07-origin-tunnel.ps1)."
}

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    # O `docker` escreve o progresso no stderr e, com ErrorActionPreference
    # 'Stop', o PowerShell transforma isso em erro fatal. Baixar a preferencia
    # durante a chamada e decidir pelo codigo de saida.
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

function Show-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $r = Invoke-Vm $RemoteCommand
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Host "  $_" } }
    return $r
}

function Invoke-VmChecked {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $r = Invoke-Vm $RemoteCommand
    if ($r.ExitCode -ne 0) {
        throw "comando remoto falhou (exit $($r.ExitCode)):`n  $RemoteCommand`n$($r.Output)"
    }
    return $r.Output
}

function Send-VmFile {
    param([Parameter(Mandatory)][string]$Local, [Parameter(Mandatory)][string]$Remote)
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Local))
    # `tr -d '\r'`: o ficheiro vem de Windows e o YAML aguenta, mas manter LF
    # evita surpresas. O base64 nao tem plicas, por isso `'...'` e seguro.
    $cmd = "mkdir -p '$RemoteDir' && printf '%s' '$b64' | base64 -d | tr -d '\r' > '$Remote'"
    Invoke-VmChecked $cmd | Out-Null
    $size = (Invoke-VmChecked "wc -c < '$Remote'").Trim()
    Write-Host "  enviado $Remote ($size bytes)"
}

if ($Logs) {
    & docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
        "$SshUser@$SshHost" "cd $RemoteDir && docker compose logs -f --tail 60"
    return
}

Write-Host ''
Write-Host '=== 1. Estado da VM (antes de mexer) ===' -ForegroundColor Cyan
Show-Vm 'df -h / | tail -1; free -m | sed -n 2p; nproc' | Out-Null

Write-Host ''
Write-Host '=== 2. Requisitos do kernel ===' -ForegroundColor Cyan
if ($SkipSysctl) {
    Write-Host '  (saltado com -SkipSysctl)'
} else {
    $atual = (Invoke-VmChecked 'sysctl -n vm.max_map_count').Trim()
    Write-Host "  vm.max_map_count atual: $atual"
    if ([int]$atual -lt $MaxMapCount) {
        Invoke-VmChecked "sysctl -w vm.max_map_count=$MaxMapCount" | ForEach-Object { Write-Host "  $_" }
        # Persistente: sobrevive a reinicios da VM.
        Invoke-VmChecked "printf 'vm.max_map_count=$MaxMapCount\n' > /etc/sysctl.d/99-elasticsearch.conf" | Out-Null
        Write-Host "  definido para $MaxMapCount (e gravado em /etc/sysctl.d/99-elasticsearch.conf)"
    } else {
        Write-Host '  ja suficiente'
    }
}

Write-Host ''
Write-Host '=== 3. A enviar o compose ===' -ForegroundColor Cyan
Send-VmFile -Local $composeLocal -Remote "$RemoteDir/compose.yml"

Write-Host ''
Write-Host '=== 4. A arrancar o Elasticsearch ===' -ForegroundColor Cyan
Write-Host '  (so o projeto de /opt/iqos/es; o edge e o tunel ficam intocados)'
Invoke-VmChecked "cd $RemoteDir && docker compose up -d" | ForEach-Object { Write-Host "  $_" }

Write-Host ''
Write-Host '=== 5. A esperar pelo cluster (ate 3 min) ===' -ForegroundColor Cyan
$pronto = $false
for ($i = 1; $i -le 18; $i++) {
    $r = Invoke-Vm "curl -fsS -m 5 'http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=5s'"
    if ($r.ExitCode -eq 0 -and "$($r.Output)" -match '"status"') {
        Write-Host "  cluster respondeu na tentativa $i" -ForegroundColor Green
        $pronto = $true
        break
    }
    Write-Host "  tentativa $i : ainda a arrancar"
    Start-Sleep -Seconds 10
}

Write-Host ''
if (-not $pronto) {
    Write-Host 'NAO arrancou. Ultimas linhas do log:' -ForegroundColor Red
    Show-Vm "cd $RemoteDir && docker compose logs --tail 30" | Out-Null
    throw 'o Elasticsearch nao ficou saudavel -- ver o log acima.'
}

Write-Host '=== 6. Resultado ===' -ForegroundColor Cyan
Invoke-VmChecked "curl -fsS 'http://127.0.0.1:9200'" | ForEach-Object { Write-Host "  $_" }
Invoke-VmChecked "curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'" | ForEach-Object { Write-Host "  $_" }
Show-Vm 'docker ps --format "{{.Names}}  {{.Status}}"' | Out-Null
Write-Host ''
Show-Vm 'df -h / | tail -1; free -m | sed -n 2p' | Out-Null
Write-Host ''
Write-Host '  O ES escuta so em 127.0.0.1:9200 (nao esta exposto a Internet).' -ForegroundColor DarkGray

# === 7. Reiniciar o backend ==-
#
# Obrigatorio, e o motivo e subtil: o cliente do Elasticsearch do backend guarda
# ligacoes em pool. Quando o ES e recriado o processo antigo desaparece, mas os
# sockets do backend ficam a apontar para um destino que ja nao existe -- e, como
# nao ha RST, a leitura fica presa ate ao `request_timeout` do cliente (30 s).
#
# O sintoma e um `502 {"detail": "Connection timed out"}` so em **alguns**
# endpoints: os que apanham a ligacao morta do pool. Os outros respondem 200, e e
# isso que faz o problema parecer aleatorio. Aconteceu a serio: depois de subir o
# heap de 512m para 2g, o dashboard de contratos ficou em 502 enquanto
# `/contracts/analytics/regional`, `/contracts/search` e `/benchmark/*` davam 200.
Write-Host ''
Write-Host '=== 7. Reiniciar o backend (pool de ligacoes para o ES antigo) ===' -ForegroundColor Cyan
$backendVivo = (Invoke-Vm 'docker ps -q -f name=iqos-backend').Output
if ($backendVivo) {
    Invoke-Vm 'docker restart iqos-backend' | Out-Null
    Write-Host '  iqos-backend reiniciado -- as ligacoes mortas foram descartadas' -ForegroundColor Green
} else {
    Write-Host '  iqos-backend nao esta a correr: nada a reiniciar' -ForegroundColor DarkGray
}
Write-Host ''
