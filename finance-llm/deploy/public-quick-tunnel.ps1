#requires -Version 5.1
<#
.SYNOPSIS
    Publica a stack local num endereco publico temporario do Cloudflare
    (quick tunnel, *.trycloudflare.com). NAO precisa de conta Cloudflare.

.DESCRIPTION
    Arranca `cloudflared tunnel --url <origem>` em primeiro plano e extrai o
    endereco publico do log. O endereco morre quando o processo termina
    (Ctrl+C).

    Limites de um quick tunnel:
      - sem garantia de disponibilidade e com pedidos limitados pelo Cloudflare;
      - hostname aleatorio, novo a cada arranque (nao serve para producao);
      - nao tem Cloudflare Access: quem tiver o URL chega a aplicacao
        (a autenticacao da propria app, por conta de utilizador, continua la).

    Para um hostname fixo no teu dominio, usa antes:
      .\gcp\01-setup-tunnels.ps1 -PublicHost iqos.teudominio.com -OriginHost iqos-origin.teudominio.com

.NOTES
    Em redes com DNS filtrado (ex.: DNS corporativo), o hostname
    *.trycloudflare.com pode nao resolver no proprio PC, mesmo funcionando
    para fora. Testar com:
      Resolve-DnsName <host> -Server 1.1.1.1

.EXAMPLE
    .\public-quick-tunnel.ps1
    .\public-quick-tunnel.ps1 -Origin http://127.0.0.1:8002
#>
[CmdletBinding()]
param(
    # O que fica exposto. 4180 = nginx da stack (SPA + proxy /api).
    [string]$Origin = 'http://127.0.0.1:4180'
)

$ErrorActionPreference = 'Stop'

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) { throw 'cloudflared nao esta no PATH. Instala com: winget install Cloudflare.cloudflared' }

# Confirma que a origem responde antes de gastar um tunel.
try {
    $r = Invoke-WebRequest -Uri $Origin -UseBasicParsing -TimeoutSec 8
    Write-Host "origem OK ($($r.StatusCode)): $Origin" -ForegroundColor Green
}
catch {
    throw "A origem $Origin nao responde: $($_.Exception.Message). Arranca a stack primeiro (..\start_solution.ps1)."
}

Write-Host "`nA criar quick tunnel Cloudflare -> $Origin" -ForegroundColor Cyan
Write-Host 'Ctrl+C termina o tunel (o endereco deixa de existir).' -ForegroundColor DarkGray

& $cf.Source tunnel --url $Origin --no-autoupdate 2>&1 |
    ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        $m = [regex]::Match($line, 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($m.Success) {
            Write-Host "`n==> Endereco publico: $($m.Value)`n" -ForegroundColor Yellow
        }
    }
