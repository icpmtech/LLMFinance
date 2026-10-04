#requires -Version 5.1
<#
.SYNOPSIS
    Impede o PC de adormecer — sem isto a origem do IQ OS cai e o endereco
    publico passa a mostrar a pagina de manutencao.

.DESCRIPTION
    Põe os tempos de suspensao, hibernacao e desligar do ecra a "nunca" (AC e DC)
    no esquema de energia ativo. Nao precisa de elevacao: so `powercfg /requests`
    e que exige Administrador.

.EXAMPLE
    .\00-keep-awake.ps1
    .\00-keep-awake.ps1 -Restore        # volta aos valores de origem
#>
[CmdletBinding()]
param(
    # Volta a por suspensao aos 30 min, ecra aos 10 min (AC) e 5/15 min (DC).
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'

if ($Restore) {
    & powercfg /change standby-timeout-ac 30
    & powercfg /change standby-timeout-dc 15
    & powercfg /change hibernate-timeout-ac 0
    & powercfg /change hibernate-timeout-dc 0
    & powercfg /change monitor-timeout-ac 10
    & powercfg /change monitor-timeout-dc 5
    Write-Host 'valores repostos (suspensao 30/15 min, ecra 10/5 min)' -ForegroundColor Yellow
}
else {
    & powercfg /change standby-timeout-ac 0
    & powercfg /change hibernate-timeout-ac 0
    & powercfg /change standby-timeout-dc 0
    & powercfg /change hibernate-timeout-dc 0
    & powercfg /change monitor-timeout-ac 0
    & powercfg /change monitor-timeout-dc 0
    Write-Host 'suspensao, hibernacao e desligar do ecra: nunca' -ForegroundColor Green
}

Write-Host ''
& powercfg /getactivescheme

function Get-Index([string]$sub, [string]$setting) {
    $out = & powercfg /query SCHEME_CURRENT $sub $setting
    $ac = ($out | Select-String 'Current AC Power Setting Index').ToString().Trim()
    $dc = ($out | Select-String 'Current DC Power Setting Index').ToString().Trim()
    "  AC: $ac`n  DC: $dc"
}

Write-Host ''
Write-Host 'Suspensao (STANDBYIDLE):'
Get-Index 'SUB_SLEEP' 'STANDBYIDLE' | Write-Host
Write-Host 'Hibernacao (HIBERNATEIDLE):'
Get-Index 'SUB_SLEEP' 'HIBERNATEIDLE' | Write-Host
Write-Host 'Desligar o ecra (VIDEOIDLE):'
Get-Index 'SUB_VIDEO' 'VIDEOIDLE' | Write-Host

Write-Host ''
Write-Host 'Notas:' -ForegroundColor DarkGray
Write-Host '  - 0x00000000 = nunca.' -ForegroundColor DarkGray
Write-Host '  - Uma politica de dominio pode voltar a impor suspensao.' -ForegroundColor DarkGray
