#requires -Version 5.1
<#
.SYNOPSIS
    Analise de custo de mover a stack IQ OS do PC para a VM Kamatera.

.DESCRIPTION
    Compara o que a stack consome (medido com `docker stats` / `docker system df`)
    com o que a VM `iq-os-edge-01` tem, e estima o custo mensal e anual dos
    tamanhos candidatos.

    Se as variaveis de ambiente `KAMATERA_CLIENT_ID` e `KAMATERA_SECRET`
    estiverem definidas, consulta tambem a API para mostrar o preco **real** do
    servidor atual (a Kamatera nao tem endpoint de orcamento: o preco de uma
    configuracao so se sabe depois de a ter).

.EXAMPLE
    .\08-custo-vm.ps1
    $env:KAMATERA_CLIENT_ID='...'; $env:KAMATERA_SECRET='...'; .\08-custo-vm.ps1
#>
[CmdletBinding()]
param(
    [string]$ServerName = 'iq-os-edge-01',
    [string]$ApiBase = 'https://cloudcli.cloudwm.com/service'
)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------------------
# 1. O que temos. RAM = memoria REAL (cgroup `memory.stat` campo `anon`), nao o
# numero do `docker stats`: esse inclui a cache de ficheiros do indice Lucene,
# que o kernel liberta quando precisa. Para o Elasticsearch sao 880 MB reais
# contra 5,8-8,5 GB reportados.
# ---------------------------------------------------------------------------
$ram = [ordered]@{
    'elasticsearch (base)'      = 880
    'backend (base)'            = 791
    'n8n (base)'                = 206
    'searxng (base)'            = 33
    'frontend (base)'           = 12
    'hermes-agent (perfil)'     = 358
    'osif (6 contentores)'      = 243
    'mirofish (perfil)'         = 82
    'mcp (perfil)'              = 20
}
$ramSistema = 420                                   # Ubuntu + dockerd
$ramBase = 880 + 791 + 206 + 33 + 12
$ramFull = $ramBase + 358 + 243 + 82 + 20

# Disco (GB). Dados medidos com `du`/`Measure-Object`; imagens com `docker images`.
$discos = [ordered]@{
    'data/ (contratos, GLEIF, scraper...)' = 37.2
    'indice Elasticsearch (derivado)'      = 31.3
    'model/ (LLMs locais)'                 = 3.0
    'cache whisper'                        = 1.1
    'hermes-data + n8n-data + logs'        = 0.9
    'sistema (Ubuntu + docker)'            = 8.0
}
$discosImagens = [ordered]@{
    'iq-os-backend (torch, scipy...)' = 13.7
    'elasticsearch + frontend + nginx' = 2.6
    'n8n'                             = 1.7
    'searxng'                         = 0.4
}
$discosOpcionais = [ordered]@{
    'mirofish'                             = 14.6
    'hermes-agent'                         = 4.0
    'osif (backend + frontend + minio...)' = 1.4
}
$dadosGB = ($discos.Values | Measure-Object -Sum).Sum
$imgBaseGB = ($discosImagens.Values | Measure-Object -Sum).Sum
$imgOpcGB = ($discosOpcionais.Values | Measure-Object -Sum).Sum

Write-Host "`n=== 1. O que a stack consome (medido no PC) ===" -ForegroundColor Cyan
Write-Host "`nRAM real (campo 'anon' do cgroup; exclui cache de ficheiros):"
$ram.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-28} {1,7:N0} MiB" -f $_.Key, $_.Value) }
Write-Host ("  {0,-28} {1,7:N0} MiB" -f 'sistema (Ubuntu + dockerd)', $ramSistema)
Write-Host ("  {0,-28} {1,7:N1} GB   (stack base)" -f 'TOTAL base', (($ramBase + $ramSistema) / 1024)) -ForegroundColor Yellow
Write-Host ("  {0,-28} {1,7:N1} GB   (com todos os perfis)" -f 'TOTAL completo', (($ramFull + $ramSistema) / 1024)) -ForegroundColor Yellow
Write-Host "  (o `docker stats` reportava 7,9 GB: 6,4 GB eram cache reclaimable do indice)" -ForegroundColor DarkGray

