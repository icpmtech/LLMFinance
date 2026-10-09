#requires -Version 5.1
<#
.SYNOPSIS
    Redimensiona a VM iq-os-edge-01 (CPU, RAM e disco) na Kamatera.

.DESCRIPTION
    A Kamatera nao deixa escolher o preco: o tamanho e definido por vCPU + RAM +
    disco, e o custo mensal e a soma. Este script:

      1. Le o estado atual do servidor (e o preco) pela API.
      2. Calcula as configuracoes que caibam num orcamento mensal.
      3. Aplica o redimensionamento -- CPU, RAM e disco, pela ordem correta.
      4. Depois de crescer o disco, cresce a particao e o sistema de ficheiros
         na VM (`growpart` + `resize2fs`), que e o passo que a API nao faz.

    Sem `-Apply` nao toca em nada: so mostra os comandos exatos que correria.
    Isso permite usar o script sem lhe confiar credenciais.

    Credenciais (nunca por chat):
      - variaveis de ambiente KAMATERA_CLIENT_ID / KAMATERA_SECRET, ou
      - ficheiro `deploy/kamatera/.kamatera.env` (ignorado pelo git) com
            KAMATERA_CLIENT_ID=...
            KAMATERA_SECRET=...

.EXAMPLE
    # So ver o estado e as opcoes dentro do orcamento (nao precisa de credenciais)
    .\10-redimensionar-vm.ps1 -Plan

.EXAMPLE
    # Ver os comandos que seriam executados
    .\10-redimensionar-vm.ps1 -Cpu 2 -RamMB 8192 -DiskGB 160

.EXAMPLE
    # Aplicar de verdade (precisa das credenciais)
    .\10-redimensionar-vm.ps1 -Cpu 2 -RamMB 8192 -DiskGB 160 -Apply -GrowFilesystem
#>
[CmdletBinding()]
param(
    [string]$ServerName = 'iq-os-edge-01',
    [string]$ApiBase    = 'https://cloudcli.cloudwm.com/service',
    [string]$SshHost    = '45.147.251.188',
    [string]$SshKey     = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [string]$TunnelContainer = 'iqos-origin-tunnel',

    # Alvo. Por omissao: 2 cores tipo A / 8 GB / 160 GB.
    [int]$Cpu = 2,
    [ValidateSet('A', 'B')][string]$CpuType = 'A',
    [int]$RamMB = 8192,
    [int]$DiskGB = 160,

    # Orcamento mensal em EUR: usado por -Plan para listar alternativas.
    [double]$BudgetEur = 23.0,
    [double]$UsdPerEur = 1.09,

    [switch]$Plan,
    [switch]$Apply,
    [switch]$GrowFilesystem,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

# Taxas inferidas de dois pontos publicos, que reproduzem exatamente:
#   1 vCPU A + 2 GB + 20 GB = 6,00 USD/mes
#   1 vCPU B + 512 MB + 5 GB = 10,00 USD/mes
$RATE = @{
    A = @{ vcpu = 2.00; ramGB = 1.50 }
    B = @{ vcpu = 9.00; ramGB = 1.50 }
}
$RATE_DISK_GB = 0.05   # publicado
$MIN_RAM_STEP = 512    # a Kamatera so oferece multiplos de 512 MB

function Get-Price([string]$type, [int]$vcpu, [int]$ramMB, [int]$diskGB) {
    $r = $RATE[$type]
    return $r.vcpu * $vcpu + $r.ramGB * ($ramMB / 1024.0) + $RATE_DISK_GB * $diskGB
}

function Format-Money([double]$usd) {
    return ('{0,8:N2} USD  ({1,6:N2} EUR)' -f $usd, ($usd / $UsdPerEur))
}

# ---------------------------------------------------------------------------
# Credenciais
# ---------------------------------------------------------------------------
function Import-KamateraEnv {
    $file = Join-Path $PSScriptRoot '.kamatera.env'
    if (Test-Path $file) {
        foreach ($line in Get-Content $file) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$') {
                $name, $value = $Matches[1], $Matches[2].Trim('"', "'")
                if (-not [Environment]::GetEnvironmentVariable($name)) {
                    Set-Item -Path "Env:$name" -Value $value
                }
            }
        }
    }
}
Import-KamateraEnv

