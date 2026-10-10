# Migra os contratos do ES do PC para o ES da VM, em tres fases sobrepostas.
#
# Contexto
# --------
# A migracao geral deixou 47 indices na VM com 3,5 M documentos, mas `contratos`
# e `contratos_es` ficaram VAZIOS -- o limite `MAX_MB` do `migrar.sh` saltou-os
# por serem os maiores. Sao 6,3 M documentos de topo.
#
# Porque nao se usa um snapshot do Elasticsearch
# ----------------------------------------------
# Um snapshot transfere ~25 GB, porque os segmentos Lucene ja vem comprimidos
# com LZ4 e gzip por cima de dados comprimidos ganha quase nada.
#
# O `_source` e JSON cru, e JSON comprime muito bem. Medido com amostras reais:
#
#     indice          JSON cru    ratio gzip    gzip
#     contratos        22,95 GB      38,2%      8,78 GB
#     contratos_es      9,54 GB      16,0%      1,53 GB
#     total            32,49 GB      31,7%     10,31 GB
#
# Sao 10,3 GB a atravessar a ligacao em vez de 25 GB. E a ligacao e o gargalo
# medido (4,39 MB/s num fluxo, e 4 fluxos em paralelo nao melhoram: e um teto
# partilhado, nao uma janela TCP).
#
# As tres fases
# -------------
#   1. exportar  -- N processos Python com scroll em fatias paralelas;
#   2. enviar    -- as partes vao sendo enviadas MAL ficam prontas, nao no fim.
#                   O exportador so renomeia para `.ndjson.gz` quando a parte
#                   esta completa, por isso `*.ndjson.gz` = ficheiro inteiro;
#   3. importar  -- `_bulk` na VM. Fica para o fim de proposito: dar-lhe a CPU
#                   toda da VM e mais rapido do que o entrelacar com o envio.
#
# Ordem de grandeza, com os numeros medidos: exportar ~20 min (mas escondido
# pelo envio), enviar ~40 min, importar ~25 min.
#
#     .\migrar_contratos.ps1
#     .\migrar_contratos.ps1 -Indices contratos -Fatias 4
#     .\migrar_contratos.ps1 -SaltarExport -SaltarEnvio   # so importar

[CmdletBinding()]
param(
    [string[]] $Indices = @('contratos', 'contratos_es'),
    [int] $Fatias = 4,
    [int] $Nivel = 3,
    [int] $MbParte = 200,
    [int] $Limite = 0,          # 0 = tudo; >0 = so para testar o encadeamento
    [string] $Python = 'c:\LLMFinance\.venv\Scripts\python.exe',
    [string] $EsPc = 'http://127.0.0.1:9200',
    [string] $EsVm = 'http://elasticsearch:9200',
    [string] $ExportDir = (Join-Path $PSScriptRoot '_export'),
    [string] $RemoteDir = '/opt/iqos/export',
    [string] $TunnelContainer = 'iqos-origin-tunnel',
    [string] $SshUser = 'root',
    [string] $SshHost = '45.147.251.188',
    [string] $ContentorImport = 'iq-os-backend:latest',
    [switch] $SaltarExport,
    [switch] $SaltarEnvio,
    [switch] $SaltarImport,
    [switch] $RefazerImport
)

$ErrorActionPreference = 'Stop'

function Invoke-Vm {
    param([Parameter(Mandatory)][string] $Comando)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $Comando 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

function Format-Bytes {
    param([double] $n)
    foreach ($u in 'B', 'KB', 'MB', 'GB', 'TB') {
        if ($n -lt 1024) { return ('{0:N1} {1}' -f $n, $u) }
        $n /= 1024
    }
    return ('{0:N1} PB' -f $n)
}

# Envia um ficheiro de texto por base64. Sem `|` no comando remoto de proposito:
# o `|` nao sobrevive a passagem PowerShell -> ssh e chega truncado a VM.
function Send-FicheiroTexto {
    param([string] $Local, [string] $DestinoRemoto)
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Local))
    $r = Invoke-Vm "echo '$b64' > /tmp/iqos-b64.txt; base64 -d /tmp/iqos-b64.txt > $DestinoRemoto; rm -f /tmp/iqos-b64.txt; wc -c $DestinoRemoto"
    $tamVm = 0
    if ($r.Output -match '(\d+)') { $tamVm = [int64]$Matches[1] }
    $tamLocal = (Get-Item $Local).Length
    if ($tamVm -ne $tamLocal) {
        throw "$Local chegou truncado a VM ($tamVm de $tamLocal bytes)"
    }
    return $tamLocal
}

