import json, unicodedata
from pathlib import Path

src = json.load(open(r'C:\LLMFinance\finance-llm\data\municipios\municipios.json', encoding='utf-8'))

FIX = {
    "Freixo de Espada à Cinta": "Guarda",
    "Santa Marta de Penaguião": "Vila Real",
    "Vila Real de Santo António": "Faro",
    "Figueira de Castelo Rodrigo": "Guarda",
    "Lagoa (R.A.A.)": "Açores",
    "Vila da Praia da Vitória": "Açores",
    "Calheta (R.A.A.)": "Açores",
}
REGIAO = {
    "Região Autónoma dos Açores": "Açores",
    "Região Autónoma da Madeira": "Madeira",
}

mapping = {}
for f in src["fichas"]:
    nome = f["nome"]
    distrito = f.get("distrito")
    distrito = REGIAO.get(distrito, distrito) or FIX.get(nome)
    mapping[nome] = distrito

missing = {k: v for k, v in mapping.items() if not v}
print("sem distrito:", missing)

distritos = [
    "Aveiro", "Beja", "Braga", "Bragança", "Castelo Branco", "Coimbra",
    "Évora", "Faro", "Guarda", "Leiria", "Lisboa", "Portalegre", "Porto",
    "Santarém", "Setúbal", "Viana do Castelo", "Vila Real", "Viseu",
    "Açores", "Madeira",
]
def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


canon = {fold(d): d for d in distritos}
mapping = {k: canon.get(fold(v), v) for k, v in mapping.items()}

assert set(mapping.values()) <= set(distritos), set(mapping.values()) - set(distritos)
print("total", len(mapping), "distritos", len(set(mapping.values())))

out = Path(r'C:\LLMFinance\finance-llm\data\geo\concelhos_distritos.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps({"distritos": distritos, "concelhos": dict(sorted(mapping.items()))},
               ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("escrito", out, out.stat().st_size)