$clientId = $env:KAMATERA_CLIENT_ID
$secret   = $env:KAMATERA_SECRET
$hasCreds = [bool]($clientId -and $secret)

function Get-ApiHeaders {
    if (-not $hasCreds) { throw 'Sem credenciais: define KAMATERA_CLIENT_ID e KAMATERA_SECRET (ver o cabecalho do script).' }
    return @{ AuthClientId = $clientId; AuthSecret = $secret }
}

function Invoke-Kamatera {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$Body,
        # `server/info` espera JSON; os `PUT` de redimensionamento esperam form.
        [string]$ContentType = 'application/x-www-form-urlencoded'
    )
    $headers = Get-ApiHeaders
    # `$args` e automatica no PowerShell: usar outro nome.
    $call = @{
        Method      = $Method
        Uri         = "$ApiBase$Path"
        Headers     = $headers
        ErrorAction = 'Stop'
    }
    if ($Body) {
        $call['Body']        = $Body
        $call['ContentType'] = $ContentType
    }
    return Invoke-RestMethod @call
}

function Wait-KamateraQueue {
    param([string]$QueueId, [int]$TimeoutSeconds = 900)
    if (-not $QueueId) { return }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 6
        $q = Invoke-Kamatera -Method Get -Path "/queue?id=$QueueId"
        $state = "$($q.status) $($q.completed) $($q.error)"
        Write-Host ("    fila {0}: {1}" -f $QueueId, ($q | ConvertTo-Json -Compress))
        if ($q.completed -eq $true -or $q.status -eq 'completed') { return $q }
        if ($q.error) { throw "Falhou na fila ${QueueId}: $($q | ConvertTo-Json -Compress)" }
    }
    throw "Timeout a esperar pela fila $QueueId"
}

# ---------------------------------------------------------------------------
# Plano
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Orcamento ===" -ForegroundColor Cyan
$budgetUsd = $BudgetEur * $UsdPerEur
Write-Host ("  {0:N2} EUR/mes  =  {1:N2} USD/mes   (cambio {2:N4} USD/EUR)" -f $BudgetEur, $budgetUsd, $UsdPerEur)
Write-Host ("  taxas: vCPU {0} 2,00 / vCPU {1} 9,00 / RAM 1,50 GB / disco 0,05 GB" -f 'A', 'B')

# Para 2 vCPU e 8 GB, quanto disco cabe no orcamento?
$fixed = (Get-Price $CpuType $Cpu $RamMB 0)
$maxDisk = [math]::Floor(($budgetUsd - $fixed) / $RATE_DISK_GB)
Write-Host ""
Write-Host ("  Com {0} vCPU {1} + {2} GB RAM (custo fixo {3:N2} USD), o orcamento da para {4} GB de disco." -f $Cpu, $CpuType, ($RamMB / 1024), $fixed, $maxDisk)