# Uma parte vazia e um frame gzip de ~30-60 bytes. Nao vale a pena enviar isso
# nem pedir a VM para o importar.
$MINIMO_BYTES = 1000

# A chave que decide "ja enviei isto" inclui o TAMANHO, nao so o nome.
#
# Aprendido da pior maneira: as partes de um teste anterior (21 MB) ainda estavam
# em `_export` quando a corrida a serio arrancou, e o exportador reutiliza os
# nomes (`contratos-s0-part-00000`). Decidir apenas pelo nome fazia o vigilante
# saltar a parte verdadeira (~200 MB) por achar que ja a tinha enviado -- perda de
# dados em silencio, com a corrida a terminar a dizer que estava tudo bem.
function Chave-Parte {
    param($Ficheiro)
    return ('{0}|{1}' -f $Ficheiro.Name, $Ficheiro.Length)
}

# So interessam as partes dos indices DESTA corrida.
#
# Sem este filtro, uma segunda invocacao (por exemplo para `contratos_es`) voltava
# a encontrar as partes de `contratos` que ficam em `_export` e reenviava-as --
# 9 GB de transferencia repetida, quase 50 minutos perdidos, e sem nenhum erro a
# avisar. O nome comeca sempre pelo indice: `contratos-s0-part-...`,
# `contratos_es-part-...`.
function Testa-Indice {
    param($Ficheiro)
    foreach ($i in $Indices) {
        if ($Ficheiro.Name.StartsWith("$i-")) { return $true }
    }
    return $false
}

$script:Inicio = Get-Date

function Escrever-Etapa {
    param([string] $Texto)
    $t = (Get-Date) - $script:Inicio
    Write-Host ''
    Write-Host ("=== {0}  [{1:mm\:ss}] ===" -f $Texto, $t) -ForegroundColor Cyan
}

# --- 0. verificacoes -------------------------------------------------------
if (-not (Test-Path $Python)) { throw "nao encontrei o python em $Python" }
$scriptExporter = Join-Path $PSScriptRoot 'exportar_source.py'
$scriptImporter = Join-Path $PSScriptRoot 'importar_source.py'
if (-not (Test-Path $scriptExporter)) { throw "falta o $scriptExporter" }
if (-not (Test-Path $scriptImporter)) { throw "falta o $scriptImporter" }

if (-not (Test-Path $ExportDir)) { New-Item -ItemType Directory -Path $ExportDir -Force | Out-Null }

Write-Host ''
Write-Host '=== Migracao dos contratos ===' -ForegroundColor Cyan
Write-Host ("  indices      : {0}" -f ($Indices -join ', '))
Write-Host ("  fatias       : {0} por indice" -f $Fatias)
Write-Host ("  nivel gzip   : {0}" -f $Nivel)
Write-Host ("  partes       : ~{0} MB de JSON cada" -f $MbParte)
Write-Host ("  destino      : {0}  ->  {1}:{2}" -f $ExportDir, $SshHost, $RemoteDir)
if ($Limite -gt 0) {
    Write-Host ("  LIMITE       : {0} documentos por fatia (modo de teste)" -f $Limite) -ForegroundColor Yellow
}

# Estado do ES de origem: sem isto o resto nao faz sentido.
$pcHealth = (Invoke-Vm "true" | Out-Null); # garante que o tunel responde
$count = curl.exe -s -m 20 "$EsPc/_cat/count" 
Write-Host ("  ES de origem : {0}" -f ($count -replace '\s+', ' '))

$vmUp = Invoke-Vm "docker ps --format '{{.Names}}' | wc -l"
Write-Host ("  VM           : {0} contentores" -f ($vmUp.Output -replace '\s+', ' '))

# O contentor do importador tem de existir na VM. `docker images -q` imprime o id
# ou nada -- evita o `&&`/`||`/`>` que nao sobrevivem a passagem PowerShell -> ssh.
$temImportador = Invoke-Vm "docker images -q $ContentorImport"
if (-not $temImportador.Output) {
    throw "a imagem $ContentorImport nao esta na VM -- sem ela nao ha como correr o importador"
}
Invoke-Vm "mkdir -p $RemoteDir; rm -f $RemoteDir/*.a-chegar" | Out-Null

