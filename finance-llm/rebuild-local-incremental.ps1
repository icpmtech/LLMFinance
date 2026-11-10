<#
.SYNOPSIS
    Rebuilds and restarts the local Docker backend and/or frontend incrementally.
.EXAMPLE
    .\rebuild-local-incremental.ps1
    .\rebuild-local-incremental.ps1 -Target backend
    .\rebuild-local-incremental.ps1 -Target frontend
#>
param(
    [ValidateSet("all", "backend", "frontend")]
    [string]$Target = "all"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Invoke-DockerCommand {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') falhou com exit code $LASTEXITCODE."
    }
}

function Get-HostPort {
    param(
        [Parameter(Mandatory)][string]$Service,
        [Parameter(Mandatory)][int]$ContainerPort
    )

    $output = & docker compose port $Service $ContainerPort
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível obter o porto publicado de $Service."
    }
    $match = [regex]::Match(($output | Select-Object -First 1), ':(\d+)$')
    if (-not $match.Success) {
        throw "Não foi possível interpretar o porto publicado de $Service`: $output"
    }
    return [int]$match.Groups[1].Value
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                Write-Host "[OK] $Name respondeu em $Url" -ForegroundColor Green
                return $response
            }
        } catch {
            Start-Sleep -Seconds 3
        }
    } while ((Get-Date) -lt $deadline)

    throw "$Name não respondeu em $Url dentro de $TimeoutSeconds segundos."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker não está disponível. Inicie o Docker Desktop e tente novamente."
}

$buildFrontend = $Target -in @("all", "frontend")
$buildBackend = $Target -in @("all", "backend")

if ($buildBackend) {
    $backendBase = & docker image inspect iq-os-backend:latest --format "{{.Id}}" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $backendBase) {
        throw "A imagem-base iq-os-backend:latest não existe localmente."
    }
}
if ($buildFrontend) {
    $frontendBase = & docker image inspect iq-os-frontend:latest --format "{{.Id}}" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $frontendBase) {
        throw "A imagem-base iq-os-frontend:latest não existe localmente."
    }
}

if ($buildFrontend) {
    Write-Host "=== Build local do frontend ===" -ForegroundColor Cyan
    $previousApiUrl = $env:VITE_API_URL
    try {
        $env:VITE_API_URL = "/api"
        & npm.cmd --prefix chat-ui run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build falhou com exit code $LASTEXITCODE."
        }
    } finally {
        if ($null -eq $previousApiUrl) {
            Remove-Item Env:VITE_API_URL -ErrorAction SilentlyContinue
        } else {
            $env:VITE_API_URL = $previousApiUrl
        }
    }

    if (-not (Test-Path "chat-ui\dist\index.html")) {
        throw "O build do frontend não produziu chat-ui\dist\index.html."
    }
}

$frontendDistPath = Join-Path $root "_frontend_dist"
$frontendDistBackup = Join-Path ([System.IO.Path]::GetTempPath()) "iqos-dist-$([guid]::NewGuid().ToString('N'))"
$hadFrontendDist = $false
$expectedBundle = $null

try {
    if ($buildFrontend) {
        if (Test-Path $frontendDistPath) {
            $resolvedFrontendDist = (Resolve-Path $frontendDistPath).Path
            if ($resolvedFrontendDist -ne $frontendDistPath) {
                throw "O caminho de saída do frontend não corresponde a _frontend_dist."
            }
            Copy-Item -LiteralPath $resolvedFrontendDist -Destination $frontendDistBackup -Recurse
            $hadFrontendDist = $true
            Remove-Item -LiteralPath $resolvedFrontendDist -Recurse -Force
        }
        $distPath = (Resolve-Path "chat-ui\dist").Path
        Copy-Item -LiteralPath $distPath -Destination $frontendDistPath -Recurse
        $builtIndex = Get-Content -Raw (Join-Path $frontendDistPath "index.html")
        $builtBundleMatch = [regex]::Match($builtIndex, 'assets/index-[A-Za-z0-9_-]+\.js')
        if (-not $builtBundleMatch.Success) {
            throw "Não foi possível identificar o bundle JavaScript produzido pelo frontend."
        }
        $expectedBundle = $builtBundleMatch.Value
    }

    if ($buildBackend) {
        if (-not (Test-Path "_frontend_dist\index.html")) {
            throw "O backend incremental precisa de _frontend_dist\index.html; execute o alvo all ou frontend."
        }
        Write-Host "=== Build incremental do backend ===" -ForegroundColor Cyan
        Invoke-DockerCommand @(
            "build", "-f", "Dockerfile.backend.incremental",
            "--build-arg", "BASE=iq-os-backend:latest",
            "-t", "iq-os-backend:latest", "."
        )
    }

    if ($buildFrontend) {
        Write-Host "=== Build incremental da imagem frontend ===" -ForegroundColor Cyan
        Invoke-DockerCommand @(
            "build", "-f", "Dockerfile.frontend.incremental",
            "--build-arg", "BASE=iq-os-frontend:latest",
            "-t", "iq-os-frontend:latest", "."
        )
    }
} finally {
    if ($buildFrontend) {
        if (Test-Path $frontendDistPath) {
            Remove-Item -LiteralPath $frontendDistPath -Recurse -Force
        }
        if ($hadFrontendDist) {
            Copy-Item -LiteralPath $frontendDistBackup -Destination $frontendDistPath -Recurse
        }
        if (Test-Path $frontendDistBackup) {
            Remove-Item -LiteralPath $frontendDistBackup -Recurse -Force
        }
    }
}

$services = @()
if ($buildBackend) { $services += "backend" }
if ($buildFrontend) { $services += "frontend" }

Write-Host "=== Recriar apenas: $($services -join ', ') ===" -ForegroundColor Cyan
Invoke-DockerCommand (@("compose", "up", "-d", "--no-build", "--no-deps", "--force-recreate") + $services)

if ($buildBackend) {
    $apiPort = Get-HostPort -Service "backend" -ContainerPort 8000
    Wait-ForHttp -Name "Backend" -Url "http://127.0.0.1:$apiPort/health" | Out-Null
}

if ($buildFrontend) {
    $uiPort = Get-HostPort -Service "frontend" -ContainerPort 80
    $response = Wait-ForHttp -Name "Frontend" -Url "http://127.0.0.1:$uiPort/"
    $servedBundleMatch = [regex]::Match($response.Content, 'assets/index-[A-Za-z0-9_-]+\.js')
    if ($servedBundleMatch.Value -ne $expectedBundle) {
        throw "O frontend serve um bundle diferente do build local."
    }
    Write-Host "[OK] Bundle servido corresponde ao build: $expectedBundle" -ForegroundColor Green
}

Write-Host ""
Write-Host "Build incremental concluído. Serviços não selecionados não foram recriados." -ForegroundColor Green
