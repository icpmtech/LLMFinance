<#
    Controlo do backfill de embeddings dos contratos (contratos -> embedding).

    ACOES
      estado    (status)   progresso, ritmo e estimativa; ficheiro de pausa; processos
      iniciar   (start)    arranca em segundo plano, desacoplado do terminal (WMI)
      pausar    (pause)    cria o ficheiro de pausa: cada processo acaba o lote em
                           curso e sai (nao se perde trabalho)
      continuar (resume)   tira a pausa e, se nao estiver a correr, volta a arrancar
      parar     (stop)     mata os processos do backfill (retomavel: so pede
                           documentos sem embedding)

    REMOTO
      -SshTarget utilizador@maquina executa a mesma acao nesse Windows por SSH:
          .\backfill.ps1 -Acao estado -SshTarget pedro@10.0.0.5
      (o servidor tem de ter o mesmo caminho do projeto e PowerShell)

    EXEMPLOS
      .\backfill.ps1 -Acao iniciar -Workers 6 -Threads 2
      .\backfill.ps1 -Acao pausar
      .\backfill.ps1 -Acao estado
      .\backfill.ps1 -Acao continuar

    O backfill real e o logs\_backfill_contratos_v2.py (paralelo e retomavel);
    este script so o arranca, para ou informa.
#>
[CmdletBinding()]
param(
    [ValidateSet('estado', 'status', 'iniciar', 'start', 'pausar', 'pause', 'continuar', 'resume', 'parar', 'stop', 'reiniciar')]
    [string]$Acao = 'estado',

    # Processos de codificacao x threads do PyTorch por processo.
    # Medido: a codificacao nao escala com threads (1 thread = 14,9 docs/s,
    # 12 threads = 36 docs/s), logo vale mais muitos processos com 2 threads.
    [int]$Workers = 6,
    [int]$Threads = 2,

    # Anos a preencher (ex.: "2025,2026"). Vazio = do mais recente para o mais antigo.
    [string]$Anos = '',

    [string]$EsUrl = 'http://127.0.0.1:9200',

    # Ex.: pedro@10.0.0.5 (executa a acao nessa maquina Windows por SSH)
    [string]$SshTarget = ''
)

$ErrorActionPreference = 'Stop'

# ------------------------------------------------------------------ caminhos
$PSRaiz = Split-Path -Parent $PSScriptRoot          # .../finance-llm
$ScriptBackfill = Join-Path $PSScriptRoot '_backfill_contratos_v2.py'
$LogBackfill = Join-Path $PSScriptRoot '_backfill_contratos.log'
$LogExecucao = Join-Path $PSScriptRoot '_backfill_run.log'
$FicheiroPausa = Join-Path $PSScriptRoot '_backfill.pausa'
$FicheiroEstado = Join-Path $PSScriptRoot '_backfill_estado.json'
$Arrancador = Join-Path $PSScriptRoot '_backfill_launch.cmd'