$processos = @()
$logDir = Join-Path $env:TEMP 'iqos-export-logs'
if (Test-Path $logDir) { Remove-Item $logDir -Recurse -Force }
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$enviados = @{}      # nome -> bytes confirmados na VM
$falhados = @{}

try {

    # --- 1. exportar (arranca em segundo plano) ---------------------------
    if (-not $SaltarExport) {
        Escrever-Etapa 'Fase 1/3 - exportar (em segundo plano)'
        foreach ($idx in $Indices) {
            foreach ($f in 0..($Fatias - 1)) {
                $log = Join-Path $logDir ("{0}-s{1}.log" -f $idx, $f)
                $argumentos = @(
                    $scriptExporter,
                    '--url', $EsPc,
                    '--indice', $idx,
                    '--destino', $ExportDir,
                    '--mb', "$MbParte",
                    '--nivel', "$Nivel",
                    '--fatia', "$f",
                    '--fatias', "$Fatias"
                )
                if ($Limite -gt 0) { $argumentos += @('--limite', "$Limite") }
                $p = Start-Process -FilePath $Python -ArgumentList $argumentos `
                    -NoNewWindow -PassThru `
                    -RedirectStandardOutput $log `
                    -RedirectStandardError "$log.erro"
                $processos += [PSCustomObject]@{ Processo = $p; Indice = $idx; Fatia = $f; Log = $log }
                Write-Host ("  arrancou {0} fatia {1}" -f $idx, $f)
            }
        }
        Write-Host ("  {0} processos a exportar; o envio comeca ja, sem esperar pelo fim." -f $processos.Count)
    } else {
        Escrever-Etapa 'Fase 1/3 - exportar (saltada)'
    }

    # --- 2. enviar, a medida que as partes ficam prontas -------------------
    if (-not $SaltarEnvio) {
        Escrever-Etapa 'Fase 2/3 - enviar (a acompanhar o exportador)'

        $concluidos = if ($SaltarExport) { $true } else { $false }
        $ultimoAviso = Get-Date

        while ($true) {

            # Um ficheiro `.ndjson.gz` so existe quando a parte esta completa: o
            # exportador escreve em `.tmp` e renomeia no fim.
            $partes = @(Get-ChildItem $ExportDir -File -Filter '*-part-*.ndjson.gz' -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -gt $MINIMO_BYTES -and (Testa-Indice $_) })

            $novas = @($partes | Where-Object { -not $enviados.ContainsKey((Chave-Parte $_)) })

            if ($novas.Count -gt 0) {
                foreach ($p in $novas) {
                    $tempName = $p.Name + '.a-chegar'
                    $tempRemoto = "$RemoteDir/$tempName"
                    $finalRemoto = "$RemoteDir/$($p.Name)"

                    $linha = 'docker exec -i {0} ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o LogLevel=ERROR {1}@{2} "cat > {3}" < "{4}"' -f `
                        $TunnelContainer, $SshUser, $SshHost, $tempRemoto, $p.FullName
                    cmd.exe /c $linha | Out-Null
                    $rc = $LASTEXITCODE

                    $ok = $false
                    if ($rc -eq 0) {
                        # Confirmar o tamanho ANTES de renomear: o importador so
                        # olha para `*.ndjson.gz`, logo nunca ve um ficheiro a meio.
                        $r = Invoke-Vm "stat -c %s $tempRemoto 2>/dev/null || echo 0"
                        $tamVm = 0
                        if ($r.Output -match '(\d+)') { $tamVm = [int64]$Matches[1] }
                        if ($tamVm -eq $p.Length) {
                            Invoke-Vm "mv $tempRemoto $finalRemoto" | Out-Null
                            $ok = $true
                        } else {
                            Write-Host ("  {0}: tamanho nao bate certo (local {1}, VM {2})" -f `
                                $p.Name, $p.Length, $tamVm) -ForegroundColor Red
                            Invoke-Vm "rm -f $tempRemoto" | Out-Null
                        }
                    }

                    if ($ok) {
                        $enviados[(Chave-Parte $p)] = $p.Length
                        $total = ($enviados.Values | Measure-Object -Sum).Sum
                        Write-Host ("  enviado {0}  ({1})  total {2}" -f `
                            $p.Name, (Format-Bytes $p.Length), (Format-Bytes $total)) -ForegroundColor DarkGray
                    } else {
                        $falhados[$p.Name] = $true
                        Write-Host ("  FALHOU {0}" -f $p.Name) -ForegroundColor Red
                    }
                }
            }

            if (-not $concluidos) {
                $vivos = @($processos | Where-Object { -not $_.Processo.HasExited })
                if ($vivos.Count -eq 0) { $concluidos = $true }
            }

            if ($concluidos) {
                # Ultima passagem para apanhar o que ficou por enviar.
                Start-Sleep -Milliseconds 300
                $restantes = @(Get-ChildItem $ExportDir -File -Filter '*-part-*.ndjson.gz' -ErrorAction SilentlyContinue |
                    Where-Object { $_.Length -gt $MINIMO_BYTES -and (Testa-Indice $_) -and -not $enviados.ContainsKey((Chave-Parte $_)) })
                if ($restantes.Count -eq 0) { break }
            } else {
                Start-Sleep -Milliseconds 400
            }
        }

        $totalGz = ($enviados.Values | Measure-Object -Sum).Sum
        Write-Host ''
        Write-Host ("  {0} partes enviadas, {1}, {2} falhadas" -f `
            $enviados.Count, (Format-Bytes $totalGz), $falhados.Count) -ForegroundColor Green

        if ($falhados.Count -gt 0) {
            Write-Host '  partes falhadas (voltar a correr com -SaltarExport -SaltarImport):' -ForegroundColor Yellow
            $falhados.Keys | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
        }
    } else {
        Escrever-Etapa 'Fase 2/3 - enviar (saltada)'
    }

    # --- 3. importar na VM -------------------------------------------------
    if (-not $SaltarImport) {
        Escrever-Etapa 'Fase 3/3 - importar na VM'

        # O importador tem de estar DENTRO da pasta montada: sem isto o `docker
        # run` arranca e morre logo com "can't open file '/export/...'".
        $tamScript = Send-FicheiroTexto -Local $scriptImporter -DestinoRemoto "$RemoteDir/importar_source.py"
        Write-Host ("  importador enviado: {0} bytes" -f $tamScript)

        $refazer = if ($RefazerImport) { ' --refazer' } else { '' }
        $cmd = "docker run --rm --network iqos-net -v ${RemoteDir}:/export --entrypoint python " +
               "$ContentorImport /export/importar_source.py --url $EsVm --pasta /export$refazer"

        Write-Host '  (o _bulk de 32 GB de JSON demora; a saida segue em baixo)'
        Write-Host ''
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $saida = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
                -o LogLevel=ERROR "$SshUser@$SshHost" $cmd 2>&1
            $saida | ForEach-Object { Write-Host "  $_" }
        } finally {
            $ErrorActionPreference = $prev
        }
    } else {
        Escrever-Etapa 'Fase 3/3 - importar (saltada)'
    }

} finally {
    # Nao deixar processos Python orfaos a martelar o ES se algo falhar.
    foreach ($p in $processos) {
        if (-not $p.Processo.HasExited) {
            Write-Host ("  a terminar {0} fatia {1}" -f $p.Indice, $p.Fatia) -ForegroundColor DarkGray
            try { $p.Processo.Kill() } catch { }
        }
    }
}

# --- resumo ---------------------------------------------------------------
$t = (Get-Date) - $script:Inicio
Write-Host ''
Write-Host '=== Resumo ===' -ForegroundColor Cyan
Write-Host ("  tempo total  : {0:hh\:mm\:ss}" -f $t)

$cnt = curl.exe -s -m 30 "$EsPc/_cat/count?h=count"
Write-Host ("  ES de origem : {0} documentos de topo" -f ($cnt -replace '\s+', ' '))

$vmCnt = Invoke-Vm "curl -s http://127.0.0.1:9200/_cat/count?h=count"
Write-Host ("  ES da VM     : {0} documentos de topo" -f ($vmCnt.Output -replace '\s+', ' '))

Write-Host ''
Write-Host '  Para confirmar os mapeamentos e as contagens:' -ForegroundColor DarkGray
Write-Host '    .\auditar_indices.ps1 -SoDiferencas' -ForegroundColor DarkGray
