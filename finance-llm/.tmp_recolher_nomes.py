"""Recolhe os nomes dos eleitos do Mapa Oficial da CNE e confere os dados."""
import json
import time

from api import remuneracoes_service as r

inicio = time.time()
r.limpar_cache()
dados = r.collect_eleitos_nomes()
print("recolha em %.1fs" % (time.time() - inicio))
print("concelhos:", dados["total_concelhos"], "| com presidente:", dados["total_com_presidente"])
print("vereadores:", dados["total_vereadores"])
print("lacunas:", len(dados["lacunas"]), "| divergências:", len(dados["divergencias"]))
for aviso in dados["lacunas"][:8]:
    print("   ", aviso)
print("divergências:", [(d.get("concelho"), d.get("nome_no_mai"), d.get("nome_no_mapa")) for d in dados["divergencias"]])
print("sem correspondência:", dados["sem_correspondencia"])

# Conferência nacional: 308 presidentes + vereadores = mandatos
mandatos = sum(registo["total_mandatos"] for registo in dados["concelhos"].values())
eleitos = sum(registo["total_eleitos"] for registo in dados["concelhos"].values())
print("mandatos das câmaras:", mandatos, "| eleitos transcritos:", eleitos)
print("presidentes:", sum(1 for x in dados["concelhos"].values() if x["presidente"]))

for chave in ("2592", "2255", "1854"):
    registo = dados["concelhos"].get(chave)
    if not registo:
        continue
    print()
    print("==", registo["concelho"], registo["codigo_ine"], "| mandatos:", registo["total_mandatos"], "| nomes:", registo["total_eleitos"])
    presidente = registo["presidente"] or {}
    print("  presidente:", presidente.get("nome"), "|", presidente.get("sigla"), "| cabeça de lista:", presidente.get("cabeça_de_lista"))
    for vereador in registo["vereadores"][:6]:
        print("   vereador:", vereador["nome"], "|", vereador["sigla"])
