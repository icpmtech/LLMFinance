#requires -Version 5.1
<#
.SYNOPSIS
    Verifica o deploy ponta-a-ponta: stack local -> túnel de origem -> edge GCP
    -> Cloudflare -> browser.

.EXAMPLE
    .\05-verify.ps1 -PublicHost iqos.exemplo.com -OriginHost iqos-origin.exemplo.com
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PublicHost,
    [string]$OriginHost,
    [string]$LocalOrigin = 'http://127.0.0.1:4180'
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text) { Write-Host "    XX  $Text" -ForegroundColor Red }

# Devolve sempre um objeto (mesmo em 4xx/5xx), para poder validar códigos.
function Invoke-Probe {
    param([string]$Uri, [int]$TimeoutSec = 30)

    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec -MaximumRedirection 3
        $sw.Stop()
        return [pscustomobject]@{
            Uri          = $Uri
            Status       = [int]$r.StatusCode
            Ms           = [int]$sw.ElapsedMilliseconds
            Bytes        = $r.RawContentLength
            Body         = $r.Content
            ErrorMessage = $null
        }
    }
    catch {
        $sw.Stop()
        $status = 0
        $body = $null
        if ($_.Exception.PSObject.Properties['Response'] -and $_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            try {
                $sr = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $sr.ReadToEnd()
            }
            catch { $body = $null }
        }
        return [pscustomobject]@{
            Uri          = $Uri
            Status       = $status
            Ms           = [int]$sw.ElapsedMilliseconds
            Bytes        = 0
            Body         = $body
            ErrorMessage = $_.Exception.Message
        }
    }
}

$fail = 0

# ---------------------------------------------------------------------------
# 1. Stack local
# ---------------------------------------------------------------------------
Write-Step "1/4 Stack local ($LocalOrigin)"
$r1 = Invoke-Probe -Uri "$LocalOrigin/api/health"
if ($r1.Status -eq 200) { Write-Ok "200 em $($r1.Ms) ms" }
else { Write-Bad "$($r1.Status) — $($r1.ErrorMessage)"; $fail++ }

# ---------------------------------------------------------------------------
# 2. Túnel de origem (deve estar FECHADO)
# ---------------------------------------------------------------------------
if ($OriginHost) {
    Write-Step "2/4 Túnel de origem ($OriginHost) — deve recusar acesso anónimo"
    $r2 = Invoke-Probe -Uri "https://$OriginHost/" -TimeoutSec 20
    if ($r2.Status -eq 403) {
        Write-Ok '403 do Cloudflare Access — origem protegida (service token obrigatório)'
    }
    elseif ($r2.Status -eq 200) {
        Write-Bad '200 sem credenciais! A origem está PÚBLICA. Cria a Access application (Service Auth).'
        $fail++
    }
    else {
        Write-Warn2 "$($r2.Status) — sem Access configurado? Confirma a aplicação em Zero Trust > Access."
    }
}
else {
    Write-Step '2/4 Túnel de origem — saltado (sem -OriginHost)'
}

# ---------------------------------------------------------------------------
# 3. Edge público: API
# ---------------------------------------------------------------------------
Write-Step "3/4 Edge público — API (https://$PublicHost/api/health)"
$r3 = Invoke-Probe -Uri "https://$PublicHost/api/health" -TimeoutSec 60
if ($r3.Status -eq 200) { Write-Ok "200 em $($r3.Ms) ms" }
elseif ($r3.Status -eq 502 -or $r3.Status -eq 503) {
    Write-Bad "$($r3.Status) — o edge responde mas a origem está inacessível (túnel do PC em baixo ou stack desligada)."
    $fail++
}
else { Write-Bad "$($r3.Status) — $($r3.ErrorMessage)"; $fail++ }

# ---------------------------------------------------------------------------
# 4. Edge público: SPA
# ---------------------------------------------------------------------------
Write-Step "4/4 Edge público — SPA (https://$PublicHost/)"
$r4 = Invoke-Probe -Uri "https://$PublicHost/" -TimeoutSec 60
if ($r4.Status -eq 200 -and $r4.Body -match 'id="root"') { Write-Ok "200 em $($r4.Ms) ms (bundle servido pelo edge)" }
elseif ($r4.Status -eq 200) { Write-Warn2 '200 mas sem <div id="root"> — pode ser a página de manutenção do edge.' }
else { Write-Bad "$($r4.Status) — $($r4.ErrorMessage)"; $fail++ }

# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '--------------------------------------------------------------------------------'
if ($fail -eq 0) {
    Write-Host 'Deploy verificado sem falhas.' -ForegroundColor Green
    $resumo = @"
Cadeia:  browser -> Cloudflare -> e2-micro (nginx) -> túnel iqos-origin -> PC
Latência: cada página atravessa o Atlântico duas vezes (~200-300 ms a mais que
o acesso local). Para uso diário pesado, ver «Variante 0» no README.
"@
    Write-Host $resumo -ForegroundColor Gray
}
else {
    Write-Host "$fail verificações falharam — ver README.md (secção Troubleshooting)." -ForegroundColor Red
    exit 1
}
