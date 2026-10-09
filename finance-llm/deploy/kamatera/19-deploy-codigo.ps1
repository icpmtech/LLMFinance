#requires -Version 5.1
<#
.SYNOPSIS
    Deploy continuo do codigo do IQ OS para a VM do edge.

.DESCRIPTION
    Porque nao transferir a imagem: a imagem do backend sao 13,7 GB (4,0 GB de
    tar). Enviar isso a cada mudanca de codigo nao e deploy continuo, e um
    transplante de orgao.

    Este script tira partido dos Dockerfiles **incrementais** que ja existem:
    eles fazem `FROM <imagem que ja funciona>` + `COPY . .`, ou seja so
    substituem o codigo. Como a VM **ja tem a imagem base**, o que falta e o
    contexto de build -- e com o `.dockerignore` corrigido sao ~37 MB em vez dos
    ~330 MB que andavam a entrar.

    Fluxo:
      1. constroi o `dist` do frontend no PC (npm);
      2. empacota o contexto de build (sem `data/`, `model/`, `node_modules/`);
      3. envia-o para a VM;
      4. corre o `docker build` dos incrementais **na VM**, sobre a imagem que
         la esta;
      5. reinicia so os servicos afectados.

    Nada disto toca no Caddy, no Elasticsearch, no tunel nem no stack do PC.

    ATENCAO: cada build incremental acrescenta camadas a imagem (nao substitui).
    Ao fim de muitas dezenas de deploys a imagem fica maior do que precisa. Um
    rebuild completo de vez em quando resolve -- ver `Dockerfile.backend`.

.EXAMPLE
    .\19-deploy-codigo.ps1                    # backend + frontend
    .\19-deploy-codigo.ps1 -Servico frontend
    .\19-deploy-codigo.ps1 -SemBuild          # usa o que ja esta no PC
    .\19-deploy-codigo.ps1 -Planear           # mostra o que faria, sem enviar
#>
[CmdletBinding()]
param(
    [ValidateSet('backend', 'frontend', 'ambos')]
    [string]$Servico = 'ambos',

    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$RemoteDir = '/opt/iqos/build',

    # Salta o `npm run build` e reutiliza o `_frontend_dist` que ja exista.
    [switch]$SemBuild,
    [switch]$Planear
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$raiz = (Resolve-Path (Join-Path $here '..\..')).Path   # finance-llm/

$fazerBackend = $Servico -in @('backend', 'ambos')
$fazerFrontend = $Servico -in @('frontend', 'ambos')

$pkg = Join-Path $env:TEMP 'iqos-contexto.tgz'
$tar = Join-Path $env:TEMP 'iqos-contexto.tar'

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
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

if (-not (docker ps --filter "name=$TunnelContainer" --format '{{.Names}}')) {
    throw "o container $TunnelContainer nao esta a correr (ver 07-origin-tunnel.ps1)."
}

Write-Host ''
Write-Host "=== Deploy de codigo: $Servico ===" -ForegroundColor Cyan

# --- 1. Frontend: construir o dist ------------------------------------------
if ($fazerFrontend -and -not $SemBuild) {
    Write-Host ''
    Write-Host '=== 1. A construir o frontend (npm) ===' -ForegroundColor Cyan
    Push-Location $raiz
    try {
        # `VITE_API_URL=/api`: o browser tem de falar com o nginx na mesma origem.
        $env:VITE_API_URL = '/api'
        npm --prefix chat-ui run build 2>&1 | Select-String -Pattern 'built in|error TS' | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) { throw 'a build do frontend falhou' }
        # O `.dockerignore` exclui `chat-ui/dist`, por isso copia-se para um nome
        # que fica no contexto. O `Remove-Item` nao e opcional: `Copy-Item
        # -Recurse` para uma pasta existente cria `_frontend_dist\dist`.
        Remove-Item -Recurse -Force _frontend_dist -ErrorAction SilentlyContinue
        Copy-Item -Recurse chat-ui\dist _frontend_dist
        $n = (Get-ChildItem -Recurse -File _frontend_dist | Measure-Object).Count
        Write-Host "  _frontend_dist com $n ficheiros"
    } finally { Pop-Location }
}

# --- 2. Empacotar o contexto ------------------------------------------------
Write-Host ''
Write-Host '=== 2. A empacotar o contexto de build ===' -ForegroundColor Cyan
foreach ($f in @($pkg, $tar)) { if (Test-Path $f) { Remove-Item $f -Force } }

# As mesmas exclusoes do `.dockerignore`. O `tar` do Windows aceita `--exclude`.
$excl = @(
    '--exclude=./data', '--exclude=./model', '--exclude=./training',
    '--exclude=./logs', '--exclude=./kronos_upstream', '--exclude=./debug_mj',
    '--exclude=./exports', '--exclude=./.git', '--exclude=*/.git',
    '--exclude=*node_modules', '--exclude=*e2e-venv', '--exclude=*.venv',
    '--exclude=*__pycache__', '--exclude=*.pytest_cache', '--exclude=./chat-ui/dist'
)
Push-Location $raiz
try {
    # `-C` evita guardar o caminho absoluto dentro do tar.
    & tar -czf $pkg @excl .
    if ($LASTEXITCODE -ne 0) { throw 'o empacotamento falhou' }
} finally { Pop-Location }
$tamPkg = (Get-Item $pkg).Length
Write-Host ("  contexto: {0:N1} MB" -f ($tamPkg / 1MB))

