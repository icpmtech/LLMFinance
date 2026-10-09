#requires -Version 5.1
<#
.SYNOPSIS
    Visualizador de progresso das transferencias de imagens Docker para a VM.

.DESCRIPTION
    Mostra, a partir do estado real (e nao de estimativas):
      - que bloco esta a ser enviado e em que tentativa (do log do 15-imagem-vm.ps1);
      - quantos bytes ja chegaram a VM (soma dos blocos em /tmp);
      - barra de progresso, velocidade e tempo restante.

    A velocidade e calculada entre duas invocacoes: a primeira mostra o total mas
    ainda nao a velocidade. O estado fica em `$env:TEMP\iqos-progresso.state`.

    Nao toca em nada: so le o log local, o ficheiro local e os blocos na VM.

.EXAMPLE
    .\18-progresso.ps1                 # uma fotografia
    .\18-progresso.ps1 -Seguir         # actualiza a cada 15s (Ctrl+C para sair)
    .\18-progresso.ps1 -Log "$env:TEMP\outro.log"
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    # Caminho base remoto: os blocos sao `$RemoteBase.000`, `.001`, ...
    [string]$RemoteBase = '/tmp/iqos-imagem.tar.gz',
    # Onde o 15-imagem-vm.ps1 escreve o progresso. Vazio = o log de transferencia
    # mais recente em $env:TEMP (assim serve para qualquer imagem, nao so a que
    # estava em curso quando isto foi escrito).
    [string]$Log = '',
    # Ficheiro local do tar: e o tamanho dele que da o total a enviar.
    [string]$TarLocal = "$env:TEMP\iqos-imagem.tar.gz",
    [int]$IntervaloSegundos = 15,
    [switch]$Seguir,
    # Com -Seguir: quantas amostras mostrar antes de sair (0 = sem fim).
    # Util para correr isto num pipeline ou num log, onde um ciclo infinito nao
    # termina.
    [int]$Amostras = 0
)

$ErrorActionPreference = 'Stop'

if (-not $Log) {
    $cand = Get-ChildItem "$env:TEMP\iqos-*img*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    $Log = if ($cand) { $cand[0].FullName } else { Join-Path $env:TEMP 'iqos-backend-img2.log' }
}
# Estado por transferencia: os contadores de uma imagem nao servem para outra, e
# um estado partilhado daria velocidades absurdas ao trocar de ficheiro.
$stateFile = Join-Path $env:TEMP ('iqos-progresso-{0}.state' -f [IO.Path]::GetFileNameWithoutExtension($Log))

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand 2>&1
    } finally {
        $ErrorActionPreference = $prev
    }
    return (($out | Out-String).TrimEnd())
}

function Get-TotalBytes {
    # O `.tar` e a referencia estavel do total. O `.gz` **cresce enquanto se
    # comprime**, por isso usa-lo como denominador dava percentagens absurdas
    # (mostrava "428 MB" no inicio da compressao de um ficheiro de 4 GB).
    # Como os layers do Docker ja vem comprimidos, o `.gz` fica ~100% do `.tar`.
    $tarBase = Join-Path $env:TEMP 'iqos-imagem.tar'
    if (Test-Path $tarBase) { return (Get-Item $tarBase).Length }
    if (Test-Path $Log) {
        $m = Select-String -Path $Log -Pattern 'tar\s*:\s*([\d.,]+)\s*MB' | Select-Object -Last 1
        if ($m) {
            $mb = [double]($m.Matches[0].Groups[1].Value -replace ',', '.')
            return [int64]($mb * 1MB)
        }
    }
    if (Test-Path $TarLocal) { return (Get-Item $TarLocal).Length }
    return 0
}

function Get-RecebidoBytes {
    # `ls -l` em vez de `du | tail`: o `|` nao chega citado ao shell remoto.
    $saida = Invoke-Vm "ls -l $RemoteBase* 2>/dev/null || true"
    $total = [int64]0
    foreach ($linha in ($saida -split "`n")) {
        if ($linha -match '^\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s') { $total += [int64]$Matches[1] }
    }
    return $total
}

function Format-Tempo([double]$segundos) {
    if ($segundos -le 0 -or [double]::IsNaN($segundos) -or [double]::IsInfinity($segundos)) { return '--' }
    $t = [TimeSpan]::FromSeconds($segundos)
    if ($t.TotalHours -ge 1) { return ('{0}h{1:D2}m' -f [int]$t.TotalHours, $t.Minutes) }
    if ($t.TotalMinutes -ge 1) { return ('{0}m{1:D2}s' -f [int]$t.TotalMinutes, $t.Seconds) }
    return ('{0}s' -f [int]$t.TotalSeconds)
}

function Get-Fase {
    if (-not (Test-Path $Log)) { return '?' }
    $l = Select-String -Path $Log -Pattern '^=== ' | Select-Object -Last 1
    if ($l) { return $l.Line.Trim() }
    return '?'
}

