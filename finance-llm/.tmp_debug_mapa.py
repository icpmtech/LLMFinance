"""Depura o casamento dos concelhos homónimos dos Açores/Madeira."""
from api import remuneracoes_service as r

r.limpar_cache()
concelhos = list(r.territorios()["concelhos"])
print("total concelhos:", len(concelhos))
for nome in ("Calheta (R.A.M.)", "Calheta (R.A.A.)", "Lagoa (R.A.A)", "Calheta", "Lagoa"):
    print(f"{nome!r} -> chave {r.chave_territorio(nome)!r}")
for concelho in concelhos:
    if r.chave_territorio(concelho["nome"]) in ("calheta", "lagoa"):
        print("  MAI:", concelho["nome"], "|", concelho["distrito"], "| id", concelho["id"])

for nome in ("Calheta (R.A.M.)", "Calheta (R.A.A.)", "Lagoa (R.A.A)"):
    achado = r._concelho_do_mapa(nome, concelhos)
    print(nome, "->", (achado or {}).get("nome"), (achado or {}).get("distrito"))