if ($Plan) {
    Write-Host ""
    Write-Host "=== Configuracoes dentro do orcamento ===" -ForegroundColor Cyan
    Write-Host ("  {0,-28} {1,10} {2,16} {3,14}" -f 'Configuracao', 'USD/mes', 'EUR/mes', 'Disco maximo')
    $combos = @(
        @{ nome = '1 core  / 2 GB  (atual)'; cpu = 1; ram = 2048 },
        @{ nome = '2 cores / 4 GB';          cpu = 2; ram = 4096 },
        @{ nome = '2 cores / 6 GB';          cpu = 2; ram = 6144 },
        @{ nome = '2 cores / 8 GB';          cpu = 2; ram = 8192 },
        @{ nome = '4 cores / 8 GB';          cpu = 4; ram = 8192 }
    )
    foreach ($c in $combos) {
        $fx = Get-Price $CpuType $c.cpu $c.ram 0
        $disk = [math]::Floor(($budgetUsd - $fx) / $RATE_DISK_GB)
        if ($disk -le 0) {
            Write-Host ("  {0,-28} {1,10:N2} {2,16} {3,14}" -f $c.nome, $fx, 'nao cabe', '-') -ForegroundColor DarkGray
            continue
        }
        $usd = $fx + $RATE_DISK_GB * $disk
        $recomendado = ($c.cpu -eq 2 -and $c.ram -eq 8192)
        $mark = if ($recomendado) { ' <-- recomendado' } else { '' }
        $cor  = if ($recomendado) { 'Green' } else { 'Gray' }
        Write-Host ("  {0,-28} {1,10:N2} {2,16:N2} {3,14}{4}" -f $c.nome, $usd, ($usd / $UsdPerEur), "$disk GB", $mark) -ForegroundColor $cor
    }
    Write-Host ""
    Write-Host "  Espaco necessario: ~57 GB so para o Elasticsearch, ~120 GB para a stack" -ForegroundColor DarkGray
    Write-Host "  completa. 160 GB deixa ~40 GB de folga e fica ~1 EUR abaixo do orcamento." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Para aplicar:" -ForegroundColor DarkGray
    Write-Host "    .\10-redimensionar-vm.ps1 -Cpu 2 -RamMB 8192 -DiskGB 160 -Apply -GrowFilesystem" -ForegroundColor DarkGray
    return
}

