# Exporta os diapositivos do PowerPoint da analise de negocio para PNG,
# para poder validar o layout sem abrir o Office a mao.
# ASCII apenas (o PowerShell 5.1 le .ps1 sem BOM como Windows-1252).
param(
    [string]$Pptx = "C:\LLMFinance\finance-llm\exports\business\IQOS_Analise_Negocio.pptx",
    [string]$Destino = "C:\LLMFinance\finance-llm\exports\business\_slides"
)

if (Test-Path $Destino) { Remove-Item $Destino -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Destino | Out-Null

$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($Pptx, $true, $false, $false)
    foreach ($slide in $pres.Slides) {
        $ficheiro = Join-Path $Destino ("slide{0:d2}.png" -f $slide.SlideIndex)
        $slide.Export($ficheiro, "PNG", 1600, 900)
    }
    "exportados: $($pres.Slides.Count)"
    $pres.Close()
}
finally {
    $ppt.Quit()
}
Get-ChildItem $Destino -Filter *.png | Measure-Object | Select-Object -ExpandProperty Count
