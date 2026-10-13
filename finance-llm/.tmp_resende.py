"""Inspeciona Resende, Porto Moniz e Braga: colunas do mapa vs partidos do MAI."""
from api import remuneracoes_service as r
from api import mapa_oficial_cne as cne
from pathlib import Path

r.limpar_cache()
print("nomes_parecidos('Olavo Bolana Gouveia Pereira', 'Olavo Balona Gouveia Câmara') =",
      r.nomes_parecidos("Olavo Bolana Gouveia Pereira", "Olavo Balona Gouveia Câmara"))
print("nomes_parecidos('Fernando Silvério Cardoso de Sousa', 'Jorge José Pereira Sala Monteiro') =",
      r.nomes_parecidos("Fernando Silvério Cardoso de Sousa", "Jorge José Pereira Sala Monteiro"))

blocos = cne.ler_blocos(Path("data/remuneracoes/mapa_3_eleitos_retificado.xlsx"))
eleitos = r.eleitos()
nomes = r.nomes_eleitos()

for alvo in ("Resende", "Porto Moniz"):
    print("=" * 60, alvo)
    registo = next((x for x in eleitos["concelhos"].values() if x["nome"] == alvo), None)
    print("  MAI presidente:", (registo.get("presidente") or {}).get("nome"),
          "| partido:", (registo.get("presidente") or {}).get("sigla"))
    print("  MAI partidos:", [(p["sigla"], p["mandatos"], p["presidentes"]) for p in registo["camara"]])
    registo_cne = nomes["concelhos"].get(str(registo["id"]))
    print("  CNE colunas:", [(l["sigla"], l["nomes"]) for l in (registo_cne or {}).get("camara", [])])