$Python = @(
    (Join-Path (Split-Path -Parent $PSRaiz) '.venv\Scripts\python.exe'),
    (Join-Path $PSRaiz '.venv\Scripts\python.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) { $Python = 'python' }

# ------------------------------------------------------------------- remoto
if ($SshTarget) {
    $partes = @("-Acao $Acao", "-Workers $Workers", "-Threads $Threads", "-EsUrl '$EsUrl'")
    if ($Anos) { $partes += "-Anos '$Anos'" }
    $linha = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" " + ($partes -join ' ')
    Write-Host "[remoto] $SshTarget :: $linha" -ForegroundColor DarkCyan
    & ssh $SshTarget $linha
    exit $LASTEXITCODE
}

# --------------------------------------------------------------- utilitarios
function Obter-Raizes {
    # Raizes do backfill: o .cmd lancador e o processo python principal.
    # Os trabalhadores do multiprocessing NAO trazem o nome do script na linha de
    # comando (arrancam por `python -c "from multiprocessing.spawn import ..."`),
    # logo so se encontram descendo a arvore de processos. Foi por isso que um
    # filtro so pela linha de comando contava 3 em vez de 8.
    $lista = @()
    $lista += Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*_backfill_*.cmd*' }
    $lista += Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*_backfill_contratos_v2*' }
    return @($lista)
}

function Obter-Arvore([int]$IdProcesso) {
    $ids = @($IdProcesso)
    foreach ($filho in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$IdProcesso" -ErrorAction SilentlyContinue)) {
        $ids += Obter-Arvore $filho.ProcessId
    }
    return $ids
}

function Obter-Processos {
    $ids = @()
    foreach ($raiz in Obter-Raizes) { $ids += Obter-Arvore $raiz.ProcessId }
    return @($ids | Sort-Object -Unique)
}

function Pausa-Pedida { return (Test-Path $FicheiroPausa) }

function Obter-Cobertura {
    $base = $EsUrl.TrimEnd('/')
    $total = (Invoke-RestMethod -Uri "$base/contratos/_count" -TimeoutSec 30).count
    $com = (Invoke-RestMethod -Uri "$base/contratos/_count?q=embedding:*" -TimeoutSec 30).count
    return @{ total = [int64]$total; com = [int64]$com; sem = [int64]$total - [int64]$com }
}

function Escrever-Arrancador {
    # Ficheiro .cmd (ASCII) porque e o que o WMI sabe arrancar de forma
    # desacoplada; leva os parametros ja resolvidos.
    $anosArg = if ($Anos) { " --anos $Anos" } else { '' }
    $linhas = @(
        '@echo off',
        'rem Gerado por backfill.ps1 - alteracoes a mao perdem-se.',
        "cd /d $PSRaiz",
        'set PYTHONIOENCODING=utf-8',
        'set TOKENIZERS_PARALLELISM=false',
        "`"$Python`" `"$ScriptBackfill`" --workers $Workers --threads $Threads --por-ano$anosArg >> `"$LogExecucao`" 2>&1",
        'echo ==== fim %DATE% %TIME% (codigo %ERRORLEVEL%) ==== >> "' + $LogExecucao + '"'
    )
    [IO.File]::WriteAllText($Arrancador, ($linhas -join "`r`n"), (New-Object Text.UTF8Encoding $false))
}

function Obter-Trabalhadores {
    # Processos python dentro da arvore do backfill. Serve para distinguir uma
    # execucao a serio de um resto (o cmd.exe lancador pode sobreviver alguns
    # segundos depois de o python sair, e nesse caso `continuar` recusava
    # arrancar com "Ja esta a correr" sem nada a correr).
    $ids = Obter-Processos
    if (-not $ids) { return @() }
    return @(
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $ids -contains $_.ProcessId }
    )
}

function Arrancar {
    $restos = Obter-Processos
    if ($restos) {
        if (Obter-Trabalhadores) {
            Write-Host 'Ja esta a correr.' -ForegroundColor Yellow
            return
        }
        Write-Host "Havia $($restos.Count) processo(s) restantes de uma execucao anterior; a limpar." -ForegroundColor Yellow
        foreach ($procId in $restos) {
            try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch { }
        }
        Start-Sleep -Seconds 2
    }
    Escrever-Arrancador
    Add-Content -LiteralPath $LogExecucao -Value "==== inicio $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Workers x $Threads | anos '$Anos' ====" -Encoding UTF8
    $argumentos = @{ CommandLine = "cmd.exe /c `"$Arrancador`""; CurrentDirectory = $PSRaiz }
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $argumentos
    if ($r.ReturnValue -ne 0) {
        Write-Host "Nao consegui arrancar (ReturnValue=$($r.ReturnValue))." -ForegroundColor Red
        return
    }
    Write-Host "Arrancado em segundo plano (PID $($r.ProcessId), $Workers x $Threads threads)." -ForegroundColor Green
    Write-Host "Log: $LogBackfill"
}

function Parar {
    $procs = Obter-Processos
    if (-not $procs) {
        Write-Host 'Nao havia processos do backfill.' -ForegroundColor Yellow
        return
    }
    foreach ($procId in $procs) {
        try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch { }
    }
    Write-Host "Parados $($procs.Count) processo(s)." -ForegroundColor Green
    Write-Host 'Retomavel: `continuar` volta a arrancar sem repetir trabalho.'
}

function Estado {
    $procs = Obter-Processos
    $pausa = Pausa-Pedida

    $cobertura = Obter-Cobertura
    $pct = if ($cobertura.total) { 100.0 * $cobertura.com / $cobertura.total } else { 0.0 }

    Write-Host ''
    Write-Host 'Backfill de embeddings dos contratos' -ForegroundColor Cyan
    Write-Host ("  cobertura : {0:N0} de {1:N0} ({2:N2}%) - faltam {3:N0}" -f $cobertura.com, $cobertura.total, $pct, $cobertura.sem)
    Write-Host ("  processos : {0}" -f $procs.Count) -ForegroundColor $(if ($procs.Count) { 'Green' } else { 'DarkGray' })
    Write-Host ("  pausa     : {0}" -f $(if ($pausa) { 'SIM (ficheiro _backfill.pausa existe)' } else { 'nao' })) -ForegroundColor $(if ($pausa) { 'Yellow' } else { 'DarkGray' })

    # Ritmo e estimativa a partir da amostra anterior (se houver).
    $agora = Get-Date
    if (Test-Path $FicheiroEstado) {
        try { $antes = Get-Content -LiteralPath $FicheiroEstado -Raw | ConvertFrom-Json } catch { $antes = $null }
        if ($antes) {
            $dt = ($agora - [datetime]$antes.ts).TotalSeconds
            $docs = $cobertura.com - [int64]$antes.com
            if ($dt -ge 30 -and $docs -gt 0) {
                $ritmo = $docs / $dt
                Write-Host ("  ritmo     : {0:N1} docs/s (desde a ultima leitura, {1:N0}s)" -f $ritmo, $dt)
                $horas = $cobertura.sem / $ritmo / 3600
                Write-Host ("  estimativa: {0:N1} h para o que falta" -f $horas) -ForegroundColor DarkGray
                $antes = @{ ts = $agora.ToString('o'); com = $cobertura.com; ritmo = $ritmo }
            } elseif ($antes.ritmo) {
                $ritmo = [double]$antes.ritmo
                Write-Host ("  ritmo     : {0:N1} docs/s (da leitura anterior)" -f $ritmo)
                Write-Host ("  estimativa: {0:N1} h para o que falta" -f ($cobertura.sem / $ritmo / 3600)) -ForegroundColor DarkGray
                $antes = @{ ts = $agora.ToString('o'); com = $cobertura.com; ritmo = $ritmo }
            } else {
                $antes = @{ ts = $agora.ToString('o'); com = $cobertura.com }
            }
        }
    } else {
        $antes = @{ ts = $agora.ToString('o'); com = $cobertura.com }
    }
    $antes | ConvertTo-Json | Set-Content -LiteralPath $FicheiroEstado -Encoding UTF8

    if (Test-Path $LogBackfill) {
        Write-Host ''
        Write-Host '  Ultimas linhas do log:' -ForegroundColor DarkGray
        Get-Content -LiteralPath $LogBackfill -Tail 6 -Encoding UTF8 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    Write-Host ''
}

# ------------------------------------------------------------------- acoes
switch ($Acao) {
    { $_ -in 'estado', 'status' } { Estado }

    { $_ -in 'iniciar', 'start' } {
        if (Pausa-Pedida) {
            Write-Host 'Ha um pedido de pausa ativo; a remove-lo antes de arrancar.' -ForegroundColor Yellow
            Remove-Item -LiteralPath $FicheiroPausa -Force
        }
        Arrancar
    }

    { $_ -in 'pausar', 'pause' } {
        if (-not (Obter-Processos)) {
            Write-Host 'Nada a correr; nada a pausar.' -ForegroundColor Yellow
        } else {
            New-Item -ItemType File -Path $FicheiroPausa -Force | Out-Null
            Write-Host 'Pausa pedida: cada processo termina o lote em curso (~1-2 min) e sai.' -ForegroundColor Green
            Write-Host 'Depois pode usar `-Acao continuar` a qualquer momento.'
        }
    }

    { $_ -in 'continuar', 'resume' } {
        if (Pausa-Pedida) { Remove-Item -LiteralPath $FicheiroPausa -Force }
        if (Obter-Processos) {
            Write-Host 'Pausa removida; os processos em curso continuam.' -ForegroundColor Green
        } else {
            Arrancar
        }
    }

    { $_ -in 'parar', 'stop' } { Parar }

    'reiniciar' {
        Parar
        Start-Sleep -Seconds 3
        Arrancar
    }
}