Write-Host "`nDisco:"
$discos.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-38} {1,6:N1} GB" -f $_.Key, $_.Value) }
Write-Host ("  {0,-38} {1,6:N1} GB" -f 'Imagens do nucleo', $imgBaseGB)
Write-Host ("  {0,-38} {1,6:N1} GB" -f 'Imagens dos perfis opcionais', $imgOpcGB)
$totalSim = $dadosGB + $imgBaseGB + $imgOpcGB
$totalSemIndice = $totalSim - 31.3
$totalSemMirofish = $totalSim - 14.6
Write-Host ("  {0,-38} {1,6:N0} GB" -f 'TOTAL (tudo, com o indice copiado)', $totalSim) -ForegroundColor Yellow
Write-Host ("  {0,-38} {1,6:N0} GB" -f 'TOTAL (indice reconstruido na VM)', $totalSemIndice) -ForegroundColor Yellow
Write-Host ("  {0,-38} {1,6:N0} GB" -f 'TOTAL (sem mirofish)', $totalSemMirofish) -ForegroundColor Yellow

# ---------------------------------------------------------------------------
# 2. O que a VM tem
# ---------------------------------------------------------------------------
$vm = @{ vcpu = 1; ram_gb = 2; disco_gb = 20; tipo = 'A' }
Write-Host "`n=== 2. O que a VM iq-os-edge-01 tem hoje ===" -ForegroundColor Cyan
Write-Host ("  {0} vCPU tipo {1} / {2} GB RAM / {3} GB NVMe" -f $vm.vcpu, $vm.tipo, $vm.ram_gb, $vm.disco_gb)
$ramPrec = ($ramFull + $ramSistema) / 1024
Write-Host ("  RAM:   {0:N1} GB precisos  vs  {1} GB  ->  {2}" -f $ramPrec, $vm.ram_gb, $(if ($ramPrec -le $vm.ram_gb) { 'OK' } else { "falta $([math]::Round($ramPrec - $vm.ram_gb, 1)) GB" })) -ForegroundColor $(if ($ramPrec -le $vm.ram_gb) { 'Green' } else { 'Red' })
Write-Host ("  Disco: {0:N0} GB precisos  vs  {1} GB  ->  falta {2:N0} GB" -f $totalSim, $vm.disco_gb, ($totalSim - $vm.disco_gb)) -ForegroundColor Red
Write-Host "  Veredicto: nao cabe hoje. O gargalo e o DISCO, nao a RAM." -ForegroundColor Red

# ---------------------------------------------------------------------------
# 3. Estimativa de custo
# ---------------------------------------------------------------------------
# Taxas derivadas de dois pontos publicos, que reproduzem exatamente:
#   A) VM atual: 1 vCPU A + 2 GB + 20 GB = 6,00 USD/mes  ->  1 vCPU A + 2 GB = 5,00
#   B) calculadora: 1 vCPU B + 512 MB + 5 GB = 10,00 USD/mes  ->  1 vCPU B + 0,5 GB = 9,75
# Disco ($0,05/GB/mes) e trafego (5 TB/mes incluidas, depois $0,01/GB) sao
# preco publicado. A divisao vCPU/RAM dentro de cada tipo e INFERIDA.
$preco = @{
    A = @{ vcpu = 2.00; ramGB = 1.50 }
    B = @{ vcpu = 9.00; ramGB = 1.50 }
}
$discoGBmes = 0.05
# Arredondamento de RAM: a Kamatera so oferece multiplos de 512 MB.
$candidatos = @(
    @{ nome = 'Atual (so edge)';            tipo = 'A'; vcpu = 1; ram = 2;  disco = 20 }
    @{ nome = 'So o nucleo, apertado';      tipo = 'A'; vcpu = 2; ram = 8;  disco = 120 }
    @{ nome = 'Recomendado: tudo';          tipo = 'A'; vcpu = 2; ram = 8;  disco = 150 }
    @{ nome = 'Tudo, 4 cores';              tipo = 'A'; vcpu = 4; ram = 8;  disco = 150 }
    @{ nome = 'Tudo, folgado';              tipo = 'A'; vcpu = 4; ram = 12; disco = 200 }
    @{ nome = 'Tudo, CPU dedicada';         tipo = 'B'; vcpu = 4; ram = 8;  disco = 150 }
)

