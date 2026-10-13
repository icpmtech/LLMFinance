"""Sonda 7: cruzar adjudicantes-municipio dos contratos com os 308 municipios do INE."""
import json
import re
import unicodedata
from pathlib import Path

base = Path(__file__).resolve().parent


def chave(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("'", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def tokens(texto: str) -> set:
    return {t for t in chave(texto).split() if len(t) > 2}


ine = json.loads((base / "despesas_ine.json").read_text(encoding="utf-8"))
linhas = ine[0]["Dados"]["2023"]
oficiais = sorted({x["geodsg"] for x in linhas if len(x["geocod"]) == 7})
print("municipios oficiais (INE):", len(oficiais))
kof = {}
for nome in oficiais:
    kof.setdefault(chave(nome), []).append(nome)
dups = {k: v for k, v in kof.items() if len(v) > 1}
print("nomes oficiais repetidos:", dups)

contratos = json.loads((base / "contratos_municipios.json").read_text(encoding="utf-8"))
print("nomes extraidos dos contratos:", len(contratos))

padrao = re.compile(
    r"(?:c[âa]mara\s+municipal|munic[íi]pio)\s+d(?:e|o|a)\s+(?P<nome>.+?)\s*$",
    re.IGNORECASE,
)

nao_casaram = []
casaram = set()
for nome in contratos:
    m = padrao.search(nome.strip())
    cand = m.group("nome").strip() if m else nome.strip()
    k = chave(cand)
    if k in kof:
        casaram.add(kof[k][0])
        continue
    # tentar por tokens (ex.: "Servicos Municipalizados ... de Abrantes")
    achou = None
    for nome_oficial in oficiais:
        if chave(nome_oficial) and chave(nome_oficial) in chave(nome):
            achou = nome_oficial
            break
    if achou:
        casaram.add(achou)
    else:
        nao_casaram.append(nome)

print("municipios oficiais cobertos pelos contratos:", len(casaram), "de", len(oficiais))
print("em falta:", sorted(set(oficiais) - casaram)[:20])
print("\nnao casaram (top 15):")
for n in nao_casaram[:15]:
    print("   ", n)
