# Espera que a app DENTRO do contentor fique a ouvir o 8000 e valida pelo nginx.
# Sem acentos: o PowerShell 5.1 le .ps1 sem BOM como Windows-1252.
$ErrorActionPreference = 'Continue'
$raiz = 'C:\LLMFinance\finance-llm'
Set-Location $raiz

Write-Output '=== quem serve o 127.0.0.1:8002 no anfitriao (nao e o Docker) ==='
Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        Write-Output ("  " + $_.LocalAddress + ":" + $_.LocalPort + " -> " + $p.ProcessName + " (" + $p.Path + ")")
    }

Write-Output ''
Write-Output '=== a espera de o contentor ouvir o 8000 ==='
# O healthcheck do proprio contentor faz `requests.get('http://127.0.0.1:8000/health')`:
# quando ele passa a `healthy`, a app esta a ouvir dentro do contentor.
$limite = (Get-Date).AddMinutes(15)
$pronto = $false
while ((Get-Date) -lt $limite) {
    $estado = docker inspect finance-llm-backend --format '{{.State.Health.Status}}' 2>$null
    Write-Output ("  " + (Get-Date -Format 'HH:mm:ss') + "  health=" + $estado)
    if ($estado -eq 'healthy') { $pronto = $true; break }
    Start-Sleep -Seconds 20
}

if (-not $pronto) {
    Write-Output 'a app do contentor nao abriu o 8000 em 15 minutos. Ultimas linhas:'
    docker logs finance-llm-backend --tail 15 2>&1 | Out-String | Write-Output
    exit 2
}

Write-Output ''
Write-Output '=== estado final ==='
docker ps --format '{{.Names}} | {{.Status}}' | Select-String 'finance-llm-backend|finance-llm-frontend'

Write-Output ''
Write-Output '=== endpoints pelo nginx (4180), como o browser usa ==='
foreach ($rota in @('deep-search/meta', 'deep-search/examples?limit=8')) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri ("http://127.0.0.1:4180/api/" + $rota) -UseBasicParsing -TimeoutSec 300
        Write-Output ("  /api/" + $rota + " -> " + $r.StatusCode + " em " + $sw.Elapsed.TotalSeconds.ToString('F1') + "s (" + $r.Content.Length + " car.)")
        if ($rota -like '*examples*') {
            $ex = $r.Content | ConvertFrom-Json
            $ex.examples | ForEach-Object { Write-Output ("     [" + $_.scope + "] " + $_.text) }
        }
    } catch {
        Write-Output ("  /api/" + $rota + " -> FALHOU em " + $sw.Elapsed.TotalSeconds.ToString('F1') + "s: " + $_.Exception.Message)
    }
}

Write-Output ''
Write-Output '=== ligacoes das fichas (pelo nginx) ==='
try {
    $busca = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/deep-search/search?q=licencas%20de%20software&sources=contracts&mode=text&per_source=2&max_sources=2' -TimeoutSec 600
    Write-Output ("  fontes: " + $busca.sources.Count)
    foreach ($fonte in $busca.sources) {
        Write-Output ("  [" + $fonte.n + "] " + $fonte.title)
        foreach ($ligacao in $fonte.links) {
            $destino = if ($ligacao.view -and $ligacao.arg) { $ligacao.view + ':' + $ligacao.arg } else { '(sem ficha)' }
            Write-Output ("      " + $ligacao.label + " -> " + $destino)
        }
    }
} catch {
    Write-Output ("  busca falhou: " + $_.Exception.Message)
}

Write-Output ''
Write-Output '=== fim ==='
