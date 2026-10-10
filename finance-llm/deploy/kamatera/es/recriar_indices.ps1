# Recria indices na VM com as settings e o mapeamento exatos do PC.
#
# Porque e que isto existe
# ------------------------
# A auditoria (`auditar_indices.ps1`) mostrou que os dois indices maiores ficaram
# VAZIOS na VM: o limite `MAX_MB` do `migrar.sh` saltou-os por serem os maiores.
#
# E, pior, os mapeamentos deles tambem nao batiam certo:
#     contratos     43 campos no PC, 42 na VM  -- faltava `embedding` (dense_vector 384)
#     contratos_es  54 campos no PC, 53 na VM  -- faltava `doc_id`
#
# Remendar so esses dois campos resolvia o sintoma visivel, mas a auditoria
# comparou *campos*, e nao *analisadores*. Um indice com os mesmos campos mas
# outro analisador da resultados de pesquisa diferentes sem dar erro nenhum.
# Reconstruir a partir das settings de origem resolve as duas coisas de uma vez.
#
# Seguranca
# ---------
# So apaga um indice da VM se ele tiver **zero documentos**. Se tiver algum, para
# e diz. Um `DELETE` distraido num indice com dados nao se desfaz.
#
#     .\recriar_indices.ps1
#     .\recriar_indices.ps1 -Indices contratos -SoVerificar

