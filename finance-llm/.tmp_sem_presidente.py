"""Lista os municípios sem presidente identificado e compara com o mapa original."""
import json

from api import remuneracoes_service as r

r.limpar_cache()
dados = r.nomes_eleitos()
sem = [registo for registo in dados["concelhos"].values() if not registo.get("presidente_identificado")]
print("sem presidente:", len(sem))
for registo in sorted(sem, key=lambda x: x["concelho"]):
    print(
        f'  {registo["concelho"]:22} nomes={registo["total_eleitos"]:3} mandatos={registo["total_mandatos"]:3} '
        f'listas={[(l["sigla"], len(l["nomes"])) for l in registo["camara"]]}'
    )
print()
print("total com presidentes:", dados["total_com_presidente"])
print("vereadores:", dados["total_vereadores"])
