# Instalador do IQ OS para Windows.
#
# Cria atalhos (Ambiente de Trabalho + Menu Iniciar) que abrem a plataforma numa
# janela própria do Edge/Chrome (`--app=...`), sem barra de endereço — o
# equivalente a uma aplicação instalada, sem precisar de loja.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\instalar-iq-os.ps1
#   powershell -ExecutionPolicy Bypass -File .\instalar-iq-os.ps1 -Url http://localhost:5174/ -Name "IQ OS"
#   powershell -ExecutionPolicy Bypass -File .\instalar-iq-os.ps1 -Uninstall
#
# Nota: a forma preferida continua a ser "Instalar aplicação" no browser
# (Edge/Chrome), que cria uma aplicação de verdade com ícone, modo offline e
# entrada no Menu Iniciar. Este script é o plano B para quando o browser não
# oferece a instalação.
[CmdletBinding()]
param(
    [string]$Url = "http://localhost:5174/",
    [string]$Name = "IQ OS",
    [string]$BrowserPath = "",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

function Get-BrowserPath {
    param([string]$Explicit)
    if ($Explicit -and (Test-Path $Explicit)) { return $Explicit }
    $candidates = @(
        (Join-Path ${env:ProgramFiles} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path ${env:ProgramFiles} "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    return ""
}

$shortcuts = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "$Name.lnk"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\$Name.lnk")
)

$shell = New-Object -ComObject WScript.Shell

if ($Uninstall) {
    $removed = 0
    foreach ($path in $shortcuts) {
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "Removido: $path" -ForegroundColor Yellow
            $removed++
        }
    }
    if ($removed -eq 0) { Write-Host "Nao encontrei atalhos do IQ OS." -ForegroundColor DarkGray }
    return
}

$browser = Get-BrowserPath -Explicit $BrowserPath
if (-not $browser) {
    Write-Host "Nao encontrei o Microsoft Edge nem o Google Chrome." -ForegroundColor Red
    Write-Host "Instale um deles, ou use o botao 'Instalar aplicacao' na propria plataforma." -ForegroundColor DarkGray
    Write-Host "Tambem pode indicar o caminho: -BrowserPath 'C:\...\msedge.exe'" -ForegroundColor DarkGray
    exit 1
}

foreach ($path in $shortcuts) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $browser
    $shortcut.Arguments = "--app=$Url --start-maximized"
    $shortcut.WorkingDirectory = Split-Path $browser
    $shortcut.IconLocation = "$browser,0"
    $shortcut.Description = "IQ OS - Plataforma de Inteligencia Financeira"
    $shortcut.Save()
    Write-Host "Atalho criado: $path" -ForegroundColor Green
}

Write-Host ""
Write-Host "Pronto. Procure '$Name' no Menu Iniciar ou no Ambiente de Trabalho." -ForegroundColor Cyan
Write-Host "Para remover: powershell -ExecutionPolicy Bypass -File .\instalar-iq-os.ps1 -Uninstall" -ForegroundColor DarkGray