if ($Planear) {
    Write-Host ''
    Write-Host '  (-Planear: nao enviei nem construi nada)' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  Seria construido na VM:' -ForegroundColor DarkGray
    if ($fazerBackend) { Write-Host '    docker build -f Dockerfile.backend.incremental  --build-arg BASE=iq-os-backend:latest  -t iq-os-backend:latest .' -ForegroundColor DarkGray }
    if ($fazerFrontend) { Write-Host '    docker build -f Dockerfile.frontend.incremental --build-arg BASE=iq-os-frontend:latest -t iq-os-frontend:latest .' -ForegroundColor DarkGray }
    Write-Host ''
    return
}

# --- 3. Enviar --------------------------------------------------------------
Write-Host ''
Write-Host '=== 3. A enviar para a VM ===' -ForegroundColor Cyan
Show-Vm "mkdir -p $RemoteDir" | Out-Null
# `cmd.exe` faz o redireccionamento binario; o PowerShell corrompe streams
# binarios em pipelines nativas.
$linha = 'docker exec -i {0} ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o LogLevel=ERROR {1}@{2} "cat > {3}/contexto.tgz" < "{4}"' -f `
    $TunnelContainer, $SshUser, $SshHost, $RemoteDir, $pkg
cmd.exe /c $linha
if ($LASTEXITCODE -ne 0) { throw 'o envio falhou' }
$tamVm = [int64]((Invoke-Vm "wc -c < $RemoteDir/contexto.tgz").Output.Trim())
if ($tamVm -ne $tamPkg) { throw "chegou incompleto: $tamVm de $tamPkg bytes" }
Write-Host ("  {0:N1} MB na VM" -f ($tamVm / 1MB))

# --- 4. Construir na VM -----------------------------------------------------
Write-Host ''
Write-Host '=== 4. A construir na VM (sobre a imagem que la esta) ===' -ForegroundColor Cyan
# `rm -rf src` + extracao limpa: se ficasse codigo antigo, o `COPY . .` levava-o
# e a imagem nova teria ficheiros que ja nao existem no repositorio.
Show-Vm "rm -rf $RemoteDir/src && mkdir -p $RemoteDir/src && tar -xzf $RemoteDir/contexto.tgz -C $RemoteDir/src && du -sh $RemoteDir/src" | Out-Null

$construir = @()
if ($fazerBackend) {
    $construir += "docker build -f Dockerfile.backend.incremental --build-arg BASE=iq-os-backend:latest -t iq-os-backend:latest $RemoteDir/src"
}
if ($fazerFrontend) {
    $construir += "docker build -f Dockerfile.frontend.incremental --build-arg BASE=iq-os-frontend:latest -t iq-os-frontend:latest $RemoteDir/src"
}
foreach ($cmd in $construir) {
    $nome = if ($cmd -match 'backend') { 'backend' } else { 'frontend' }
    Write-Host "  a construir: $nome"
    $r = Invoke-Vm "$cmd 2>&1 | tail -14"
    $r.Output -split "`n" | Where-Object { $_ } | ForEach-Object { Write-Host "    $_" }
    if ($r.ExitCode -ne 0) { throw "a build do $nome falhou" }
}

# --- 5. Reiniciar -----------------------------------------------------------
Write-Host ''
Write-Host '=== 5. A reiniciar os servicos afectados ===' -ForegroundColor Cyan
Write-Host '  (so estes projetos: o edge, o ES e o tunel ficam intocados)'
if ($fazerBackend) { Show-Vm "cd /opt/iqos/servicos/mcp && docker compose up -d --force-recreate 2>&1 | tail -3" | Out-Null }
if ($fazerFrontend) { Show-Vm "cd /opt/iqos/servicos/frontend && docker compose up -d --force-recreate 2>&1 | tail -3" | Out-Null }

Write-Host ''
Write-Host '=== 6. Validacao ===' -ForegroundColor Cyan
$sondas = @()
if ($fazerFrontend) { $sondas += @{ Nome = 'frontend'; Url = 'http://127.0.0.1:4180/' } }
if ($fazerBackend) { $sondas += @{ Nome = 'mcp'; Url = 'http://127.0.0.1:8765/' } }
foreach ($s in $sondas) {
    $codigo = (Invoke-Vm "curl -s -o /dev/null -m 8 -w %{http_code} $($s.Url)").Output.Trim()
    $ok = $codigo -match '^[234]'
    Write-Host ("  {0,-10} {1}  HTTP {2}" -f $s.Nome, $(if ($ok) { 'ok  ' } else { 'FALHA' }), $codigo) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}
Show-Vm 'df -h / | tail -1' | Out-Null
Write-Host ''
Write-Host 'Deploy concluido.' -ForegroundColor Green
Write-Host ''
Remove-Item $pkg -Force -ErrorAction SilentlyContinue
