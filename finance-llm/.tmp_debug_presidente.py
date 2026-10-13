"""Porque é que estes municípios ficaram sem presidente identificado?"""
from api import remuneracoes_service as r

r.limpar_cache()
eleitos = r.eleitos()
nomes = r.nomes_eleitos()

for nome_concelho in ("Alcácer do Sal", "Alpiarça", "Barrancos", "Sines", "Torre de Moncorvo"):
    registo_mais = None
    for chave, registo in eleitos["concelhos"].items():
        if registo["nome"] == nome_concelho:
            registo_mais = registo
            break
    if not registo_mais:
        print(nome_concelho, "-> não está no MAI")
        continue
    presidente = registo_mais.get("presidente") or {}
    print("=" * 60)
    print(nome_concelho)
    print("  MAI presidente:", repr(presidente.get("nome")), "| sigla:", presidente.get("sigla"))
    registo_cne = nomes["concelhos"].get(str(registo_mais["id"]))
    if registo_cne:
        for lista in registo_cne["camara"]:
            print("   CNE", lista["sigla"], "->", lista["nomes"])
        print("   compatível?", [
            (n, r.nomes_compativeis(n, presidente.get("nome")))
            for lista in registo_cne["camara"]
            for n in lista["nomes"][:2]
        ])
    # compara com os resultados por partido do MAI
    print("  MAI por partido:", [(p["sigla"], p["mandatos"], p["presidentes"]) for p in registo_mais["camara"]])
