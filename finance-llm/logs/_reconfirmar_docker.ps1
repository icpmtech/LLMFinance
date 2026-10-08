# Reconfirmacao completa depois de o Docker Desktop voltar.
# Sem acentos de proposito: o PowerShell 5.1 le .ps1 sem BOM como Windows-1252.
$ErrorActionPreference = 'Continue'
$raiz = 'C:\LLMFinance\finance-llm'
Set-Location $raiz

function Esperar-Daemon {
    param([int]$Minutos = 8)
    $limite = (Get-Date).AddMinutes($Minutos)
    while ((Get-Date) -lt $limite) {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

Write-Output '=== 1. daemon ==='
if (-not (Esperar-Daemon -Minutos 10)) {
    Write-Output 'daemon NAO subiu em 10 minutos'
    exit 1
}
Write-Output ("daemon OK - versao " + (docker info --format '{{.ServerVersion}}'))

Write-Output ''
Write-Output '=== 2. etiquetas ==='
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}' |
    Select-String 'iq-os-backend|iq-os-frontend'

Write-Output ''
Write-Output '=== 3. contentores: que imagem e que estado ==='
$backendImage = docker inspect finance-llm-backend --format '{{.Image}}' 2>$null
$frontendImage = docker inspect finance-llm-frontend --format '{{.Image}}' 2>$null
Write-Output ("backend  a correr -> " + $backendImage)
Write-Output ("frontend a correr -> " + $frontendImage)
Write-Output ("etiqueta latest -> " + (docker inspect iq-os-backend:latest --format '{{.Id}}' 2>$null))
Write-Output ("etiqueta latest -> " + (docker inspect iq-os-frontend:latest --format '{{.Id}}' 2>$null))
Write-Output ('latest do backend == a correr? ' + ($backendImage -eq (docker inspect iq-os-backend:latest --format '{{.Id}}' 2>$null)))

Write-Output ''
Write-Output '=== 4. estado dos servicos ==='
docker ps --format '{{.Names}} | {{.Status}} | {{.Image}}' | Select-String 'finance-llm-backend|finance-llm-frontend'

Write-Output ''
Write-Output '=== 5. a espera do /health (arranque demora minutos) ==='
$limite = (Get-Date).AddMinutes(12)
$pronto = $false
while ((Get-Date) -lt $limite) {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/health' -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $pronto = $true; break }
    } catch { }
    Start-Sleep -Seconds 10
}
if (-not $pronto) {
    Write-Output 'backend sem /health em 12 minutos - ultimas linhas do log:'
    docker logs finance-llm-backend --tail 12 2>&1 | Out-String | Write-Output
    exit 2
}
Write-Output 'backend /health 200'

Write-Output ''
Write-Output '=== 6. bundle servido pelo frontend ==='
try {
    $html = (Invoke-WebRequest -Uri ("http://127.0.0.1:4180/?v=" + (Get-Random)) -UseBasicParsing -TimeoutSec 20).Content
    [regex]::Matches($html, 'assets/index-[A-Za-z0-9_\-]+\.js') | ForEach-Object { $_.Value } | Select-Object -Unique
} catch { Write-Output ('falhou: ' + $_.Exception.Message) }
Write-Output 'no dist local:'
Get-ChildItem "$raiz\chat-ui\dist\assets\index-*.js" | Select-Object -ExpandProperty Name

Write-Output ''
Write-Output '=== 7. endpoints (via nginx, como o browser ve) ==='
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    $meta = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/deep-search/meta' -TimeoutSec 60
    Write-Output ("meta: " + $meta.sources.Count + " fontes, " + $meta.modes.Count + " modos, " + $meta.examples.Count + " exemplos em " + $sw.Elapsed.TotalMilliseconds.ToString('F0') + " ms")
    Write-Output ('rotas novas no catalogo: ' + (($meta.sources | Where-Object { $_.id -in @('contracts','news','imprensa','entities','pessoas') }).Count) + ' ambitos esperados presentes')
} catch { Write-Output ('meta falhou: ' + $_.Exception.Message) }

$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    $ex = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/deep-search/examples?limit=8' -TimeoutSec 120
    Write-Output ("exemplos dinamicos: " + $ex.examples.Count + " em " + $sw.Elapsed.TotalSeconds.ToString('F1') + " s")
    $ex.examples | ForEach-Object { Write-Output ("   [" + $_.scope + "] " + $_.text) }
} catch { Write-Output ('exemplos falharam: ' + $_.Exception.Message) }

Write-Output ''
Write-Output '=== 8. ligacoes das fichas num contrato ==='
try {
    $busca = Invoke-RestMethod -Uri 'http://127.0.0.1:4180/api/deep-search/search?q=licencas%20de%20software&sources=contracts&mode=text&per_source=2&max_sources=2' -TimeoutSec 300
    Write-Output ("fontes: " + $busca.sources.Count)
    foreach ($fonte in $busca.sources) {
        Write-Output ('  [' + $fonte.n + '] ' + $fonte.title)
        foreach ($ligacao in $fonte.links) {
            $destino = if ($ligacao.view -and $ligacao.arg) { $ligacao.view + ':' + $ligacao.arg } else { '(sem ficha)' }
            Write-Output ('      ' + $ligacao.label + ' -> ' + $destino)
        }
    }
} catch { Write-Output ('busca falhou: ' + $_.Exception.Message) }

Write-Output ''
Write-Output '=== fim ==='