# ---------------------------------------------------------------------------
# Alvo
# ---------------------------------------------------------------------------
$targetUsd = Get-Price $CpuType $Cpu $RamMB $DiskGB
Write-Host ""
Write-Host "=== Alvo ===" -ForegroundColor Cyan
Write-Host ("  {0} vCPU tipo {1} / {2} GB RAM / {3} GB disco" -f $Cpu, $CpuType, ($RamMB / 1024), $DiskGB)
Write-Host ("  custo estimado: {0}" -f (Format-Money $targetUsd))
if ($targetUsd -gt $budgetUsd) {
    Write-Host ("  ATENCAO: excede o orcamento de {0:N2} EUR/mes." -f $BudgetEur) -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Estado atual
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Estado atual do servidor ===" -ForegroundColor Cyan
if (-not $hasCreds) {
    Write-Host "  Sem credenciais - nao consigo consultar a API." -ForegroundColor Yellow
    Write-Host "  Ultimo valor conhecido: 1 vCPU A / 2 GB / 20 GB = 6,00 USD/mes." -ForegroundColor DarkGray
} else {
    try {
        $info = Invoke-Kamatera -Method Post -Path '/server/info' `
            -Body (@{ name = $ServerName } | ConvertTo-Json) -ContentType 'application/json'
        $info | ConvertTo-Json -Depth 4 | Write-Host
        if ($info.priceMonthlyOn) {
            Write-Host ("  preco atual: {0:N2} USD/mes" -f [double]$info.priceMonthlyOn) -ForegroundColor Yellow
        }
    } catch {
        Write-Host ("  Falhou: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Acoes ===" -ForegroundColor Cyan

$serverId = $null
if ($hasCreds) {
    try {
        $list = Invoke-Kamatera -Method Get -Path '/servers'
        $entry = $list | Where-Object { $_.name -eq $ServerName } | Select-Object -First 1
        if ($entry) {
            $serverId = $entry.id
            Write-Host "  servidor: $ServerName  ($serverId)"
        }
    } catch {
        Write-Host ("  nao consegui listar os servidores: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
}
if (-not $serverId) {
    # A API so aceita o ID, nunca o nome. Sem credenciais nao o consigo descobrir.
    Write-Host "  Sem o ID do servidor: os comandos abaixo trazem <serverId>." -ForegroundColor Yellow
    Write-Host "  Descobre-o com:  GET /servers  (devolve a lista com name + id)" -ForegroundColor DarkGray
}
if ($Apply -and -not $serverId) {
    throw "Preciso do ID do servidor '$ServerName' para aplicar."
}
$idForUrl = if ($serverId) { $serverId } else { '<serverId>' }

$calls = @(
    @{ ordem = 1; nome = 'CPU';   path = "/server/$idForUrl/cpu";  body = "cpu=$Cpu$CpuType" }
    @{ ordem = 2; nome = 'RAM';   path = "/server/$idForUrl/ram";  body = "ram=$RamMB" }
    @{ ordem = 3; nome = 'disco'; path = "/server/$idForUrl/disk"; body = "size=$DiskGB&index=0&provision=1" }
)

foreach ($c in $calls) {
    $preview = "curl -X PUT -H `"AuthClientId: <id>`" -H `"AuthSecret: <secret>`" -d '$($c.body)' $ApiBase$($c.path)"
    Write-Host ""
    Write-Host ("  [{0}] {1}: {2}" -f $c.ordem, $c.nome, $c.body)
    if (-not $Apply) {
        Write-Host "      $preview" -ForegroundColor DarkGray
        continue
    }
    try {
        $resp = Invoke-Kamatera -Method Put -Path $c.path -Body $c.body
        Write-Host ("      resposta: {0}" -f ($resp | ConvertTo-Json -Compress)) -ForegroundColor Green
        $queueId = $null
        if ($resp -is [string]) { $queueId = $resp }
        elseif ($resp.id)   { $queueId = $resp.id }
        elseif ($resp.queue) { $queueId = $resp.queue }
        if ($queueId) { Wait-KamateraQueue -QueueId $queueId }
    } catch {
        Write-Host ("      FALHOU: {0}" -f $_.Exception.Message) -ForegroundColor Red
        Write-Host "      Abortar: as alteracoes seguintes podem ficar inconsistentes." -ForegroundColor Red
        return
    }
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "  (modo simulacao: nada foi alterado; acrescenta -Apply para executar)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Depois do disco crescer, a particao tem de crescer tambem na VM:" -ForegroundColor DarkGray
    Write-Host "    .\10-redimensionar-vm.ps1 -DiskGB $DiskGB -GrowFilesystem" -ForegroundColor DarkGray
    return
}

# ---------------------------------------------------------------------------
# Crescer a particao dentro da VM
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Sistema de ficheiros dentro da VM ===" -ForegroundColor Cyan

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    # O `ssh` do host encrava nesta rede; o do contentor do tunel nao. Um unico
    # argumento chega ao shell remoto inteiro, por isso os `|` funcionam.
    docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
        -o ConnectTimeout=10 -o LogLevel=ERROR "root@$SshHost" $RemoteCommand
}

if (-not $GrowFilesystem) {
    Write-Host "  Sem -GrowFilesystem: nao mexo na particao."
    Write-Host "  Corre isto na VM quando o disco estiver maior:" -ForegroundColor DarkGray
    Write-Host "    growpart /dev/sda 2 && resize2fs /dev/sda2" -ForegroundColor DarkGray
    return
}

Write-Host "  Antes:"
Invoke-Vm 'df -h / | tail -1'
Write-Host "  A crescer /dev/sda2..."
Invoke-Vm 'growpart /dev/sda 2; resize2fs /dev/sda2'
Write-Host "  Depois:"
Invoke-Vm 'df -h / | tail -1; free -m | sed -n 2p'

Write-Host ""
Write-Host "  Se a RAM ainda aparecer a antiga, a VM precisa de um reboot:" -ForegroundColor DarkGray
Write-Host "    docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 root@$SshHost reboot" -ForegroundColor DarkGray
Write-Host ""
