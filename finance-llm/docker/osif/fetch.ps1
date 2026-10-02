# Obtem o codigo do OSINT Framework (OSIF) para `docker/osif/src`.
#
# O diretorio `src/` nao vai para o repositorio do IQ OS (esta no .gitignore):
# e um clone do upstream, feito por este script, para as imagens serem
# construidas localmente. Ver `docker/osif/README.md`.
#
#   powershell -ExecutionPolicy Bypass -File docker/osif/fetch.ps1
#   powershell -ExecutionPolicy Bypass -File docker/osif/fetch.ps1 -Force
param(
    [string]$Ref = "main",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "src"

if (Test-Path (Join-Path $dest ".git")) {
    if (-not $Force) {
        Write-Output "Ja existe um clone em $dest (usa -Force para re-clonar)."
        exit 0
    }
    Remove-Item -Recurse -Force $dest
}

git clone --depth 1 --branch $Ref https://github.com/fr4nc1stein/osint-framework.git $dest
Write-Output "Clonado '$Ref' para $dest"
