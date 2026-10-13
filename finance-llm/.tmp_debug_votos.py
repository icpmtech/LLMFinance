"""Depura a identificação do presidente pelas votações (CM)."""
from api import remuneracoes_service as r
from api import mapa_oficial_cne as cne

r.limpar_cache()
mapa = cne.coletar(r._data_dir())
resultados = mapa["resultados"]
nomes = r.nomes_eleitos()

falhas = []
for registo in nomes["concelhos"].values():
    if registo.get("presidente"):
        continue
    cod = registo.get("codigo_ine")
    resultado = resultados.get(f"{cod}|CM")
    votos = (resultado or {}).get("votos") or []
    bloco = next((b for b in mapa["camaras"] if b["cod"] == cod), None)
    falhas.append({
        "concelho": registo["concelho"],
        "top": [(v["sigla"], v["votos"]) for v in votos[:3]],
        "colunas": [(l["sigla"], len(l["nomes"])) for l in (bloco or {}).get("listas", [])],
    })

print("sem presidente:", len(falhas))
for falha in falhas[:12]:
    print(f'  {falha["concelho"]:22} top={falha["top"]} colunas={falha["colunas"]}')

print()
print("chaves de sigla:")
for sigla in ("SET-V 25", "SET-V-25", "PPD/PSD.CDS-PP.PPM", "ASB", "Jonet", "PS - PAN", "PS.PAN"):
    print(f"   {sigla!r:24} -> {r._sigla_chave(sigla)!r}")