[CmdletBinding()]
param(
    [string[]] $Indices = @('contratos', 'contratos_es'),
    [string] $EsPc = 'http://127.0.0.1:9200',
    [string] $EsVm = 'http://127.0.0.1:9200',
    [string] $TunnelContainer = 'iqos-origin-tunnel',
    [string] $SshUser = 'root',
    [string] $SshHost = '45.147.251.188',
    [switch] $SoVerificar
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

# Settings que existem numa resposta mas que o Elasticsearch RECUSA num pedido de
# criacao: sao gerados por ele proprio.
$proibidas = @(
    'uuid', 'creation_date', 'creation_date_string', 'provided_name', 'version',
    'resize', 'routing', 'store', 'history_uuid', 'verified_before_close',
    'hidden', 'blocks'
)

$tmp = Join-Path $env:TEMP 'iqos-recriar'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null

foreach ($idx in $Indices) {

    Write-Host ''
    Write-Host "===== $idx =====" -ForegroundColor Cyan

    # --- 1. ler o PC -------------------------------------------------------
    $setFile = Join-Path $tmp "pc-$idx-settings.json"
    $mapFile = Join-Path $tmp "pc-$idx-mapping.json"
    curl.exe -s -o $setFile "$EsPc/$idx/_settings" | Out-Null
    curl.exe -s -o $mapFile "$EsPc/$idx/_mapping" | Out-Null

    if ((Get-Item $setFile).Length -eq 0) { throw "o PC nao devolveu settings de '$idx'" }

    $set = Get-Content $setFile -Raw | ConvertFrom-Json
    $map = Get-Content $mapFile -Raw | ConvertFrom-Json

    $settingsPc = $set.$idx.settings.index
    $analisadoresPc = @($settingsPc.analysis.analyzer.PSObject.Properties.Name)
    $shardsPc = $settingsPc.number_of_shards

    Write-Host ("  PC: shards={0}  analisadores={1}  campos={2}" -f `
        $shardsPc, $analisadoresPc.Count,
        @($map.$idx.mappings.properties.PSObject.Properties.Name).Count)

    # --- 2. estado da VM ---------------------------------------------------
    $cnt = Invoke-Vm "curl -s $EsVm/$idx/_count"
    $docsVm = -1
    if ($cnt.Output -match '"count"\s*:\s*(\d+)') { $docsVm = [int64]$Matches[1] }

    $existeVm = $cnt.Output -match '"count"'
    Write-Host ("  VM: existe={0}  docs={1}" -f $existeVm, $(if ($existeVm) { $docsVm } else { 'n/a' }))

    if ($SoVerificar) {
        Write-Host '  --SoVerificar: nao mexo.' -ForegroundColor DarkGray
        continue
    }

    if ($existeVm -and $docsVm -gt 0) {
        Write-Host "  PARA: o indice da VM tem $docsVm documentos." -ForegroundColor Red
        Write-Host '        Esta rotina so recria indices VAZIOS. Apagar este seria perder dados.' -ForegroundColor Red
        continue
    }

    # --- 3. construir o corpo de criacao ----------------------------------
    # Mantem tudo excepto o que o ES recusa; assim os analisadores, o
    # `max_result_window` e o que mais estiver la passam tal e qual.
    $novo = [ordered]@{}
    foreach ($p in $settingsPc.PSObject.Properties) {
        if ($proibidas -contains $p.Name) { continue }
        $novo[$p.Name] = $p.Value
    }

    $corpo = [ordered]@{
        settings = @{ index = $novo }
        mappings = $map.$idx.mappings
    }
    $json = $corpo | ConvertTo-Json -Depth 40 -Compress

    Write-Host ("  corpo de criacao: {0:N0} bytes, settings mantidas: {1}" -f `
        $json.Length, (($novo.Keys) -join ', '))

    # --- 4. enviar e recriar ----------------------------------------------
    # Base64 e depois `base64 -d` a partir de FICHEIRO, nao por pipe: o `|`
    # nao sobrevive a passagem PowerShell -> ssh e chega truncado a VM.
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $envio = Invoke-Vm "rm -f /tmp/iqos-b64.txt; echo '$b64' > /tmp/iqos-b64.txt; base64 -d /tmp/iqos-b64.txt > /tmp/iqos-create.json; rm -f /tmp/iqos-b64.txt; wc -c /tmp/iqos-create.json"
    Write-Host ("  enviado: {0}" -f ($envio.Output -replace '\s+', ' '))

    # O ficheiro tem de chegar inteiro; um JSON truncado cria um indice a metade.
    if ($envio.Output -notmatch "(\d+)") { throw 'nao consegui confirmar o ficheiro na VM' }
    $bytesVm = [int64]$Matches[1]
    if ($bytesVm -ne $json.Length) {
        throw "o corpo chegou truncado a VM ($bytesVm de $($json.Length) bytes)"
    }

    if ($existeVm) {
        $del = Invoke-Vm "curl -s -X DELETE $EsVm/$idx"
        Write-Host ("  apagado: {0}" -f (($del.Output -replace '\s+', ' ').Substring(0, [Math]::Min(80, ($del.Output -replace '\s+',' ').Length))))
    }

    $criar = Invoke-Vm "curl -s -X PUT -H 'Content-Type: application/json' --data-binary @/tmp/iqos-create.json $EsVm/$idx"
    $criarTxt = $criar.Output -replace '\s+', ' '
    Write-Host ("  criado: {0}" -f $criarTxt.Substring(0, [Math]::Min(120, $criarTxt.Length)))

    # --- 5. confirmar ------------------------------------------------------
    $setVm = Invoke-Vm "curl -s $EsVm/$idx/_settings"
    $mapVm = Invoke-Vm "curl -s $EsVm/$idx/_mapping"

    if ($mapVm.Output -notmatch '\{') { throw "nao consegui ler o mapeamento de '$idx' na VM depois de criar" }

    $vm = $mapVm.Output | ConvertFrom-Json
    $vmProps = @($vm.$idx.mappings.properties.PSObject.Properties.Name)
    $pcProps = @($map.$idx.mappings.properties.PSObject.Properties.Name)

    $faltam = @(Compare-Object $pcProps $vmProps |
        Where-Object { $_.SideIndicator -eq '<=' } | Select-Object -ExpandProperty InputObject)
    $sobram = @(Compare-Object $pcProps $vmProps |
        Where-Object { $_.SideIndicator -eq '=>' } | Select-Object -ExpandProperty InputObject)

    $sVm = $setVm.Output | ConvertFrom-Json
    $analisadoresVm = @($sVm.$idx.settings.index.analysis.analyzer.PSObject.Properties.Name)

    Write-Host ("  VM depois: campos={0}  analisadores={1}" -f $vmProps.Count, $analisadoresVm.Count)

    if ($faltam.Count -eq 0 -and $sobram.Count -eq 0 -and $analisadoresVm.Count -eq $analisadoresPc.Count) {
        Write-Host '  OK: mapeamento e analisadores iguais aos do PC.' -ForegroundColor Green
    } else {
        Write-Host ("  ATENCAO: faltam={0} sobram={1} analisadores PC/VM={2}/{3}" -f `
            ($faltam -join ','), ($sobram -join ','), $analisadoresPc.Count, $analisadoresVm.Count) -ForegroundColor Red
    }

    Invoke-Vm 'rm -f /tmp/iqos-create.json' | Out-Null
}