Write-Host "`n=== 3. Estimativa de custo Kamatera (USD) ===" -ForegroundColor Cyan
Write-Host ("  taxas: vCPU A 2,00 / vCPU B 9,00 | RAM 1,50/GB | disco ${discoGBmes}/GB")
Write-Host ("  trafego: 5 TB/mes incluidas`n")
Write-Host ("  {0,-24} {1,-5} {2,-20} {3,10} {4,10}" -f 'Configuracao', 'Tipo', 'vCPU/RAM/Disco', 'USD/mes', 'USD/ano')
foreach ($c in $candidatos) {
    $t = $preco[$c.tipo]
    $m = $t.vcpu * $c.vcpu + $t.ramGB * $c.ram + $discoGBmes * $c.disco
    Write-Host ("  {0,-24} {1,-5} {2,-20} {3,10:N2} {4,10:N2}" -f $c.nome, $c.tipo, "$($c.vcpu) / $($c.ram) / $($c.disco) GB", $m, ($m * 12))
}
Write-Host "`n  (estimativa: a Kamatera nao tem endpoint de orcamento; ver comentario acima)" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# 4. Eletricidade: o custo escondido de deixar o PC ligado
# ---------------------------------------------------------------------------
Write-Host "`n=== 4. Eletricidade do PC (24/7) ===" -ForegroundColor Cyan
$watts = @(60, 90, 130)
$eurKwh = 0.20
Write-Host ("  preco do kWh assumido: {0:N2} EUR" -f $eurKwh)
foreach ($w in $watts) {
    $kwh = $w / 1000 * 730
    Write-Host ("  {0,4} W -> {1,6:N0} kWh/mes -> {2,5:N2} EUR/mes -> {3,6:N2} EUR/ano" -f $w, $kwh, ($kwh * $eurKwh), ($kwh * $eurKwh * 12))
}
Write-Host "  Ajusta os watts ao teu PC (medidor de tomada ou spec da fonte)." -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# 5. Preco real do servidor atual (precisa das credenciais)
# ---------------------------------------------------------------------------
Write-Host "`n=== 5. Preco real na API (opcional) ===" -ForegroundColor Cyan
$id = $env:KAMATERA_CLIENT_ID
$secret = $env:KAMATERA_SECRET
if (-not $id -or -not $secret) {
    Write-Host '  Sem KAMATERA_CLIENT_ID / KAMATERA_SECRET no ambiente.'
    Write-Host '  Define-as e volta a correr para ler o preco exato do servidor atual:'
    Write-Host '    $env:KAMATERA_CLIENT_ID="..."; $env:KAMATERA_SECRET="..."; .\08-custo-vm.ps1' -ForegroundColor DarkGray
} else {
    $headers = @{ AuthClientId = $id; AuthSecret = $secret; 'Content-Type' = 'application/json' }
    try {
        $r = Invoke-RestMethod -Uri "$ApiBase/server/info" -Method Post -Headers $headers -Body (@{ name = $ServerName } | ConvertTo-Json)
        $mes = $r.priceMonthlyOn
        Write-Host ("  {0}: {1} USD/mes -> {2:N2} USD/ano" -f $ServerName, $mes, ($mes * 12)) -ForegroundColor Yellow
        Write-Host ("  (verificado em {0})" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    } catch {
        Write-Host ("  Falhou a consulta: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------------------
# 6. Alternativas
# ---------------------------------------------------------------------------
Write-Host "`n=== 6. Alternativas (mais barato -> mais caro) ===" -ForegroundColor Cyan
Write-Host '  a) Hibrido atual: so o edge na VM + o PC sempre ligado. 6 USD/mes + 9-19 EUR/mes de luz.'
Write-Host '  b) Hibrido aliviado: largar os perfis opcionais. So poupa RAM/disco, nao muda a fatura.'
Write-Host '  c) Tudo na VM: ~24 USD/mes. Substitui a luz do PC pelo aluguer, e liberta a maquina de casa.'
Write-Host ''
Write-Host '  Nota: com o PC ligado 24/7 as duas opcoes ficam ela por ela (19 vs 22 EUR/mes).'
Write-Host '  A decisao e de disponibilidade, nao de custo.'
Write-Host ''