function Mostrar {
    $total = Get-TotalBytes
    $fase = Get-Fase
    $etiqueta = 'recebido na VM'

    # Cada fase mede-se de maneira diferente. Sem isto a barra ficava parada a 0%
    # durante a compressao -- que leva minutos.
    if ($fase -match 'Comprimir') {
        $gzf = Join-Path $env:TEMP 'iqos-imagem.tar.gz'
        $rec = if (Test-Path $gzf) { (Get-Item $gzf).Length } else { 0 }
        $etiqueta = 'comprimido'
    } elseif ($fase -match 'Exportar') {
        $tarf = Join-Path $env:TEMP 'iqos-imagem.tar'
        $rec = if (Test-Path $tarf) { (Get-Item $tarf).Length } else { 0 }
        $etiqueta = 'exportado'
        $total = 0   # so se sabe o tamanho final quando o `docker save` acabar
    } else {
        $rec = Get-RecebidoBytes
    }

    Write-Host ''
    Write-Host '=== Progresso da transferencia ===' -ForegroundColor Cyan
    Write-Host "  fase: $fase" -ForegroundColor DarkGray

    # So dizer "nada em curso" quando nao ha fase conhecida. No inicio do
    # `docker save` o ficheiro ainda nao existe, e a mensagem dava a ideia de que
    # a transferencia nao tinha arrancado quando estava a correr bem.
    if ($total -le 0 -and $rec -le 0 -and $fase -eq '?') {
        Write-Host '  Nada em curso: nem tar local, nem blocos na VM.' -ForegroundColor DarkGray
        return
    }

    $pct = if ($total -gt 0) { [Math]::Min(100.0, 100.0 * $rec / $total) } else { 0 }
    $largura = 44
    $cheio = [int]($largura * $pct / 100)
    $barra = ('#' * $cheio) + ('.' * ($largura - $cheio))

    # Em que passo esta o 15-imagem-vm.ps1? (ja mostrado acima, via Get-Fase)

    if ($total -gt 0) {
        Write-Host ("  [{0}] {1,5:N1}%" -f $barra, $pct)
        Write-Host ("  {0} {1:N1} MB de {2:N1} MB  (faltam {3:N1} MB)" -f $etiqueta, ($rec / 1MB), ($total / 1MB), (($total - $rec) / 1MB))
    } else {
        Write-Host ("  {0} {1:N1} MB  (total so se sabe quando o export acabar)" -f $etiqueta, ($rec / 1MB))
    }

    # Velocidade entre esta amostra e a anterior.
    $agora = Get-Date
    if (Test-Path $stateFile) {
        $antigo = Get-Content $stateFile
        # Segundos Unix: o formato ISO (`-f o`) tem `+` e `:`, que nao batiam com
        # o regex `^(\d+)\|(\d+)$` -- o estado nunca casava e a velocidade nunca
        # aparecia.
        if ($antigo -match '^(\d+)\|(\d+)$') {
            # Os parenteses em volta do cast sao obrigatorios: sem eles o
            # PowerShell le `[DateTime]'1970-01-01'.AddSeconds(...)` como
            # `[DateTime]('1970-01-01'.AddSeconds(...))` e rebenta com
            # "String does not contain a method named AddSeconds".
            $tsAntigo = ([DateTime]'1970-01-01').AddSeconds([int64]$Matches[1])
            $bytesAntigo = [int64]$Matches[2]
            $dt = ($agora - $tsAntigo).TotalSeconds
            $db = $rec - $bytesAntigo
            if ($dt -ge 2 -and $db -gt 0) {
                $vel = $db / $dt
                $falta = ($total - $rec) / $vel
                Write-Host ("  velocidade: {0:N2} MB/s   restante: {1}" -f ($vel / 1MB), (Format-Tempo $falta)) -ForegroundColor Green
            } elseif ($db -eq 0) {
                Write-Host '  velocidade: parado desde a ultima amostra' -ForegroundColor Yellow
            }
        }
    }
    # Segundos desde a epoch na hora LOCAL, e reconstruidos como local: guardar
    # UTC e reconstruir como local (ou o contrario) desvia o intervalo pelo fuso
    # e inflaciona o tempo restante (dava 16 min para 245 MB a 1 MB/s).
    $unix = [int64]($agora - [DateTime]'1970-01-01').TotalSeconds
    "$unix|$rec" | Set-Content -Path $stateFile -Encoding ascii

    # Ultimas linhas do log: dizem que bloco vai a caminho e se houve repeticoes.
    if (Test-Path $Log) {
        Write-Host ''
        $linhas = Get-Content $Log | Where-Object { $_ -match 'bloco|incompleto|ligacao caiu|a juntar|na VM|Carregar|Loaded|enviado|falhou' }
        if ($linhas) {
            Write-Host '  ultimas linhas do log:' -ForegroundColor DarkGray
            $linhas | Select-Object -Last 4 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        }
    }
    Write-Host ''
}

if ($Seguir) {
    Write-Host ''
    Write-Host "a actualizar a cada $IntervaloSegundos s -- Ctrl+C para sair" -ForegroundColor DarkGray
    $n = 0
    while ($true) {
        # `Clear-Host` rebenta quando a saida nao e um terminal (redireccionada
        # para ficheiro ou num pipeline). Engolir o erro e nao custa nada.
        try { Clear-Host } catch { }
        $n++
        Mostrar
        if ($Amostras -gt 0 -and $n -ge $Amostras) {
            Write-Host "  ($n amostras, como pedido em -Amostras)" -ForegroundColor DarkGray
            break
        }
        Start-Sleep -Seconds $IntervaloSegundos
    }
} else {
    Mostrar
}
