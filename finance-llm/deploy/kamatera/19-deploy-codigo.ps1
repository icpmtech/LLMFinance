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
    # Limpa a cache de build no fim. A cache acelera builds repetidos, mas cresce
    # ~GB por deploy com o driver `docker` do buildkit.
    [switch]$LimparCache,
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
        # `npm` escreve avisos no stderr e, com ErrorActionPreference 'Stop', o
        # PowerShell transforma isso em erro fatal -- dava exit 1 numa build que
        # estava a correr bem (o aviso era o INEFFECTIVE_DYNAMIC_IMPORT do rolldown).
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            npm --prefix chat-ui run build 2>&1 | Select-String -Pattern 'built in|built in|error TS' | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" }
            $rc = $LASTEXITCODE
        } finally { $ErrorActionPreference = $prevEap }
        if ($rc -ne 0) { throw "a build do frontend falhou (exit $rc)" }
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
    $construir += @{ Nome = 'backend'; Dockerfile = 'Dockerfile.backend.incremental'; Alvo = 'iq-os-backend:latest' }
}
if ($fazerFrontend) {
    $construir += @{ Nome = 'frontend'; Dockerfile = 'Dockerfile.frontend.incremental'; Alvo = 'iq-os-frontend:latest' }
}
foreach ($b in $construir) {
    Write-Host "  a construir: $($b.Nome)"
    # `cd` para o contexto **antes** do `-f`: o `-f` e relativo ao directorio
    # actual, nao ao contexto -- sem isto o Docker procura o Dockerfile em /root
    # e falha com "open Dockerfile...: no such file or directory".
    #
    # Sem `| tail` de proposito: o codigo de saida viria do `tail` e uma build
    # falhada passava por boa. Corta-se a saida do lado de ca.
    $r = Invoke-Vm "cd $RemoteDir/src && docker build -f ./$($b.Dockerfile) --build-arg BASE=$($b.Alvo) -t $($b.Alvo) . 2>&1"
    ($r.Output -split "`n" | Where-Object { $_ } | Select-Object -Last 14) | ForEach-Object { Write-Host "    $_" }
    if ($r.ExitCode -ne 0) { throw "a build do $($b.Nome) falhou (exit $($r.ExitCode))" }
}

# --- 5. Reiniciar -----------------------------------------------------------
Write-Host ''
Write-Host '=== 5. A reiniciar os servicos afectados ===' -ForegroundColor Cyan
Write-Host '  (so estes projetos: o edge, o ES e o tunel ficam intocados)'
# A ordem importa: o `backend` primeiro, porque o `mcp` e um cliente dele.
if ($fazerBackend) { Show-Vm "cd /opt/iqos/servicos/backend && docker compose up -d --force-recreate 2>&1 | tail -3" | Out-Null }
if ($fazerBackend) { Show-Vm "cd /opt/iqos/servicos/mcp && docker compose up -d --force-recreate 2>&1 | tail -3" | Out-Null }
if ($fazerFrontend) { Show-Vm "cd /opt/iqos/servicos/frontend && docker compose up -d --force-recreate 2>&1 | tail -3" | Out-Null }

Write-Host ''
Write-Host '=== 6. Validacao ===' -ForegroundColor Cyan
$problemas = 0
$sondas = @()
if ($fazerFrontend) { $sondas += @{ Nome = 'frontend'; Url = 'http://127.0.0.1:4180/' } }
if ($fazerBackend) { $sondas += @{ Nome = 'backend'; Url = 'http://127.0.0.1:8000/health' } }
if ($fazerBackend) { $sondas += @{ Nome = 'mcp'; Url = 'http://127.0.0.1:8765/' } }
foreach ($s in $sondas) {
    # Com repeticao: o contentor acabou de ser recriado, e um `curl` imediato da
    # 000 -- o que fez um deploy que correu bem parecer falhado.
    $codigo = '000'
    for ($i = 1; $i -le 12; $i++) {
        $codigo = (Invoke-Vm "curl -s -o /dev/null -m 8 -w %{http_code} $($s.Url)").Output.Trim()
        if ($codigo -match '^[234]') { break }
        Start-Sleep -Seconds 5
    }
    $ok = $codigo -match '^[234]'
    if (-not $ok) { $problemas++ }
    Write-Host ("  {0,-10} {1}  HTTP {2}" -f $s.Nome, $(if ($ok) { 'ok   ' } else { 'FALHA' }), $codigo) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}
Show-Vm 'df -h / | tail -1' | Out-Null

# A cache de build cresce a cada deploy (o driver `docker` do buildkit guarda
# snapshots). Depois de um deploy vi-a ir de 89 MB para 13,8 GB. Nao e erro, mas
# enche o disco sem avisar.
$cache = (Invoke-Vm "docker system df --format '{{.Type}} {{.Size}}' | grep -i build").Output.Trim()
if ($cache) { Write-Host "  $cache" -ForegroundColor DarkGray }
if ($LimparCache) {
    Write-Host '  a limpar a cache de build...' -ForegroundColor DarkGray
    Show-Vm 'docker builder prune -af 2>&1 | tail -2' | Out-Null
}

Write-Host ''
if ($problemas -eq 0) {
    Write-Host 'Deploy concluido.' -ForegroundColor Green
} else {
    Write-Host "Deploy com $problemas servico(s) sem resposta." -ForegroundColor Red
}
Write-Host ''
Remove-Item $pkg -Force -ErrorAction SilentlyContinue
if ($problemas -gt 0) { exit 1 }
